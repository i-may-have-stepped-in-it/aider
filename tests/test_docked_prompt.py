"""
Tests for docked prompt UI components.
"""
import pytest
from aider.ui import DockedPromptSession, PromptMode
from aider.ui.status_bar import StatusBarRenderer, GitStatus


class TestPromptMode:
    """Test PromptMode enum."""
    
    def test_agent_symbol(self):
        assert PromptMode.AGENT.symbol == "✨"
        assert PromptMode.AGENT.thinking_symbol == "💫"
    
    def test_shell_symbol(self):
        assert PromptMode.SHELL.symbol == "$"
        assert PromptMode.SHELL.thinking_symbol == "⚡"
    
    def test_toggle(self):
        assert PromptMode.AGENT.toggle() == PromptMode.SHELL
        assert PromptMode.SHELL.toggle() == PromptMode.AGENT
        # Double toggle should return to original
        assert PromptMode.AGENT.toggle().toggle() == PromptMode.AGENT


class TestGitStatus:
    """Test GitStatus dataclass."""
    
    def test_badge_clean_branch(self):
        status = GitStatus(branch="main", dirty=False)
        assert status.badge == "main"
    
    def test_badge_dirty_branch(self):
        status = GitStatus(branch="main", dirty=True)
        assert status.badge == "main*"
    
    def test_badge_ahead_behind(self):
        status = GitStatus(branch="feature", dirty=False, ahead=2, behind=1)
        assert status.badge == "feature↑2↓1"
    
    def test_badge_full_status(self):
        status = GitStatus(branch="feature", dirty=True, ahead=1, behind=0)
        assert status.badge == "feature*↑1"


class TestDockedPromptSession:
    """Test DockedPromptSession."""
    
    def test_creation_defaults(self):
        session = DockedPromptSession()
        assert session.mode == PromptMode.AGENT
        assert session._status.model_name == ""
    
    def test_creation_with_model(self):
        session = DockedPromptSession(model_name="gpt-4")
        assert session._status.model_name == "gpt-4"
    
    def test_mode_toggle(self):
        session = DockedPromptSession()
        assert session.mode == PromptMode.AGENT
        
        session.mode = PromptMode.SHELL
        assert session.mode == PromptMode.SHELL
    
    def test_update_status(self):
        session = DockedPromptSession()
        session.update_status(
            model_name="claude-3",
            git_branch="main",
            context_used=1000,
            context_total=8000,
        )
        
        assert session._status.model_name == "claude-3"
        assert session._status.git_branch == "main"
        assert session._status.context_used == 1000
        assert session._status.context_total == 8000
    
    def test_running_state(self):
        session = DockedPromptSession()
        
        # Initially not running
        assert not session._running
        
        # Set running
        session.set_running(True)
        assert session._running
        
        # Stop running
        session.set_running(False)
        assert not session._running
        assert session._queued_input is None
    
    def test_queued_input(self):
        session = DockedPromptSession()
        
        # No queued input initially
        assert not session.has_queued_input()
        assert session.get_queued_input() is None
        
        # Simulate queued input (would normally happen via Tab during generation)
        session._queued_input = "test message"
        assert session.has_queued_input()
        assert session.get_queued_input() == "test message"
        
        # Queue is now empty
        assert not session.has_queued_input()


class TestStatusBarRenderer:
    """Test StatusBarRenderer."""
    
    def test_creation(self):
        def provider():
            return {"mode": PromptMode.AGENT}
        
        renderer = StatusBarRenderer(provider)
        assert renderer._status_provider is provider
    
    def test_shorten_cwd_home(self):
        import os
        renderer = StatusBarRenderer(lambda: {})
        home = os.path.expanduser("~")
        result = renderer._shorten_cwd(home)
        assert result == "~"
    
    def test_shorten_cwd_subdir(self):
        import os
        renderer = StatusBarRenderer(lambda: {})
        home = os.path.expanduser("~")
        path = f"{home}/projects/myapp"
        result = renderer._shorten_cwd(path)
        assert "~" in result
        assert "myapp" in result
    
    def test_get_shortcuts_agent_mode(self):
        renderer = StatusBarRenderer(lambda: {})
        shortcuts = renderer._get_shortcuts({"mode": PromptMode.AGENT})
        
        assert "ctrl-x" in shortcuts
        assert "agent mode" in shortcuts or "shell mode" in shortcuts
    
    def test_get_shortcuts_shell_mode(self):
        renderer = StatusBarRenderer(lambda: {})
        shortcuts = renderer._get_shortcuts({"mode": PromptMode.SHELL})
        
        assert "ctrl-x" in shortcuts
        # In shell mode, ctrl-x switches to agent mode
        assert "agent" in shortcuts
    
    def test_get_shortcuts_running(self):
        renderer = StatusBarRenderer(lambda: {})
        shortcuts = renderer._get_shortcuts({"mode": PromptMode.AGENT, "running": True})
        
        assert "steer" in shortcuts
        assert "cancel" in shortcuts


class TestIntegrationWithIO:
    """Test integration with InputOutput class."""
    
    def test_io_has_docked_prompt_methods(self):
        from aider.io import InputOutput
        
        io = InputOutput(pretty=False, fancy_input=False)
        
        # Check that docked prompt methods exist
        assert hasattr(io, '_docked_prompt')
        assert hasattr(io, 'set_running_state')
        assert hasattr(io, 'on_context_update')
    
    def test_io_set_model_updates_docked_prompt(self):
        from aider.io import InputOutput
        
        io = InputOutput(pretty=False, fancy_input=False)
        # When fancy_input=False, docked_prompt is not created
        assert io._docked_prompt is None
        
        # Method should still work
        io.set_model("gpt-4")
        assert io.status_data["model_name"] == "gpt-4"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
