import logging
import time

logger = logging.getLogger(__name__)


class RouterSearchMixin:
    """Search and code-intelligence tool handlers."""

    def _exec_search(self, params):
        """
        Search codebase using grep/ripgrep.

        Searches are executed in sandbox for isolation.
        Results are compressed intelligently.
        """
        start_time = time.time()
        query = params.get("query", "")
        path = params.get("path", ".")
        file_pattern = params.get("file_pattern", "*")
        from .router import ToolExecutionResult

        if not query:
            return ToolExecutionResult(
                tool_name="search",
                parameters=params,
                success=False,
                output="",
                error="No search query specified",
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            command = f"grep -r -n --include='{file_pattern}' '{query}' {path} 2>/dev/null || true"
            sandbox_result = self.async_executor.run(
                self.sandbox.execute(["/bin/sh", "-c", command], timeout=30.0)
            )

            output = sandbox_result.output
            if output.strip():
                lines = output.strip().split("\n")
                output = f"Found {len(lines)} matches:\n\n{output}"
            else:
                output = "No matches found."

            if len(output) > self.config.max_output_size:
                output = output[: self.config.max_output_size]
                output += "\n\n[Results truncated]"
                truncated = True
            else:
                truncated = False

            return ToolExecutionResult(
                tool_name="search",
                parameters=params,
                success=True,
                output=output,
                start_time=start_time,
                end_time=time.time(),
                sandbox_result=sandbox_result,
                truncated=truncated,
            )
        except Exception as e:
            logger.exception("Search failed")
            return ToolExecutionResult(
                tool_name="search",
                parameters=params,
                success=False,
                output="",
                error=f"Search failed: {type(e).__name__}: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
            )

    def _exec_find(self, params):
        """Find files by pattern."""
        start_time = time.time()
        pattern = params.get("pattern", "*")
        path = params.get("path", ".")
        from .router import ToolExecutionResult

        try:
            command = f"find {path} -name '{pattern}' -type f 2>/dev/null | head -100"
            sandbox_result = self.async_executor.run(
                self.sandbox.execute(["/bin/sh", "-c", command], timeout=30.0)
            )

            output = sandbox_result.output
            files = [f for f in output.strip().split("\n") if f]
            if files:
                output = f"Found {len(files)} files:\n\n" + "\n".join(files)
            else:
                output = "No files found."

            return ToolExecutionResult(
                tool_name="find",
                parameters=params,
                success=True,
                output=output,
                start_time=start_time,
                end_time=time.time(),
                sandbox_result=sandbox_result,
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="find",
                parameters=params,
                success=False,
                output="",
                error=str(e),
                start_time=start_time,
                end_time=time.time(),
            )

    def _exec_index_search(self, params):
        """Search the global semantic index."""
        start_time = time.time()
        query = params.get("query", "")
        limit = params.get("limit", 5)
        from .router import ToolExecutionResult

        if not query:
            return ToolExecutionResult(
                tool_name="index_search",
                parameters=params,
                success=False,
                output="",
                error="No search query specified",
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            from aider.indexers.semantic import SemanticIndexer

            if hasattr(self.coder, "get_semantic_indexer"):
                indexer = self.coder.get_semantic_indexer(start_background=True)
            else:
                indexer = getattr(self.coder, "semantic_indexer", None)

            if indexer is None:
                indexer = SemanticIndexer.get_global(getattr(self.coder, "root", None))

            results = indexer.query(query, limit=limit)

            if results:
                output = "Matches found in global semantic index:\n\n"
                for path, score in results:
                    output += f"  [{score:.2f}] {path}\n"
            else:
                output = "No matches found in global semantic index."

            return ToolExecutionResult(
                tool_name="index_search",
                parameters=params,
                success=True,
                output=output,
                start_time=start_time,
                end_time=time.time(),
            )
        except Exception as e:
            logger.exception("Global index search failed")
            return ToolExecutionResult(
                tool_name="index_search",
                parameters=params,
                success=False,
                output="",
                error=f"Global index search failed: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
            )

    def _exec_definitions(self, params):
        """Get code definitions using grep-ast."""
        start_time = time.time()
        symbol = params.get("symbol", "")
        from .router import ToolExecutionResult

        if not symbol:
            return ToolExecutionResult(
                tool_name="definitions",
                parameters=params,
                success=False,
                output="",
                error="No symbol specified",
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            if not self.coder.repo_map:
                return ToolExecutionResult(
                    tool_name="definitions",
                    parameters=params,
                    success=False,
                    output="",
                    error="Repository map not available",
                    start_time=start_time,
                    end_time=time.time(),
                )

            other_files = set(self.coder.get_all_abs_files()) - set(self.coder.abs_fnames)
            definitions = self.coder.repo_map.get_repo_map(self.coder.abs_fnames, other_files)
            lines = definitions.splitlines()
            matches = [line for line in lines if symbol in line]
            output = "\n".join(matches) if matches else f"No definitions found for '{symbol}'"

            return ToolExecutionResult(
                tool_name="definitions",
                parameters=params,
                success=True,
                output=output,
                start_time=start_time,
                end_time=time.time(),
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="definitions",
                parameters=params,
                success=False,
                output="",
                error=f"Search failed: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
            )

    def _exec_references(self, params):
        """Get code references using ripgrep."""
        start_time = time.time()
        symbol = params.get("symbol", "")
        from .router import ToolExecutionResult

        if not symbol:
            return ToolExecutionResult(
                tool_name="references",
                parameters=params,
                success=False,
                output="",
                error="No symbol specified",
                start_time=start_time,
                end_time=time.time(),
            )

        try:
            command = f"git grep -n '{symbol}'"
            sandbox_result = self.async_executor.run(
                self.sandbox.execute(["/bin/sh", "-c", command], timeout=30.0)
            )

            return ToolExecutionResult(
                tool_name="references",
                parameters=params,
                success=True,
                output=sandbox_result.output or f"No references found for '{symbol}'",
                start_time=start_time,
                end_time=time.time(),
                sandbox_result=sandbox_result,
            )
        except Exception as e:
            return ToolExecutionResult(
                tool_name="references",
                parameters=params,
                success=False,
                output="",
                error=f"Reference search failed: {str(e)}",
                start_time=start_time,
                end_time=time.time(),
            )
