"""
Test that all UI components are properly exported.
"""
import pytest


class TestUIExports:
    """Test all UI exports are available."""
    
    def test_docked_prompt_session_export(self):
        """Verify DockedPromptSession is exported."""
        from aider.ui import DockedPromptSession
        assert DockedPromptSession is not None
    
    def test_prompt_mode_export(self):
        """Verify PromptMode is exported."""
        from aider.ui import PromptMode
        assert PromptMode is not None
        # Verify enum values
        assert PromptMode.AGENT.value == "agent"
        assert PromptMode.SHELL.value == "shell"
    
    def test_status_bar_renderer_export(self):
        """Verify StatusBarRenderer is exported."""
        from aider.ui import StatusBarRenderer
        assert StatusBarRenderer is not None
    
    def test_live_output_manager_export(self):
        """Verify LiveOutputManager is exported."""
        from aider.ui import LiveOutputManager
        assert LiveOutputManager is not None
    
    def test_live_rich_console_export(self):
        """Verify LiveRichConsole is exported."""
        from aider.ui import LiveRichConsole
        assert LiveRichConsole is not None
    
    def test_thinking_state_manager_export(self):
        """Verify ThinkingStateManager is exported."""
        from aider.ui import ThinkingStateManager
        assert ThinkingStateManager is not None
    
    def test_async_send_message_adapter_export(self):
        """Verify AsyncSendMessageAdapter is exported."""
        from aider.ui import AsyncSendMessageAdapter
        assert AsyncSendMessageAdapter is not None
    
    def test_thinking_state_export(self):
        """Verify ThinkingState is exported."""
        from aider.ui import ThinkingState
        assert ThinkingState is not None
    
    def test_file_mention_completer_export(self):
        """Verify FileMentionCompleter is exported."""
        from aider.ui import FileMentionCompleter
        assert FileMentionCompleter is not None
    
    def test_slash_command_completer_export(self):
        """Verify SlashCommandCompleter is exported."""
        from aider.ui import SlashCommandCompleter
        assert SlashCommandCompleter is not None
    
    def test_input_highlighter_export(self):
        """Verify InputHighlighter is exported."""
        from aider.ui import InputHighlighter
        assert InputHighlighter is not None
    
    def test_create_enhanced_completer_export(self):
        """Verify create_enhanced_completer is exported."""
        from aider.ui import create_enhanced_completer
        assert create_enhanced_completer is not None


class TestLiveOutputManagerFunctionality:
    """Test LiveOutputManager specific functionality."""
    
    def test_creation(self):
        """Verify LiveOutputManager can be created."""
        from aider.ui import LiveOutputManager
        
        manager = LiveOutputManager()
        assert manager is not None
        assert not manager.is_active
    
    def test_add_output(self):
        """Verify output can be added."""
        from aider.ui import LiveOutputManager
        
        manager = LiveOutputManager()
        manager.add_output("Test message")
        
        assert len(manager._output_buffer) > 0
    
    def test_clear(self):
        """Verify clear works."""
        from aider.ui import LiveOutputManager
        
        manager = LiveOutputManager()
        manager.add_output("Test")
        manager.clear()
        
        assert len(manager._output_buffer) == 0


class TestLiveRichConsoleFunctionality:
    """Test LiveRichConsole specific functionality."""
    
    def test_creation(self):
        """Verify LiveRichConsole can be created."""
        from aider.ui import LiveOutputManager, LiveRichConsole
        from rich.console import Console
        
        live = LiveOutputManager()
        base = Console()
        bridged = LiveRichConsole(live, base)
        
        assert bridged is not None
    
    def test_print_routes_to_live(self):
        """Verify print routes to live manager."""
        from aider.ui import LiveOutputManager, LiveRichConsole
        from rich.console import Console
        
        live = LiveOutputManager()
        base = Console()
        bridged = LiveRichConsole(live, base)
        
        initial = len(live._output_buffer)
        bridged.print("Test message")
        
        assert len(live._output_buffer) > initial


class TestEndToEndIntegration:
    """Test end-to-end integration of all components."""
    
    def test_full_ui_stack_creation(self):
        """Verify full UI stack can be created."""
        import os
        os.environ['TERM'] = 'xterm-256color'
        
        from aider.io import InputOutput
        from aider.ui import (
            DockedPromptSession,
            LiveOutputManager,
            LiveRichConsole,
        )
        
        io = InputOutput(
            pretty=True,
            fancy_input=True,
            input_history_file="/tmp/test",
        )
        
        # Verify all components are linked
        assert io._docked_prompt is not None
        assert io._live_output is not None
        assert isinstance(io.console, LiveRichConsole)
        
        # Verify live output manager is correct type
        assert isinstance(io._live_output, LiveOutputManager)
    
    def test_io_start_stop_live_output(self):
        """Verify IO can start and stop live output."""
        import os
        os.environ['TERM'] = 'xterm-256color'
        
        from aider.io import InputOutput
        
        io = InputOutput(
            pretty=True,
            fancy_input=True,
            input_history_file="/tmp/test",
        )
        
        # Start live output
        io.start_live_output()
        # Don't check is_active because Live requires real terminal
        
        # Stop live output
        io.stop_live_output()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
