"""
Advanced tests for AsyncRunningPromptManager.

Tests edge cases, concurrency, and error handling.
"""

import asyncio
import pytest

from aider.async_compat import GenerationState
from aider.async_running_prompt import AsyncPromptDelegate, AsyncRunningPromptManager


class TestAsyncRunningPromptAdvanced:
    """Advanced tests for AsyncRunningPromptManager."""
    
    @pytest.mark.asyncio
    async def test_concurrent_generation_prevention(self):
        """Test that starting a second generation while one is running raises error."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            await asyncio.sleep(0.1)
            return "done"
        
        # Start first generation
        await manager.start_generation(slow_task)
        
        # Try to start second generation - should raise
        with pytest.raises(RuntimeError, match="Already generating"):
            await manager.start_generation(slow_task)
        
        # Clean up
        await manager.cancel()
    
    @pytest.mark.asyncio
    async def test_cancellation_during_chunk_processing(self):
        """Test cancellation while processing chunks."""
        manager = AsyncRunningPromptManager()
        chunks_processed = []
        
        async def task_with_chunks():
            for i in range(100):
                if manager._cancel_event.is_set():
                    raise asyncio.CancelledError()
                chunks_processed.append(i)
                await asyncio.sleep(0.001)
            return "completed"
        
        await manager.start_generation(task_with_chunks)
        
        # Let it process a few chunks
        await asyncio.sleep(0.01)
        
        # Cancel it
        await manager.cancel()
        
        # Should have processed some but not all chunks (timing dependent)
        assert 1 <= len(chunks_processed) < 100
    
    @pytest.mark.asyncio
    async def test_message_queue_under_load(self):
        """Test message queue with many messages."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            await asyncio.sleep(0.05)
            return "done"
        
        await manager.start_generation(slow_task)
        
        # Queue many messages
        for i in range(50):
            await manager.queue_message(f"Message {i}")
        
        await manager.cancel()
        
        # All messages should be preserved
        messages = manager.get_queued_messages()
        assert len(messages) == 50
    
    @pytest.mark.asyncio
    async def test_steering_mid_generation(self):
        """Test steering (cancel + new direction) during generation."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            for _ in range(200):
                if manager._cancel_event.is_set():
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.001)
            return "should not complete"
        
        await manager.start_generation(slow_task)
        
        # Steer to new direction
        result = await manager.steer("New direction")
        
        assert result.state == GenerationState.CANCELLED
        assert manager.has_queued_messages
        assert "New direction" in manager.get_queued_messages()
    
    @pytest.mark.asyncio
    async def test_error_recovery_and_cleanup(self):
        """Test that error state is properly captured and cleanup occurs."""
        manager = AsyncRunningPromptManager()
        
        async def failing_task():
            raise ValueError("Test error")
        
        await manager.start_generation(failing_task)
        
        result = await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        
        assert result.state == GenerationState.FAILED
        assert result.error is not None
        assert str(result.error) == "Test error"
        assert manager._current_task is None  # Cleaned up
    
    @pytest.mark.asyncio
    async def test_callback_invocation_order(self):
        """Test that callbacks are invoked in correct order."""
        manager = AsyncRunningPromptManager()
        events = []
        
        async def on_start():
            events.append("start")
        
        async def on_complete(result):
            events.append("complete")
        
        async def task():
            events.append("task_running")
            await asyncio.sleep(0.01)
            return "done"
        
        manager.on_generation_start = on_start
        manager.on_generation_complete = on_complete
        
        await manager.start_generation(task)
        await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        
        assert events == ["start", "task_running", "complete"]
    
    @pytest.mark.asyncio
    async def test_multiple_cancellations_idempotent(self):
        """Test that multiple cancellations don't cause errors."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            await asyncio.sleep(10)
            return "done"
        
        await manager.start_generation(slow_task)
        
        # Cancel multiple times
        await manager.cancel()
        await manager.cancel()  # Should not raise
        await manager.cancel()  # Should not raise
        
        assert not manager.is_generating
    
    @pytest.mark.asyncio
    async def test_wait_for_completion_timeout(self):
        """Test wait_for_completion with timeout."""
        manager = AsyncRunningPromptManager()
        
        async def very_slow_task():
            await asyncio.sleep(100)
            return "done"
        
        await manager.start_generation(very_slow_task)
        
        with pytest.raises(asyncio.TimeoutError):
            await manager.wait_for_completion(timeout=0.01)
        
        # Clean up
        await manager.cancel()
    
    @pytest.mark.asyncio
    async def test_progress_callback_invocation(self):
        """Test that progress callback receives chunks."""
        manager = AsyncRunningPromptManager()
        chunks = []
        
        def on_chunk(chunk):
            chunks.append(chunk)
        
        manager.on_chunk = on_chunk
        
        # Note: This requires function to accept _progress_callback
        # which is checked in _generation_worker
        async def task_with_progress(_progress_callback=None):
            if _progress_callback:
                _progress_callback("chunk1")
                _progress_callback("chunk2")
                _progress_callback("chunk3")
            await asyncio.sleep(0.01)
            return "done"
        
        await manager.start_generation(task_with_progress)
        await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        
        assert chunks == ["chunk1", "chunk2", "chunk3"]


class TestAsyncPromptDelegateAdvanced:
    """Advanced tests for AsyncPromptDelegate."""
    
    @pytest.mark.asyncio
    async def test_handle_tab_not_generating(self):
        """Test Tab handling when not generating - should not handle."""
        manager = AsyncRunningPromptManager()
        delegate = AsyncPromptDelegate(manager)
        delegate.activate()
        
        # Not generating - should return False
        handled = await delegate.handle_tab("test")
        assert not handled
    
    @pytest.mark.asyncio
    async def test_handle_enter_not_generating(self):
        """Test Enter handling when not generating - should not handle."""
        manager = AsyncRunningPromptManager()
        delegate = AsyncPromptDelegate(manager)
        delegate.activate()
        
        # Not generating - should return False
        handled = await delegate.handle_enter("test")
        assert not handled
    
    @pytest.mark.asyncio
    async def test_handle_escape_not_generating(self):
        """Test Escape handling when not generating - should not handle."""
        manager = AsyncRunningPromptManager()
        delegate = AsyncPromptDelegate(manager)
        delegate.activate()
        
        # Not generating - should return False
        handled = await delegate.handle_escape()
        assert not handled
    
    @pytest.mark.asyncio
    async def test_handle_tab_when_inactive(self):
        """Test Tab handling when delegate is inactive."""
        manager = AsyncRunningPromptManager()
        delegate = AsyncPromptDelegate(manager)
        # Don't activate
        
        async def slow_task():
            await asyncio.sleep(0.1)
            return "done"
        
        await manager.start_generation(slow_task)
        
        # Inactive - should return False
        handled = await delegate.handle_tab("test")
        assert not handled
        
        await manager.cancel()
    
    @pytest.mark.asyncio
    async def test_delegate_lifecycle(self):
        """Test activate/deactivate lifecycle."""
        manager = AsyncRunningPromptManager()
        delegate = AsyncPromptDelegate(manager)
        
        assert not delegate.is_active
        
        delegate.activate()
        assert delegate.is_active
        
        delegate.deactivate()
        assert not delegate.is_active
        
        # Can reactivate
        delegate.activate()
        assert delegate.is_active
