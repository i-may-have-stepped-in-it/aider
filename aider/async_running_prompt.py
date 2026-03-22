"""
Async Running Prompt Manager - Background generation with persistent prompt.

This module provides true async background generation, allowing users to:
- Continue typing while AI generates
- Queue messages with Tab
- Steer generation with Enter
- Cancel with Escape
"""

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from rich.markup import escape

from aider.async_compat import (
    AsyncEvent,
    GenerationResult,
    GenerationState,
    MessageQueue,
    QueuedMessage,
    SteerMessage,
    TaskManager,
    run_in_thread,
)

logger = logging.getLogger(__name__)


class AsyncRunningPromptManager:
    """
    Manages background generation with async/await.
    
    Key features:
    - Non-blocking prompt during generation
    - Message queuing (Tab)
    - Generation steering (Enter)  
    - Cooperative cancellation
    - Proper cleanup on exit
    """
    
    def __init__(self, io=None):
        self.io = io
        self._state = GenerationState.IDLE
        self._current_task: Optional[asyncio.Task] = None
        self._message_queue: MessageQueue = MessageQueue()
        self._cancel_event: AsyncEvent = AsyncEvent()
        self._task_manager: TaskManager = TaskManager()
        self._result: Optional[GenerationResult] = None
        self._lock = asyncio.Lock()
        
        # Callbacks
        self.on_generation_start: Optional[Callable] = None
        self.on_generation_complete: Optional[Callable[[GenerationResult], None]] = None
        self.on_generation_cancel: Optional[Callable] = None
        self.on_chunk: Optional[Callable[[str], None]] = None
    
    @property
    def state(self) -> GenerationState:
        return self._state
    
    @property
    def is_generating(self) -> bool:
        return self._state == GenerationState.GENERATING
    
    @property
    def is_idle(self) -> bool:
        return self._state == GenerationState.IDLE
    
    @property
    def has_queued_messages(self) -> bool:
        return not self._message_queue.empty()
    
    def get_queued_messages(self) -> list[str]:
        """Get all queued messages and clear queue."""
        messages = []
        while not self._message_queue.empty():
            msg = self._message_queue.get_nowait()
            if msg:
                messages.append(msg.text)
        return messages
    
    async def start_generation(
        self,
        func: Callable[..., Any],
        *args,
        **kwargs
    ) -> asyncio.Task:
        """Start a background generation task."""
        async with self._lock:
            if self._state == GenerationState.GENERATING:
                raise RuntimeError("Already generating. Use steer() or cancel() first.")
            
            self._cancel_event.clear()
            self._state = GenerationState.GENERATING
            self._result = None
            
            task = self._task_manager.create_task(
                self._generation_worker(func, args, kwargs),
                name="generation_task"
            )
            self._current_task = task
            
            if self.on_generation_start:
                try:
                    if asyncio.iscoroutinefunction(self.on_generation_start):
                        await self.on_generation_start()
                    else:
                        self.on_generation_start()
                except Exception as e:
                    logger.warning(f"on_generation_start callback error: {e}", exc_info=True)
            
            return task
    
    async def queue_message(self, text: str) -> None:
        """Queue a message for processing after current generation (Tab)."""
        await self._message_queue.put(QueuedMessage(text))
        
        if self.io:
            # Escape text to prevent Rich markup injection
            safe_text = escape(text[:50])
            await run_in_thread(
                self.io.console.print,
                f"[dim]Queued: {safe_text}{'...' if len(text) > 50 else ''}[/dim]"
            )
    
    async def steer(self, text: str) -> GenerationResult:
        """Steer the current generation with a new message (Enter)."""
        # Capture task reference under lock, then release before awaiting
        task = None
        async with self._lock:
            if self._state != GenerationState.GENERATING:
                return GenerationResult(
                    state=GenerationState.IDLE,
                    content=text
                )
            
            self._cancel_event.set()
            steer_msg = SteerMessage(text)
            await self._message_queue.put(steer_msg)
            
            if self.io:
                # Escape text to prevent Rich markup injection
                safe_text = escape(text[:50])
                await run_in_thread(
                    self.io.console.print,
                    f"[yellow]Steering: {safe_text}{'...' if len(text) > 50 else ''}[/yellow]"
                )
            
            # Capture reference to task before releasing lock
            task = self._current_task
        
        # Wait for task completion OUTSIDE the lock to prevent deadlock
        # If the worker task calls back into manager methods, it needs the lock
        if task:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
        
        if self.on_generation_cancel:
            try:
                if asyncio.iscoroutinefunction(self.on_generation_cancel):
                    await self.on_generation_cancel()
                else:
                    self.on_generation_cancel()
            except Exception as e:
                logger.warning(f"on_generation_cancel callback error: {e}", exc_info=True)
        
        return self._result or GenerationResult(
            state=GenerationState.CANCELLED
        )
    
    async def cancel(self) -> Optional[GenerationResult]:
        """Cancel the current generation without steering (Escape)."""
        async with self._lock:
            if self._state != GenerationState.GENERATING:
                return None
            
            self._cancel_event.set()
            self._state = GenerationState.CANCELLED
            
            if self._current_task:
                self._current_task.cancel()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass
            
            if self.on_generation_cancel:
                try:
                    if asyncio.iscoroutinefunction(self.on_generation_cancel):
                        await self.on_generation_cancel()
                    else:
                        self.on_generation_cancel()
                except Exception as e:
                    logger.warning(f"on_generation_cancel callback error: {e}", exc_info=True)
            
            return self._result or GenerationResult(state=GenerationState.CANCELLED)
    
    async def wait_for_completion(self, timeout: Optional[float] = None) -> GenerationResult:
        """Wait for current generation to complete."""
        if self._current_task is None:
            return self._result or GenerationResult(state=GenerationState.IDLE)
        
        try:
            await asyncio.wait_for(self._current_task, timeout=timeout)
        except asyncio.TimeoutError:
            # Cancel the task on timeout to prevent resource leak
            if self._current_task is not None:
                self._current_task.cancel()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass
            raise
        
        return self._result or GenerationResult(state=GenerationState.IDLE)
    
    async def _generation_worker(
        self,
        func: Callable[..., Any],
        args: tuple,
        kwargs: dict
    ):
        """Worker that runs the generation function."""
        start_time = time.time()
        accumulated = ""
        
        try:
            def progress_callback(chunk: str):
                nonlocal accumulated
                accumulated += chunk
                if self.on_chunk:
                    try:
                        self.on_chunk(chunk)
                    except Exception as e:
                        logger.warning(f"on_chunk callback error: {e}", exc_info=True)
            
            # Check if function accepts special kwargs
            import inspect
            sig = inspect.signature(func)
            accepts_cancel = '_cancel_event' in sig.parameters
            accepts_progress = '_progress_callback' in sig.parameters
            
            kwargs = kwargs.copy()
            if accepts_cancel:
                kwargs['_cancel_event'] = self._cancel_event
            if accepts_progress:
                kwargs['_progress_callback'] = progress_callback
            
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = await run_in_thread(func, *args, **kwargs)
            
            if self._cancel_event.is_set():
                self._state = GenerationState.CANCELLED
                self._result = GenerationResult(
                    state=GenerationState.CANCELLED,
                    content=accumulated if accumulated else None,
                    messages=[accumulated] if accumulated else []
                )
            else:
                self._state = GenerationState.COMPLETED
                content = str(result) if result is not None else accumulated
                self._result = GenerationResult(
                    state=GenerationState.COMPLETED,
                    content=content,
                    messages=[content] if content else []
                )
                
        except asyncio.CancelledError:
            self._state = GenerationState.CANCELLED
            self._result = GenerationResult(
                state=GenerationState.CANCELLED,
                content=accumulated if accumulated else None,
                messages=[accumulated] if accumulated else []
            )
            raise
        except Exception as e:
            self._state = GenerationState.FAILED
            self._result = GenerationResult(
                state=GenerationState.FAILED,
                error=e,
                content=accumulated if accumulated else None
            )
        finally:
            self._current_task = None
            
            if self.on_generation_complete and self._result:
                try:
                    if asyncio.iscoroutinefunction(self.on_generation_complete):
                        await self.on_generation_complete(self._result)
                    else:
                        self.on_generation_complete(self._result)
                except Exception as e:
                    logger.warning(f"on_generation_complete callback error: {e}", exc_info=True)
    
    async def shutdown(self):
        """Clean shutdown - cancel all tasks and cleanup."""
        await self._task_manager.cancel_all(timeout=5.0)
        self._state = GenerationState.IDLE


class AsyncPromptDelegate:
    """Delegate that handles prompt input during async generation."""
    
    def __init__(
        self,
        manager: AsyncRunningPromptManager,
        io=None,
        on_submit: Optional[Callable[[str], None]] = None
    ):
        self.manager = manager
        self.io = io
        self.on_submit = on_submit
        self._active = False
    
    def activate(self):
        """Activate the delegate."""
        self._active = True
    
    def deactivate(self):
        """Deactivate the delegate."""
        self._active = False
    
    @property
    def is_active(self) -> bool:
        return self._active
    
    async def handle_tab(self, text: str) -> bool:
        """Handle Tab key press. Returns True if handled."""
        if not self._active or not self.manager.is_generating:
            return False
        
        await self.manager.queue_message(text)
        return True
    
    async def handle_enter(self, text: str) -> bool:
        """Handle Enter key press. Returns True if handled (steered)."""
        if not self._active or not self.manager.is_generating:
            return False
        
        await self.manager.steer(text)
        return True
    
    async def handle_escape(self) -> bool:
        """Handle Escape key press. Returns True if handled (cancelled)."""
        if not self._active or not self.manager.is_generating:
            return False
        
        await self.manager.cancel()
        return True
