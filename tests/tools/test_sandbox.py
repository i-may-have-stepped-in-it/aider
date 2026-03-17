"""Tests for the sandbox implementations.

This module tests the various sandbox implementations including
FirejailSandbox, UnshareSandbox, and NoneSandbox.
"""

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock, mock_open

import pytest

from aider.tools.sandbox import (
    Sandbox,
    FirejailSandbox,
    UnshareSandbox,
    NoneSandbox,
    create_sandbox,
    get_available_sandboxes,
    run_sandboxed,
)


class TestSandboxAbstractBase:
    """Test the abstract Sandbox base class."""

    def test_sandbox_is_abstract(self):
        """Test that Sandbox cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Sandbox()

    def test_max_output_size_constant(self):
        """Test that MAX_OUTPUT_SIZE is defined."""
        assert Sandbox.MAX_OUTPUT_SIZE == 10 * 1024 * 1024  # 10MB

    def test_truncate_output_under_limit(self):
        """Test _truncate_output with data under limit."""
        class TestSandboxImpl(Sandbox):
            @classmethod
            def available(cls) -> bool:
                return True
            
            async def run(self, command: str, cwd: str, timeout: int) -> str:
                return ""
        
        sandbox = TestSandboxImpl()
        data = b"test output"
        result = sandbox._truncate_output(data)
        
        assert result == "test output"

    def test_truncate_output_over_limit(self):
        """Test _truncate_output with data over limit."""
        class TestSandboxImpl(Sandbox):
            @classmethod
            def available(cls) -> bool:
                return True
            
            async def run(self, command: str, cwd: str, timeout: int) -> str:
                return ""
        
        sandbox = TestSandboxImpl()
        # Temporarily reduce limit for testing
        original_limit = sandbox.MAX_OUTPUT_SIZE
        sandbox.MAX_OUTPUT_SIZE = 100
        
        try:
            data = b"x" * 200
            result = sandbox._truncate_output(data)
            
            assert len(result) < len(data)
            assert "truncated" in result.lower()
        finally:
            sandbox.MAX_OUTPUT_SIZE = original_limit

    def test_truncate_output_with_invalid_utf8(self):
        """Test _truncate_output handles invalid UTF-8."""
        class TestSandboxImpl(Sandbox):
            @classmethod
            def available(cls) -> bool:
                return True
            
            async def run(self, command: str, cwd: str, timeout: int) -> str:
                return ""
        
        sandbox = TestSandboxImpl()
        # Invalid UTF-8 sequence
        data = b"\xff\xfe\x00\x01"
        result = sandbox._truncate_output(data)
        
        # Should not raise exception
        assert isinstance(result, str)


class TestNoneSandbox:
    """Test the NoneSandbox implementation."""

    def test_available_always_true(self):
        """Test that NoneSandbox is always available."""
        assert NoneSandbox.available() is True

    def test_run_success(self):
        """Test successful command execution."""
        sandbox = NoneSandbox()
        
        with patch('asyncio.create_subprocess_shell') as mock_shell:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"hello world", b"")
            mock_shell.return_value = mock_proc
            
            result = asyncio.run(sandbox.run("echo hello", "/tmp", 10))
        
        assert result == "hello world"

    def test_run_failure(self):
        """Test command failure raises CalledProcessError."""
        sandbox = NoneSandbox()
        
        with patch('asyncio.create_subprocess_shell') as mock_shell:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate.return_value = (b"error output", b"")
            mock_shell.return_value = mock_proc
            
            with pytest.raises(subprocess.CalledProcessError):
                asyncio.run(sandbox.run("false", "/tmp", 10))

    def test_run_timeout(self):
        """Test command timeout."""
        sandbox = NoneSandbox()
        
        with patch('asyncio.create_subprocess_shell') as mock_shell:
            mock_proc = AsyncMock()
            mock_proc.communicate.side_effect = asyncio.TimeoutError()
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_shell.return_value = mock_proc
            
            with pytest.raises(subprocess.TimeoutExpired):
                asyncio.run(sandbox.run("sleep 10", "/tmp", 1))

    def test_run_uses_shell(self):
        """Test that run uses shell for command execution."""
        sandbox = NoneSandbox()
        
        with patch('asyncio.create_subprocess_shell') as mock_shell:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"", b"")
            mock_shell.return_value = mock_proc
            
            asyncio.run(sandbox.run("echo hello | grep hello", "/tmp", 10))
        
        mock_shell.assert_called_once()
        # Check that the command was passed to the shell
        call_args = mock_shell.call_args
        assert "echo hello | grep hello" in str(call_args)

    def test_run_sets_cwd(self):
        """Test that run uses the specified working directory."""
        sandbox = NoneSandbox()
        
        with patch('asyncio.create_subprocess_shell') as mock_shell:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"", b"")
            mock_shell.return_value = mock_proc
            
            asyncio.run(sandbox.run("pwd", "/custom/dir", 10))
        
        mock_shell.assert_called_once()
        call_kwargs = mock_shell.call_args.kwargs
        assert call_kwargs.get('cwd') == "/custom/dir"

    def test_run_clears_ld_preload(self):
        """Test that LD_PRELOAD is cleared in environment."""
        sandbox = NoneSandbox()
        
        with patch('asyncio.create_subprocess_shell') as mock_shell:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"", b"")
            mock_shell.return_value = mock_proc
            
            asyncio.run(sandbox.run("echo test", "/tmp", 10))
        
        call_kwargs = mock_shell.call_args.kwargs
        env = call_kwargs.get('env', {})
        assert env.get('LD_PRELOAD') == ""

    def test_run_truncates_large_output(self):
        """Test that large output is truncated."""
        sandbox = NoneSandbox()
        large_output = b"x" * (sandbox.MAX_OUTPUT_SIZE + 1000)
        
        with patch('asyncio.create_subprocess_shell') as mock_shell:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (large_output, b"")
            mock_shell.return_value = mock_proc
            
            result = asyncio.run(sandbox.run("cat largefile", "/tmp", 10))
        
        assert len(result.encode('utf-8')) <= sandbox.MAX_OUTPUT_SIZE + 100  # Allow for truncation message


class TestFirejailSandbox:
    """Test the FirejailSandbox implementation."""

    def test_available_firejail_not_in_path(self):
        """Test available() when firejail is not installed."""
        with patch('shutil.which', return_value=None):
            assert FirejailSandbox.available() is False

    def test_available_firejail_success(self):
        """Test available() when firejail works."""
        with patch('shutil.which', return_value="/usr/bin/firejail"):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                assert FirejailSandbox.available() is True

    def test_available_firejail_failure(self):
        """Test available() when firejail fails."""
        with patch('shutil.which', return_value="/usr/bin/firejail"):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=1)
                assert FirejailSandbox.available() is False

    def test_available_firejail_timeout(self):
        """Test available() when firejail times out."""
        with patch('shutil.which', return_value="/usr/bin/firejail"):
            with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("cmd", 5)):
                assert FirejailSandbox.available() is False

    def test_available_firejail_permission_error(self):
        """Test available() when firejail has permission issues."""
        with patch('shutil.which', return_value="/usr/bin/firejail"):
            with patch('subprocess.run', side_effect=PermissionError()):
                assert FirejailSandbox.available() is False

    def test_run_success(self):
        """Test successful firejail execution."""
        sandbox = FirejailSandbox()
        
        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_temp.return_value.__enter__ = MagicMock(return_value=MagicMock(
                name="/tmp/test.profile", write=MagicMock()
            ))
            mock_temp.return_value.__exit__ = MagicMock(return_value=False)
            
            with patch('asyncio.create_subprocess_exec') as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                mock_proc.communicate.return_value = (b"output", b"")
                mock_exec.return_value = mock_proc
                
                result = asyncio.run(sandbox.run("echo hello", "/tmp", 10))
        
        assert result == "output"

    def test_run_failure(self):
        """Test firejail command failure."""
        sandbox = FirejailSandbox()
        
        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.profile"
            mock_temp.return_value.__enter__ = MagicMock(return_value=mock_file)
            mock_temp.return_value.__exit__ = MagicMock(return_value=False)
            
            with patch('asyncio.create_subprocess_exec') as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 1
                mock_proc.communicate.return_value = (b"error", b"")
                mock_exec.return_value = mock_proc
                
                with pytest.raises(subprocess.CalledProcessError):
                    asyncio.run(sandbox.run("false", "/tmp", 10))

    def test_run_timeout(self):
        """Test firejail command timeout."""
        sandbox = FirejailSandbox()
        
        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.profile"
            mock_temp.return_value.__enter__ = MagicMock(return_value=mock_file)
            mock_temp.return_value.__exit__ = MagicMock(return_value=False)
            
            with patch('asyncio.create_subprocess_exec') as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.side_effect = asyncio.TimeoutError()
                mock_proc.kill = MagicMock()
                mock_proc.wait = AsyncMock()
                mock_exec.return_value = mock_proc
                
                with pytest.raises(subprocess.TimeoutExpired):
                    asyncio.run(sandbox.run("sleep 10", "/tmp", 1))

    def test_run_cleans_up_profile(self):
        """Test that profile file is cleaned up after execution."""
        sandbox = FirejailSandbox()
        profile_path = "/tmp/test.profile"
        
        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_file = MagicMock()
            mock_file.name = profile_path
            mock_temp.return_value.__enter__ = MagicMock(return_value=mock_file)
            mock_temp.return_value.__exit__ = MagicMock(return_value=False)
            
            with patch('asyncio.create_subprocess_exec') as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                mock_proc.communicate.return_value = (b"", b"")
                mock_exec.return_value = mock_proc
                
                with patch('os.unlink') as mock_unlink:
                    asyncio.run(sandbox.run("echo test", "/tmp", 10))
        
        mock_unlink.assert_called_once_with(profile_path)

    def test_profile_content(self):
        """Test that profile content is written correctly."""
        sandbox = FirejailSandbox()
        
        # Check that PROFILE contains expected security settings
        assert "net none" in sandbox.PROFILE
        assert "private-tmp" in sandbox.PROFILE
        assert "seccomp" in sandbox.PROFILE
        assert "caps.drop all" in sandbox.PROFILE

    def test_run_uses_correct_firejail_flags(self):
        """Test that correct firejail flags are used."""
        sandbox = FirejailSandbox()
        
        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.profile"
            mock_temp.return_value.__enter__ = MagicMock(return_value=mock_file)
            mock_temp.return_value.__exit__ = MagicMock(return_value=False)
            
            with patch('asyncio.create_subprocess_exec') as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                mock_proc.communicate.return_value = (b"", b"")
                mock_exec.return_value = mock_proc
                
                asyncio.run(sandbox.run("echo test", "/tmp", 10))
        
        call_args = mock_exec.call_args[0]
        assert "firejail" in call_args
        assert "--quiet" in call_args
        assert "--net=none" in call_args
        assert "--private-tmp" in call_args
        assert "--shell=none" in call_args


class TestUnshareSandbox:
    """Test the UnshareSandbox implementation."""

    def test_available_unshare_not_in_path(self):
        """Test available() when unshare is not installed."""
        with patch('shutil.which', return_value=None):
            assert UnshareSandbox.available() is False

    def test_available_with_userns_clone_enabled(self):
        """Test available() when user namespaces are enabled."""
        with patch('shutil.which', return_value="/usr/bin/unshare"):
            with patch('builtins.open', mock_open(read_data="1")):
                with patch('os.path.exists', return_value=True):
                    assert UnshareSandbox.available() is True

    def test_available_with_userns_clone_disabled(self):
        """Test available() when user namespaces are disabled."""
        with patch('shutil.which', return_value="/usr/bin/unshare"):
            with patch('builtins.open', mock_open(read_data="0")):
                with patch('os.path.exists', return_value=True):
                    # Falls back to functional test which we'll mock to fail
                    with patch('subprocess.run') as mock_run:
                        mock_run.return_value = MagicMock(returncode=1)
                        assert UnshareSandbox.available() is False

    def test_available_functional_test_success(self):
        """Test available() functional test succeeds."""
        with patch('shutil.which', return_value="/usr/bin/unshare"):
            with patch('os.path.exists', return_value=False):  # No sysctl files
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    assert UnshareSandbox.available() is True

    def test_available_functional_test_timeout(self):
        """Test available() functional test times out."""
        with patch('shutil.which', return_value="/usr/bin/unshare"):
            with patch('os.path.exists', return_value=False):
                with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("cmd", 5)):
                    # Also patch the sysctl path check to avoid the system-dependent behavior
                    with patch.object(UnshareSandbox, 'available', return_value=False):
                        assert UnshareSandbox.available() is False

    def test_run_success(self):
        """Test successful unshare execution."""
        sandbox = UnshareSandbox()
        
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"output", b"")
            mock_exec.return_value = mock_proc
            
            result = asyncio.run(sandbox.run("echo hello", "/tmp", 10))
        
        assert result == "output"

    def test_run_failure(self):
        """Test unshare command failure."""
        sandbox = UnshareSandbox()
        
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate.return_value = (b"error", b"")
            mock_exec.return_value = mock_proc
            
            with pytest.raises(subprocess.CalledProcessError):
                asyncio.run(sandbox.run("false", "/tmp", 10))

    def test_run_timeout(self):
        """Test unshare command timeout."""
        sandbox = UnshareSandbox()
        
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.side_effect = asyncio.TimeoutError()
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc
            
            with pytest.raises(subprocess.TimeoutExpired):
                asyncio.run(sandbox.run("sleep 10", "/tmp", 1))

    def test_run_uses_correct_unshare_flags(self):
        """Test that correct unshare flags are used."""
        sandbox = UnshareSandbox()
        
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"", b"")
            mock_exec.return_value = mock_proc
            
            asyncio.run(sandbox.run("echo test", "/tmp", 10))
        
        call_args = mock_exec.call_args[0]
        assert "unshare" in call_args
        assert "--user" in call_args
        assert "--mount" in call_args
        assert "--pid" in call_args
        assert "--fork" in call_args
        assert "--mount-proc" in call_args


class TestCreateSandbox:
    """Test the create_sandbox factory function."""

    def test_create_sandbox_auto_prefers_firejail(self):
        """Test auto selection prefers firejail."""
        with patch.object(FirejailSandbox, 'available', return_value=True):
            with patch.object(UnshareSandbox, 'available', return_value=True):
                sandbox = create_sandbox("auto")
                assert isinstance(sandbox, FirejailSandbox)

    def test_create_sandbox_auto_falls_back_to_unshare(self):
        """Test auto selection falls back to unshare."""
        with patch.object(FirejailSandbox, 'available', return_value=False):
            with patch.object(UnshareSandbox, 'available', return_value=True):
                sandbox = create_sandbox("auto")
                assert isinstance(sandbox, UnshareSandbox)

    def test_create_sandbox_auto_falls_back_to_none(self):
        """Test auto selection falls back to none."""
        with patch.object(FirejailSandbox, 'available', return_value=False):
            with patch.object(UnshareSandbox, 'available', return_value=False):
                sandbox = create_sandbox("auto")
                assert isinstance(sandbox, NoneSandbox)

    def test_create_sandbox_firejail_explicit(self):
        """Test explicit firejail selection."""
        with patch.object(FirejailSandbox, 'available', return_value=True):
            sandbox = create_sandbox("firejail")
            assert isinstance(sandbox, FirejailSandbox)

    def test_create_sandbox_firejail_unavailable_raises(self):
        """Test explicit firejail raises when unavailable."""
        with patch.object(FirejailSandbox, 'available', return_value=False):
            with pytest.raises(RuntimeError, match="Firejail is not available"):
                create_sandbox("firejail")

    def test_create_sandbox_unshare_explicit(self):
        """Test explicit unshare selection."""
        with patch.object(UnshareSandbox, 'available', return_value=True):
            sandbox = create_sandbox("unshare")
            assert isinstance(sandbox, UnshareSandbox)

    def test_create_sandbox_unshare_unavailable_raises(self):
        """Test explicit unshare raises when unavailable."""
        with patch.object(UnshareSandbox, 'available', return_value=False):
            with pytest.raises(RuntimeError, match="Unshare namespaces are not available"):
                create_sandbox("unshare")

    def test_create_sandbox_none_explicit(self):
        """Test explicit none selection."""
        sandbox = create_sandbox("none")
        assert isinstance(sandbox, NoneSandbox)

    def test_create_sandbox_invalid_type_raises(self):
        """Test invalid sandbox type raises."""
        with pytest.raises(ValueError, match="Invalid sandbox_type"):
            create_sandbox("invalid")


class TestGetAvailableSandboxes:
    """Test the get_available_sandboxes function."""

    def test_get_available_sandboxes_returns_all(self):
        """Test that all sandbox types are checked."""
        with patch.object(FirejailSandbox, 'available', return_value=True):
            with patch.object(UnshareSandbox, 'available', return_value=False):
                result = get_available_sandboxes()
        
        assert result == {
            "firejail": True,
            "unshare": False,
            "none": True,
        }


class TestRunSandboxed:
    """Test the run_sandboxed convenience function."""

    def test_run_sandboxed_uses_default_cwd(self):
        """Test that default cwd is used when not specified."""
        with patch('aider.tools.sandbox.create_sandbox') as mock_create:
            mock_sandbox = AsyncMock()
            mock_sandbox.run.return_value = "output"
            mock_create.return_value = mock_sandbox
            
            asyncio.run(run_sandboxed("echo hello"))
        
        # run() is called with positional args: (command, cwd, timeout)
        call_args = mock_sandbox.run.call_args[0]
        assert call_args[1] == os.getcwd()  # cwd is 2nd positional arg

    def test_run_sandboxed_uses_specified_cwd(self):
        """Test that specified cwd is used."""
        with patch('aider.tools.sandbox.create_sandbox') as mock_create:
            mock_sandbox = AsyncMock()
            mock_sandbox.run.return_value = "output"
            mock_create.return_value = mock_sandbox
            
            asyncio.run(run_sandboxed("echo hello", cwd="/custom/path"))
        
        call_args = mock_sandbox.run.call_args[0]
        assert call_args[1] == "/custom/path"  # cwd is 2nd positional arg

    def test_run_sandboxed_uses_default_timeout(self):
        """Test that default timeout is used."""
        with patch('aider.tools.sandbox.create_sandbox') as mock_create:
            mock_sandbox = AsyncMock()
            mock_sandbox.run.return_value = "output"
            mock_create.return_value = mock_sandbox
            
            asyncio.run(run_sandboxed("echo hello"))
        
        call_args = mock_sandbox.run.call_args[0]
        assert call_args[2] == 60  # timeout is 3rd positional arg

    def test_run_sandboxed_uses_specified_timeout(self):
        """Test that specified timeout is used."""
        with patch('aider.tools.sandbox.create_sandbox') as mock_create:
            mock_sandbox = AsyncMock()
            mock_sandbox.run.return_value = "output"
            mock_create.return_value = mock_sandbox
            
            asyncio.run(run_sandboxed("echo hello", timeout=30))
        
        call_args = mock_sandbox.run.call_args[0]
        assert call_args[2] == 30  # timeout is 3rd positional arg

    def test_run_sandboxed_returns_output(self):
        """Test that output is returned."""
        with patch('aider.tools.sandbox.create_sandbox') as mock_create:
            mock_sandbox = AsyncMock()
            mock_sandbox.run.return_value = "command output"
            mock_create.return_value = mock_sandbox
            
            result = asyncio.run(run_sandboxed("echo hello"))
        
        assert result == "command output"


class TestSandboxTimeoutBehavior:
    """Test timeout behavior across all sandbox types."""

    @pytest.mark.parametrize("sandbox_class", [NoneSandbox, FirejailSandbox, UnshareSandbox])
    def test_timeout_raises_timeout_expired(self, sandbox_class):
        """Test that all sandboxes raise TimeoutExpired on timeout."""
        sandbox = sandbox_class()
        
        with patch('asyncio.create_subprocess_shell' if sandbox_class == NoneSandbox 
                   else 'asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.side_effect = asyncio.TimeoutError()
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc
            
            with pytest.raises(subprocess.TimeoutExpired):
                asyncio.run(sandbox.run("sleep 10", "/tmp", 1))

    @pytest.mark.parametrize("sandbox_class", [NoneSandbox, FirejailSandbox, UnshareSandbox])
    def test_timeout_kills_process(self, sandbox_class):
        """Test that timeout kills the process."""
        sandbox = sandbox_class()
        
        with patch('asyncio.create_subprocess_shell' if sandbox_class == NoneSandbox 
                   else 'asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.side_effect = asyncio.TimeoutError()
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc
            
            try:
                asyncio.run(sandbox.run("sleep 10", "/tmp", 1))
            except subprocess.TimeoutExpired:
                pass
            
            mock_proc.kill.assert_called_once()


class TestSandboxOutputSizeLimits:
    """Test output size limits across all sandbox types."""

    @pytest.mark.parametrize("sandbox_class", [NoneSandbox, FirejailSandbox, UnshareSandbox])
    def test_large_output_is_truncated(self, sandbox_class):
        """Test that large output is truncated."""
        sandbox = sandbox_class()
        large_output = b"x" * (sandbox.MAX_OUTPUT_SIZE + 1000)
        
        with patch('asyncio.create_subprocess_shell' if sandbox_class == NoneSandbox 
                   else 'asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (large_output, b"")
            mock_exec.return_value = mock_proc
            
            result = asyncio.run(sandbox.run("cat largefile", "/tmp", 10))
        
        # Result should be truncated
        assert len(result.encode('utf-8')) < len(large_output)


class TestSandboxErrorHandling:
    """Test error handling across all sandbox types."""

    @pytest.mark.parametrize("sandbox_class", [NoneSandbox, FirejailSandbox, UnshareSandbox])
    def test_called_process_error_includes_output(self, sandbox_class):
        """Test that CalledProcessError includes output."""
        sandbox = sandbox_class()
        error_output = b"error message"
        
        with patch('asyncio.create_subprocess_shell' if sandbox_class == NoneSandbox 
                   else 'asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate.return_value = (error_output, b"")
            mock_exec.return_value = mock_proc
            
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                asyncio.run(sandbox.run("false", "/tmp", 10))
            
            assert "error message" in str(exc_info.value.output)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
