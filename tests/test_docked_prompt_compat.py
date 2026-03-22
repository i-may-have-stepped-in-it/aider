"""
Test docked prompt compatibility with AsyncPromptSession interface.
"""
import pytest


class TestAsyncPromptSessionCompatibility:
    """Test docked prompt is compatible with AsyncAiderPromptSession interface."""
    
    def test_has_attach_running_prompt(self):
        """Verify docked prompt has attach_running_prompt method."""
        from aider.ui.docked_prompt import DockedPromptSession
        
        session = DockedPromptSession()
        assert hasattr(session, 'attach_running_prompt')
        assert callable(session.attach_running_prompt)
    
    def test_has_detach_running_prompt(self):
        """Verify docked prompt has detach_running_prompt method."""
        from aider.ui.docked_prompt import DockedPromptSession
        
        session = DockedPromptSession()
        assert hasattr(session, 'detach_running_prompt')
        assert callable(session.detach_running_prompt)
    
    def test_has_prompt_async_with_message_param(self):
        """Verify prompt_async accepts message parameter."""
        from aider.ui.docked_prompt import DockedPromptSession
        import inspect
        
        session = DockedPromptSession()
        sig = inspect.signature(session.prompt_async)
        params = list(sig.parameters.keys())
        
        # Should have 'message' parameter for compatibility
        assert 'message' in params
    
    def test_attach_running_prompt_sets_running(self):
        """Verify attach_running_prompt sets running state."""
        from aider.ui.docked_prompt import DockedPromptSession
        
        session = DockedPromptSession()
        assert not session._running
        
        # Mock delegate
        class MockDelegate:
            pass
        
        session.attach_running_prompt(MockDelegate())
        assert session._running
    
    def test_detach_running_prompt_clears_running(self):
        """Verify detach_running_prompt clears running state."""
        from aider.ui.docked_prompt import DockedPromptSession
        
        session = DockedPromptSession()
        session._running = True
        
        session.detach_running_prompt()
        assert not session._running
    
    def test_io_async_prompt_session_returns_docked(self):
        """Verify io.async_prompt_session returns docked prompt when active."""
        import os
        os.environ['TERM'] = 'xterm-256color'
        
        from aider.io import InputOutput
        
        io = InputOutput(
            pretty=True,
            fancy_input=True,
            input_history_file="/tmp/test_history",
        )
        
        # Should return docked prompt when available
        assert io._docked_prompt is not None
        assert io.async_prompt_session is io._docked_prompt


class TestRunningPromptIntegration:
    """Test running prompt integration with docked prompt."""
    
    def test_running_prompt_lifecycle(self):
        """Test full attach/detach lifecycle."""
        from aider.ui.docked_prompt import DockedPromptSession
        
        session = DockedPromptSession()
        
        # Initially not running
        assert not session._running
        
        # Attach
        class MockDelegate:
            pass
        session.attach_running_prompt(MockDelegate())
        assert session._running
        
        # Detach
        session.detach_running_prompt()
        assert not session._running


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
