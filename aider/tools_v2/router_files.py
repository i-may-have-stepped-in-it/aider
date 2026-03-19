import time
from pathlib import Path


class RouterFileOpsMixin:
    """File, edit, git, and lint handlers."""

    def _exec_read_file(self, params):
        """Read file with pagination and smart compression."""
        from .router import ToolExecutionResult

        start_time = time.time()
        file_path = params.get("path", "")
        offset = params.get("offset", 0)
        limit = params.get("limit", None)

        if not file_path:
            return ToolExecutionResult(
                tool_name="read_file",
                parameters=params,
                success=False,
                output="",
                error="No file path specified",
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            path = Path(file_path)
            if not path.exists():
                return ToolExecutionResult(
                    tool_name="read_file",
                    parameters=params,
                    success=False,
                    output="",
                    error=f"File not found: {file_path}",
                    start_time=start_time,
                    end_time=time.time(),
                )

            content = path.read_text(encoding="utf-8", errors="replace")
            total_lines = content.count("\n") + 1

            if offset or limit:
                lines = content.split("\n")
                if offset:
                    lines = lines[offset:]
                if limit:
                    lines = lines[:limit]
                content = "\n".join(lines)
                pagination_info = f"[Lines {offset + 1}-{offset + len(lines)} of {total_lines}]\n"
                content = pagination_info + content

            compressed = False
            truncated = False
            compression_result = None

            if self.config.enable_compression and len(content) > self.config.compression_threshold:
                compression_result = self.compressor.compress(content)
                content = compression_result.compressed_text
                compressed = True
                truncated = compression_result.was_truncated

            return ToolExecutionResult(
                tool_name="read_file",
                parameters=params,
                success=True,
                output=content,
                start_time=start_time,
                end_time=time.time(),
                compression_result=compression_result,
                truncated=truncated,
                compressed=compressed,
            )
        except Exception as e:
            self.io.tool_error(f"Failed to read file: {file_path}") if hasattr(self.io, "tool_error") else None
            return ToolExecutionResult(
                tool_name="read_file",
                parameters=params,
                success=False,
                output="",
                error=f"Read failed: {type(e).__name__}: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
            )

    def _exec_edit(self, params):
        """Apply edit to file."""
        from .router import ToolExecutionResult

        start_time = time.time()
        path = params.get("path")
        content = params.get("content")

        if not path or not content:
            return ToolExecutionResult(
                tool_name="edit",
                parameters=params,
                success=False,
                output="",
                error="Path and content are required",
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            rel_path = self.coder.get_rel_fname(path)
            edit_prompt = f"Apply this change to {rel_path}:\n\n{content}"
            self.coder.run(with_message=edit_prompt)

            return ToolExecutionResult(
                tool_name="edit",
                parameters=params,
                success=True,
                output=f"Successfully applied edit to {rel_path}",
                start_time=start_time,
                end_time=time.time(),
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="edit",
                parameters=params,
                success=False,
                output="",
                error=f"Failed to apply edit: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
            )

    def _exec_git(self, params):
        """Execute git command."""
        from .router import ToolExecutionResult

        start_time = time.time()
        subcommand = params.get("command", "")

        if not subcommand:
            return ToolExecutionResult(
                tool_name="git",
                parameters=params,
                success=False,
                output="",
                error="No git command specified",
                start_time=start_time,
                end_time=time.time(),
            )

        blocked_commands = {"push", "reset", "clean", "rebase", "filter-branch", "filter-repo"}
        if subcommand.split()[0] in blocked_commands:
            return ToolExecutionResult(
                tool_name="git",
                parameters=params,
                success=False,
                output="",
                error=(
                    f"Git command '{subcommand.split()[0]}' is blocked (destructive). "
                    "Use aider commit tools instead."
                ),
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            command_list = ["/bin/sh", "-c", f"git {subcommand}"]
            sandbox_result = self.async_executor.run(
                self.sandbox.execute(command_list, timeout=30.0)
            )

            return ToolExecutionResult(
                tool_name="git",
                parameters=params,
                success=sandbox_result.success,
                output=sandbox_result.output,
                exit_code=sandbox_result.exit_code,
                error=sandbox_result.error,
                start_time=start_time,
                end_time=time.time(),
                sandbox_result=sandbox_result,
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="git",
                parameters=params,
                success=False,
                output="",
                error=str(e),
                start_time=start_time,
                end_time=time.time(),
            )

    def _exec_lint(self, params):
        """Run linter on file."""
        from .router import ToolExecutionResult

        start_time = time.time()
        file_path = params.get("path", "")

        if not file_path:
            return ToolExecutionResult(
                tool_name="lint",
                parameters=params,
                success=False,
                output="",
                error="No file path specified",
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            path = Path(file_path)
            if path.suffix == ".py":
                command = f"python -m py_compile {file_path} 2>&1 || true"
            else:
                return ToolExecutionResult(
                    tool_name="lint",
                    parameters=params,
                    success=False,
                    output="",
                    error=f"No linter configured for {path.suffix} files",
                    start_time=start_time,
                    end_time=time.time(),
                )

            sandbox_result = self.async_executor.run(
                self.sandbox.execute(["/bin/sh", "-c", command], timeout=30.0)
            )

            success = sandbox_result.exit_code == 0
            output = sandbox_result.output or "No linting errors found."

            return ToolExecutionResult(
                tool_name="lint",
                parameters=params,
                success=success,
                output=output,
                exit_code=sandbox_result.exit_code,
                error=sandbox_result.error if not success else None,
                start_time=start_time,
                end_time=time.time(),
                sandbox_result=sandbox_result,
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="lint",
                parameters=params,
                success=False,
                output="",
                error=str(e),
                start_time=start_time,
                end_time=time.time(),
            )
