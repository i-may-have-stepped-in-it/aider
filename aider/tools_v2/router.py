"""Production tool router with resilient execution and full observability.

This module provides the main entry point for tool execution in the aider system.
It replaces the v1 router with a production-ready implementation that addresses
critical reliability and observability gaps.

Error Handling Strategy:
------------------------
1. Layered error handling: Each layer (resilience, execution, sandbox) handles
   errors at its appropriate level, with outer layers receiving sanitized errors.

2. Partial state capture: On any failure (timeout, cancellation, exception), we
   capture whatever output was produced before the failure. This allows recovery
   and debugging even when operations don't complete.

3. Resource cleanup guarantee: All resources (sandboxes, temp files, async tasks)
   are cleaned up in finally blocks, ensuring no leaks even on unexpected failures.

4. Circuit breaker pattern: Prevents cascade failures by stopping calls to
   failing components, giving them time to recover.

5. Structured logging: All execution details are logged in structured format
   for easy querying and analysis in production.

Async Pattern:
--------------
We use AsyncExecutor to bridge sync and async code without nested asyncio.run()
calls. This is critical because:
- The main aider loop runs in synchronous context
- Many operations (sandbox I/O, file operations) benefit from async
- Nested asyncio.run() raises RuntimeError and deadlocks

The pattern is:
    async_executor = AsyncExecutor()
    result = async_executor.run(async_func())  # Safe from sync context
"""

import collections
import json
import logging
import os
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

# Core infrastructure imports
from .async_executor import AsyncExecutor
from .circuit_breaker import (
    BackoffStrategies,
    CircuitBreakerOpen,
    CircuitBreakers,
    RateLimiters,
    ResilientExecutor,
)
from .compression import CompressionResult, SmartCompressor
from .cost_tracker import AccurateCostTracker
from .mcp_manager import MCPManager

# from .search_web import SearchWebTool
from .openclaw_client import OpenClawToolClient
from .router_files import RouterFileOpsMixin
from .router_mcp import RouterMCPMixin
from .router_search import RouterSearchMixin
from .router_terminal import RouterTerminalMixin
from .sandbox import SandboxResult, create_sandbox
from .terminal_watcher import TerminalWatcher

if TYPE_CHECKING:
    from aider.coders.base_coder import Coder
    from aider.commands import Commands
    from aider.io import InputOutput

# Structured logging - use module-level logger for proper log hierarchy
logger = logging.getLogger(__name__)


class ToolError(Exception):
    """Base exception for tool execution errors."""

    def __init__(self, message: str, result: Optional["ToolExecutionResult"] = None):
        super().__init__(message)
        self.result = result


class ToolTimeoutError(ToolError):
    """Tool execution exceeded time limit."""

    pass


class ToolBudgetExceededError(ToolError):
    """Tool execution would exceed cost budget."""

    pass


class ToolLimitExceededError(ToolError):
    """Tool call limit exceeded."""

    pass


class ToolNotFoundError(ToolError):
    """Requested tool does not exist."""

    pass


@dataclass
class ToolExecutionResult:
    """
    Comprehensive result from tool execution.

    Captures everything needed for debugging, cost tracking, and recovery.
    This dataclass is designed to be:
    - Serializable for persistence/audit logs
    - Informative for debugging failures
    - Complete for cost analysis
    - Safe to pass through the system (no sensitive data in default fields)

    Attributes:
        tool_name: Name of the executed tool
        parameters: Parameters passed to the tool (may be sanitized for logging)
        success: Whether execution completed successfully
        output: The main output from the tool (possibly truncated/compressed)
        exit_code: Process exit code if applicable
        error: Error message if failed
        start_time: Unix timestamp when execution started
        end_time: Unix timestamp when execution ended
        duration_ms: Execution duration in milliseconds
        partial_output: Output captured before failure (for recovery)
        sandbox_result: Full sandbox execution details
        compression_result: Details of any compression applied
        truncated: Whether output was truncated
        compressed: Whether output was compressed
        retry_count: Number of retries attempted
        circuit_breaker_open: Whether circuit breaker prevented execution
    """

    tool_name: str
    parameters: dict
    success: bool
    output: str
    exit_code: Optional[int] = None
    error: Optional[str] = None

    # Timing
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None

    # State preservation - critical for debugging failures
    partial_output: Optional[str] = None  # What we got before failure
    sandbox_result: Optional[SandboxResult] = None
    compression_result: Optional[CompressionResult] = None

    # Metadata
    truncated: bool = False
    compressed: bool = False
    retry_count: int = 0
    circuit_breaker_open: bool = False

    def __post_init__(self):
        if self.end_time and self.start_time:
            self.duration_ms = (self.end_time - self.start_time) * 1000

    def finalize(self) -> "ToolExecutionResult":
        """Finalize timing calculations. Call when execution is complete."""
        if self.end_time is None:
            self.end_time = time.time()
            self.duration_ms = (self.end_time - self.start_time) * 1000
        return self

    def to_log_dict(self) -> dict:
        """
        Convert to structured log format.

        This format is optimized for log ingestion and analysis.
        Sensitive data in parameters should be sanitized before logging.
        """
        return {
            "event": "tool_execution",
            "tool": self.tool_name,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "output_size": len(self.output),
            "truncated": self.truncated,
            "compressed": self.compressed,
            "error": self.error,
            "exit_code": self.exit_code,
            "retry_count": self.retry_count,
            "circuit_breaker_open": self.circuit_breaker_open,
        }

    def to_error_dict(self) -> dict:
        """Convert to error report format for debugging."""
        return {
            "tool": self.tool_name,
            "success": self.success,
            "error": self.error,
            "partial_output_preview": self.partial_output[:500] if self.partial_output else None,
            "duration_ms": self.duration_ms,
            "sandbox_result": self.sandbox_result.to_dict() if self.sandbox_result else None,
        }


@dataclass
class RouterConfig:
    """Configuration for ToolRouterV2."""

    sandbox_type: str = "auto"
    max_tool_calls: int = 50
    max_cost: float = 5.0
    default_timeout: float = 60.0
    max_output_size: int = 100_000  # Characters
    enable_compression: bool = True
    compression_threshold: int = 10_000  # Compress outputs larger than this
    preserve_partial_output: bool = True  # Always capture partial output on failure
    audit_log_path: Optional[Path] = None


class ToolRouterV2(
    RouterFileOpsMixin, RouterMCPMixin, RouterSearchMixin, RouterTerminalMixin
):
    """
    Production tool router with full resilience and observability.

    Key improvements over v1:
    - AsyncExecutor for proper async/sync boundary (no nested asyncio.run())
    - ResilientExecutor for circuit breakers and retries
    - SmartCompressor for semantic output handling (not naive truncation)
    - AccurateCostTracker for budget management
    - Structured logging for observability
    - Guaranteed cleanup even on failures

    Usage:
        router = ToolRouterV2(commands, io, coder)
        result = router.execute("run", {"command": "ls -la"})
        if result.success:
            print(result.output)
        else:
            logger.error("Tool failed", extra=result.to_log_dict())

    Thread Safety:
        This class is designed for single-threaded use within the aider main loop.
        The AsyncExecutor handles all async concurrency internally.
    """

    def __init__(
        self,
        commands: "Commands",
        io: "InputOutput",
        coder: "Coder",
        config: Optional[RouterConfig] = None,
        runtime=None,
    ):
        self.commands = commands
        self.io = io
        self.coder = coder
        self.config = config or RouterConfig()
        self.runtime = runtime or getattr(coder, "runtime", None)

        # Core infrastructure - initialized once, reused for all executions
        self._init_infrastructure()

        # Tool registry - maps tool names to handler methods
        self._init_tool_registry()

        # Execution tracking — bounded deque prevents unbounded memory growth
        self.tool_call_count = 0
        self.execution_history: collections.deque[ToolExecutionResult] = collections.deque(
            maxlen=500
        )

        logger.info(
            "ToolRouterV2 initialized",
            extra={
                "sandbox_type": self.config.sandbox_type,
                "max_tool_calls": self.config.max_tool_calls,
                "max_cost": self.config.max_cost,
            },
        )

    def _init_infrastructure(self) -> None:
        """Initialize core infrastructure components by consuming runtime-owned services."""
        shared_services = self._get_shared_services()

        if shared_services:
            # Consume runtime-owned services to avoid duplicate instantiation
            self.async_executor = shared_services.async_executor
            self.compressor = shared_services.compressor
            self.openclaw_client = shared_services.openclaw_client
            self.mcp_manager = shared_services.mcp_manager
            self.terminal_watcher = shared_services.terminal_watcher
            self.resilient_executor = shared_services.resilient_executor
            self.cost_tracker = shared_services.cost_tracker
            self.sandbox = shared_services.sandbox
        else:
            self._create_default_infrastructure()

    def _get_shared_services(self):
        """Get shared services from runtime if available."""
        if (
            self.runtime
            and getattr(self.runtime, "is_session_runtime", False) is True
            and hasattr(self.runtime, "get_tool_services")
        ):
            try:
                return self.runtime.get_tool_services(self.config.sandbox_type)
            except Exception as e:
                logger.debug(f"Failed to load shared runtime tool services: {e}")
        return None

    def _get_hooks_manager(self):
        """Get hooks from the session runtime first, else local compatibility fallback."""
        if self.runtime is not None:
            return getattr(self.runtime, "hooks_manager", None)
        return getattr(self.coder, "hooks_manager", None)

    def _create_default_infrastructure(self) -> None:
        """Create default infrastructure when runtime services are not available."""
        # AsyncExecutor: Bridges sync and async without nested event loops
        self.async_executor = AsyncExecutor()

        # SmartCompressor: Semantic output compression (not naive truncation)
        self.compressor = SmartCompressor()

        # OpenClawToolClient: Remote tool execution
        self.openclaw_client = OpenClawToolClient()

        # MCPManager: Support for external MCP servers
        self.mcp_manager = MCPManager()

        # TerminalWatcher: Real-time background process monitoring
        self.terminal_watcher = TerminalWatcher()

        # ResilientExecutor: Circuit breakers, retries, rate limiting
        self.resilient_executor = ResilientExecutor(
            circuit_breaker=CircuitBreakers.tool_execution(),
            rate_limiter=RateLimiters.aggressive(),
            backoff=BackoffStrategies.standard(),
        )

        # Sandbox: Isolated execution environment
        self.sandbox = create_sandbox(self.config.sandbox_type)

        # AccurateCostTracker: Precise cost tracking for budget management
        self.cost_tracker = AccurateCostTracker(
            max_budget=self.config.max_cost,
            hooks=self._get_hooks_manager(),
        )

    def _init_tool_registry(self) -> None:
        """Register tool handlers."""
        self._tools: dict[str, Callable[[dict], ToolExecutionResult]] = {
            # Shell execution
            "run": self._exec_run,
            "terminal_watch_start": self._exec_terminal_watch_start,
            "terminal_watch_read": self._exec_terminal_watch_read,
            "terminal_watch_input": self._exec_terminal_watch_input,
            "terminal_watch_signal": self._exec_terminal_watch_signal,
            "terminal_watch_stop": self._exec_terminal_watch_stop,
            "shell": self._exec_run,
            "exec": self._exec_run,
            # File operations
            "read": self._exec_read_file,
            "read_file": self._exec_read_file,
            "cat": self._exec_read_file,
            # Search operations
            "search": self._exec_search,
            "search_web": self._exec_search_web,
            "scrape_web": self._exec_scrape_web,
            "index_search": self._exec_index_search,
            "delegate": self._exec_delegate,
            "browser_action": self._exec_browser_action,
            "mcp_list_resources": self._exec_mcp_list_resources,
            "mcp_read_resource": self._exec_mcp_read_resource,
            "grep": self._exec_search,
            "find": self._exec_find,
            # Editor operations
            "edit": self._exec_edit,
            "apply_edit": self._exec_edit,
            # Git operations
            "git": self._exec_git,
            # Code intelligence
            "definitions": self._exec_definitions,
            "references": self._exec_references,
            # Linting
            "lint": self._exec_lint,
        }

    def _trigger_ui_tool(self, tool_name: str, message: str, progress: float = None):
        """Notify UI of tool execution progress."""
        hooks_manager = self._get_hooks_manager()
        if hooks_manager:
            from aider.hooks_manager import HookPoint

            try:
                context = {
                    "tool_name": tool_name,
                    "message": message,
                    "progress": progress,
                }
                if hasattr(hooks_manager, "execute_hooks"):
                    hooks_manager.execute_hooks(HookPoint.UI_TOOL_PROGRESS, context)
                else:
                    hooks_manager.trigger(HookPoint.UI_TOOL_PROGRESS, **context)
            except Exception as e:
                logger.debug(f"Error triggering UI_TOOL_PROGRESS hook: {e}")

    def execute(self, tool_name: str, params: dict) -> ToolExecutionResult:
        """
        Execute tool with full resilience and observability.

        This is the main entry point for tool execution. It implements a layered
        error handling strategy where each layer adds value:

        Layer 1 - Limits: Check budget and call limits before any work
        Layer 2 - Resilience: Circuit breaker and retry via ResilientExecutor
        Layer 3 - Execution: Actual tool execution with timeout handling
        Layer 4 - Post-processing: Compression, cost tracking, logging

        Error Handling:
            All exceptions are caught and converted to ToolExecutionResult.
            The original exception is logged with full traceback for debugging.
            Partial output is always captured when available.

        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters (dict)

        Returns:
            ToolExecutionResult with full execution details
        """
        start_time = time.time()
        self.tool_call_count += 1
        self._trigger_ui_tool(tool_name, "executing")

        # Layer 1: Check limits before doing any work
        limit_error = self._check_limits(tool_name)
        if limit_error:
            return limit_error

        # Check for MCP tools first (Dynamic Tools)
        for server in self.mcp_manager.servers.values():
            for mcp_tool in server.tools:
                if mcp_tool.name == tool_name:
                    try:
                        res = server.call_tool(tool_name, params)
                        # Extract text from MCP result
                        output = ""
                        for content in res.get("content", []):
                            if content.get("type") == "text":
                                output += content.get("text", "")

                        result = ToolExecutionResult(
                            tool_name=tool_name,
                            parameters=params,
                            success=True,
                            output=output,
                            start_time=start_time,
                            end_time=time.time(),
                        )
                        self._log_result(result)
                        self.execution_history.append(result)
                        return result
                    except Exception as e:
                        logger.error(f"MCP tool {tool_name} failed: {e}")
                        result = ToolExecutionResult(
                            tool_name=tool_name,
                            parameters=params,
                            success=False,
                            output="",
                            error=f"MCP tool execution failed: {str(e)}",
                            start_time=start_time,
                            end_time=time.time(),
                        )
                        self._log_result(result)
                        return result

        # Check if tool exists in local registry
        if tool_name not in self._tools:
            result = ToolExecutionResult(
                tool_name=tool_name,
                parameters=params,
                success=False,
                output="",
                error=f"Unknown tool: {tool_name}",
                start_time=start_time,
                end_time=time.time(),
            )
            self._log_result(result)
            return result

        # Layer 2-4: Execute with full resilience
        try:
            result = self._execute_with_resilience(tool_name, params)
        except Exception as e:
            # Catch-all for unexpected errors - this should rarely happen
            # as _execute_with_resilience handles most errors internally
            logger.exception("Unexpected error in tool execution")
            result = ToolExecutionResult(
                tool_name=tool_name,
                parameters=params,
                success=False,
                output="",
                error=f"Unexpected error: {type(e).__name__}: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
            )

        # Always log and record the result
        self._log_result(result)
        self.execution_history.append(result)

        # Trigger UI update
        if result.success:
            self._trigger_ui_tool(tool_name, "complete")
        else:
            self._trigger_ui_tool(tool_name, "failed")

        return result

    def _check_limits(self, tool_name: str) -> Optional[ToolExecutionResult]:
        """
        Check if execution should proceed based on limits.

        Returns:
            Error result if limits exceeded, None if OK to proceed
        """
        # Check call count limit
        if self.tool_call_count > self.config.max_tool_calls:
            logger.warning(
                "Tool call limit exceeded", extra={"tool": tool_name, "count": self.tool_call_count}
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                parameters={},
                success=False,
                output="",
                error=(
                    f"Tool call limit exceeded: {self.tool_call_count}/{self.config.max_tool_calls}"
                ),
                end_time=time.time(),
            )

        # Check budget
        if not self.cost_tracker.can_execute():
            logger.warning(
                "Cost budget exceeded", extra={"tool": tool_name, "budget": self.config.max_cost}
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                parameters={},
                success=False,
                output="",
                error=(
                    f"Cost budget exceeded: ${self.cost_tracker.consumed_budget:.2f}/"
                    f"${self.config.max_cost:.2f}"
                ),
                end_time=time.time(),
            )

        return None

    def _execute_with_resilience(self, tool_name: str, params: dict) -> ToolExecutionResult:
        """
        Execute with circuit breaker and retry logic.

        The ResilientExecutor provides:
        - Circuit breaker: Stop calling failing services
        - Retry: Automatic retry with exponential backoff
        - Rate limiting: Prevent overwhelming downstream services

        If the circuit breaker is open, we return immediately with a clear error.
        """
        start_time = time.time()

        def do_execute() -> ToolExecutionResult:
            """Wrapped execution for resilient executor."""
            return self._do_execute(tool_name, params)

        try:
            # Execute through resilient wrapper
            result = self.resilient_executor.execute(do_execute)
            result.retry_count = self.resilient_executor.last_retry_count
            return result

        except CircuitBreakerOpen:
            # Circuit breaker is open - service is unhealthy
            logger.error("Circuit breaker open - tool execution blocked", extra={"tool": tool_name})
            return ToolExecutionResult(
                tool_name=tool_name,
                parameters=params,
                success=False,
                output="",
                error="Tool execution temporarily unavailable (circuit breaker open)",
                start_time=start_time,
                end_time=time.time(),
                circuit_breaker_open=True,
            )

    def _do_execute(self, tool_name: str, params: dict) -> ToolExecutionResult:
        """
        Actual tool execution with comprehensive error handling.

        This method handles:
        1. Calling the appropriate tool handler
        2. Catching and formatting errors
        3. Capturing partial output on failure
        4. Finalizing the result
        """
        start_time = time.time()
        partial_output = ""

        try:
            # Get the tool handler
            handler = self._tools[tool_name]

            # Execute the tool
            # Handlers are responsible for their own error handling and
            # should return a ToolExecutionResult, not raise exceptions
            result = handler(params)

            # Ensure result is properly finalized
            if result.end_time is None:
                result.finalize()

            return result

        except Exception as e:
            # Handler raised an exception - this is a bug in the handler
            logger.exception(f"Tool handler raised exception: {tool_name}")

            return ToolExecutionResult(
                tool_name=tool_name,
                parameters=params,
                success=False,
                output=partial_output,
                error=f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
                start_time=start_time,
                end_time=time.time(),
                partial_output=partial_output if self.config.preserve_partial_output else None,
            )

    def _log_result(self, result: ToolExecutionResult) -> None:
        """Log execution result with appropriate level."""
        log_data = result.to_log_dict()

        if result.success:
            logger.info("Tool execution completed", extra=log_data)
        else:
            logger.error("Tool execution failed", extra=log_data)

        # Also write to audit log if configured
        if self.config.audit_log_path:
            self._write_audit_log(result)

    def _write_audit_log(self, result: ToolExecutionResult) -> None:
        """Write to persistent audit log."""
        try:
            log_entry = {
                "timestamp": time.time(),
                **result.to_log_dict(),
            }
            with open(self.config.audit_log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")

    # =======================================================================
    # Tool Handlers
    # =======================================================================

    def _exec_upstream_tool(self, tool_name: str, params: dict) -> ToolExecutionResult:
        """
        Execute a tool that exists on the upstream gateway but not locally.
        This provides 'Skill Awareness' for OpenAI/OpenClaw/etc.
        """
        start_time = time.time()
        gateway_url = os.environ.get("OPENAI_API_BASE")
        if not gateway_url:
            raise ToolNotFoundError(f"No gateway configured for upstream tool: {tool_name}")

        exec_url = gateway_url.rstrip("/") + f"/tools/{tool_name}/execute"

        import httpx

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(exec_url, json=params)
                if response.status_code == 200:
                    data = response.json()
                    return ToolExecutionResult(
                        tool_name=tool_name,
                        parameters=params,
                        success=True,
                        output=data.get("output", ""),
                        start_time=start_time,
                        end_time=time.time(),
                    )
                else:
                    return ToolExecutionResult(
                        tool_name=tool_name,
                        parameters=params,
                        success=False,
                        output="",
                        error=f"Upstream execution error: {response.status_code} - {response.text}",
                        start_time=start_time,
                        end_time=time.time(),
                    )
        except Exception as e:
            logger.error(f"Failed to execute upstream tool {tool_name}: {e}")
            raise

    def _exec_run(self, params: dict) -> ToolExecutionResult:
        """
        Execute shell command via sandbox.

        Uses AsyncExecutor for non-blocking execution.
        Captures partial output on timeout/cancellation.
        """
        start_time = time.time()
        command = params.get("command", "")
        timeout = params.get("timeout", self.config.default_timeout)

        if not command:
            return ToolExecutionResult(
                tool_name="run",
                parameters=params,
                success=False,
                output="",
                error="No command specified",
                start_time=start_time,
                end_time=time.time(),
            )

        # Log command (sanitized)
        logger.debug(f"Executing command: {command[:100]}...")

        try:
            # Use AsyncExecutor for proper async execution
            # This is the KEY fix - no asyncio.run() here!
            # Wrap string commands in a shell so semicolons, pipes, etc. work.
            if isinstance(command, str):
                command_list = ["/bin/sh", "-c", command]
            else:
                command_list = command
            sandbox_result = self.async_executor.run(
                self.sandbox.execute(command_list, timeout=timeout)
            )

            # Process result
            output = sandbox_result.output
            truncated = False
            compressed = False
            compression_result = None

            # Apply smart compression if enabled and output is large
            if self.config.enable_compression and len(output) > self.config.compression_threshold:
                compression_result = self.compressor.compress(output)
                output = compression_result.compressed_text
                compressed = True
                truncated = compression_result.was_truncated
            elif len(output) > self.config.max_output_size:
                # Fallback to simple truncation if compression disabled
                output = output[: self.config.max_output_size]
                output += (
                    f"\n\n[Output truncated: {len(sandbox_result.output)} chars -> "
                    f"{len(output)} chars]"
                )
                truncated = True

            return ToolExecutionResult(
                tool_name="run",
                parameters=params,
                success=sandbox_result.success,
                output=output,
                exit_code=sandbox_result.exit_code,
                error=sandbox_result.error,
                start_time=start_time,
                end_time=time.time(),
                sandbox_result=sandbox_result,
                compression_result=compression_result,
                truncated=truncated,
                compressed=compressed,
            )

        except Exception as e:
            # Capture partial output if available
            partial = getattr(e, "partial_output", None)

            logger.exception("Command execution failed")
            return ToolExecutionResult(
                tool_name="run",
                parameters=params,
                success=False,
                output=partial or "",
                error=f"Execution failed: {type(e).__name__}: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
                partial_output=partial if self.config.preserve_partial_output else None,
            )

    def _exec_search_web(self, params: dict) -> ToolExecutionResult:
        """Search the web via OpenClaw Gateway."""
        start_time = time.time()
        query = params.get("query", "")

        if not query:
            return ToolExecutionResult(
                tool_name="search_web",
                parameters=params,
                success=False,
                output="",
                error="No search query specified",
                start_time=start_time,
                end_time=time.time(),
            )

        res = self.openclaw_client.invoke("search_web", params)

        return ToolExecutionResult(
            tool_name="search_web",
            parameters=params,
            success=res.get("success", False),
            output=res.get("output", ""),
            error=res.get("error"),
            start_time=start_time,
            end_time=time.time(),
        )

    def _exec_scrape_web(self, params: dict) -> ToolExecutionResult:
        """Scrape a webpage via OpenClaw Gateway."""
        start_time = time.time()
        url = params.get("url", "")

        if not url:
            return ToolExecutionResult(
                tool_name="scrape_web",
                parameters=params,
                success=False,
                output="",
                error="No URL specified",
                start_time=start_time,
                end_time=time.time(),
            )

        res = self.openclaw_client.invoke("scrape_web", params)

        return ToolExecutionResult(
            tool_name="scrape_web",
            parameters=params,
            success=res.get("success", False),
            output=res.get("output", ""),
            error=res.get("error"),
            start_time=start_time,
            end_time=time.time(),
        )

    def _exec_delegate(self, params: dict) -> ToolExecutionResult:
        """Dynamically spawn a specialized sub-agent for a mission."""
        start_time = time.time()
        agent_name = params.get("agent_name", "specialist")
        mission_prompt = params.get("mission", "")
        decompose = params.get("decompose", False)

        if not mission_prompt:
            return ToolExecutionResult(
                tool_name="delegate",
                parameters=params,
                success=False,
                output="",
                error="No mission prompt specified",
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            # Import here to avoid circular dependencies
            runtime = getattr(self.coder, "runtime", None)
            if runtime and getattr(runtime, "agent_service", None):
                registry = runtime.agent_service.registry
                executor = runtime.agent_service.executor
                self.coder.agent_registry = registry
            else:
                from aider.agents.executor import AgentExecutor
                from aider.agents.registry import AgentRegistry

                registry = getattr(self.coder, "agent_registry", None)
                if registry is None:
                    registry = AgentRegistry()
                    self.coder.agent_registry = registry

                executor = AgentExecutor(registry, self.io)
            current_depth = getattr(self.coder, "delegation_depth", 0) + 1

            if decompose:
                from aider.agents.decomposition import TaskDecomposer

                decomposer = TaskDecomposer(self.coder)
                # Decompose mission into subtasks
                subtasks = self.async_executor.run(decomposer.decompose(mission_prompt))

                if subtasks:
                    # Run parallel sub-missions
                    results = self.async_executor.run(
                        executor.spawn_parallel(
                            parent_coder=self.coder,
                            subtasks=subtasks,
                            depth=current_depth,
                            model="@speed",
                        )
                    )

                    # Synthesize results into a collective report
                    report = []
                    for i, res in enumerate(results):
                        status = "✅ SUCCESS" if res.success else "❌ FAILED"
                        report.append(
                            f"Sub-mission [{subtasks[i]['name']}]: {status}\n"
                            f"{res.output or res.error}"
                        )

                    return ToolExecutionResult(
                        tool_name="delegate",
                        parameters=params,
                        success=True,
                        output="\n\n".join(report),
                        start_time=start_time,
                        end_time=time.time(),
                    )

            # Standard single delegation (fallback or if decompose=False)
            self.io.tool_output(f"Delegating mission to specialized agent [{agent_name}]...")
            result = self.async_executor.run(
                executor.spawn_and_run(
                    parent_coder=self.coder,
                    task=mission_prompt,
                    name=agent_name,
                    depth=current_depth,
                    model="@speed",
                )
            )

            return ToolExecutionResult(
                tool_name="delegate",
                parameters=params,
                success=True,
                output=f"Agent [{agent_name}] completed mission. Result: {result.output}",
                start_time=start_time,
                end_time=time.time(),
            )
        except Exception as e:
            logger.exception(f"Delegation to {agent_name} failed")
            return ToolExecutionResult(
                tool_name="delegate",
                parameters=params,
                success=False,
                output="",
                error=f"Delegation failed: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
            )

    # =======================================================================
    # Lifecycle Management
    # =======================================================================

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with guaranteed cleanup."""
        self._cleanup()
        return False  # Don't suppress exceptions

    def _cleanup(self):
        """
        Guaranteed cleanup of resources.

        This method MUST NOT raise exceptions - it's called in finally blocks
        and during object destruction. Any errors are logged but suppressed.
        """
        logger.debug("ToolRouterV2 cleanup started")

        # Clean up async executor
        try:
            if hasattr(self, "sandbox") and self.sandbox:
                self.sandbox.cleanup()
        except Exception as e:
            logger.warning(f"Error cleaning up sandbox: {e}")

        # Clean up cost tracker
        try:
            if hasattr(self, "cost_tracker") and self.cost_tracker:
                self.cost_tracker.finalize()
        except Exception as e:
            logger.warning(f"Error finalizing cost tracker: {e}")

        logger.debug("ToolRouterV2 cleanup completed")

    def shutdown(self):
        """Explicit shutdown for non-context-manager usage."""
        self._cleanup()

    def __del__(self):
        """Destructor - last resort cleanup."""
        try:
            self._cleanup()
        except Exception:
            # Cannot raise in destructor
            pass

    # =======================================================================
    # Utility Methods
    # =======================================================================

    def get_stats(self) -> dict:
        """Get execution statistics."""
        return {
            "tool_call_count": self.tool_call_count,
            "max_tool_calls": self.config.max_tool_calls,
            "successful_calls": sum(1 for r in self.execution_history if r.success),
            "failed_calls": sum(1 for r in self.execution_history if not r.success),
            "total_duration_ms": sum(r.duration_ms or 0 for r in self.execution_history),
            "current_cost": self.cost_tracker.current_cost if hasattr(self, "cost_tracker") else 0,
            "max_cost": self.config.max_cost,
        }

    def get_execution_history(self, limit: Optional[int] = None) -> list[ToolExecutionResult]:
        """Get recent execution history."""
        history = self.execution_history
        if limit:
            history = history[-limit:]
        return history

    def reset_counters(self):
        """Reset execution counters (for testing)."""
        self.tool_call_count = 0
        self.execution_history.clear()
        if hasattr(self, "cost_tracker"):
            self.cost_tracker.reset()


# =============================================================================
# Convenience Functions
# =============================================================================


def create_router(
    commands: "Commands", io: "InputOutput", coder: "Coder", **config_kwargs
) -> ToolRouterV2:
    """Factory function to create a configured router."""
    config = RouterConfig(**config_kwargs)
    return ToolRouterV2(commands, io, coder, config)


@contextmanager
def router_context(*args, **kwargs):
    """Context manager for router lifecycle."""
    router = create_router(*args, **kwargs)
    try:
        yield router
    finally:
        router.shutdown()
