"""
Tool-enabled coder with native LLM function calling.

This module extends BaseCoder to support LLM tool use via native function calling
(OpenAI/Anthropic/Gemini), enabling autonomous agent behavior.

Key design decisions:
1. Extends BaseCoder - no parallel loop architecture
2. Sync-first with isolated async for I/O operations
3. Tool loop with budget and iteration limits
4. Comprehensive cost tracking (including tool output)
5. Output truncation to prevent context overflow

Architecture:
```
User prompt -> Coder.run() -> Tool loop -> LLM with tools
                     ^                        |
                     |                        v
              Tool results <- ToolRouter <- Tool calls
```
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Optional

from .base_coder import Coder
# UPGRADED: Using Tools V2 for production resilience
from ..tools.schema import ToolSchemaGenerator
from ..tools_v2.router import ToolRouterV2, RouterConfig
from ..tools_v2.cost_tracker import AccurateCostTracker
from ..tools.risk import RiskLevel

if TYPE_CHECKING:
    from aider.models import Model
    from aider.io import InputOutput


class ToolEnabledCoder(Coder):
    """
    Coder that enables LLM tool use for autonomous task execution.
    
    This coder extends the base Coder with a tool execution loop. When the LLM
    requests tool calls, they are executed and results returned to the LLM,
    which can then request more tools or provide a final response.
    
    Safety features:
    - Cost limits with warnings at 50%, 80%, 90%
    - Iteration limits to prevent infinite loops
    - Output truncation to prevent context overflow
    - Risk-based confirmation for destructive operations
    - Sandboxed shell execution
    
    Usage:
        coder = ToolEnabledCoder.create(
            main_model=model,
            io=io,
            auto_confirm_tools=False,  # Ask before each tool
            max_tool_calls=20,
            max_tool_cost=5.0
        )
        coder.run(with_message="Find all TODO comments and create issues")
    
    Configuration via environment variables:
        AIDER_MAX_TOOL_CALLS: Maximum tool calls per session (default: 50)
        AIDER_MAX_TOOL_COST: Maximum cost in dollars (default: 5.0)
        AIDER_TOOL_SANDBOX: Sandbox type - auto/firejail/unshare/none
    """
    
    edit_format = "tool"
    
    # Default limits
    DEFAULT_MAX_TOOL_CALLS = 50
    DEFAULT_MAX_TOOL_COST = 5.0  # $5
    DEFAULT_RISK_THRESHOLD = RiskLevel.RISKY
    
    def __init__(
        self,
        main_model: Model,
        io: InputOutput,
        *args,
        auto_confirm_tools: bool = False,
        max_tool_calls: Optional[int] = None,
        max_tool_cost: Optional[float] = None,
        risk_confirm_threshold: RiskLevel = DEFAULT_RISK_THRESHOLD,
        sandbox_type: str = "auto",
        **kwargs
    ):
        """
        Initialize tool-enabled coder.
        
        Args:
            main_model: The LLM model to use
            io: InputOutput for user interaction
            auto_confirm_tools: If True, execute tools without asking
            max_tool_calls: Maximum number of tool calls (None = no limit)
            max_tool_cost: Maximum cost in dollars (None = no limit)
            risk_confirm_threshold: Minimum risk level requiring confirmation
            sandbox_type: Sandbox type for shell commands
            *args, **kwargs: Passed to BaseCoder
        """
        super().__init__(main_model, io, *args, **kwargs)
        
        # Configuration with env var overrides (MUST be set before RouterConfig)
        self.auto_confirm_tools = auto_confirm_tools
        self.max_tool_calls = max_tool_calls or int(
            os.getenv("AIDER_MAX_TOOL_CALLS", self.DEFAULT_MAX_TOOL_CALLS)
        )
        self.max_tool_cost = max_tool_cost or float(
            os.getenv("AIDER_MAX_TOOL_COST", self.DEFAULT_MAX_TOOL_COST)
        )
        
        # Tool infrastructure
        self.tools = ToolSchemaGenerator.generate_all()
        # UPGRADED: ToolRouterV2 with circuit breakers, accurate cost tracking,
        # async execution, and comprehensive observability
        router_config = RouterConfig(
            sandbox_type=sandbox_type,
            max_tool_calls=self.max_tool_calls,
            max_cost=self.max_tool_cost,
            default_timeout=60.0,
            enable_compression=True,
            preserve_partial_output=True,
        )
        self.tool_router = ToolRouterV2(
            commands=self.commands,
            io=io,
            coder=self,
            config=router_config,
        )
        
        # UPGRADED: AccurateCostTracker with overhead accounting and safety margins
        self.cost_tracker = AccurateCostTracker(max_budget=self.max_tool_cost)
        
        # State
        self.tool_call_count = 0
        self._tool_mode = False  # True when in tool loop
    
    def get_system_prompt(self) -> str:
        """Get system prompt with tool usage instructions."""
        # Get base system prompt if available
        try:
            base = super().get_system_prompt()
        except AttributeError:
            # Base class doesn't have get_system_prompt
            base = self.gpt_prompts.main_system if hasattr(self, 'gpt_prompts') else ""
        
        # Add tool instructions
        tool_help = """

You have access to tools to help complete tasks:

- `run`: Execute shell commands (tests, linters, git, etc.)
- `add`: Add files to the chat context
- `read_file`: Read file contents with pagination
- `search`: Search for patterns in the codebase
- `git`: Run git commands
- `ls`: List files in a directory
- `drop`: Remove files from context
- `commit`: Commit changes to git

Use these tools proactively when you need to:
1. Explore the codebase (ls, read_file, search)
2. Run tests or linting (run)
3. Check git status (git)
4. Add relevant files to context (add)

After each tool call, you'll see the result and can continue.
"""
        return base + tool_help
    
    def run(self, with_message: str | None = None) -> str | None:
        """
        Run with potential tool usage.
        
        This extends the base Coder.run() with a tool execution loop.
        If the LLM requests tool calls, they are executed and results
        returned, allowing the LLM to continue iteratively.
        
        Args:
            with_message: Initial user message
            
        Returns:
            Final response content, or None if interrupted
        """
        if not with_message:
            # No message, run normal coder flow
            return super().run()
        
        # Enter tool mode
        self._tool_mode = True
        self.tool_call_count = 0
        
        try:
            # Build initial messages
            messages = self._build_initial_messages(with_message)
            
            # Tool execution loop
            iteration = 0
            while self.tool_call_count < self.max_tool_calls:
                # Check cost budget
                if self.cost_tracker.is_budget_exceeded():
                    self.io.tool_warning(
                        f"Tool cost limit (${self.max_tool_cost:.2f}) exceeded. "
                        "Stopping to prevent runaway costs."
                    )
                    break
                
                # Start tracking this iteration
                self.cost_tracker.start_iteration(iteration)
                
                # Get LLM response with tools
                response = self._send_with_tools(messages)
                
                # Track LLM cost
                self.cost_tracker.record_llm_cost(
                    response,
                    self.main_model.info
                )
                
                # Extract message
                message = response.choices[0].message
                
                # Check for tool calls
                tool_calls = getattr(message, 'tool_calls', None)
                
                if not tool_calls:
                    # No tools - normal response, process and return
                    return self._process_final_response(message.content, messages)
                
                # Execute tool calls
                self.tool_call_count += len(tool_calls)
                
                # Add assistant message with tool calls
                messages.append(self._format_assistant_message(message, tool_calls))
                
                # Execute each tool and collect results
                for tool_call in tool_calls:
                    result = self._execute_tool_call(tool_call)
                    
                    # Track tool output cost (becomes input to next LLM call)
                    self.cost_tracker.record_tool_output(result.output)
                    
                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result.output if result.success else f"Error: {result.error}"
                    })
                
                # End iteration tracking
                self.cost_tracker.end_iteration()
                iteration += 1
                
                # Warn about budget
                remaining = self.cost_tracker.remaining_budget
                if remaining < self.max_tool_cost * 0.2:  # Less than 20% remaining
                    self.io.tool_warning(
                        f"Tool budget running low: ${remaining:.2f} remaining"
                    )
                
                # Continue loop for next LLM response
                continue
            
            # Max iterations reached
            if self.tool_call_count >= self.max_tool_calls:
                self.io.tool_warning(
                    f"Max tool calls ({self.max_tool_calls}) reached. "
                    "Task may be incomplete."
                )
            
            return None
            
        finally:
            self._tool_mode = False
            
            # Print cost summary
            if self.cost_tracker.total_cost > 0:
                self.io.tool_output(self.cost_tracker.get_summary())
    
    def _build_initial_messages(self, user_message: str) -> list[dict]:
        """Build initial message list including system prompt."""
        messages = []
        
        # System prompt
        system_content = self.get_system_prompt()
        if system_content:
            messages.append({
                "role": "system",
                "content": system_content
            })
        
        # Add repo map if available
        if self.repo_map:
            repo_content = self.repo_map.get_repo_map(
                self.abs_fnames,
                set(self.get_all_abs_files()) - set(self.abs_fnames)
            )
            if repo_content:
                messages.append({
                    "role": "system",
                    "content": f"Repository map:\n{repo_content}"
                })
        
        # Add file context
        for fname in self.abs_fnames:
            content = self.io.read_text(fname)
            if content:
                rel_fname = self.get_rel_fname(fname)
                messages.append({
                    "role": "system",
                    "content": f"File {rel_fname}:\n```\n{content}\n```"
                })
        
        # User message
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        return messages
    
    def _send_with_tools(self, messages: list[dict]) -> Any:
        """
        Send messages to LLM with tool definitions.
        
        Args:
            messages: Conversation history
            
        Returns:
            LLM response object
        """
        from ..llm import litellm
        
        # Prepare parameters
        kwargs = {
            "model": self.main_model.name,
            "messages": messages,
            "tools": self.tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
        }
        
        # Add stream parameter if supported
        if getattr(self, "yield_stream", False):
            kwargs["stream"] = True
        
        # Make request
        response = litellm.completion(**kwargs)
        
        return response
    
    def _format_assistant_message(
        self,
        message: Any,
        tool_calls: list[Any]
    ) -> dict:
        """Format assistant message with tool calls for conversation history."""
        formatted_calls = []
        for tc in tool_calls:
            formatted_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            })
        
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": formatted_calls
        }
    
    def _execute_tool_call(self, tool_call: Any) -> Any:
        """
        Execute a single tool call.
        
        Args:
            tool_call: Tool call from LLM response
            
        Returns:
            ToolResult
        """
        # Parse tool call
        name = tool_call.function.name
        try:
            params = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            return self.tool_router.execute("run", {
                "command": f"echo 'Invalid tool arguments: {e}'",
                "timeout": 1
            })
        
        # Execute via router
        return self.tool_router.execute(name, params)
    
    def _process_final_response(
        self,
        content: str | None,
        messages: list[dict]
    ) -> str | None:
        """
        Process final LLM response (no tools).
        
        This applies edits and updates coder state like normal aider flow.
        
        Args:
            content: Response content
            messages: Full conversation history
            
        Returns:
            Processed content
        """
        if not content:
            return None
        
        # Apply normal aider processing (edit extraction, etc.)
        # This calls the base coder's logic for handling responses
        self.partial_response_content = content
        
        # Process any edits in the response
        edited = self.apply_updates(content)
        
        if edited:
            self.aider_edited_files.update(self.get_edited_files())
        
        # Return final content
        return content
    
    def apply_updates(self, content: str = None) -> bool:
        """
        Apply updates from LLM response.
        
        Override to handle tool-enabled responses.
        """
        # Set partial_response_content if content provided
        if content:
            self.partial_response_content = content
        # For now, use base implementation
        # In future, could add special handling for tool results
        return super().apply_updates()
    
    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    
    def get_tool_summary(self) -> str:
        """Get summary of tool usage for this session."""
        lines = [
            f"Tool Mode: {'Active' if self._tool_mode else 'Inactive'}",
            f"Tool Calls: {self.tool_call_count} / {self.max_tool_calls}",
            ""
        ]
        
        # UPGRADED: Get stats from ToolRouterV2
        stats = self.tool_router.get_stats()
        lines.append(f"Successful calls: {stats.get('successful_calls', 0)}")
        lines.append(f"Failed calls: {stats.get('failed_calls', 0)}")
        lines.append(f"Total duration: {stats.get('total_duration_ms', 0):.0f}ms")
        
        # Add cost summary
        lines.append("")
        lines.append(self.cost_tracker.get_summary())
        
        return "\n".join(lines)
    
    def is_tool_mode(self) -> bool:
        """Check if currently in tool execution mode."""
        return self._tool_mode
