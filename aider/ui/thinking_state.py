"""
Thinking state manager for docked prompt UI.

Manages the "thinking" indicator (💫 vs ✨) during LLM generation.
Provides smooth transitions between idle and thinking states.
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Callable


class ThinkingState(Enum):
    """States for thinking indicator."""
    IDLE = auto()
    STARTING = auto()  # Brief delay before showing thinking
    THINKING = auto()
    STREAMING = auto()  # Actively receiving tokens


@dataclass
class ThinkingConfig:
    """Configuration for thinking state transitions."""
    # Delay before showing thinking indicator (prevents flicker on fast responses)
    start_delay_ms: float = 150.0
    # Timeout for transitioning from THINKING to IDLE if no activity
    timeout_ms: float = 500.0
    # Animation interval for spinner update
    animation_interval_ms: float = 100.0


class ThinkingStateManager:
    """
    Manages thinking state for LLM generation.
    
    Provides smooth transitions:
    - IDLE → STARTING (after generation starts)
    - STARTING → THINKING (after delay if still generating)
    - THINKING → STREAMING (when tokens start arriving)
    - Any state → IDLE (when generation completes)
    """
    
    def __init__(
        self,
        config: Optional[ThinkingConfig] = None,
        on_state_change: Optional[Callable[[ThinkingState], None]] = None,
    ):
        self._config = config or ThinkingConfig()
        self._on_state_change = on_state_change
        self._state = ThinkingState.IDLE
        self._last_activity_time = 0.0
        self._generation_start_time = 0.0
        self._tokens_received = 0
        self._monitoring_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> ThinkingState:
        return self._state
    
    @property
    def is_thinking(self) -> bool:
        return self._state in (ThinkingState.THINKING, ThinkingState.STREAMING)
    
    @property
    def show_thinking_indicator(self) -> bool:
        """Whether to show the thinking symbol (💫)."""
        return self._state != ThinkingState.IDLE
    
    async def start_generation(self) -> None:
        """Called when generation starts."""
        async with self._lock:
            self._generation_start_time = time.monotonic()
            self._tokens_received = 0
            await self._transition_to(ThinkingState.STARTING)
        
        # Start monitoring task
        if self._monitoring_task and not self._monitoring_task.done():
            self._monitoring_task.cancel()
        self._monitoring_task = asyncio.create_task(self._monitor_state())
    
    async def on_token_received(self, token: str = "") -> None:
        """Called when a token is received from the LLM."""
        async with self._lock:
            self._last_activity_time = time.monotonic()
            self._tokens_received += len(token)
            
            if self._state == ThinkingState.STARTING:
                # Transition to THINKING when first token arrives
                await self._transition_to(ThinkingState.THINKING)
            elif self._state == ThinkingState.THINKING:
                # After receiving several tokens, we're streaming
                if self._tokens_received > 10:
                    await self._transition_to(ThinkingState.STREAMING)
    
    async def end_generation(self) -> None:
        """Called when generation completes."""
        async with self._lock:
            await self._transition_to(ThinkingState.IDLE)
        
        # Cancel monitoring
        if self._monitoring_task and not self._monitoring_task.done():
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
    
    async def _monitor_state(self) -> None:
        """Background task to monitor state transitions."""
        try:
            while True:
                await asyncio.sleep(self._config.animation_interval_ms / 1000)
                
                async with self._lock:
                    now = time.monotonic()
                    
                    if self._state == ThinkingState.STARTING:
                        # Check if we should show thinking
                        elapsed = (now - self._generation_start_time) * 1000
                        if elapsed > self._config.start_delay_ms:
                            await self._transition_to(ThinkingState.THINKING)
                    
                    elif self._state == ThinkingState.THINKING:
                        # Check for timeout
                        elapsed = (now - self._last_activity_time) * 1000
                        if elapsed > self._config.timeout_ms:
                            # No activity, might be stuck or done
                            pass  # Stay in thinking state
        except asyncio.CancelledError:
            pass
    
    async def _transition_to(self, new_state: ThinkingState) -> None:
        """Transition to a new state."""
        if self._state == new_state:
            return
        
        self._state = new_state
        
        if self._on_state_change:
            try:
                res = self._on_state_change(new_state)
                # Handle both sync and async callbacks robustly
                if asyncio.iscoroutine(res):
                    await res
                elif res is not None and (asyncio.isfuture(res) or hasattr(res, "__await__")):
                    await res
            except Exception:
                pass  # Don't let callbacks break state machine


class AsyncSendMessageAdapter:
    """
    Adapts Aider's send_message generator for async streaming.
    
    Runs the generator in an executor and yields chunks asynchronously,
    allowing the UI to remain responsive during generation.
    """
    
    def __init__(
        self,
        send_message_func,
        thinking_manager: Optional[ThinkingStateManager] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ):
        self._send_message = send_message_func
        self._thinking = thinking_manager
        self._on_chunk = on_chunk
        self._chunk_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self._done_event = asyncio.Event()
        self._error: Optional[Exception] = None
    
    async def stream(self, message: str):
        """
        Stream messages asynchronously.
        
        Yields chunks as they arrive from the generator.
        """
        # Start generation
        if self._thinking:
            await self._thinking.start_generation()
        
        # Start producer task
        producer_task = asyncio.create_task(
            self._produce_chunks(message)
        )
        
        try:
            # Yield chunks as they arrive
            while not self._done_event.is_set() or not self._chunk_queue.empty():
                try:
                    # Short timeout to check done_event frequently
                    chunk = await asyncio.wait_for(
                        self._chunk_queue.get(),
                        timeout=0.05
                    )
                    if chunk is not None:
                        if self._thinking:
                            await self._thinking.on_token_received(chunk)
                        if self._on_chunk:
                            self._on_chunk(chunk)
                        yield chunk
                except asyncio.TimeoutError:
                    continue
            
            # Check for errors
            if self._error:
                raise self._error
                
        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except asyncio.CancelledError:
                    pass
            
            if self._thinking:
                await self._thinking.end_generation()
    
    async def _produce_chunks(self, message: str) -> None:
        """Producer: runs generator in executor and puts chunks in queue."""
        loop = asyncio.get_running_loop()
        
        def _run_generator():
            try:
                for chunk in self._send_message(message):
                    # Put chunk in queue (sync thread calling async queue)
                    if chunk is not None:
                        loop.call_soon_threadsafe(
                            self._chunk_queue.put_nowait, chunk
                        )
            except Exception as e:
                self._error = e
            finally:
                loop.call_soon_threadsafe(self._done_event.set)
        
        # Run generator in thread pool
        await loop.run_in_executor(None, _run_generator)
