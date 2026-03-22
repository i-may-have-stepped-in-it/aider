"""
Async compatibility layer for Aider.

Provides async versions of synchronous operations and shared async utilities.
"""

import asyncio
import functools
import queue
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Coroutine, Generic, Optional, TypeVar

T = TypeVar('T')


class GenerationState(Enum):
    """State of background generation."""
    IDLE = auto()
    GENERATING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


@dataclass
class GenerationResult:
    """Result of a background generation."""
    state: GenerationState
    content: Optional[str] = None
    error: Optional[Exception] = None
    messages: list = field(default_factory=list)


class AsyncCallable(Generic[T]):
    """
    Wrapper that provides both sync and async versions of a function.
    
    Usage:
        async_func = AsyncCallable(sync_function)
        
        # Call synchronously (in thread pool)
        result = await async_func(*args)
        
        # Or get the sync version
        sync_result = async_func.sync(*args)
    """
    
    def __init__(self, func: Callable[..., T]):
        self._func = func
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    async def __call__(self, *args, **kwargs) -> T:
        """Call the function asynchronously in a thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, functools.partial(self._func, *args, **kwargs)
        )
    
    def sync(self, *args, **kwargs) -> T:
        """Call the function synchronously."""
        return self._func(*args, **kwargs)


def to_async(func: Callable[..., T]) -> AsyncCallable[T]:
    """Convert a synchronous function to an async callable."""
    return AsyncCallable(func)


async def run_in_thread(func: Callable[..., T], *args, **kwargs) -> T:
    """Run a blocking function in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


class AsyncLock:
    """
    Thread-safe lock for use in async contexts.
    
    This is a wrapper around threading.Lock that provides async-compatible
    context manager support. It uses only thread-safe primitives.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
    
    def acquire(self):
        """Acquire lock (synchronous)."""
        self._lock.acquire()
    
    def release(self):
        """Release lock."""
        self._lock.release()
    
    async def __aenter__(self):
        """Async context entry - runs sync acquire in executor."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._lock.acquire)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context exit."""
        self._lock.release()
    
    def __enter__(self):
        """Sync context entry."""
        self._lock.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Sync context exit."""
        self._lock.release()


class AsyncEvent:
    """Thread-safe event that can be used across sync/async boundaries."""
    
    def __init__(self):
        self._event = threading.Event()
    
    def set(self):
        """Set the event (thread-safe)."""
        self._event.set()
    
    def clear(self):
        """Clear the event (thread-safe)."""
        self._event.clear()
    
    async def wait_async(self, timeout: Optional[float] = None) -> bool:
        """Wait for the event asynchronously."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._event.wait, timeout)
    
    def wait_sync(self, timeout: Optional[float] = None) -> bool:
        """Wait for the event synchronously."""
        return self._event.wait(timeout)
    
    def is_set(self) -> bool:
        """Check if event is set."""
        return self._event.is_set()


class MessageQueue:
    """
    Thread-safe message queue for communication between tasks.
    
    Uses queue.Queue (thread-safe) internally for cross-thread safety.
    Supports both sync and async usage patterns.
    """
    
    def __init__(self, maxsize: int = 100):
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
    
    async def put(self, message: Any) -> None:
        """Put a message in the queue (async wrapper)."""
        self._queue.put(message, block=False)
    
    def put_nowait(self, message: Any) -> bool:
        """Put a message without blocking (thread-safe). Returns True if successful."""
        try:
            self._queue.put_nowait(message)
            return True
        except queue.Full:
            import logging
            logging.getLogger(__name__).warning("MessageQueue full, dropping message")
            return False
    
    async def get(self) -> Any:
        """Get a message from the queue (async wrapper)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._queue.get, True, None)
    
    def get_nowait(self) -> Optional[Any]:
        """Get a message without blocking (thread-safe)."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None
    
    def empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()
    
    def qsize(self) -> int:
        """Get approximate queue size."""
        return self._queue.qsize()


@dataclass
class QueuedMessage:
    """A message queued during generation."""
    text: str
    timestamp: float = field(default_factory=lambda: __import__('time').time())
    
    def __post_init__(self):
        # timestamp is already set by default_factory
        pass


@dataclass
class SteerMessage:
    """A steer message that cancels current generation."""
    text: str
    timestamp: float = field(default_factory=lambda: __import__('time').time())


class TaskManager:
    """
    Manages asyncio tasks with proper cleanup.
    
    Tracks running tasks and provides graceful cancellation.
    """
    
    def __init__(self):
        self._tasks: set[asyncio.Task] = set()
        self._shutdown = False
    
    def create_task(self, coro: Coroutine, name: Optional[str] = None) -> asyncio.Task:
        """Create and track a task."""
        if self._shutdown:
            raise RuntimeError("TaskManager is shutting down")
        
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
    
    async def cancel_all(self, timeout: float = 5.0) -> None:
        """Cancel all tracked tasks."""
        self._shutdown = True
        
        if not self._tasks:
            return
        
        # Cancel all tasks
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        
        # Wait for cancellation with timeout
        if self._tasks:
            done, pending = await asyncio.wait(
                self._tasks,
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED
            )
            # Force cancel any still pending
            for task in pending:
                task.cancel()
    
    async def wait_for(self, task: asyncio.Task, timeout: Optional[float] = None) -> Any:
        """Wait for a specific task with optional timeout."""
        return await asyncio.wait_for(task, timeout=timeout)


class AsyncIteratorWrapper:
    """
    Wraps a synchronous iterator for async consumption.
    
    Useful for converting sync generators (like litellm streaming) to async.
    """
    
    def __init__(self, sync_iterator, loop: Optional[asyncio.AbstractEventLoop] = None):
        self._iterator = sync_iterator
        self._loop = loop or asyncio.get_event_loop()
    
    def __aiter__(self):
        return self
    
    async def __anext__(self):
        try:
            return await self._loop.run_in_executor(None, next, self._iterator)
        except StopIteration:
            raise StopAsyncIteration


def get_running_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Get the currently running event loop, or None if not in async context."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def is_in_async_context() -> bool:
    """Check if we're currently in an async context."""
    return get_running_loop() is not None


class AsyncResource:
    """
    Base class for resources that need async initialization/cleanup.
    
    Subclass and implement:
    - async def initialize(self)
    - async def cleanup(self)
    """
    
    def __init__(self):
        self._initialized = False
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
    
    async def initialize(self):
        """Initialize the resource. Override in subclass."""
        self._initialized = True
    
    async def cleanup(self):
        """Cleanup the resource. Override in subclass."""
        self._initialized = False
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized
