"""
Tool router for executing LLM tool calls via existing Commands.

Design decisions:
1. Synchronous interface - matches aider's architecture
2. Async subprocesses handled via asyncio.run() in dedicated methods
3. All output truncated before return to prevent context overflow
4. Comprehensive audit logging for debugging
5. Risk-based confirmation for destructive operations
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from .risk import RiskLevel, get_tool_risk
from .truncate import truncate_output
from .sandbox import create_sandbox, Sandbox

if TYPE_CHECKING:
    from aider.commands import Commands
    from aider.io import InputOutput
    from aider.coders.base_coder import Coder


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    output: str
    error: Optional[str] = None
    exit_code: Optional[int] = None
    execution_time: float = 0.0
    truncated: bool = False
    original_size: int = 0  # Original output size in chars


@dataclass
class ToolCallRecord:
    """Audit record of a tool call."""
    call_id: str
    timestamp: float
    tool_name: str
    parameters: dict
    risk_level: RiskLevel
    success: bool
    execution_time: float
    error: Optional[str] = None
    output_preview: str = field(default="")
    was_truncated: bool = False
    original_size: int = 0


class ToolRouter:
    """
    Routes LLM tool calls to existing aider Commands.
    
    This class bridges between LLM function calling and aider's existing
    command infrastructure. It provides:
    - Tool execution with proper error handling
    - Output truncation for context window management
    - Risk-based user confirmation
    - Audit logging for debugging
    - Sandboxed execution for shell commands
    
    Thread safety: This class is NOT thread-safe. Each Coder should have
    its own ToolRouter instance.
    
    Example:
        router = ToolRouter(commands, io, coder)
        result = router.execute("run", {"command": "ls -la"})
        print(result.output)
    """
    
    # Maximum output size before truncation (characters)
    MAX_OUTPUT_SIZE = 100_000  # ~25k tokens
    TRUNCATED_OUTPUT_TOKENS = 4000  # Target after truncation
    
    def __init__(
        self,
        commands: Commands,
        io: InputOutput,
        coder: Coder,
        sandbox_type: str = "auto",
        auto_confirm: bool = False,
        risk_confirm_threshold: RiskLevel = RiskLevel.RISKY
    ):
        """
        Initialize tool router.
        
        Args:
            commands: Aider Commands instance for cmd_* methods
            io: InputOutput for user interaction
            coder: Coder instance for context
            sandbox_type: Sandbox type ("auto", "firejail", "unshare", "none")
            auto_confirm: If True, skip confirmation for all tools
            risk_confirm_threshold: Minimum risk level requiring confirmation
        """
        self.commands = commands
        self.io = io
        self.coder = coder
        self.auto_confirm = auto_confirm
        self.risk_confirm_threshold = risk_confirm_threshold
        
        # Initialize sandbox for shell execution
        self.sandbox: Sandbox = create_sandbox(sandbox_type)
        
        # Audit log
        self.call_history: list[ToolCallRecord] = []
        self._call_counter = 0
        
        # Track if we're in an async context (for nested calls)
        self._in_async_context = False
    
    def execute(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        """
        Execute a tool call.
        
        This is the main entry point for tool execution. It handles:
        1. Risk assessment
        2. User confirmation (if needed)
        3. Tool routing
        4. Output truncation
        5. Audit logging
        
        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters as dict
            
        Returns:
            ToolResult with execution results
            
        Raises:
            ValueError: If tool doesn't exist
        """
        start_time = time.time()
        self._call_counter += 1
        call_id = f"{tool_name}_{self._call_counter}"
        
        # Assess risk
        risk_level = get_tool_risk(tool_name, params)
        
        # Check for user confirmation
        if not self._should_auto_execute(tool_name, params, risk_level):
            confirmed = self._confirm_tool_execution(tool_name, params, risk_level)
            if not confirmed:
                return ToolResult(
                    success=False,
                    output="",
                    error="Tool execution declined by user",
                    execution_time=time.time() - start_time
                )
        
        # Route to implementation
        try:
            handler = self._get_handler(tool_name)
            result = handler(params)
            
            # Truncate output if needed
            if result.output and len(result.output) > self.MAX_OUTPUT_SIZE:
                original_size = len(result.output)
                truncated = truncate_output(
                    result.output,
                    max_tokens=self.TRUNCATED_OUTPUT_TOKENS
                )
                result = ToolResult(
                    success=result.success,
                    output=truncated,
                    error=result.error,
                    exit_code=result.exit_code,
                    execution_time=result.execution_time,
                    truncated=True,
                    original_size=original_size
                )
            
            # Log to audit trail
            self._log_call(ToolCallRecord(
                call_id=call_id,
                timestamp=start_time,
                tool_name=tool_name,
                parameters=params,
                risk_level=risk_level,
                success=result.success,
                execution_time=result.execution_time,
                error=result.error,
                output_preview=result.output[:200] if result.output else "",
                was_truncated=result.truncated,
                original_size=result.original_size
            ))
            
            return result
            
        except Exception as e:
            error_msg = f"Tool execution failed: {type(e).__name__}: {e}"
            self.io.tool_error(error_msg)
            
            # Log failed call
            self._log_call(ToolCallRecord(
                call_id=call_id,
                timestamp=start_time,
                tool_name=tool_name,
                parameters=params,
                risk_level=risk_level,
                success=False,
                execution_time=time.time() - start_time,
                error=error_msg,
                output_preview="",
                was_truncated=False,
                original_size=0
            ))
            
            return ToolResult(
                success=False,
                output="",
                error=error_msg,
                execution_time=time.time() - start_time
            )
    
    def _get_handler(self, tool_name: str):
        """Get handler method for a tool."""
        handlers = {
            "run": self._exec_run,
            "add": self._exec_add,
            "read_file": self._exec_read_file,
            "search": self._exec_search,
            "git": self._exec_git,
            "ls": self._exec_ls,
            "drop": self._exec_drop,
            "commit": self._exec_commit,
        }
        
        handler = handlers.get(tool_name)
        if not handler:
            raise ValueError(f"Unknown tool: {tool_name}")
        return handler
    
    def _should_auto_execute(
        self,
        tool_name: str,
        params: dict,
        risk_level: RiskLevel
    ) -> bool:
        """Check if tool should execute without confirmation."""
        if self.auto_confirm:
            return True
        
        # Always confirm DANGEROUS
        if risk_level == RiskLevel.DANGEROUS:
            return False
        
        # Confirm if above threshold
        if risk_level.value >= self.risk_confirm_threshold.value:
            return False
        
        return True
    
    def _confirm_tool_execution(
        self,
        tool_name: str,
        params: dict,
        risk_level: RiskLevel
    ) -> bool:
        """Ask user to confirm tool execution."""
        # Format parameters for display
        params_str = json.dumps(params, indent=2)
        if len(params_str) > 200:
            params_str = params_str[:200] + "..."
        
        risk_label = risk_level.name.upper()
        
        message = f"Allow {risk_label} tool call: {tool_name}?"
        details = f"Parameters: {params_str}"
        
        # Use io.confirm_ask with details
        if hasattr(self.io, 'confirm_ask'):
            return self.io.confirm_ask(
                message,
                default="n",
                subject=details
            )
        else:
            # Fallback to basic input
            print(f"\n{message}")
            print(details)
            response = input("Confirm [y/N]: ").lower().strip()
            return response in ('y', 'yes')
    
    def _log_call(self, record: ToolCallRecord):
        """Add call to audit history."""
        self.call_history.append(record)
        
        # Optional: verbose logging
        if hasattr(self.coder, 'verbose') and self.coder.verbose:
            status = "✓" if record.success else "✗"
            self.io.tool_output(
                f"[{status}] {record.tool_name} ({record.execution_time:.2f}s)"
            )
    
    # -------------------------------------------------------------------------
    # Tool Implementations
    # -------------------------------------------------------------------------
    
    def _exec_run(self, params: dict) -> ToolResult:
        """
        Execute shell command via sandbox.
        
        Uses async subprocess internally but exposes sync interface.
        """
        command = params.get("command", "")
        timeout = params.get("timeout", 30)
        
        if not command:
            return ToolResult(
                success=False,
                output="",
                error="No command provided"
            )
        
        # Run in sandbox using async helper
        start = time.time()
        
        try:
            # Use asyncio.run for isolated async execution
            output = asyncio.run(
                self.sandbox.run(command, self.coder.root, timeout)
            )
            
            # Sandbox doesn't give us exit code directly, infer from output
            # (This is a limitation - sandbox abstracts exit codes)
            exit_code = 0  # Assume success if no exception
            
            return ToolResult(
                success=True,
                output=output,
                exit_code=exit_code,
                execution_time=time.time() - start
            )
            
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout}s",
                exit_code=-1,
                execution_time=time.time() - start
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Sandbox execution failed: {e}",
                exit_code=-1,
                execution_time=time.time() - start
            )
    
    def _exec_add(self, params: dict) -> ToolResult:
        """Add files to chat context."""
        files = params.get("files", [])
        
        if not files:
            return ToolResult(
                success=False,
                output="",
                error="No files specified"
            )
        
        # Build argument string
        # Handle both list and single string
        if isinstance(files, str):
            files = [files]
        
        args = " ".join(f'"{f}"' if ' ' in f else f for f in files)
        
        start = time.time()
        try:
            # Commands.cmd_add prints to io, doesn't return much
            self.commands.cmd_add(args)
            
            return ToolResult(
                success=True,
                output=f"Added {len(files)} file(s) to chat",
                execution_time=time.time() - start
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                execution_time=time.time() - start
            )
    
    def _exec_read_file(self, params: dict) -> ToolResult:
        """Read file contents with pagination."""
        path = params.get("path", "")
        offset = params.get("offset", 0)
        limit = params.get("limit", 100)
        
        if not path:
            return ToolResult(
                success=False,
                output="",
                error="No path specified"
            )
        
        start = time.time()
        
        try:
            # Resolve path
            abs_path = self.coder.abs_root_path(path)
            
            # Read file
            content = self.io.read_text(abs_path)
            
            if content is None:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found: {path}"
                )
            
            # Paginate
            lines = content.split("\n")
            total_lines = len(lines)
            
            # Validate offset
            if offset < 0:
                offset = 0
            if offset >= total_lines:
                return ToolResult(
                    success=True,
                    output=f"[File has {total_lines} lines, offset {offset} is past end]",
                    execution_time=time.time() - start
                )
            
            # Extract range
            selected = lines[offset:offset + limit]
            result = "\n".join(selected)
            
            # Add header if paginated
            if offset > 0 or offset + limit < total_lines:
                header = f"[Lines {offset}-{min(offset + limit, total_lines)} of {total_lines}]\n"
                result = header + result
            
            return ToolResult(
                success=True,
                output=result,
                execution_time=time.time() - start
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to read file: {e}",
                execution_time=time.time() - start
            )
    
    def _exec_search(self, params: dict) -> ToolResult:
        """Search codebase using ripgrep or git grep."""
        pattern = params.get("pattern", "")
        path = params.get("path", ".")
        
        if not pattern:
            return ToolResult(
                success=False,
                output="",
                error="No search pattern provided"
            )
        
        start = time.time()
        
        # Try ripgrep first, fall back to git grep
        async def do_search():
            # Resolve search path
            search_path = self.coder.abs_root_path(path)
            
            # Try ripgrep
            if self._command_exists("rg"):
                cmd = [
                    "rg",
                    "-n",  # Line numbers
                    "--color=never",
                    "--max-count", "50",  # Limit results
                    "--max-columns", "200",  # Limit line length
                    pattern,
                    str(search_path)
                ]
            else:
                # Fall back to git grep
                cmd = [
                    "git", "grep", "-n",
                    "--max-count", "50",
                    pattern,
                    "--", str(search_path)
                ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.coder.root
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=30
            )
            
            if proc.returncode == 0:
                return stdout.decode('utf-8', errors='replace')
            elif proc.returncode == 1:
                return "No matches found"
            else:
                error = stderr.decode('utf-8', errors='replace')
                raise RuntimeError(f"Search failed: {error}")
        
        try:
            output = asyncio.run(do_search())
            return ToolResult(
                success=True,
                output=output,
                execution_time=time.time() - start
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="Search timed out after 30s",
                execution_time=time.time() - start
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                execution_time=time.time() - start
            )
    
    def _exec_git(self, params: dict) -> ToolResult:
        """Execute git command."""
        args = params.get("command", params.get("args", ""))
        
        start = time.time()
        
        try:
            # Commands.cmd_git handles the actual execution
            # It prints to io but we need to capture output
            
            # Redirect output capture
            import io as io_module
            import sys
            
            # Capture stdout
            old_stdout = sys.stdout
            sys.stdout = captured = io_module.StringIO()
            
            try:
                self.commands.cmd_git(args)
                output = captured.getvalue()
            finally:
                sys.stdout = old_stdout
            
            return ToolResult(
                success=True,
                output=output or "Git command executed successfully",
                execution_time=time.time() - start
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                execution_time=time.time() - start
            )
    
    def _exec_ls(self, params: dict) -> ToolResult:
        """List files in repository."""
        path = params.get("path", ".")
        
        start = time.time()
        
        try:
            abs_path = self.coder.abs_root_path(path)
            
            if not os.path.isdir(abs_path):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Not a directory: {path}"
                )
            
            entries = os.listdir(abs_path)
            
            # Categorize
            files = []
            dirs = []
            for entry in sorted(entries):
                full = os.path.join(abs_path, entry)
                if os.path.isdir(full):
                    dirs.append(entry + "/")
                else:
                    files.append(entry)
            
            output = "\n".join(dirs + files)
            
            return ToolResult(
                success=True,
                output=output,
                execution_time=time.time() - start
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                execution_time=time.time() - start
            )
    
    def _exec_drop(self, params: dict) -> ToolResult:
        """Remove files from chat context."""
        files = params.get("files", [])
        
        if not files:
            # Drop all if no files specified
            self.commands.cmd_drop("")
            return ToolResult(
                success=True,
                output="Dropped all files from chat"
            )
        
        if isinstance(files, str):
            files = [files]
        
        args = " ".join(f'"{f}"' if ' ' in f else f for f in files)
        
        start = time.time()
        try:
            self.commands.cmd_drop(args)
            return ToolResult(
                success=True,
                output=f"Dropped {len(files)} file(s) from chat",
                execution_time=time.time() - start
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                execution_time=time.time() - start
            )
    
    def _exec_commit(self, params: dict) -> ToolResult:
        """Commit changes to git."""
        message = params.get("message", "")
        
        start = time.time()
        
        try:
            self.commands.cmd_commit(message)
            
            return ToolResult(
                success=True,
                output=f"Committed changes: {message}" if message else "Committed changes",
                execution_time=time.time() - start
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                execution_time=time.time() - start
            )
    
    def _command_exists(self, cmd: str) -> bool:
        """Check if a command exists in PATH."""
        import shutil
        return shutil.which(cmd) is not None
    
    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    
    def get_call_history(self) -> list[ToolCallRecord]:
        """Get audit log of all tool calls."""
        return self.call_history.copy()
    
    def get_summary(self) -> str:
        """Get human-readable summary of tool usage."""
        if not self.call_history:
            return "No tool calls made"
        
        total = len(self.call_history)
        successful = sum(1 for r in self.call_history if r.success)
        failed = total - successful
        
        total_time = sum(r.execution_time for r in self.call_history)
        
        lines = [
            f"Tool Calls: {total}",
            f"  Successful: {successful}",
            f"  Failed: {failed}",
            f"  Total time: {total_time:.2f}s",
            "",
            "Call breakdown:"
        ]
        
        # Group by tool
        from collections import Counter
        tool_counts = Counter(r.tool_name for r in self.call_history)
        for tool, count in tool_counts.most_common():
            lines.append(f"  {tool}: {count}")
        
        return "\n".join(lines)
    
    def clear_history(self):
        """Clear audit history."""
        self.call_history.clear()
        self._call_counter = 0
