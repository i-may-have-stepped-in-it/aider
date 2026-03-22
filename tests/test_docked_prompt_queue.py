"""
Tests for docked prompt queue input methods.

These tests verify the queue_input, get_queued_input, and has_queued_input
methods work correctly on DockedPromptSession and InputOutput.
"""

import pytest


class TestDockedPromptSessionQueue:
    """Test queue methods on DockedPromptSession."""
    
    def test_queue_input_exists(self):
        """DockedPromptSession must have queue_input method."""
        from aider.ui import DockedPromptSession
        
        ds = DockedPromptSession()
        assert hasattr(ds, 'queue_input')
        assert callable(ds.queue_input)
    
    def test_has_queued_input_initially_false(self):
        """has_queued_input should return False initially."""
        from aider.ui import DockedPromptSession
        
        ds = DockedPromptSession()
        assert ds.has_queued_input() is False
    
    def test_queue_input_and_get(self):
        """queue_input followed by get_queued_input should return the text."""
        from aider.ui import DockedPromptSession
        
        ds = DockedPromptSession()
        ds.queue_input("test message")
        
        assert ds.has_queued_input() is True
        assert ds.get_queued_input() == "test message"
        assert ds.has_queued_input() is False  # Should be cleared after get
    
    def test_multiple_queue_inputs_overwrite(self):
        """Multiple queue_input calls should overwrite."""
        from aider.ui import DockedPromptSession
        
        ds = DockedPromptSession()
        ds.queue_input("first")
        ds.queue_input("second")
        
        assert ds.get_queued_input() == "second"
    
    def test_get_queued_input_returns_none_when_empty(self):
        """get_queued_input should return None when no input queued."""
        from aider.ui import DockedPromptSession
        
        ds = DockedPromptSession()
        assert ds.get_queued_input() is None


class TestInputOutputQueueMethods:
    """Test queue methods on InputOutput."""
    
    def test_queue_methods_exist(self):
        """InputOutput must have queue methods."""
        from aider.io import InputOutput
        
        io = InputOutput(fancy_input=False)
        assert hasattr(io, 'queue_input')
        assert hasattr(io, 'has_queued_input')
        assert hasattr(io, 'get_queued_input')
    
    def test_has_queued_input_safe_when_no_session(self):
        """has_queued_input should return False safely when no session."""
        from aider.io import InputOutput
        
        io = InputOutput(fancy_input=False)
        # Should not raise, should return False
        assert io.has_queued_input() is False
    
    def test_get_queued_input_safe_when_no_session(self):
        """get_queued_input should return None safely when no session."""
        from aider.io import InputOutput
        
        io = InputOutput(fancy_input=False)
        # Should not raise, should return None
        assert io.get_queued_input() is None
    
    def test_queue_input_safe_when_no_session(self):
        """queue_input should not raise when no session."""
        from aider.io import InputOutput
        
        io = InputOutput(fancy_input=False)
        # Should not raise
        io.queue_input("test")


class TestAsyncPromptSessionQueue:
    """Test queue methods on AsyncAiderPromptSession."""
    
    def test_queue_methods_exist(self):
        """AsyncAiderPromptSession must have queue methods."""
        from aider.io import AsyncAiderPromptSession
        from prompt_toolkit import PromptSession
        
        session = PromptSession()
        aps = AsyncAiderPromptSession(session)
        
        assert hasattr(aps, 'queue_input')
        assert hasattr(aps, 'has_queued_input')
        assert hasattr(aps, 'get_queued_input')
    
    def test_queue_input_works(self):
        """queue_input should queue text."""
        from aider.io import AsyncAiderPromptSession
        from prompt_toolkit import PromptSession
        
        session = PromptSession()
        aps = AsyncAiderPromptSession(session)
        
        aps.queue_input("test message")
        
        assert aps.has_queued_input() is True
        assert aps.get_queued_input() == "test message"
        assert aps.has_queued_input() is False


class TestQueueIntegration:
    """Integration tests for queue functionality."""
    
    def test_docked_prompt_queue_flow(self):
        """Full queue flow with DockedPromptSession."""
        from aider.ui import DockedPromptSession
        
        ds = DockedPromptSession()
        
        # Initially empty
        assert ds.has_queued_input() is False
        assert ds.get_queued_input() is None
        
        # Queue input
        ds.queue_input("hello world")
        assert ds.has_queued_input() is True
        
        # Get input
        text = ds.get_queued_input()
        assert text == "hello world"
        assert ds.has_queued_input() is False
    
    def test_input_output_delegates_to_docked(self):
        """InputOutput should delegate queue methods to docked prompt."""
        from aider.io import InputOutput
        
        # Note: fancy_input=True would be needed for full test,
        # but that requires a terminal. We just verify the method exists
        # and has the correct structure.
        io = InputOutput(fancy_input=False)
        
        # Methods should exist and not raise
        io.queue_input("test")
        io.has_queued_input()
        io.get_queued_input()
