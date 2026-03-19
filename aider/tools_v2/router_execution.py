import logging
import time
import traceback

from .circuit_breaker import CircuitBreakerOpen
from .router_observability import ToolExecutionResult

logger = logging.getLogger(__name__)


class RouterExecutionMixin:
    """Preflight and resilient execution helpers for the tool router."""

    def _check_limits(self, tool_name: str):
        """Check if execution should proceed based on limits."""
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
        """Execute with circuit breaker and retry logic."""
        start_time = time.time()

        def do_execute() -> ToolExecutionResult:
            return self._do_execute(tool_name, params)

        try:
            result = self.resilient_executor.execute(do_execute)
            result.retry_count = self.resilient_executor.last_retry_count
            return result
        except CircuitBreakerOpen:
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
        """Execute a registered handler with catch-all error shaping."""
        start_time = time.time()
        partial_output = ""

        try:
            handler = self._tools[tool_name]
            result = handler(params)

            if result.end_time is None:
                result.finalize()

            return result
        except Exception as e:
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
