import time

from .router_observability import ToolExecutionResult


class RouterTerminalMixin:
    """Terminal watcher tool handlers."""

    def _exec_terminal_watch_start(self, params):
        """Start a background process for monitoring."""
        start_time = time.time()
        name = params.get("name")
        command = params.get("command")

        if not name or not command:
            return ToolExecutionResult(
                tool_name="terminal_watch_start",
                parameters=params,
                success=False,
                output="",
                error="Name and command are required",
                start_time=start_time,
                end_time=time.time(),
            )

        success = self.terminal_watcher.start_process(name, command, self.coder.root)
        return ToolExecutionResult(
            tool_name="terminal_watch_start",
            parameters=params,
            success=success,
            output=f"Process '{name}' started in background." if success else "",
            error=f"Failed to start process '{name}'" if not success else None,
            start_time=start_time,
            end_time=time.time(),
        )

    def _exec_terminal_watch_read(self, params):
        """Read the latest logs from a background process."""
        start_time = time.time()
        name = params.get("name")
        lines = params.get("lines", 50)

        if not name:
            return ToolExecutionResult(
                tool_name="terminal_watch_read",
                parameters=params,
                success=False,
                output="",
                error="Process name is required",
                start_time=start_time,
                end_time=time.time(),
            )

        logs = self.terminal_watcher.get_logs(name, lines)
        output = "\n".join(logs)
        return ToolExecutionResult(
            tool_name="terminal_watch_read",
            parameters=params,
            success=True,
            output=output,
            start_time=start_time,
            end_time=time.time(),
        )

    def _exec_terminal_watch_input(self, params):
        """Send input to a monitored background process."""
        start_time = time.time()
        name = params.get("name")
        text = params.get("text", "")

        if not name:
            return ToolExecutionResult(
                tool_name="terminal_watch_input",
                parameters=params,
                success=False,
                output="",
                error="Process name is required",
                start_time=start_time,
                end_time=time.time(),
            )

        success = self.terminal_watcher.send_input(name, text)
        return ToolExecutionResult(
            tool_name="terminal_watch_input",
            parameters=params,
            success=success,
            output=f"Sent input to '{name}'." if success else "",
            error=f"Failed to send input to '{name}'" if not success else None,
            start_time=start_time,
            end_time=time.time(),
        )

    def _exec_terminal_watch_signal(self, params):
        """Send a signal to a monitored background process."""
        start_time = time.time()
        name = params.get("name")
        sig = params.get("signal")

        if not name or sig is None:
            return ToolExecutionResult(
                tool_name="terminal_watch_signal",
                parameters=params,
                success=False,
                output="",
                error="Process name and signal are required",
                start_time=start_time,
                end_time=time.time(),
            )

        success = self.terminal_watcher.send_signal(name, int(sig))
        return ToolExecutionResult(
            tool_name="terminal_watch_signal",
            parameters=params,
            success=success,
            output=f"Sent signal {sig} to '{name}'." if success else "",
            error=f"Failed to send signal to '{name}'" if not success else None,
            start_time=start_time,
            end_time=time.time(),
        )

    def _exec_terminal_watch_stop(self, params):
        """Stop a background process."""
        start_time = time.time()
        name = params.get("name")

        if not name:
            return ToolExecutionResult(
                tool_name="terminal_watch_stop",
                parameters=params,
                success=False,
                output="",
                error="Process name is required",
                start_time=start_time,
                end_time=time.time(),
            )

        self.terminal_watcher.stop_process(name)
        return ToolExecutionResult(
            tool_name="terminal_watch_stop",
            parameters=params,
            success=True,
            output=f"Process '{name}' stopped.",
            start_time=start_time,
            end_time=time.time(),
        )
