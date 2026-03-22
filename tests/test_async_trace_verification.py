"""
Tests for async integration trace verification.

These tests verify that all methods and imports required by the async
integration are properly defined and accessible.
"""

import asyncio
import inspect
import pytest


class TestUIExports:
    """Verify all UI component exports are valid."""
    
    def test_live_rich_console_export(self):
        """LiveRichConsole must be exported."""
        from aider.ui import LiveRichConsole
        
        # Should be importable from main ui module
        from aider.ui import LiveRichConsole as BC
        assert BC is LiveRichConsole
    
    def test_all_ui_exports_exist(self):
        """All exports in __all__ must be importable."""
        from aider.ui import (
            DockedPromptSession,
            PromptMode,
            StatusBarRenderer,
            LiveOutputManager,
            LiveRichConsole,
            ThinkingStateManager,
            AsyncSendMessageAdapter,
            ThinkingState,
            FileMentionCompleter,
            SlashCommandCompleter,
            InputHighlighter,
            create_enhanced_completer,
        )
        
        # Verify they're all defined
        assert DockedPromptSession is not None
        assert PromptMode is not None
        assert StatusBarRenderer is not None
        assert LiveOutputManager is not None
        assert LiveRichConsole is not None
        assert ThinkingStateManager is not None
        assert AsyncSendMessageAdapter is not None
        assert ThinkingState is not None
        assert FileMentionCompleter is not None
        assert SlashCommandCompleter is not None
        assert InputHighlighter is not None
        assert create_enhanced_completer is not None


class TestHooksManagerAsync:
    """Verify HooksManager has async execution methods."""
    
    def test_execute_async_exists(self):
        """execute_async must exist and be a coroutine."""
        from aider.hooks_manager import HooksManager
        
        assert hasattr(HooksManager, 'execute_async')
        assert inspect.iscoroutinefunction(HooksManager.execute_async)
    
    def test_execute_hooks_async_exists(self):
        """_execute_hooks_async must exist and be a coroutine."""
        from aider.hooks_manager import HooksManager
        
        assert hasattr(HooksManager, '_execute_hooks_async')
        assert inspect.iscoroutinefunction(HooksManager._execute_hooks_async)
    
    def test_execute_hook_async_exists(self):
        """_execute_hook_async must exist and be a coroutine."""
        from aider.hooks_manager import HooksManager
        
        assert hasattr(HooksManager, '_execute_hook_async')
        assert inspect.iscoroutinefunction(HooksManager._execute_hook_async)
    
    @pytest.mark.asyncio
    async def test_execute_async_basic(self):
        """execute_async works with no hooks registered."""
        from aider.hooks_manager import HooksManager
        
        manager = HooksManager()
        
        # Should not fail when no hooks are registered
        result = await manager.execute_async("on_exit", coder=None)
        
        assert isinstance(result, dict)
        assert result["hook_name"] == "on_exit"
        assert result["executed"] is False


class TestAsyncRunningPromptManagerMethods:
    """Verify AsyncRunningPromptManager has all required methods."""
    
    def test_all_async_methods_exist(self):
        """All required async methods must exist."""
        from aider.async_running_prompt import AsyncRunningPromptManager
        
        required_async_methods = [
            'start_generation',
            'queue_message',
            'steer',
            'cancel',
            'wait_for_completion',
            'shutdown',
        ]
        
        for method_name in required_async_methods:
            assert hasattr(AsyncRunningPromptManager, method_name), \
                f"Missing method: {method_name}"
            assert inspect.iscoroutinefunction(
                getattr(AsyncRunningPromptManager, method_name)
            ), f"{method_name} should be async"
    
    def test_properties_exist(self):
        """Required properties must exist."""
        from aider.async_running_prompt import AsyncRunningPromptManager
        
        manager = AsyncRunningPromptManager()
        
        # These should be properties/attributes
        assert hasattr(manager, 'state')
        assert hasattr(manager, 'is_generating')
        assert hasattr(manager, 'is_idle')
        assert hasattr(manager, 'has_queued_messages')


class TestInputOutputAsyncMethods:
    """Verify InputOutput has all required async methods."""
    
    def test_async_methods_exist(self):
        """All async methods must exist on InputOutput."""
        from aider.io import InputOutput
        
        io = InputOutput(fancy_input=False)
        
        required_methods = [
            'get_input_async',
            'display_user_input_async',
            'start_live_output',
            'stop_live_output',
        ]
        
        for method_name in required_methods:
            assert hasattr(io, method_name), f"Missing method: {method_name}"
    
    def test_async_properties_exist(self):
        """Async-related properties must exist."""
        from aider.io import InputOutput
        
        io = InputOutput(fancy_input=False)
        
        assert hasattr(io, 'async_prompt_session')
        assert hasattr(io, 'async_running_prompt_manager')


class TestBaseCoderControlAsync:
    """Verify BaseCoderControlMixin has async methods."""
    
    def test_run_async_exists(self):
        """run_async must exist and be a coroutine."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        assert hasattr(BaseCoderControlMixin, 'run_async')
        assert inspect.iscoroutinefunction(BaseCoderControlMixin.run_async)
    
    def test_get_input_async_exists(self):
        """get_input_async must exist and be a coroutine."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        assert hasattr(BaseCoderControlMixin, 'get_input_async')
        assert inspect.iscoroutinefunction(BaseCoderControlMixin.get_input_async)
    
    def test_run_one_async_exists(self):
        """run_one_async must exist and be a coroutine."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        assert hasattr(BaseCoderControlMixin, 'run_one_async')
        assert inspect.iscoroutinefunction(BaseCoderControlMixin.run_one_async)


class TestRuntimeAsync:
    """Verify runtime module has async session support."""
    
    def test_run_interactive_session_async_exists(self):
        """run_interactive_session_async must exist and be a coroutine."""
        from aider.bootstrap.runtime import run_interactive_session_async
        
        assert inspect.iscoroutinefunction(run_interactive_session_async)


class TestImportChain:
    """Verify the full async import chain works."""
    
    def test_main_imports(self):
        """main module must import successfully."""
        from aider.main import main
        assert callable(main)
    
    def test_main_async_imports(self):
        """main_async module must import successfully."""
        from aider.main_async import run_async_main, async_main
        assert callable(run_async_main)
        assert inspect.iscoroutinefunction(async_main)
    
    def test_full_async_chain(self):
        """Full async chain must be importable."""
        from aider.main import main
        from aider.main_async import run_async_main, async_main
        from aider.bootstrap.runtime import run_interactive_session_async
        from aider.coders.base_coder_control import BaseCoderControlMixin
        from aider.async_running_prompt import AsyncRunningPromptManager
        from aider.io import InputOutput
        from aider.hooks_manager import HooksManager
        
        # Verify the chain is connected
        assert hasattr(BaseCoderControlMixin, 'run_async')
        assert hasattr(AsyncRunningPromptManager, 'start_generation')
        assert hasattr(InputOutput, 'get_input_async')
        assert hasattr(HooksManager, 'execute_async')


class TestMessageQueueBounded:
    """Verify MessageQueue has size limits."""
    
    def test_queue_has_maxsize(self):
        """MessageQueue must have maxsize parameter."""
        from aider.async_compat import MessageQueue
        
        # Default maxsize
        q1 = MessageQueue()
        assert q1._queue.maxsize == 100
        
        # Custom maxsize
        q2 = MessageQueue(maxsize=50)
        assert q2._queue.maxsize == 50


class TestRichMarkupEscape:
    """Verify Rich markup is escaped in user-facing output."""
    
    def test_escape_imported(self):
        """escape must be imported in async_running_prompt."""
        from aider.async_running_prompt import escape
        from rich.markup import escape as rich_escape
        
        assert escape is rich_escape
