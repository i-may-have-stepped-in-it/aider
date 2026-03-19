import logging
import time

from .router_observability import ToolExecutionResult

logger = logging.getLogger(__name__)


class RouterDispatchMixin:
    """Helpers for router dispatch flow without changing execution semantics."""

    def _try_execute_dynamic_tool(
        self, tool_name: str, params: dict, start_time: float
    ) -> ToolExecutionResult | None:
        """Execute an MCP-provided tool if one is registered dynamically."""
        for server in self.mcp_manager.servers.values():
            for mcp_tool in server.tools:
                if mcp_tool.name != tool_name:
                    continue

                try:
                    res = server.call_tool(tool_name, params)
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

        return None

    def _build_unknown_tool_result(
        self, tool_name: str, params: dict, start_time: float
    ) -> ToolExecutionResult:
        """Build and log the result for an unknown local tool."""
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

    def _record_execution_result(self, tool_name: str, result: ToolExecutionResult) -> ToolExecutionResult:
        """Log, persist, and emit UI completion for a local tool execution result."""
        self._log_result(result)
        self.execution_history.append(result)

        if result.success:
            self._trigger_ui_tool(tool_name, "complete")
        else:
            self._trigger_ui_tool(tool_name, "failed")

        return result
