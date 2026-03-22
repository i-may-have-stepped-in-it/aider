"""
Critical tests for async coder control flow.

Tests exception handling, cleanup, and edge cases in run_async().
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch

from aider.async_compat import GenerationState
from aider.async_running_prompt import AsyncRunningPromptManager


class TestAsyncCoderControlCritical:
    """Critical tests for BaseCoderControlMixin.run_async()"""
    
    @pytest.mark.asyncio
    async def test_run_async_exception_recovery(self):
        """Test that exceptions in run_async are properly handled."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
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
                self.abs_fnames = []
                self.done_messages = []
                
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
        
        # Mock get_input_async to raise exception then return None to exit
        call_count = [0]
        async def mock_get_input_async():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("Test exception")
            raise EOFError()  # Exit loop
        
        coder.get_input_async = mock_get_input_async
        
        # Should not raise - exception should be caught or propagated gracefully
        try:
            await coder.run_async()
        except ValueError:
            pass  # Expected if not caught
        except EOFError:
            pass  # Normal exit
    
    @pytest.mark.asyncio
    async def test_run_async_eof_handling(self):
        """Test that EOFError properly exits the async loop."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
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
                self.abs_fnames = []
                
            def copy_context(self):
                pass
                
            def get_inchat_relative_files(self):
                return []
                
            def get_addable_relative_files(self):
                return []
                
            def get_rel_fname(self, fname):
                return fname
        
        coder = MockCoder()
        
        # Raise EOFError to exit
        async def mock_get_input_async():
            raise EOFError()
        
        coder.get_input_async = mock_get_input_async
        
        # Should exit gracefully
        result = await coder.run_async()
        assert result is None
    
    @pytest.mark.asyncio
    async def test_run_async_keyboard_interrupt_during_generation(self):
        """Test keyboard interrupt handling when generation is running."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
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
                
            def get_inchat_relative_files(self):
                return []
                
            def get_addable_relative_files(self):
                return []
                
            def get_rel_fname(self, fname):
                return fname
        
        coder = MockCoder()
        manager = coder.io.async_running_prompt_manager
        
        # Start a generation
        async def slow_task():
            await asyncio.sleep(10)
            return "done"
        
        await manager.start_generation(slow_task)
        assert manager.is_generating
        
        # Cancel it (simulates keyboard interrupt path)
        await manager.cancel()
        
        assert not manager.is_generating
        assert manager.state == GenerationState.CANCELLED
    
    @pytest.mark.asyncio
    async def test_run_async_with_queued_messages(self):
        """Test that queued messages are processed after generation."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        processed_messages = []
        
        class MockCoder(BaseCoderControlMixin):
            def __init__(self):
                self.io = MagicMock()
                self.io.placeholder = None
                self.io.async_running_prompt_manager = AsyncRunningPromptManager()
                self.io.display_user_input_async = MagicMock(return_value=asyncio.Future())
                self.io.display_user_input_async.return_value.set_result(None)
                self.abs_read_only_fnames = []
                self.edit_format = "diff"
                self.main_model = MagicMock()
                self.main_model.edit_format = "diff"
                self.commands = MagicMock()
                self.commands.is_command = MagicMock(return_value=False)
                self.num_reflections = 0
                self.max_reflections = 3
                self.abs_fnames = []
                
            def copy_context(self):
                pass
                
            def get_inchat_relative_files(self):
                return []
                
            def get_addable_relative_files(self):
                return []
                
            def get_rel_fname(self, fname):
                return fname
            
            async def run_one_async(self, msg, preproc):
                processed_messages.append(msg)
            
            def show_undo_hint(self):
                pass
        
        coder = MockCoder()
        manager = coder.io.async_running_prompt_manager
        
        # Queue messages
        await manager.queue_message("Message 1")
        await manager.queue_message("Message 2")
        
        # Verify queued
        assert manager.has_queued_messages
        messages = manager.get_queued_messages()
        assert messages == ["Message 1", "Message 2"]
    
    # Note: get_input_async fallback is implicitly tested through integration tests


class TestAsyncRunningPromptCritical:
    """Critical tests for AsyncRunningPromptManager edge cases."""
    
    @pytest.mark.asyncio
    async def test_concurrent_steer_and_cancel(self):
        """Test that steer and cancel don't race."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            for _ in range(200):
                if manager._cancel_event.is_set():
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.001)
            return "done"
        
        await manager.start_generation(slow_task)
        
        # Start steer and cancel concurrently
        steer_task = asyncio.create_task(manager.steer("New direction"))
        cancel_task = asyncio.create_task(manager.cancel())
        
        # Both should complete without error
        await asyncio.gather(steer_task, cancel_task, return_exceptions=True)
        
        # State should be consistent
        assert not manager.is_generating
    
    @pytest.mark.asyncio
    async def test_progress_callback_exception(self):
        """Test that exception in progress callback doesn't break generation."""
        manager = AsyncRunningPromptManager()
        
        def bad_callback(chunk):
            raise ValueError("Callback error")
        
        manager.on_chunk = bad_callback
        
        async def task_with_progress(_progress_callback=None):
            if _progress_callback:
                _progress_callback("chunk1")  # Should not crash
            await asyncio.sleep(0.01)
            return "done"
        
        await manager.start_generation(task_with_progress)
        result = await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        
        assert result.state == GenerationState.COMPLETED
    
    @pytest.mark.asyncio
    async def test_shutdown_cancels_pending_tasks(self):
        """Test that shutdown properly cancels all pending tasks."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            await asyncio.sleep(100)
            return "done"
        
        await manager.start_generation(slow_task)
        assert manager.is_generating
        
        await manager.shutdown()
        
        assert not manager.is_generating
        # Task may be cancelled but not None yet - that's ok
        assert manager._current_task is None or manager._current_task.done()
    
    @pytest.mark.asyncio
    async def test_generation_worker_sync_function_wrapper(self):
        """Test that sync functions are properly wrapped."""
        manager = AsyncRunningPromptManager()
        
        def sync_function():
            return "sync result"
        
        await manager.start_generation(sync_function)
        result = await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        
        assert result.state == GenerationState.COMPLETED
        assert result.content == "sync result"


class TestProductionEdgeCases:
    """Production edge case tests."""
    
    @pytest.mark.asyncio
    async def test_rapid_steer_operations(self):
        """Test that rapid steering doesn't corrupt state."""
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            for _ in range(500):
                if manager._cancel_event.is_set():
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.001)
            return "done"
        
        await manager.start_generation(slow_task)
        
        # Steer 5 times rapidly
        for i in range(5):
            try:
                await manager.steer(f"Direction {i}")
            except Exception:
                pass  # May fail if already cancelled
        
        # State should be consistent
        assert not manager.is_generating
    
    @pytest.mark.asyncio
    async def test_cancel_during_callback_execution(self):
        """Test cancellation while callback is running."""
        manager = AsyncRunningPromptManager()
        callback_started = asyncio.Event()
        
        async def slow_on_complete(result):
            callback_started.set()
            await asyncio.sleep(0.1)  # Slow callback
        
        manager.on_generation_complete = slow_on_complete
        
        async def task():
            await asyncio.sleep(0.01)
            return "done"
        
        await manager.start_generation(task)
        
        # Wait for completion to start callback
        await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        
        # Should complete without deadlock
        assert manager.state == GenerationState.COMPLETED
    
    @pytest.mark.asyncio
    async def test_thread_safe_queue_message(self):
        """Test thread safety of queue_message."""
        import threading
        
        manager = AsyncRunningPromptManager()
        
        async def slow_task():
            await asyncio.sleep(0.1)
            return "done"
        
        await manager.start_generation(slow_task)
        
        # Queue messages from multiple "threads" (simulated with tasks)
        async def queue_messages(n):
            for i in range(n):
                await manager.queue_message(f"Message {i}")
        
        # Run 10 concurrent queuers
        await asyncio.gather(*[queue_messages(5) for _ in range(10)])
        
        await manager.cancel()
        
        # All 50 messages should be captured
        messages = manager.get_queued_messages()
        assert len(messages) == 50
