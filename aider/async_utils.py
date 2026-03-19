"""
Shared async helpers for bridging synchronous call sites into async code.
"""

from __future__ import annotations

from aider.tools_v2.async_executor import AsyncExecutor


def run_async_safely(coro, timeout=30.0):
    """
    Safely run an async coroutine from synchronous code.

    This delegates to the shared AsyncExecutor singleton so sync-to-async
    bridging follows the same execution policy across the codebase.
    """
    return AsyncExecutor().run(coro, timeout=timeout)
