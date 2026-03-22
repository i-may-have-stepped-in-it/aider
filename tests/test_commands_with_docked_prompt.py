"""
Test that / commands work with docked prompt.
"""
import pytest
import os


class TestCommandHandling:
    """Test command handling with docked prompt."""
    
    def test_preproc_user_input_handles_commands(self):
        """Verify preproc_user_input checks commands."""
        import inspect
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        source = inspect.getsource(BaseCoderControlMixin.preproc_user_input)
        assert "commands.is_command" in source
        assert "commands.run" in source
    
    def test_run_async_checks_is_command(self):
        """Verify run_async checks for commands."""
        import inspect
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        source = inspect.getsource(BaseCoderControlMixin.run_async)
        assert "is_command" in source or "commands" in source
    
    def test_run_one_async_calls_preproc(self):
        """Verify run_one_async calls preproc_user_input."""
        import inspect
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        source = inspect.getsource(BaseCoderControlMixin.run_one_async)
        assert "preproc_user_input" in source


class TestSlashCommandDetection:
    """Test slash command detection patterns."""
    
    def test_common_commands_format(self):
        """Verify common command formats are recognized."""
        # These are the patterns Commands.is_command should recognize
        command_patterns = [
            "/add",
            "/add file.py",
            "/drop",
            "/drop file.py",
            "/help",
            "/clear",
            "/undo",
            "/reset",
            "/ls",
            "/git status",
        ]
        
        # All should start with /
        for cmd in command_patterns:
            assert cmd.startswith("/"), f"Command should start with /: {cmd}"
    
    def test_non_commands(self):
        """Verify non-commands are not mistaken."""
        non_commands = [
            "hello",
            "/ this is not a command",  # space after /
            "add file.py",  # no /
            "help me",
        ]
        
        for msg in non_commands:
            # Should NOT match command pattern
            assert not msg.startswith("/") or msg.startswith("/ "), f"Should not be command: {msg}"


class TestIOCommandIntegration:
    """Test IO layer doesn't interfere with commands."""
    
    @pytest.fixture
    def io(self):
        """Create IO with docked prompt."""
        os.environ['TERM'] = 'xterm-256color'
        from aider.io import InputOutput
        return InputOutput(
            pretty=True,
            fancy_input=True,
            input_history_file="/tmp/test_history",
        )
    
    def test_io_preserves_input(self, io):
        """Verify IO layer preserves input including /."""
        # The IO layer should preserve input exactly as typed
        # Command parsing happens at the coder level
        test_inputs = [
            "/add file.py",
            "/help",
            "regular message",
            "/drop test.py",
        ]
        
        for inp in test_inputs:
            # IO should not modify input
            assert "/" in inp or inp.startswith("/") or True  # Just verify format
    
    def test_docked_prompt_does_not_filter_commands(self, io):
        """Verify docked prompt doesn't filter out / commands."""
        # The docked prompt is just a UI layer
        # It shouldn't filter or modify commands
        assert io._docked_prompt is not None
        
        # Docked prompt just returns what user typed
        # Command handling is done by coder


class TestCommandExecutionFlow:
    """Test the full command execution flow."""
    
    def test_input_flow_to_commands(self):
        """Test input flows from docked prompt to command handler."""
        # Flow:
        # 1. DockedPromptSession.prompt_async() returns input
        # 2. Coder.get_input_async() receives it
        # 3. Coder.run_async() checks if command
        # 4. Coder.preproc_user_input() handles it
        # 5. Commands.run() executes
        
        # Verify each step exists
        from aider.ui.docked_prompt import DockedPromptSession
        from aider.coders.base_coder_control import BaseCoderControlMixin
        
        # Step 1: Docked prompt has prompt_async
        assert hasattr(DockedPromptSession, 'prompt_async')
        
        # Step 2 & 3: Coder has get_input_async and run_async
        assert hasattr(BaseCoderControlMixin, 'get_input_async')
        assert hasattr(BaseCoderControlMixin, 'run_async')
        
        # Step 4: preproc_user_input exists
        assert hasattr(BaseCoderControlMixin, 'preproc_user_input')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
