"""
Shared fixtures and utilities for async tests.
"""

import asyncio
import pytest


@pytest.fixture
def event_loop():
    """Create a fresh event loop for each test."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def async_running_prompt_manager():
    """Create an AsyncRunningPromptManager for testing."""
    from aider.async_running_prompt import AsyncRunningPromptManager
    manager = AsyncRunningPromptManager()
    yield manager
    await manager.shutdown()


@pytest.fixture
async def async_prompt_delegate(async_running_prompt_manager):
    """Create an AsyncPromptDelegate for testing."""
    from aider.async_running_prompt import AsyncPromptDelegate
    delegate = AsyncPromptDelegate(async_running_prompt_manager)
    yield delegate


@pytest.fixture
def mock_io():
    """Create a mock IO object for testing."""
    from unittest.mock import MagicMock
    io = MagicMock()
    io.console = MagicMock()
    io.console.print = MagicMock()
    return io


@pytest.fixture
async def message_queue():
    """Create a MessageQueue for testing."""
    from aider.async_compat import MessageQueue
    return MessageQueue()


@pytest.fixture
def async_event():
    """Create an AsyncEvent for testing."""
    from aider.async_compat import AsyncEvent
    return AsyncEvent()


@pytest.fixture
async def task_manager():
    """Create a TaskManager for testing."""
    from aider.async_compat import TaskManager
    tm = TaskManager()
    yield tm
    await tm.cancel_all()


class AsyncTestBase:
    """Base class for async tests with common utilities."""
    
    async def run_with_timeout(self, coro, timeout=5.0):
        """Run a coroutine with a timeout."""
        return await asyncio.wait_for(coro, timeout=timeout)
    
    async def wait_for_condition(self, condition_func, timeout=5.0, interval=0.01):
        """Wait for a condition to become true."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            if condition_func():
                return True
            await asyncio.sleep(interval)
        raise TimeoutError(f"Condition not met within {timeout}s")
