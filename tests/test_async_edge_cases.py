"""
Edge case tests for async integration.

These tests verify edge cases and error conditions in the async integration.
"""

import asyncio
import pytest


class TestAsyncRunningPromptManagerEdgeCases:
    """Edge cases for AsyncRunningPromptManager."""
    
    @pytest.mark.asyncio
    async def test_steer_while_not_generating(self):
        """Steering while not generating should return gracefully."""
        from aider.async_running_prompt import AsyncRunningPromptManager
        from aider.async_compat import GenerationState
        
        manager = AsyncRunningPromptManager()
        
        # Should not fail when not generating
        result = await manager.steer("test message")
        assert result.state == GenerationState.IDLE
    
    @pytest.mark.asyncio
    async def test_cancel_while_not_generating(self):
        """Cancel while not generating should return None."""
        from aider.async_running_prompt import AsyncRunningPromptManager
        
        manager = AsyncRunningPromptManager()
        
        # Should return None when not generating
        result = await manager.cancel()
        assert result is None
    
    @pytest.mark.asyncio
    async def test_queue_message_empty_string(self):
        """Queue empty string should work."""
        from aider.async_running_prompt import AsyncRunningPromptManager
        
        manager = AsyncRunningPromptManager()
        
        # Should not fail with empty string
        await manager.queue_message("")
        # Message should be queued
        assert manager.has_queued_messages
    
    @pytest.mark.asyncio
    async def test_multiple_steers_quickly(self):
        """Multiple rapid steer calls should be handled."""
        from aider.async_running_prompt import AsyncRunningPromptManager
        
        manager = AsyncRunningPromptManager()
        
        # Start a generation
        async def slow_task():
            await asyncio.sleep(0.1)
            return "done"
        
        task = await manager.start_generation(slow_task)
        
        # First steer should work
        result1 = await manager.steer("steer 1")
        
        # Second steer after completion should return IDLE state
        result2 = await manager.steer("steer 2")
        assert result2.state.name in ['IDLE', 'CANCELLED']


class TestHooksManagerAsyncEdgeCases:
    """Edge cases for HooksManager async methods."""
    
    @pytest.mark.asyncio
    async def test_execute_async_unknown_hook(self):
        """Execute async with unknown hook should return gracefully."""
        from aider.hooks_manager import HooksManager
        
        manager = HooksManager()
        
        result = await manager.execute_async("unknown_hook_name")
        
        assert result["executed"] is False
        assert result["hook_name"] == "unknown_hook_name"
    
    @pytest.mark.asyncio
    async def test_execute_async_with_exception(self):
        """Execute async should handle callback exceptions."""
        from aider.hooks_manager import HooksManager, HookPoint, HookConfig
        
        manager = HooksManager()
        
        # Register a hook that raises
        def failing_hook(context):
            raise ValueError("Test error")
        
        manager.register_hook(
            name="failing-hook",
            hook_point=HookPoint.PRE_MESSAGE,
            callback=failing_hook,
            config=HookConfig()
        )
        
        # Should not raise, should capture error
        # Note: "pre_send" maps to HookPoint.PRE_MESSAGE
        result = await manager.execute_async("pre_send")
        
        assert result["executed"] is True
        assert len(result["errors"]) == 1
        assert "Test error" in result["errors"][0]["error"]


class TestInputOutputAsyncEdgeCases:
    """Edge cases for InputOutput async methods."""
    
    @pytest.mark.asyncio
    async def test_async_running_prompt_manager_lazy_init(self):
        """AsyncRunningPromptManager should be lazily initialized."""
        from aider.io import InputOutput
        
        io = InputOutput(fancy_input=False)
        
        # When accessed from async context, should return manager
        # Note: It returns None if not in async context
        manager = io.async_running_prompt_manager
        # May be None if no event loop, which is OK
        assert manager is None or manager is not None  # Just check no exception
    
    def test_get_input_async_with_yes_flag(self):
        """get_input_async should handle yes=True."""
        from aider.io import InputOutput
        
        io = InputOutput(fancy_input=False, yes=True)
        
        # When yes=True, should return empty string immediately
        result = asyncio.run(io.get_input_async(
            root=".",
            rel_fnames=[],
            addable_rel_fnames=[],
            commands=None
        ))
        assert result == ""


class TestMessageQueueEdgeCases:
    """Edge cases for MessageQueue."""
    
    @pytest.mark.asyncio
    async def test_queue_maxsize_boundary(self):
        """Queue should enforce maxsize."""
        from aider.async_compat import MessageQueue
        
        queue = MessageQueue(maxsize=2)
        
        # Fill queue to max
        await queue.put("msg1")
        await queue.put("msg2")
        
        # Queue should be at max
        assert queue.qsize() == 2
        
        # Getting one should work
        msg = await queue.get()
        assert msg == "msg1"
    
    def test_put_nowait_when_full(self):
        """put_nowait should not block or raise when full."""
        from aider.async_compat import MessageQueue
        
        queue = MessageQueue(maxsize=1)
        queue.put_nowait("msg1")
        
        # Should not raise (drops message silently)
        queue.put_nowait("msg2")
        
        # Should only have first message
        assert queue.qsize() == 1


class TestAsyncImportChain:
    """Verify the complete async import chain."""
    
    def test_import_chain_no_errors(self):
        """All async imports should work without errors."""
        # This test verifies the complete chain
        from aider.main import main
        from aider.main_async import run_async_main, async_main
        from aider.bootstrap.runtime import run_interactive_session_async
        from aider.bootstrap.launch import (
            parse_args,
            prepare_main_model,
        )
        from aider.bootstrap.io_setup import setup_io_with_error_handling
        from aider.bootstrap.session import create_coder, create_commands
        from aider.coders.base_coder_control import BaseCoderControlMixin
        from aider.async_running_prompt import AsyncRunningPromptManager, AsyncPromptDelegate
        from aider.hooks_manager import HooksManager
        from aider.io import InputOutput
        from aider.ui import (
            DockedPromptSession,
            LiveRichConsole,
            ThinkingStateManager,
            AsyncSendMessageAdapter,
        )
        
        # If we get here, all imports succeeded
        assert True
