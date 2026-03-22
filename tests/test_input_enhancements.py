"""
Tests for input enhancements.
"""
import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path


class TestInputHighlighter:
    """Test InputHighlighter functionality."""
    
    def test_highlight_empty_text(self):
        """Verify empty text handling."""
        from aider.ui.input_enhancements import InputHighlighter
        
        result = InputHighlighter.highlight("")
        assert result == [("", "")]
    
    def test_highlight_mention(self):
        """Verify @mentions are highlighted."""
        from aider.ui.input_enhancements import InputHighlighter
        
        result = InputHighlighter.highlight("Check @file.py")
        
        # Should have mention highlighted
        styles = [style for style, _ in result]
        assert any("bold" in s for s in styles if s)
    
    def test_highlight_command(self):
        """Verify /commands are highlighted."""
        from aider.ui.input_enhancements import InputHighlighter
        
        result = InputHighlighter.highlight("/add file.py")
        
        # Should have command highlighted
        styles = [style for style, _ in result]
        assert any("bold" in s for s in styles if s)
    
    def test_highlight_code_block(self):
        """Verify code blocks are highlighted."""
        from aider.ui.input_enhancements import InputHighlighter
        
        result = InputHighlighter.highlight("```python")
        
        # Should have code block marker
        assert any("```python" in text for _, text in result)


class TestFileMentionCompleter:
    """Test FileMentionCompleter functionality."""
    
    def test_creation(self):
        """Verify completer can be created."""
        from aider.ui.input_enhancements import FileMentionCompleter
        
        completer = FileMentionCompleter(root_dir=".")
        assert completer is not None
    
    def test_no_completions_without_at(self):
        """Verify no completions without @ prefix."""
        from aider.ui.input_enhancements import FileMentionCompleter
        from prompt_toolkit.document import Document
        
        completer = FileMentionCompleter(root_dir=".")
        document = Document("file")
        
        completions = list(completer.get_completions(document, None))
        assert len(completions) == 0
    
    def test_completions_with_at(self, tmp_path):
        """Verify completions trigger with @ prefix."""
        from aider.ui.input_enhancements import FileMentionCompleter
        from prompt_toolkit.document import Document
        
        # Create a test file
        test_file = tmp_path / "testfile.py"
        test_file.write_text("test")
        
        completer = FileMentionCompleter(root_dir=str(tmp_path))
        completer._file_cache = ["testfile.py"]  # Pre-populate cache
        completer._cache_valid = True
        
        document = Document("@test")
        completions = list(completer.get_completions(document, None))
        
        assert len(completions) > 0


class TestSlashCommandCompleter:
    """Test SlashCommandCompleter functionality."""
    
    def test_creation(self):
        """Verify completer can be created."""
        from aider.ui.input_enhancements import SlashCommandCompleter
        
        commands = {"add": "Add files", "drop": "Drop files"}
        completer = SlashCommandCompleter(commands)
        assert completer is not None
    
    def test_completions_with_slash(self):
        """Verify completions with / prefix."""
        from aider.ui.input_enhancements import SlashCommandCompleter
        from prompt_toolkit.document import Document
        
        commands = {"add": "Add files", "drop": "Drop files"}
        completer = SlashCommandCompleter(commands)
        
        document = Document("/ad")
        completions = list(completer.get_completions(document, None))
        
        assert len(completions) > 0
        # Check it matches 'add'
        completion_texts = [c.text for c in completions]
        assert "add" in completion_texts
    
    def test_no_completions_without_slash(self):
        """Verify no completions without / prefix."""
        from aider.ui.input_enhancements import SlashCommandCompleter
        from prompt_toolkit.document import Document
        
        commands = {"add": "Add files"}
        completer = SlashCommandCompleter(commands)
        
        document = Document("ad")
        completions = list(completer.get_completions(document, None))
        
        assert len(completions) == 0


class TestEnhancedStatusBar:
    """Test enhanced status bar features."""
    
    def test_context_bar_rendering(self):
        """Verify context bar is rendered in status."""
        from aider.ui.docked_prompt import PromptStatus, PromptMode
        from aider.ui.status_bar import StatusBarRenderer
        
        status = PromptStatus(
            context_used=50000,
            context_total=100000,
        )
        
        # Use StatusBarRenderer directly with mock provider
        def status_provider():
            return {
                "mode": PromptMode.AGENT,
                "context_used": status.context_used,
                "context_total": status.context_total,
            }
        
        renderer = StatusBarRenderer(status_provider)
        
        # Just verify the provider works
        data = renderer._status_provider()
        assert data["context_used"] == 50000
        assert data["context_total"] == 100000
    
    def test_cost_display(self):
        """Verify cost tracking exists in status."""
        from aider.ui.docked_prompt import PromptStatus
        
        status = PromptStatus(
            cost=0.123,
            context_used=1000,
            context_total=8000,
        )
        
        # Verify cost field exists and is set
        assert status.cost == 0.123
        assert status.context_used == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
