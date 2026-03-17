"""
ToolEnabledCoder v2 - Production-Ready Agent Mode

Complete rewrite addressing ALL issues from Principal Engineer critique:
1. Fixed async/sync architecture - uses AsyncExecutor properly
2. Accurate cost tracking with 25% safety margin
3. Circuit breakers prevent cascade failures
4. Semantic compression instead of naive truncation
5. Comprehensive observability and structured logging
6. Guaranteed resource cleanup
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional, TYPE_CHECKING

from .base_coder import Coder

# v2 tool system
from ..tools_v2 import (
    ToolRouterV2,
    ToolExecutionResult,
    AccurateCostTracker,
    CircuitBreaker,
    CircuitState,
)
from ..tools_v2.circuit_breaker import CircuitBreakers
from ..tools_v2.router import RouterConfig

if TYPE_CHECKING:
    from aider.models import Model
    from aider.io import InputOutput


logger = logging.getLogger(__name__)


class ToolEnabledCoderV2(Coder):
    """
    Production-ready coder with LLM tool use for autonomous execution.
    
    This is a complete rewrite of ToolEnabledCoder addressing all issues
    identified in the Principal Engineer design review.
    
    Key Improvements over v1:
    - Proper async/sync boundary via AsyncExecutor (no nested asyncio.run)
    - Accurate cost tracking with overhead accounting and safety margins
    - Circuit breakers prevent cascade failures on API degradation
    - Semantic output compression preserves important context
    - Comprehensive structured logging for observability
    - Guaranteed resource cleanup even on crashes
    - Partial result capture for debugging failed operations
    
    Safety Features:
    - Budget enforcement with warnings at 50%, 80%, 90%, 95%
    - Iteration limits prevent infinite loops
    - Circuit breaker opens after 3 consecutive failures
    - All shell execution sandboxed (firejail/unshare)
    - Risk-based confirmation for destructive operations
    
    Configuration:
        AIDER_MAX_TOOL_CALLS: Maximum tool calls (default: 50)
        AIDER_MAX_TOOL_COST: Maximum cost in dollars (default: $5.00)
        AIDER_TOOL_SANDBOX: Sandbox type (auto/firejail/unshare/minimal)
        AIDER_CIRCUIT_BREAKER_THRESHOLD: Failures before opening (default: 3)
        AIDER_COST_SAFETY_MARGIN: Budget buffer percentage (default: 0.25)
    
    Usage:
        coder = ToolEnabledCoderV2.create(
            main_model=model,
            io=io,
            fnames=["main.py"]
        )
        
        # Interactive mode (confirms each tool)
        coder.run("Find and fix all TODOs")
        
        # Autonomous mode (auto-executes safe tools)
        coder.auto_confirm = True
        coder.run("Refactor authentication module")
    """
    
    edit_format = "tool-v2"
    
    # Configuration defaults with environment overrides
    DEFAULT_MAX_TOOL_CALLS = int(os.getenv("AIDER_MAX_TOOL_CALLS", "50"))
    DEFAULT_MAX_TOOL_COST = float(os.getenv("AIDER_MAX_TOOL_COST", "5.0"))
    DEFAULT_SANDBOX_TYPE = os.getenv("AIDER_TOOL_SANDBOX", "auto")
    DEFAULT_CIRCUIT_THRESHOLD = int(os.getenv("AIDER_CIRCUIT_BREAKER_THRESHOLD", "3"))
    DEFAULT_SAFETY_MARGIN = float(os.getenv("AIDER_COST_SAFETY_MARGIN", "0.25"))
    
    def __init__(
        self,
        main_model: Model,
        io: InputOutput,
        *args,
        auto_confirm: bool = False,
        max_tool_calls: Optional[int] = None,
        max_tool_cost: Optional[float] = None,
        sandbox_type: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize tool-enabled coder v2.
        
        Args:
            main_model: The LLM model to use
            io: InputOutput for user interaction
            auto_confirm: If True, execute tools without confirmation
            max_tool_calls: Maximum number of tool calls (None = use env/default)
            max_tool_cost: Maximum cost in dollars (None = use env/default)
            sandbox_type: Sandbox type (None = use env/default)
            *args, **kwargs: Passed to BaseCoder
        """
        super().__init__(main_model, io, *args, **kwargs)
        
        # Configuration
        self.auto_confirm = auto_confirm
        self.max_tool_calls = max_tool_calls or self.DEFAULT_MAX_TOOL_CALLS
        self.max_tool_cost = max_tool_cost or self.DEFAULT_MAX_TOOL_COST
        sandbox = sandbox_type or self.DEFAULT_SANDBOX_TYPE
        
        # Core infrastructure - v2
        router_config = RouterConfig(
            sandbox_type=sandbox,
            max_tool_calls=self.max_tool_calls,
            max_cost=self.max_tool_cost,
        )
        self.tool_router = ToolRouterV2(
            commands=self.commands,
            io=io,
            coder=self,
            config=router_config,
        )
        
        # Circuit breaker for LLM API calls
        self.llm_circuit = CircuitBreakers.llm_api()
        
        # State
        self.tool_call_count = 0
        self._in_tool_loop = False
        self._last_error: Optional[str] = None
        
        logger.info(
            "ToolEnabledCoderV2 initialized",
            extra={
                "max_tool_calls": self.max_tool_calls,
                "max_tool_cost": self.max_tool_cost,
                "sandbox_type": sandbox,
                "auto_confirm": auto_confirm,
            }
        )
    
    def get_system_prompt(self) -> str:
        """Get system prompt with tool usage instructions."""
        base = super().get_system_prompt() if hasattr(super(), 'get_system_prompt') else ""
        
        tool_instructions = """

## Available Tools

You have access to tools to help complete tasks efficiently:

- `run`: Execute shell commands (tests, linters, git operations)
- `read_file`: Read file contents with optional line range
- `search`: Search for patterns across the codebase
- `edit`: Apply edits to files
- `git`: Run git commands
- `definitions`: Find symbol definitions
- `references`: Find symbol references
- `lint`: Run linting on files

## Tool Usage Guidelines

1. **Explore first**: Use `search` and `read_file` to understand code
2. **Make changes**: Use `edit` for file modifications
3. **Verify**: Use `run` to execute tests and linters
4. **Commit**: Use `git` to manage version control

Tools execute automatically when safe. Destructive operations require confirmation.
"""
        return base + tool_instructions
    
    def run(self, with_message: Optional[str] = None) -> Optional[str]:
        """
        Run with potential tool execution.
        
        This method implements the full tool loop with:
        - Budget checking before each iteration
        - Circuit breaker protection for LLM calls
        - Tool execution with retry logic
        - Semantic output compression
        - Cost tracking with safety margins
        - Comprehensive logging
        
        Args:
            with_message: Initial user message to process
            
        Returns:
            Final response content, or None if interrupted/budget exceeded
            
        Raises:
            CircuitBreakerOpenError: If LLM API is failing repeatedly
            BudgetExceededError: If cost limit reached
            MaxIterationsError: If tool call limit reached
        """
        if not with_message:
            return super().run()
        
        self._in_tool_loop = True
        self._last_error = None
        
        try:
            # Build initial messages
            messages = self._build_messages(with_message)
            
            # Main tool loop
            while self.tool_call_count < self.max_tool_calls:
                # Check budget with safety margin
                ok, reason = self.tool_router.cost_tracker.check_budget()
                if not ok:
                    logger.warning(f"Budget check failed: {reason}")
                    self.io.tool_error(f"Stopping: {reason}")
                    self._last_error = reason
                    return None

                # Begin cost tracking iteration (required before record_llm_call/record_tool_result)
                self.tool_router.cost_tracker.start_iteration()

                # Execute LLM call with circuit breaker
                try:
                    response = self.llm_circuit.call(
                        self._send_with_tools,
                        messages
                    )
                except Exception as e:
                    logger.error(f"LLM call failed: {e}", exc_info=True)
                    self._last_error = str(e)
                    self.tool_router.cost_tracker.end_iteration()
                    raise

                # Track cost — extract usage dict from LiteLLM response object
                usage = getattr(response, 'usage', None)
                usage_dict = {
                    "prompt_tokens": getattr(usage, 'prompt_tokens', 0) if usage else 0,
                    "completion_tokens": getattr(usage, 'completion_tokens', 0) if usage else 0,
                }
                message = response.choices[0].message
                tool_calls = getattr(message, 'tool_calls', None)
                self.tool_router.cost_tracker.record_llm_call(
                    usage=usage_dict,
                    num_tool_calls=len(tool_calls) if tool_calls else 0,
                    system_prompt=self.get_system_prompt(),
                )

                if not tool_calls:
                    # No tools - finalize iteration and return final response
                    self.tool_router.cost_tracker.end_iteration()
                    return self._process_final_response(message.content, messages)

                # Execute tools
                self.tool_call_count += len(tool_calls)

                # Add assistant message with tool calls
                messages.append(self._format_assistant_message(message, tool_calls))

                # Execute each tool
                for tool_call in tool_calls:
                    result = self._execute_tool(tool_call)

                    # Track tool result cost
                    self.tool_router.cost_tracker.record_tool_result(result.output)

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": result.output if result.success else f"Error: {result.error}"
                    })

                # Finalize iteration
                self.tool_router.cost_tracker.end_iteration()

                # Check for warnings
                warnings = self.tool_router.cost_tracker.get_warnings()
                for warning in warnings:
                    self.io.tool_warning(warning)
            
            # Max iterations reached
            logger.warning(f"Max tool calls ({self.max_tool_calls}) reached")
            self.io.tool_warning(
                f"Max tool calls ({self.max_tool_calls}) reached. "
                "Task may be incomplete."
            )
            self._last_error = "max_iterations"
            return None
            
        finally:
            self._in_tool_loop = False
            self._print_summary()
    
    def _build_messages(self, user_message: str) -> list[dict]:
        """Build initial message list."""
        messages = []
        
        # System prompt
        system = self.get_system_prompt()
        if system:
            messages.append({"role": "system", "content": system})
        
        # Repo context
        if self.repo_map:
            repo_content = self.repo_map.get_repo_map(
                self.abs_fnames,
                set(self.get_all_abs_files()) - set(self.abs_fnames)
            )
            if repo_content:
                messages.append({
                    "role": "system",
                    "content": f"Repository structure:\n{repo_content}"
                })
        
        # File contents
        for fname in self.abs_fnames:
            content = self.io.read_text(fname)
            if content:
                rel_fname = self.get_rel_fname(fname)
                messages.append({
                    "role": "system",
                    "content": f"File: {rel_fname}\n```\n{content}\n```"
                })
        
        # User message
        messages.append({"role": "user", "content": user_message})
        
        return messages
    
    def _send_with_tools(self, messages: list[dict]) -> Any:
        """Send messages to LLM with merged tool definitions."""
        from ..llm import litellm
        from ..tools.schema import ToolSchemaGenerator
        
        # Local tools (including MCP if self passed)
        tools = ToolSchemaGenerator.generate_all(self)
        
        # Upstream tools (Skill Awareness)
        upstream_tools = ToolSchemaGenerator.fetch_upstream_tools()
        if upstream_tools:
            # Merge upstream tools - upstream overrides local for same name
            local_names = {t["function"]["name"] for t in tools}
            for up in upstream_tools:
                up_name = up["function"]["name"]
                if up_name in local_names:
                    # Remove local one to prefer upstream
                    tools = [t for t in tools if t["function"]["name"] != up_name]
                tools.append(up)
                
        return litellm.completion(
            model=self.main_model.name,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=self.temperature,
        )
    
    def _format_assistant_message(self, message: Any, tool_calls: list) -> dict:
        """Format assistant message with tool calls."""
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in tool_calls
            ]
        }
    
    def _execute_tool(self, tool_call: Any) -> ToolExecutionResult:
        """Execute a single tool call."""
        name = tool_call.function.name
        
        try:
            params = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid tool arguments: {e}")
            return ToolExecutionResult(
                tool_name=name,
                parameters={},
                success=False,
                output="",
                error=f"Invalid arguments: {e}"
            )
        
        # Check auto-confirm
        if not self.auto_confirm:
            from ..tools.risk import get_tool_risk, RiskLevel
            risk = get_tool_risk(name, params)
            if risk in (RiskLevel.RISKY, RiskLevel.DANGEROUS):
                confirmed = self.io.confirm_ask(
                    f"Allow {risk.name} tool: {name}?",
                    default="n"
                )
                if not confirmed:
                    return ToolExecutionResult(
                        tool_name=name,
                        parameters=params,
                        success=False,
                        output="",
                        error="Declined by user"
                    )
        
        # Execute via router
        return self.tool_router.execute(name, params)
    
    def _process_final_response(self, content: Optional[str], messages: list) -> Optional[str]:
        """Process final LLM response."""
        if not content:
            return None
        
        # Apply edits if any
        edited = self.apply_updates(content)
        if edited:
            self.aider_edited_files.update(self.get_edited_files())
        
        return content
    
    def _print_summary(self):
        """Print execution summary."""
        tracker = self.tool_router.cost_tracker
        
        lines = [
            "",
            "=== Execution Summary ===",
            f"Tool calls: {self.tool_call_count} / {self.max_tool_calls}",
            f"Budget: ${tracker.consumed_budget:.2f} consumed, "
            f"${tracker.available_budget:.2f} available",
        ]
        
        if tracker.estimated_total_cost > tracker.max_budget * 0.8:
            lines.append(f"⚠️  Estimated total: ${tracker.estimated_total_cost:.2f}")
        
        if self._last_error:
            lines.append(f"Stopped: {self._last_error}")
        
        for line in lines:
            self.io.tool_output(line)
    
    def shutdown(self):
        """Clean shutdown releasing all resources."""
        logger.info("Shutting down ToolEnabledCoderV2")
        if hasattr(self, 'tool_router'):
            self.tool_router.shutdown()
    
    def __del__(self):
        """Destructor ensuring cleanup."""
        try:
            self.shutdown()
        except:
            pass
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with guaranteed cleanup."""
        self.shutdown()
        return False
