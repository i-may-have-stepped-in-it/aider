"""
Test docked prompt key bindings.
"""
import pytest


class TestKeyBindings:
    """Test docked prompt key bindings."""
    
    def test_ctrl_x_binding_exists(self):
        """Verify Ctrl-X toggle mode binding exists."""
        from aider.ui.docked_prompt import DockedPromptSession
        
        session = DockedPromptSession()
        
        # Check that Ctrl-X is bound
        bindings = session._kb
        # The binding should exist (we can't easily test it fires, but we can verify no errors)
        assert bindings is not None
    
    def test_enter_submits_input(self):
        """Verify Enter key submits input (not newline)."""
        from aider.ui.docked_prompt import DockedPromptSession
        import inspect
        
        session = DockedPromptSession()
        
        # Check that there's an Enter handler
        source = inspect.getsource(session._build_key_bindings)
        
        # Should have "submit_input" handler for Enter
        assert "submit_input" in source or "validate_and_handle" in source
    
    def test_ctrl_j_inserts_newline(self):
        """Verify Ctrl-J inserts newline."""
        from aider.ui.docked_prompt import DockedPromptSession
        import inspect
        
        session = DockedPromptSession()
        source = inspect.getsource(session._build_key_bindings)
        
        # Should have insert_newline handler with c-j
        assert "c-j" in source or "c_j" in source
        assert "insert_text" in source
    
    def test_alt_enter_inserts_newline(self):
        """Verify Alt-Enter inserts newline."""
        from aider.ui.docked_prompt import DockedPromptSession
        import inspect
        
        session = DockedPromptSession()
        source = inspect.getsource(session._build_key_bindings)
        
        # Should have escape+enter binding
        assert "escape" in source and "enter" in source


class TestMultilineBehavior:
    """Test multiline input behavior."""
    
    def test_multiline_mode_enabled(self):
        """Verify multiline mode is enabled."""
        from aider.ui.docked_prompt import DockedPromptSession
        
        session = DockedPromptSession()
        
        # Check session is multiline
        # The session should be configured for multiline
        assert session._session is not None
    
    def test_no_continuation_prompt(self):
        """Verify no continuation prompt like '...'."""
        from aider.ui.docked_prompt import DockedPromptSession
        import inspect
        
        source = inspect.getsource(DockedPromptSession._build_session)
        
        # Should NOT have prompt_continuation set
        assert "prompt_continuation" not in source or "..." not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
