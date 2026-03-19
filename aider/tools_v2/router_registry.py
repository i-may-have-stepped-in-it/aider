from typing import Callable

from .router_observability import ToolExecutionResult


def build_tool_registry(router) -> dict[str, Callable[[dict], ToolExecutionResult]]:
    """Build the local tool handler registry for a router instance."""
    return {
        "run": router._exec_run,
        "terminal_watch_start": router._exec_terminal_watch_start,
        "terminal_watch_read": router._exec_terminal_watch_read,
        "terminal_watch_input": router._exec_terminal_watch_input,
        "terminal_watch_signal": router._exec_terminal_watch_signal,
        "terminal_watch_stop": router._exec_terminal_watch_stop,
        "shell": router._exec_run,
        "exec": router._exec_run,
        "read": router._exec_read_file,
        "read_file": router._exec_read_file,
        "cat": router._exec_read_file,
        "search": router._exec_search,
        "search_web": router._exec_search_web,
        "scrape_web": router._exec_scrape_web,
        "index_search": router._exec_index_search,
        "delegate": router._exec_delegate,
        "browser_action": router._exec_browser_action,
        "mcp_list_resources": router._exec_mcp_list_resources,
        "mcp_read_resource": router._exec_mcp_read_resource,
        "grep": router._exec_search,
        "find": router._exec_find,
        "edit": router._exec_edit,
        "apply_edit": router._exec_edit,
        "git": router._exec_git,
        "definitions": router._exec_definitions,
        "references": router._exec_references,
        "lint": router._exec_lint,
    }
