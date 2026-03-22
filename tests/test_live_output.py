"""
Tests for LiveOutputManager and LiveRichConsole.
"""
import pytest
from unittest.mock import Mock, MagicMock


class TestLiveOutputManager:
    """Test LiveOutputManager functionality."""
    
    def test_creation(self):
        """Verify LiveOutputManager can be created."""
        from aider.ui.live_output import LiveOutputManager
        
        manager = LiveOutputManager()
        assert manager is not None
        assert not manager.is_active
    
    def test_add_output(self):
        """Verify output can be added."""
        from aider.ui.live_output import LiveOutputManager
        
        manager = LiveOutputManager()
        manager.add_output("Hello world")
        
        # Output buffer should have content
        assert len(manager._output_buffer) > 0
    
    def test_add_output_with_style(self):
        """Verify output can be added with style."""
        from aider.ui.live_output import LiveOutputManager
        
        manager = LiveOutputManager()
        manager.add_output("Error message", style="red")
        
        assert len(manager._output_buffer) > 0
    
    def test_clear(self):
        """Verify clear empties the buffer."""
        from aider.ui.live_output import LiveOutputManager
        
        manager = LiveOutputManager()
        manager.add_output("Line 1")
        manager.add_output("Line 2")
        assert len(manager._output_buffer) > 0
        
        manager.clear()
        assert len(manager._output_buffer) == 0
    
    def test_buffer_limit(self):
        """Verify buffer respects max lines limit."""
        from aider.ui.live_output import LiveOutputManager
        
        manager = LiveOutputManager()
        manager._max_lines = 10
        
        # Add more lines than limit
        for i in range(15):
            manager.add_output(f"Line {i}")
        
        # Buffer should be trimmed
        assert len(manager._output_buffer) <= 10


class TestLiveRichConsole:
    """Test LiveRichConsole functionality."""
    
    def test_creation(self):
        """Verify LiveRichConsole can be created."""
        from aider.ui.live_output import LiveOutputManager, LiveRichConsole
        from rich.console import Console
        
        live = LiveOutputManager()
        base = Console()
        bridged = LiveRichConsole(live, base)
        
        assert bridged is not None
        assert bridged._live is live
        assert bridged._base is base
    
    def test_print_routes_to_live(self):
        """Verify print routes to live manager when capturing."""
        from aider.ui.live_output import LiveOutputManager, LiveRichConsole
        from rich.console import Console
        
        live = LiveOutputManager()
        base = Console()
        bridged = LiveRichConsole(live, base)
        
        initial_count = len(live._output_buffer)
        bridged.print("Test message")
        
        # Should have added to live output
        assert len(live._output_buffer) > initial_count
    
    def test_print_passthrough_when_not_capturing(self):
        """Verify print passes through when not capturing."""
        from aider.ui.live_output import LiveOutputManager, LiveRichConsole
        from rich.console import Console
        
        live = LiveOutputManager()
        base = Mock(spec=Console)
        bridged = LiveRichConsole(live, base)
        bridged._capturing = False
        
        bridged.print("Test message")
        
        # Should have called base console
        base.print.assert_called_once()
    
    def test_clear_routes_to_live(self):
        """Verify clear routes to live manager."""
        from aider.ui.live_output import LiveOutputManager, LiveRichConsole
        from rich.console import Console
        
        live = LiveOutputManager()
        base = Console()
        bridged = LiveRichConsole(live, base)
        
        bridged.print("Line 1")
        bridged.print("Line 2")
        assert len(live._output_buffer) > 0
        
        bridged.clear()
        assert len(live._output_buffer) == 0


class TestIOIntegration:
    """Test integration with InputOutput."""
    
    def test_io_has_live_output_methods(self):
        """Verify IO has live output methods."""
        import os
        os.environ['TERM'] = 'xterm-256color'
        
        from aider.io import InputOutput
        
        io = InputOutput(
            pretty=True,
            fancy_input=True,
            input_history_file="/tmp/test_history",
        )
        
        assert hasattr(io, 'start_live_output')
        assert hasattr(io, 'stop_live_output')
    
    def test_io_creates_live_output_with_docked_prompt(self):
        """Verify IO creates live output when using docked prompt."""
        import os
        os.environ['TERM'] = 'xterm-256color'
        
        from aider.io import InputOutput
        
        io = InputOutput(
            pretty=True,
            fancy_input=True,
            input_history_file="/tmp/test_history",
        )
        
        # Should have created live output
        assert io._docked_prompt is not None
        assert io._live_output is not None
        assert io._base_console is not None
    
    def test_io_uses_live_rich_console_with_docked_prompt(self):
        """Verify IO uses LiveRichConsole when docked prompt is active."""
        import os
        os.environ['TERM'] = 'xterm-256color'
        
        from aider.io import InputOutput
        from aider.ui.live_output import LiveRichConsole
        
        io = InputOutput(
            pretty=True,
            fancy_input=True,
            input_history_file="/tmp/test_history",
        )
        
        # Console should be LiveRichConsole
        assert isinstance(io.console, LiveRichConsole)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
