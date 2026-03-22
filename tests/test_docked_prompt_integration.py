"""
Integration tests for docked prompt UI.

Tests the complete execution path from main() through to docked prompt.
"""
import os
import sys
import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock


class TestMainExecutionPath:
    """Test the main execution path uses async/docked prompt."""
    
    def test_main_delegates_to_run_async_main(self):
        """Verify main() delegates to run_async_main."""
        from aider.main import main
        import inspect
        
        source = inspect.getsource(main)
        assert "run_async_main" in source
        assert "from aider.main_async import run_async_main" in source
    
    def test_run_async_main_exists(self):
        """Verify run_async_main exists and is callable."""
        from aider.main_async import run_async_main
        assert callable(run_async_main)
    
    def test_async_main_imports(self):
        """Verify all imports in async_main are available."""
        # These are all the imports from async_main
        from aider.bootstrap.launch import (
            apply_env_and_deprecated_args,
            check_and_load_imports,
            get_git_root,
            is_first_run_of_new_version,
            prepare_main_model,
            prepare_repo_and_runtime,
            should_background_semantic_index,
            should_preload_imports,
            parse_args,
        )
        from aider.bootstrap.runtime import (
            attach_runtime_services,
            dispatch_session_mode,
            handle_pre_run_actions,
            run_interactive_session_async,
        )
        from aider.bootstrap.session import (
            create_coder,
            create_commands,
            create_summarizer,
            finalize_streaming_settings,
        )
        from aider.bootstrap.update_flows import (
            handle_analytics_setup,
            handle_gui_flow,
            handle_hooks_setup,
            handle_shell_completions,
            handle_ssl_setup,
            handle_theme_setup,
            handle_timeout_setup,
            handle_update_flows,
            setup_git,
        )
        from aider.bootstrap.git_handler import handle_git_root_recursion
        from aider.bootstrap.gui import launch_gui
        from aider.bootstrap.io_setup import (
            format_and_log_settings,
            resolve_file_arguments,
            setup_io_with_error_handling,
        )
        
        # If we get here, all imports succeeded
        assert True


class TestIOCompleteInterface:
    """Test InputOutput has all methods needed by coders."""
    
    @pytest.fixture
    def io(self):
        """Create an InputOutput instance with docked prompt."""
        os.environ['TERM'] = 'xterm-256color'
        from aider.io import InputOutput
        return InputOutput(
            pretty=True,
            fancy_input=True,
            input_history_file="/tmp/test_history",
        )
    
    def test_io_has_docked_prompt(self, io):
        """Verify docked prompt is created."""
        assert io._docked_prompt is not None
    
    def test_io_has_required_methods(self, io):
        """Verify all methods used by coders exist."""
        required_methods = [
            'user_input',
            'tool_error',
            'tool_warning',
            'get_input',
            'get_input_async',
            'display_user_input_async',
            'confirm_ask',
            'offer_url',
            'set_model',
            'set_git_branch',
            'clear',
            'on_context_update',
            'set_running_state',
        ]
        for method in required_methods:
            assert hasattr(io, method), f"Missing method: {method}"
    
    def test_io_has_required_attributes(self, io):
        """Verify all attributes used by coders exist."""
        required_attrs = [
            'placeholder',
            'async_running_prompt_manager',
            'async_prompt_session',
            'fancy_input',
        ]
        for attr in required_attrs:
            assert hasattr(io, attr), f"Missing attribute: {attr}"
    
    def test_set_model_updates_docked_prompt(self, io):
        """Verify set_model updates docked prompt."""
        io.set_model("gpt-4")
        assert io._docked_prompt._status.model_name == "gpt-4"
    
    def test_set_git_branch_updates_docked_prompt(self, io):
        """Verify set_git_branch updates docked prompt."""
        io.set_git_branch("main")
        assert io._docked_prompt._status.git_branch == "main"
    
    def test_on_context_update_updates_docked_prompt(self, io):
        """Verify on_context_update updates docked prompt."""
        io.on_context_update(1000, 8000)
        assert io._docked_prompt._status.context_used == 1000
        assert io._docked_prompt._status.context_total == 8000
    
    def test_set_running_state_updates_docked_prompt(self, io):
        """Verify set_running_state updates docked prompt."""
        io.set_running_state(True)
        assert io._docked_prompt._running is True
        io.set_running_state(False)
        assert io._docked_prompt._running is False


class TestCoderUsesAsyncPath:
    """Test that coders use the async path correctly."""
    
    def test_base_coder_control_has_run_async(self):
        """Verify BaseCoderControlMixin has run_async method."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        assert hasattr(BaseCoderControlMixin, 'run_async')
    
    def test_base_coder_control_has_get_input_async(self):
        """Verify BaseCoderControlMixin has get_input_async method."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        assert hasattr(BaseCoderControlMixin, 'get_input_async')
    
    def test_get_input_async_uses_io_get_input_async(self):
        """Verify get_input_async calls io.get_input_async."""
        import inspect
        from aider.coders.base_coder_control import BaseCoderControlMixin
        source = inspect.getsource(BaseCoderControlMixin.get_input_async)
        assert "io.get_input_async" in source


class TestDockedPromptModes:
    """Test docked prompt mode switching."""
    
    @pytest.fixture
    def session(self):
        """Create a DockedPromptSession."""
        from aider.ui import DockedPromptSession
        return DockedPromptSession(model_name="test-model")
    
    def test_default_mode_is_agent(self, session):
        """Verify default mode is AGENT."""
        from aider.ui import PromptMode
        assert session.mode == PromptMode.AGENT
    
    def test_mode_toggle(self, session):
        """Verify mode can be toggled."""
        from aider.ui import PromptMode
        session.mode = PromptMode.SHELL
        assert session.mode == PromptMode.SHELL
        session.mode = PromptMode.AGENT
        assert session.mode == PromptMode.AGENT
    
    def test_mode_symbols(self, session):
        """Verify mode symbols are correct."""
        from aider.ui import PromptMode
        assert PromptMode.AGENT.symbol == "✨"
        assert PromptMode.SHELL.symbol == "$"


class TestStatusBarRendering:
    """Test status bar rendering components."""
    
    def test_git_status_badge_clean(self):
        """Verify GitStatus badge for clean branch."""
        from aider.ui.status_bar import GitStatus
        status = GitStatus(branch="main", dirty=False)
        assert status.badge == "main"
    
    def test_git_status_badge_dirty(self):
        """Verify GitStatus badge for dirty branch."""
        from aider.ui.status_bar import GitStatus
        status = GitStatus(branch="main", dirty=True)
        assert status.badge == "main*"
    
    def test_git_status_badge_ahead(self):
        """Verify GitStatus badge with ahead commits."""
        from aider.ui.status_bar import GitStatus
        status = GitStatus(branch="feature", ahead=3)
        assert "↑3" in status.badge
    
    def test_status_bar_shortens_cwd(self):
        """Verify status bar shortens cwd correctly."""
        from aider.ui.status_bar import StatusBarRenderer
        renderer = StatusBarRenderer(lambda: {})
        
        # Test home directory shortening
        home = os.path.expanduser("~")
        result = renderer._shorten_cwd(home)
        assert result == "~"
        
        # Test long path shortening
        long_path = f"{home}/very/long/path/to/project"
        result = renderer._shorten_cwd(long_path)
        assert len(result) <= 35  # Should be shortened


class TestEndToEndImports:
    """Test that all imports work in the complete chain."""
    
    def test_full_import_chain(self):
        """Verify all imports from entry point to docked prompt."""
        # Entry point
        from aider.main import main
        
        # Async path
        from aider.main_async import run_async_main, async_main
        
        # Bootstrap
        from aider.bootstrap.runtime import run_interactive_session_async
        from aider.bootstrap.session import create_coder
        
        # IO
        from aider.io import InputOutput
        
        # UI
        from aider.ui import DockedPromptSession, PromptMode
        from aider.ui.status_bar import StatusBarRenderer
        
        # Coders
        from aider.coders import Coder
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        # If we get here, all imports succeeded
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
