import time


class RouterMCPMixin:
    """Browser and MCP resource handlers."""

    def _exec_browser_action(self, params: dict):
        """Perform interactive browser actions via OpenClaw Gateway."""
        from .router import ToolExecutionResult

        start_time = time.time()

        res = self.openclaw_client.invoke("browser_action", params)

        return ToolExecutionResult(
            tool_name="browser_action",
            parameters=params,
            success=res.get("success", False),
            output=res.get("output", ""),
            error=res.get("error"),
            start_time=start_time,
            end_time=time.time(),
        )

    def _exec_mcp_list_resources(self, params: dict):
        """List all available MCP resources."""
        from .router import ToolExecutionResult

        start_time = time.time()
        resources = self.mcp_manager.get_all_resources()

        output = "Available MCP Resources:\n\n"
        if not resources:
            output = "No MCP resources available."
        else:
            for resource in resources:
                output += f"- {resource.name} ({resource.uri}): {resource.description}\n"

        return ToolExecutionResult(
            tool_name="mcp_list_resources",
            parameters=params,
            success=True,
            output=output,
            start_time=start_time,
            end_time=time.time(),
        )

    def _exec_mcp_read_resource(self, params: dict):
        """Read an MCP resource."""
        from .router import ToolExecutionResult

        start_time = time.time()
        uri = params.get("uri")
        if not uri:
            return ToolExecutionResult(
                tool_name="mcp_read_resource",
                parameters=params,
                success=False,
                output="",
                error="No resource URI specified",
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            res = self.mcp_manager.read_resource(uri)
            output = ""
            for item in res.get("contents", []):
                if "text" in item:
                    output += item["text"]
                elif "blob" in item:
                    output += f"[Binary data: {item.get('mimeType')}]"

            return ToolExecutionResult(
                tool_name="mcp_read_resource",
                parameters=params,
                success=True,
                output=output,
                start_time=start_time,
                end_time=time.time(),
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="mcp_read_resource",
                parameters=params,
                success=False,
                output="",
                error=f"Failed to read resource: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
            )
