"""
Smoke tests for main entry point methods.

Verifies all method calls in main.py and main_async.py exist on IO.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestIOSmokeTests:
    """Verify IO class has all methods called by main/main_async."""
    
    def test_io_has_set_model(self):
        """Verify io.set_model() exists."""
        from aider.io import InputOutput
        io = InputOutput(pretty=False, fancy_input=False)
        assert hasattr(io, 'set_model')
        assert callable(io.set_model)
        io.set_model('gpt-4')
        assert io.status_data.get('model_name') == 'gpt-4'
    
    def test_io_has_set_git_branch(self):
        """Verify io.set_git_branch() exists."""
        from aider.io import InputOutput
        io = InputOutput(pretty=False, fancy_input=False)
        assert hasattr(io, 'set_git_branch')
        assert callable(io.set_git_branch)
        io.set_git_branch('main')
        assert io.status_data.get('git_branch') == 'main'
    
    def test_io_has_clear(self):
        """Verify io.clear() exists."""
        from aider.io import InputOutput
        io = InputOutput(pretty=False, fancy_input=False)
        assert hasattr(io, 'clear')
        assert callable(io.clear)
    
    def test_io_has_tool_output(self):
        """Verify io.tool_output() exists."""
        from aider.io import InputOutput
        io = InputOutput(pretty=False, fancy_input=False)
        assert hasattr(io, 'tool_output')
        assert callable(io.tool_output)
    
    def test_io_has_fancy_input_attribute(self):
        """Verify io.fancy_input attribute exists."""
        from aider.io import InputOutput
        io = InputOutput(pretty=False, fancy_input=False)
        assert hasattr(io, 'fancy_input')
    
    def test_io_has_status_data(self):
        """Verify io.status_data attribute exists."""
        from aider.io import InputOutput
        io = InputOutput(pretty=False, fancy_input=False)
        assert hasattr(io, 'status_data')
        assert isinstance(io.status_data, dict)
        # Check required keys
        assert 'model_name' in io.status_data
        assert 'git_branch' in io.status_data


class TestCoderSmokeTests:
    """Verify coder has all methods called by main/main_async."""
    
    def test_coder_has_run_async(self):
        """Verify coder.run_async() exists."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        assert hasattr(BaseCoderControlMixin, 'run_async')
    
    def test_coder_has_run(self):
        """Verify coder.run() exists for backward compatibility."""
        from aider.coders.base_coder_control import BaseCoderControlMixin
        assert hasattr(BaseCoderControlMixin, 'run')


class TestMainEntryPoint:
    """Test main entry points can be imported and have required functions."""
    
    def test_main_imports(self):
        """Verify main.py can be imported."""
        from aider import main
        assert hasattr(main, 'main')
        assert callable(main.main)
    
    def test_main_async_imports(self):
        """Verify main_async.py can be imported."""
        from aider import main_async
        assert hasattr(main_async, 'run_async_main')
        assert callable(main_async.run_async_main)
        assert hasattr(main_async, 'async_main')
    
    def test_version_matches(self):
        """Verify all version strings match."""
        from aider import __version__
        from aider._version import __version__ as _version
        from aider.main_async import run_async_main
        
        # These should all be the same
        assert __version__ == _version
        assert __version__ == "2.2.0"


class TestRuntimeSmokeTests:
    """Test runtime module has async methods."""
    
    def test_run_interactive_session_async_exists(self):
        """Verify run_interactive_session_async exists."""
        from aider.bootstrap.runtime import run_interactive_session_async
        assert callable(run_interactive_session_async)
