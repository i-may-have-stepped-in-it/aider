"""
Integration tests for async/Option B architecture.

These tests verify the persistent prompt behavior where:
- Tab during generation queues a message
- Enter during generation steers (cancels + new)
- Input is never blocked during generation
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch

from aider.async_compat import GenerationState, QueuedMessage, SteerMessage
from aider.async_running_prompt import (
    AsyncPromptDelegate,
    AsyncRunningPromptManager,
)
from aider.io import InputOutput


class TestAsyncRunningPromptManager:
    """Test the AsyncRunningPromptManager core functionality."""
    
    @pytest.mark.asyncio
    async def test_initial_state(self):
        """Test that manager starts in IDLE state."""
        manager = AsyncRunningPromptManager()
        
        assert manager.state == GenerationState.IDLE
        assert manager.is_idle
        assert not manager.is_generating
        assert not manager.has_queued_messages
    
    @pytest.mark.asyncio
    async def test_start_generation(self):
        """Test starting a generation task."""
        manager = AsyncRunningPromptManager()
        
        async def dummy_task():
            await asyncio.sleep(0.001)
            return "result"
        
        task = await manager.start_generation(dummy_task)
        
        # State should be GENERATING
        assert manager.state == GenerationState.GENERATING
        assert manager.is_generating
        assert not manager.is_idle
        
        # Wait for completion with timeout
        result = await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        
        assert result.state == GenerationState.COMPLETED
        # After completion, state is COMPLETED (not IDLE)
        assert manager.state == GenerationState.COMPLETED
    
    @pytest.mark.asyncio
    async def test_queue_message(self):
        """Test queuing messages during generation."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            await asyncio.sleep(0.01)
            return "done"
        
        await manager.start_generation(slow_task)
        
        # Queue messages while generating
        await manager.queue_message("Message 1")
        await manager.queue_message("Message 2")
        
        assert manager.has_queued_messages
        
        # Wait for generation
        await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        
        # Check queued messages are still there
        assert manager.has_queued_messages
        messages = manager.get_queued_messages()
        assert messages == ["Message 1", "Message 2"]
        assert not manager.has_queued_messages
    
    @pytest.mark.asyncio
    async def test_steer_generation(self):
        """Test steering (cancel + new direction) during generation."""
        manager = AsyncRunningPromptManager()
        
        cancel_check = asyncio.Event()
        
        async def slow_task():
            # Check for cancellation periodically
            for _ in range(100):
                if manager._cancel_event.is_set():
                    cancel_check.set()
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.001)
            return "should not complete"
        
        await manager.start_generation(slow_task)
        
        # Steer the generation
        result = await manager.steer("New direction")
        
        assert result.state == GenerationState.CANCELLED
        assert manager.state == GenerationState.CANCELLED
        
        # Check steer message was queued
        assert manager.has_queued_messages
    
    @pytest.mark.asyncio
    async def test_cancel_generation(self):
        """Test cancelling generation without steering."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            for _ in range(100):
                if manager._cancel_event.is_set():
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.001)
            return "should not complete"
        
        await manager.start_generation(slow_task)
        
        result = await manager.cancel()
        
        assert result.state == GenerationState.CANCELLED
        assert manager.state == GenerationState.CANCELLED
    
    @pytest.mark.asyncio
    async def test_generation_error(self):
        """Test handling of generation errors."""
        manager = AsyncRunningPromptManager()
        
        async def failing_task():
            raise ValueError("Test error")
        
        await manager.start_generation(failing_task)
        
        result = await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        
        assert result.state == GenerationState.FAILED
        assert result.error is not None
        assert str(result.error) == "Test error"
    
    @pytest.mark.asyncio
    async def test_cannot_start_while_generating(self):
        """Test that starting new generation while one is active raises error."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            await asyncio.sleep(0.1)
            return "done"
        
        await manager.start_generation(slow_task)
        
        with pytest.raises(RuntimeError, match="Already generating"):
            await manager.start_generation(slow_task)
        
        # Clean up
        await manager.cancel()


class TestAsyncPromptDelegate:
    """Test the AsyncPromptDelegate bridge."""
    
    @pytest.mark.asyncio
    async def test_delegate_activation(self):
        """Test delegate activation/deactivation."""
        manager = AsyncRunningPromptManager()
        delegate = AsyncPromptDelegate(manager)
        
        assert not delegate.is_active
        
        delegate.activate()
        assert delegate.is_active
        
        delegate.deactivate()
        assert not delegate.is_active
    
    @pytest.mark.asyncio
    async def test_handle_tab_queues_message(self):
        """Test Tab key handling during generation."""
        manager = AsyncRunningPromptManager()
        delegate = AsyncPromptDelegate(manager)
        
        async def slow_task():
            for _ in range(100):
                if manager._cancel_event.is_set():
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.001)
            return "done"
        
        await manager.start_generation(slow_task)
        delegate.activate()
        
        # Tab should queue the message
        handled = await delegate.handle_tab("test message")
        
        assert handled
        assert manager.has_queued_messages
        
        # Clean up
        await manager.cancel()
    
    @pytest.mark.asyncio
    async def test_handle_enter_steers(self):
        """Test Enter key handling during generation."""
        manager = AsyncRunningPromptManager()
        delegate = AsyncPromptDelegate(manager)
        
        async def slow_task():
            for _ in range(100):
                if manager._cancel_event.is_set():
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.001)
            return "done"
        
        await manager.start_generation(slow_task)
        delegate.activate()
        
        # Enter should steer
        handled = await delegate.handle_enter("new direction")
        
        assert handled
        assert manager.state == GenerationState.CANCELLED  # Was cancelled
    
    @pytest.mark.asyncio
    async def test_handle_escape_cancels(self):
        """Test Escape key handling during generation."""
        manager = AsyncRunningPromptManager()
        delegate = AsyncPromptDelegate(manager)
        
        async def slow_task():
            for _ in range(100):
                if manager._cancel_event.is_set():
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.001)
            return "done"
        
        await manager.start_generation(slow_task)
        delegate.activate()
        
        # Escape should cancel
        handled = await delegate.handle_escape()
        
        assert handled
        assert manager.state == GenerationState.CANCELLED


class TestInputOutputAsync:
    """Test InputOutput async integration."""
    
    @pytest.mark.asyncio
    async def test_async_running_prompt_manager_creation(self):
        """Test that IO can create/get async running prompt manager."""
        io = InputOutput(pretty=False, fancy_input=False)
        
        manager = io.async_running_prompt_manager
        
        assert manager is not None
        assert isinstance(manager, AsyncRunningPromptManager)
        
        # Should return same instance
        manager2 = io.async_running_prompt_manager
        assert manager is manager2
    
    @pytest.mark.asyncio
    async def test_async_prompt_session(self):
        """Test async prompt session wrapper."""
        io = InputOutput(pretty=False, fancy_input=False)
        
        # Without fancy input, should be None
        assert io.async_prompt_session is None
    
    def test_is_async_mode_always_true(self):
        """Test that async mode is always on (default architecture)."""
        io = InputOutput(pretty=False, fancy_input=False)
        
        assert io.is_async_mode()


class TestAsyncCoderIntegration:
    """Test async coder integration."""
    
    @pytest.mark.asyncio
    async def test_run_async_methods_exist(self):
        """Test that all async methods exist on coder."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        # Check async methods exist
        assert hasattr(BaseCoderControlMixin, 'run_async')
        assert hasattr(BaseCoderControlMixin, 'get_input_async')
        assert hasattr(BaseCoderControlMixin, 'run_one_async')
    
    @pytest.mark.asyncio
    async def test_run_async_basic_flow(self):
        """Test basic async run flow."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        # Create a minimal mock setup
        class MockCoder(BaseCoderControlMixin):
            def __init__(self):
                self.io = MagicMock()
                self.io.placeholder = None
                self.io.async_running_prompt_manager = AsyncRunningPromptManager()
                self.abs_read_only_fnames = []
                self.edit_format = "diff"
                self.main_model = MagicMock()
                self.main_model.edit_format = "diff"
                self.commands = MagicMock()
                self.num_reflections = 0
                self.max_reflections = 3
                
            def copy_context(self):
                pass
                
            def show_undo_hint(self):
                pass
                
            def keyboard_interrupt(self):
                raise KeyboardInterrupt()
                
            def init_before_message(self):
                pass
                
            def preproc_user_input(self, inp):
                return inp
                
            def get_inchat_relative_files(self):
                return []
                
            def get_addable_relative_files(self):
                return []
                
            def get_rel_fname(self, fname):
                return fname
        
        coder = MockCoder()
        
        # Mock get_input_async to return a value then raise EOFError
        call_count = [0]
        async def mock_get_input_async():
            call_count[0] += 1
            if call_count[0] == 1:
                return "test message"
            raise EOFError()
        
        async def mock_run_one_async(msg, preproc):
            pass
        
        coder.get_input_async = mock_get_input_async
        coder.run_one_async = mock_run_one_async
        
        # Run should complete without error
        await coder.run_async()
        
        assert call_count[0] == 2


class TestAsyncCompatibility:
    """Test async compatibility utilities."""
    
    @pytest.mark.asyncio
    async def test_run_in_thread(self):
        """Test run_in_thread helper."""
        from aider.async_compat import run_in_thread
        
        def sync_func(x, y):
            return x + y
        
        result = await run_in_thread(sync_func, 1, 2)
        
        assert result == 3
    
    @pytest.mark.asyncio
    async def test_message_queue(self):
        """Test MessageQueue functionality."""
        from aider.async_compat import MessageQueue
        
        queue = MessageQueue()
        
        assert queue.empty()
        
        await queue.put("message 1")
        await queue.put("message 2")
        
        assert not queue.empty()
        assert queue.qsize() == 2
        
        msg1 = await queue.get()
        msg2 = await queue.get()
        
        assert msg1 == "message 1"
        assert msg2 == "message 2"
        assert queue.empty()
    
    @pytest.mark.asyncio
    async def test_async_event(self):
        """Test AsyncEvent functionality."""
        from aider.async_compat import AsyncEvent
        
        event = AsyncEvent()
        
        assert not event.is_set()
        
        event.set()
        
        assert event.is_set()
        
        # Test async wait
        result = await event.wait_async()
        assert result
        
        event.clear()
        assert not event.is_set()
    
    @pytest.mark.asyncio
    async def test_task_manager(self):
        """Test TaskManager functionality."""
        from aider.async_compat import TaskManager
        
        tm = TaskManager()
        
        async def dummy_task():
            await asyncio.sleep(0.001)
            return "done"
        
        task = tm.create_task(dummy_task())
        
        result = await task
        assert result == "done"
        
        # Test cleanup
        await tm.cancel_all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
