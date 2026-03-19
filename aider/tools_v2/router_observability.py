import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .compression import CompressionResult
from .sandbox import SandboxResult

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

    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None

    partial_output: Optional[str] = None
    sandbox_result: Optional[SandboxResult] = None
    compression_result: Optional[CompressionResult] = None

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
        """Convert to structured log format."""
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


class RouterObservabilityMixin:
    """Logging, audit, and stats helpers shared by the router."""

    def _log_result(self, result: ToolExecutionResult) -> None:
        """Log execution result with appropriate level."""
        log_data = result.to_log_dict()

        if result.success:
            logger.info("Tool execution completed", extra=log_data)
        else:
            logger.error("Tool execution failed", extra=log_data)

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
