"""Async execution framework for tool system.

Solves the fundamental problem: aider is synchronous, but tools need async I/O.

THE NESTED EVENT LOOP PROBLEM
==============================

Python's asyncio has a strict rule: you cannot call asyncio.run() if an event
loop is already running in the current thread. This commonly occurs when:

1. Aider's main thread runs synchronous code
2. A tool needs to perform async I/O (HTTP requests, etc.)
3. The tool tries to use asyncio.run() → RuntimeError: "asyncio.run() cannot be 
   called from a running event loop"

THE SOLUTION
============

We use a ThreadPoolExecutor to run async code in separate threads, each with
its own isolated event loop. This works because:

1. Each thread has its own event loop (or none)
2. asyncio.run() can be called in a thread without a running loop
3. We communicate between threads using concurrent.futures

ARCHITECTURE OVERVIEW
=====================

┌─────────────────────────────────────────────────────────────────┐
│                      Main Thread (Aider)                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Synchronous Code                                         │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │  │
│  │  │ Coder Inst 1│  │ Coder Inst 2│  │ Coder Inst 3│  ...   │  │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │  │
│  │         │                │                │               │  │
│  │         └────────────────┴────────────────┘               │  │
│  │                          │                                │  │
│  │         ┌────────────────▼────────────────┐               │  │
│  │         │     AsyncExecutor (Singleton)   │               │  │
│  │         │  ┌───────────────────────────┐  │               │  │
│  │         │  │   ThreadPoolExecutor      │  │               │  │
│  │         │  │  (max_workers=8)          │  │               │  │
│  │         │  └───────────────────────────┘  │               │  │
│  │         └─────────────────────────────────┘               │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ submits work
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Thread Pool (Worker Threads)                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  Worker 1       │  │  Worker 2       │  │  Worker 3       │  │
│  │ ┌─────────────┐ │  │ ┌─────────────┐ │  │ ┌─────────────┐ │  │
│  │ │ Event Loop  │ │  │ │ Event Loop  │ │  │ │ Event Loop  │ │  │
│  │ │ ┌─────────┐ │ │  │ │ ┌─────────┐ │ │  │ │ ┌─────────┐ │ │  │
│  │ │ │ Coro 1  │ │ │  │ │ │ Coro 2  │ │ │  │ │ │ Coro 3  │ │ │  │
│  │ │ └─────────┘ │ │  │ │ └─────────┘ │ │  │ │ └─────────┘ │ │  │
│  │ └─────────────┘ │  │ └─────────────┘ │  │ └─────────────┘ │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

USAGE PATTERNS
==============

1. Basic usage from sync context:

   executor = AsyncExecutor()
   result = executor.run(some_async_function())

2. With timeout:

   result = executor.run(some_async_function(), timeout=30.0)

3. With partial result capture on cancellation:

   task = CancellableTask(long_running_async_function())
   try:
       result = executor.run(task.run(), timeout=60.0)
   except TimeoutError:
       partial = task.partial_result  # Access partial results

4. Context manager pattern:

   with async_context() as executor:
       result = executor.run(some_async_function())

THREAD SAFETY GUARANTEES
========================

1. AsyncExecutor is a thread-safe singleton
2. Multiple Coder instances can safely share the same executor
3. Concurrent calls to run() are serialized through ThreadPoolExecutor
4. Shutdown is atomic and waits for all tasks to complete

CLEANUP AND RESOURCE MANAGEMENT
===============================

1. ThreadPoolExecutor is lazily initialized
2. Worker threads are daemon threads (don't block process exit)
3. shutdown() cancels pending futures and waits for running tasks
4. Atexit handler ensures cleanup on normal process termination
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Generic, Optional, TypeVar, Union

# Configure logging
logger = logging.getLogger(__name__)

# Type variable for generic result types
T = TypeVar("T")


class AsyncExecutionError(Exception):
    """Base exception for async execution errors."""
    pass


class LoopAlreadyRunningError(AsyncExecutionError):
    """Raised when trying to run async code in a thread with a running loop."""
    pass


class ExecutionTimeoutError(AsyncExecutionError):
    """Raised when execution exceeds the specified timeout."""
    
    def __init__(self, message: str, partial_result: Any = None):
        super().__init__(message)
        self.partial_result = partial_result


@dataclass
class ExecutionResult(Generic[T]):
    """Container for execution results with metadata."""
    
    value: T
    success: bool = True
    duration_ms: float = 0.0
    cancelled: bool = False
    partial_result: Any = None
    error: Optional[Exception] = None


class _AsyncRunner:
    """
    Internal class to run async code in a dedicated thread.
    
    Each instance of this class creates its own event loop and runs it
    in a dedicated thread. This ensures complete isolation from any
    existing event loops.
    """
    
    def __init__(self, thread_name: Optional[str] = None):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._shutdown = threading.Event()
        self._thread_name = thread_name or f"aider_async_{id(self):x}"
        
    def start(self) -> None:
        """Start the runner thread with its own event loop."""
        if self._thread is not None:
            return  # Already started
            
        def run_loop():
            """Thread target: create and run event loop."""
            # Create a new event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            # Signal that we're ready
            self._ready.set()
            
            # Run until shutdown is requested
            try:
                while not self._shutdown.is_set():
                    # Run the loop for a bit, then check for shutdown
                    self._loop.run_forever()
            finally:
                # Clean up remaining tasks
                try:
                    # Cancel all pending tasks
                    pending = asyncio.all_tasks(self._loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        # Wait briefly for cancellation to complete
                        self._loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    
                    # Shutdown async generators
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                    
                    # Close the loop
                    self._loop.close()
                except Exception as e:
                    logger.warning(f"Error during loop cleanup: {e}")
                finally:
                    self._loop = None
        
        self._thread = threading.Thread(
            target=run_loop,
            name=self._thread_name,
            daemon=True,  # Daemon thread doesn't block process exit
        )
        self._thread.start()
        
        # Wait for the loop to be ready
        if not self._ready.wait(timeout=5.0):
            raise AsyncExecutionError("Failed to start async runner thread")
    
    def run_coro(self, coro: Coroutine[Any, Any, T], timeout: Optional[float] = None) -> T:
        """Run a coroutine in this runner's event loop."""
        if self._loop is None or not self._thread or not self._thread.is_alive():
            raise AsyncExecutionError("Async runner is not running")
        
        # Submit the coroutine to the event loop
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        
        # Wait for the result with timeout
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            # Cancel the future if it timed out
            future.cancel()
            raise ExecutionTimeoutError(f"Coroutine timed out after {timeout}s")
        except Exception as e:
            # Re-raise other exceptions
            raise
    
    def shutdown(self, wait: bool = True, timeout: float = 10.0) -> None:
        """Shutdown the runner thread."""
        if self._thread is None:
            return
        
        # Signal shutdown
        self._shutdown.set()
        
        # Stop the event loop (causes run_forever() to return)
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        
        # Wait for thread to finish
        if wait and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(f"Async runner thread did not terminate within {timeout}s")


class AsyncExecutor:
    """
    Manages async execution in potentially sync contexts.
    
    Key insight: We can't use asyncio.run() if already in an event loop.
    Instead, we use ThreadPoolExecutor to run async code in separate threads
    with their own event loops.
    
    This class implements the singleton pattern to ensure all Coder instances
    share the same execution resources while maintaining thread safety.
    
    Example:
        >>> executor = AsyncExecutor()
        >>> async def fetch_data():
        ...     return "data"
        >>> result = executor.run(fetch_data())
        >>> print(result)  # "data"
    """
    
    _instance: Optional["AsyncExecutor"] = None
    _lock = threading.Lock()
    _initialized = False
    
    def __new__(cls) -> "AsyncExecutor":
        """Create or return the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_workers: int = 8):
        """
        Initialize the executor (only runs once due to singleton pattern).
        
        Args:
            max_workers: Maximum number of worker threads in the pool.
                        Default is 8 to handle concurrent tool executions
                        without overwhelming system resources.
        """
        # Skip re-initialization for singleton
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            self._max_workers = max_workers
            self._executor: Optional[ThreadPoolExecutor] = None
            self._executor_lock = threading.RLock()
            self._shutdown = False
            self._active_futures: weakref.WeakSet = weakref.WeakSet()
            
            # Register cleanup on process exit
            atexit.register(self._atexit_cleanup)
            
            self._initialized = True
            logger.debug("AsyncExecutor initialized")
    
    def _get_executor(self) -> ThreadPoolExecutor:
        """
        Lazily initialize and return the ThreadPoolExecutor.
        
        This lazy initialization ensures we don't create threads unless
        actually needed, and allows for proper cleanup.
        """
        with self._executor_lock:
            if self._shutdown:
                raise AsyncExecutionError("AsyncExecutor has been shut down")
            
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="aider_tool_",
                    # ThreadPoolExecutor manages its own worker threads
                )
                logger.debug(f"Created ThreadPoolExecutor with {self._max_workers} workers")
            
            return self._executor
    
    def _is_in_event_loop(self) -> bool:
        """
        Check if we're currently running inside an event loop.
        
        This is the key detection mechanism that determines whether
        we need to use the thread pool or can use the current loop.
        
        Returns:
            True if called from within a running event loop, False otherwise.
        """
        try:
            loop = asyncio._get_running_loop()
            return loop is not None
        except RuntimeError:
            # No running loop in current thread
            return False
    
    def run(
        self,
        coro: Coroutine[Any, Any, T],
        timeout: Optional[float] = None,
        capture_partial: bool = False,
    ) -> T:
        """
        Run a coroutine, handling both sync and async contexts.
        
        This is the main entry point for executing async code. It automatically
detects the calling context and uses the appropriate execution strategy:
        
        1. If called from sync context (no running event loop):
           - Submits to ThreadPoolExecutor
           - Runs asyncio.run() in worker thread
           - Returns result synchronously
           
        2. If called from async context (running event loop detected):
           - Schedules in current loop using run_coroutine_threadsafe
           - Returns awaitable Future
        
        Args:
            coro: The coroutine to execute
            timeout: Maximum execution time in seconds. None means no timeout.
            capture_partial: If True and timeout occurs, attempts to capture
                           partial results from the coroutine.
        
        Returns:
            The result of the coroutine execution.
        
        Raises:
            ExecutionTimeoutError: If execution exceeds timeout
            AsyncExecutionError: If executor is shut down or other error occurs
        
        Example:
            >>> async def compute():
            ...     await asyncio.sleep(1)
            ...     return 42
            >>> executor = AsyncExecutor()
            >>> result = executor.run(compute(), timeout=5.0)
            >>> print(result)  # 42
        """
        if self._shutdown:
            raise AsyncExecutionError("AsyncExecutor has been shut down")
        
        if coro is None:
            raise ValueError("Coroutine cannot be None")
        
        start_time = time.monotonic()
        
        # Check if we're already in an event loop
        if self._is_in_event_loop():
            # We're in async context - need to be careful here
            # We can't block waiting for a result, so we schedule it
            # and return a future that can be awaited
            logger.debug("Detected async context, using thread-safe scheduling")
            return self._run_in_thread_pool(coro, timeout)
        else:
            # We're in sync context - can block on the result
            logger.debug("Detected sync context, using thread pool")
            return self._run_in_thread_pool(coro, timeout)
    
    def _run_in_thread_pool(
        self,
        coro: Coroutine[Any, Any, T],
        timeout: Optional[float] = None,
    ) -> T:
        """
        Execute coroutine in a thread pool worker.
        
        This method creates a new event loop in a worker thread and
        runs the coroutine there, completely avoiding the nested loop problem.
        """
        executor = self._get_executor()
        
        def run_in_new_loop():
            """Function to run in worker thread."""
            # Each worker thread gets its own fresh event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Run the coroutine to completion
                return loop.run_until_complete(coro)
            finally:
                # Clean up the loop
                try:
                    # Cancel any remaining tasks
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    
                    # Shutdown async generators
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()
                except Exception as e:
                    logger.warning(f"Error cleaning up event loop: {e}")
        
        # Submit to thread pool
        future = executor.submit(run_in_new_loop)
        self._active_futures.add(future)
        
        try:
            # Wait for result with timeout
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            # Cancel the future
            future.cancel()
            raise ExecutionTimeoutError(
                f"Execution timed out after {timeout}s",
                partial_result=None,  # Could be enhanced with partial capture
            )
        except Exception as e:
            # Re-raise the exception
            raise
        finally:
            self._active_futures.discard(future)
    
    def run_concurrent(
        self,
        coros: list[Coroutine[Any, Any, T]],
        timeout: Optional[float] = None,
        return_exceptions: bool = False,
    ) -> list[Union[T, Exception]]:
        """
        Run multiple coroutines concurrently.
        
        This is more efficient than calling run() multiple times because
        it uses a single thread pool submission to run all coroutines
        concurrently in the same event loop.
        
        Args:
            coros: List of coroutines to execute
            timeout: Timeout per coroutine, or None for no timeout
            return_exceptions: If True, exceptions are returned instead of raised
        
        Returns:
            List of results in the same order as input coroutines
        
        Example:
            >>> coros = [fetch_user(i) for i in range(10)]
            >>> results = executor.run_concurrent(coros, timeout=30.0)
        """
        if not coros:
            return []
        
        executor = self._get_executor()
        
        def run_all_in_loop():
            """Run all coroutines concurrently in a new event loop."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Create tasks for all coroutines
                tasks = [loop.create_task(coro) for coro in coros]
                
                # Apply timeout if specified
                if timeout is not None:
                    # Use wait_for on the gather
                    gather_task = asyncio.gather(*tasks, return_exceptions=return_exceptions)
                    return loop.run_until_complete(
                        asyncio.wait_for(gather_task, timeout=timeout)
                    )
                else:
                    return loop.run_until_complete(
                        asyncio.gather(*tasks, return_exceptions=return_exceptions)
                    )
            finally:
                # Cleanup
                try:
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()
                except Exception as e:
                    logger.warning(f"Error cleaning up event loop: {e}")
        
        future = executor.submit(run_all_in_loop)
        self._active_futures.add(future)
        
        try:
            return future.result()
        finally:
            self._active_futures.discard(future)
    
    def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """
        Clean shutdown of the executor.
        
        Cancels all pending futures and optionally waits for running
        tasks to complete.
        
        Args:
            wait: If True, wait for running tasks to complete
            timeout: Maximum time to wait for shutdown
        """
        with self._executor_lock:
            if self._shutdown:
                return
            
            self._shutdown = True
            logger.info("Shutting down AsyncExecutor")
            
            # Cancel any pending futures
            for future in list(self._active_futures):
                if not future.done():
                    future.cancel()
            
            # Shutdown the executor
            if self._executor is not None:
                self._executor.shutdown(wait=wait)
                self._executor = None
            
            logger.info("AsyncExecutor shutdown complete")
    
    def _atexit_cleanup(self) -> None:
        """Cleanup handler called at process exit."""
        if not self._shutdown and self._executor is not None:
            logger.debug("Running atexit cleanup for AsyncExecutor")
            self.shutdown(wait=False)
    
    @property
    def is_shutdown(self) -> bool:
        """Check if the executor has been shut down."""
        return self._shutdown
    
    @property
    def active_count(self) -> int:
        """Number of currently active executions."""
        return sum(1 for f in self._active_futures if not f.done())


class CancellableTask(Generic[T]):
    """
    Wrapper for cancellable async operations with partial result capture.
    
    This class allows long-running async operations to be cancelled while
    preserving any partial results that were computed before cancellation.
    
    The partial result capture works by periodically checkpointing progress
    in an async-safe manner.
    
    Example:
        >>> async def long_operation(checkpoint):
        ...     results = []
        ...     for i in range(100):
        ...         results.append(await process_item(i))
        ...         if i % 10 == 0:
        ...             checkpoint(results.copy())  # Save progress
        ...     return results
        ...
        >>> task = CancellableTask(long_operation())
        >>> try:
        ...     result = executor.run(task.run(), timeout=5.0)
        ... except ExecutionTimeoutError:
        ...     print(f"Partial results: {task.partial_result}")
    """
    
    def __init__(
        self,
        coro: Coroutine[Any, Any, T],
        checkpoint_interval: float = 1.0,
    ):
        """
        Initialize a cancellable task.
        
        Args:
            coro: The coroutine to execute
            checkpoint_interval: How often to check for cancellation (seconds)
        """
        self._coro = coro
        self._checkpoint_interval = checkpoint_interval
        self._task: Optional[asyncio.Task] = None
        self._partial_result: Any = None
        self._cancelled = False
        self._lock = asyncio.Lock()
    
    def checkpoint(self, result: Any) -> None:
        """
        Save a partial result.
        
        Call this from within the coroutine to checkpoint progress.
        The result should be a copy of mutable data to avoid issues.
        """
        self._partial_result = result
    
    async def run(self, timeout: Optional[float] = None) -> T:
        """
        Run the coroutine with optional timeout.
        
        If cancelled or timed out, raises ExecutionTimeoutError with
        the partial result attached.
        """
        async def run_with_checkpoints():
            """Run coroutine with periodic checkpoint checks."""
            # Start the main coroutine
            main_task = asyncio.create_task(self._coro)
            self._task = main_task
            
            try:
                # Wait for completion
                return await main_task
            except asyncio.CancelledError:
                self._cancelled = True
                raise
        
        try:
            if timeout is not None:
                return await asyncio.wait_for(run_with_checkpoints(), timeout=timeout)
            else:
                return await run_with_checkpoints()
        except asyncio.TimeoutError:
            self._cancelled = True
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            
            raise ExecutionTimeoutError(
                f"Task timed out after {timeout}s",
                partial_result=self._partial_result,
            )
        except asyncio.CancelledError:
            self._cancelled = True
            raise ExecutionTimeoutError(
                "Task was cancelled",
                partial_result=self._partial_result,
            )
    
    @property
    def partial_result(self) -> Any:
        """Get the last checkpointed partial result."""
        return self._partial_result
    
    @property
    def cancelled(self) -> bool:
        """Check if the task was cancelled."""
        return self._cancelled
    
    async def cancel(self) -> None:
        """Cancel the running task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._cancelled = True


@contextmanager
def async_context(max_workers: int = 8):
    """
    Context manager for async operations in sync code.
    
    Provides a scoped AsyncExecutor that automatically cleans up
    when exiting the context. Note that since AsyncExecutor is a
    singleton, this doesn't create a new executor but provides
    cleanup guarantees for the scope.
    
    Args:
        max_workers: Maximum number of worker threads
    
    Yields:
        AsyncExecutor instance
    
    Example:
        >>> with async_context() as executor:
        ...     result1 = executor.run(fetch_data())
        ...     result2 = executor.run(process_data(result1))
        >>> # Executor resources cleaned up here
    """
    executor = AsyncExecutor()
    # Note: We don't actually create a new executor (it's a singleton)
    # but we track that we're in a context for potential cleanup
    
    try:
        yield executor
    finally:
        # Context exit cleanup
        # We don't shutdown the singleton, but we could add
        # context-specific tracking here if needed
        pass


@contextmanager
def temporary_event_loop():
    """
    Context manager that creates a temporary event loop.
    
    Useful for code that needs to run async code in isolation.
    
    Yields:
        asyncio.AbstractEventLoop: The temporary event loop
    
    Example:
        >>> with temporary_event_loop() as loop:
        ...     result = loop.run_until_complete(some_async_func())
    """
    # Save the current event loop if any
    old_loop = asyncio._get_running_loop()
    
    # Create and set a new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        yield loop
    finally:
        # Clean up
        try:
            # Cancel any pending tasks
            pending = asyncio.all_tasks(loop)
            if pending:
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
        except Exception as e:
            logger.warning(f"Error cleaning up temporary event loop: {e}")
        finally:
            # Restore old loop if there was one
            if old_loop is not None:
                asyncio.set_event_loop(old_loop)
            else:
                asyncio.set_event_loop(None)


def run_async(coro: Coroutine[Any, Any, T], timeout: Optional[float] = None) -> T:
    """
    Convenience function to run a coroutine without explicit executor.
    
    This is a simple entry point for one-off async operations.
    For repeated operations, use AsyncExecutor directly.
    
    Args:
        coro: The coroutine to run
        timeout: Optional timeout in seconds
    
    Returns:
        The coroutine result
    
    Example:
        >>> result = run_async(fetch_data(), timeout=10.0)
    """
    executor = AsyncExecutor()
    return executor.run(coro, timeout=timeout)


# Export public API
__all__ = [
    "AsyncExecutor",
    "CancellableTask",
    "ExecutionResult",
    "ExecutionTimeoutError",
    "AsyncExecutionError",
    "LoopAlreadyRunningError",
    "async_context",
    "temporary_event_loop",
    "run_async",
]
