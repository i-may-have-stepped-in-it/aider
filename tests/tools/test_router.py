"""Tests for the ToolRouter class.

This module tests the ToolRouter which routes LLM tool calls to aider Commands.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from aider.tools.router import ToolRouter, ToolResult, ToolCallRecord
from aider.tools.risk import RiskLevel
from aider.tools.sandbox import NoneSandbox


@pytest.fixture
def mock_commands():
    """Create a mock Commands object."""
    commands = MagicMock()
    commands.cmd_add = MagicMock()
    commands.cmd_drop = MagicMock()
    commands.cmd_git = MagicMock()
    commands.cmd_commit = MagicMock()
    return commands


@pytest.fixture
def mock_io():
    """Create a mock InputOutput object."""
    io = MagicMock()
    io.confirm_ask = MagicMock(return_value=True)
    io.tool_error = MagicMock()
    io.tool_output = MagicMock()
    io.read_text = MagicMock(return_value="file content")
    return io


@pytest.fixture
def mock_coder():
    """Create a mock Coder object."""
    coder = MagicMock()
    coder.root = "/tmp/test_repo"
    coder.verbose = False
    coder.abs_root_path = MagicMock(side_effect=lambda p: os.path.join(coder.root, p))
    return coder


@pytest.fixture
def tool_router(mock_commands, mock_io, mock_coder):
    """Create a ToolRouter instance with mocked dependencies."""
    router = ToolRouter(
        commands=mock_commands,
        io=mock_io,
        coder=mock_coder,
        sandbox_type="none",
        auto_confirm=True
    )
    return router


class TestToolRouterInit:
    """Test ToolRouter initialization."""

    def test_init_default(self, mock_commands, mock_io, mock_coder):
        """Test default initialization."""
        router = ToolRouter(mock_commands, mock_io, mock_coder)
        assert router.commands == mock_commands
        assert router.io == mock_io
        assert router.coder == mock_coder
        assert router.auto_confirm is False
        assert router.risk_confirm_threshold == RiskLevel.RISKY
        assert router.call_history == []
        assert router._call_counter == 0

    def test_init_with_params(self, mock_commands, mock_io, mock_coder):
        """Test initialization with custom parameters."""
        router = ToolRouter(
            mock_commands,
            mock_io,
            mock_coder,
            sandbox_type="none",
            auto_confirm=True,
            risk_confirm_threshold=RiskLevel.DANGEROUS
        )
        assert router.auto_confirm is True
        assert router.risk_confirm_threshold == RiskLevel.DANGEROUS

    def test_init_creates_sandbox(self, mock_commands, mock_io, mock_coder):
        """Test that initialization creates a sandbox."""
        router = ToolRouter(mock_commands, mock_io, mock_coder, sandbox_type="none")
        assert isinstance(router.sandbox, NoneSandbox)


class TestToolRouterExecute:
    """Test ToolRouter.execute() method."""

    def test_execute_unknown_tool(self, tool_router):
        """Test execution of unknown tool raises ValueError."""
        with pytest.raises(ValueError, match="Unknown tool: unknown_tool"):
            tool_router._get_handler("unknown_tool")

    def test_execute_success(self, tool_router):
        """Test successful tool execution."""
        with patch.object(tool_router, '_exec_ls', return_value=ToolResult(
            success=True,
            output="file1.txt\nfile2.txt",
            execution_time=0.1
        )):
            result = tool_router.execute("ls", {"path": "."})
            
        assert result.success is True
        assert result.output == "file1.txt\nfile2.txt"
        assert result.error is None

    def test_execute_logs_to_history(self, tool_router):
        """Test that execution logs to call history."""
        with patch.object(tool_router, '_exec_ls', return_value=ToolResult(
            success=True,
            output="test output",
            execution_time=0.1
        )):
            tool_router.execute("ls", {"path": "."})
        
        assert len(tool_router.call_history) == 1
        record = tool_router.call_history[0]
        assert isinstance(record, ToolCallRecord)
        assert record.tool_name == "ls"
        assert record.success is True
        assert record.parameters == {"path": "."}

    def test_execute_failure_logged(self, tool_router):
        """Test that failed execution is logged."""
        with patch.object(tool_router, '_exec_ls', return_value=ToolResult(
            success=False,
            output="",
            error="Test error",
            execution_time=0.1
        )):
            result = tool_router.execute("ls", {"path": "."})
        
        assert result.success is False
        assert len(tool_router.call_history) == 1
        assert tool_router.call_history[0].success is False
        assert tool_router.call_history[0].error == "Test error"

    def test_execute_exception_handling(self, tool_router, mock_io):
        """Test exception handling during execution."""
        with patch.object(tool_router, '_exec_ls', side_effect=Exception("Test exception")):
            result = tool_router.execute("ls", {"path": "."})
        
        assert result.success is False
        assert "Test exception" in result.error
        mock_io.tool_error.assert_called_once()

    def test_execute_declined_by_user(self, tool_router, mock_io):
        """Test tool execution declined by user."""
        mock_io.confirm_ask.return_value = False
        
        with patch.object(tool_router, '_should_auto_execute', return_value=False):
            result = tool_router.execute("run", {"command": "ls"})
        
        assert result.success is False
        assert "declined by user" in result.error


class TestToolRouterOutputTruncation:
    """Test output truncation for large outputs."""

    def test_output_truncation_applied(self, tool_router):
        """Test that large outputs are truncated."""
        large_output = "x" * (tool_router.MAX_OUTPUT_SIZE + 1000)
        
        with patch.object(tool_router, '_exec_run', return_value=ToolResult(
            success=True,
            output=large_output,
            execution_time=0.1
        )):
            with patch('aider.tools.router.truncate_output', return_value="truncated") as mock_truncate:
                result = tool_router.execute("run", {"command": "cat large_file"})
        
        mock_truncate.assert_called_once()
        assert result.truncated is True
        assert result.original_size == len(large_output)

    def test_output_no_truncation_needed(self, tool_router):
        """Test that small outputs are not truncated."""
        small_output = "small output"
        
        with patch.object(tool_router, '_exec_ls', return_value=ToolResult(
            success=True,
            output=small_output,
            execution_time=0.1
        )):
            result = tool_router.execute("ls", {"path": "."})
        
        assert result.truncated is False
        assert result.output == small_output

    def test_truncation_preserves_success_status(self, tool_router):
        """Test that truncation preserves success status."""
        large_output = "x" * (tool_router.MAX_OUTPUT_SIZE + 1000)
        
        with patch.object(tool_router, '_exec_run', return_value=ToolResult(
            success=True,
            output=large_output,
            execution_time=0.1
        )):
            with patch('aider.tools.router.truncate_output', return_value="truncated"):
                result = tool_router.execute("run", {"command": "echo test"})
        
        assert result.success is True
        assert result.truncated is True


class TestToolRouterAuditLogging:
    """Test audit logging (call_history)."""

    def test_log_call_adds_record(self, tool_router):
        """Test that _log_call adds a record."""
        record = ToolCallRecord(
            call_id="test_1",
            timestamp=0.0,
            tool_name="ls",
            parameters={"path": "."},
            risk_level=RiskLevel.SAFE,
            success=True,
            execution_time=0.1
        )
        tool_router._log_call(record)
        
        assert len(tool_router.call_history) == 1
        assert tool_router.call_history[0] == record

    def test_get_call_history_returns_copy(self, tool_router):
        """Test that get_call_history returns a copy."""
        record = ToolCallRecord(
            call_id="test_1",
            timestamp=0.0,
            tool_name="ls",
            parameters={},
            risk_level=RiskLevel.SAFE,
            success=True,
            execution_time=0.1
        )
        tool_router._log_call(record)
        
        history = tool_router.get_call_history()
        history.clear()  # Modify the copy
        
        assert len(tool_router.call_history) == 1  # Original unchanged

    def test_clear_history(self, tool_router):
        """Test clearing history."""
        tool_router.call_history.append(MagicMock())
        tool_router._call_counter = 5
        
        tool_router.clear_history()
        
        assert len(tool_router.call_history) == 0
        assert tool_router._call_counter == 0

    def test_get_summary_empty(self, tool_router):
        """Test summary with no calls."""
        summary = tool_router.get_summary()
        assert "No tool calls made" in summary

    def test_get_summary_with_calls(self, tool_router):
        """Test summary with calls."""
        tool_router.call_history = [
            ToolCallRecord(
                call_id="ls_1", timestamp=0.0, tool_name="ls",
                parameters={}, risk_level=RiskLevel.SAFE,
                success=True, execution_time=0.1
            ),
            ToolCallRecord(
                call_id="run_1", timestamp=0.0, tool_name="run",
                parameters={}, risk_level=RiskLevel.DANGEROUS,
                success=False, execution_time=0.2, error="timeout"
            ),
        ]
        
        summary = tool_router.get_summary()
        
        assert "Tool Calls: 2" in summary
        assert "Successful: 1" in summary
        assert "Failed: 1" in summary
        assert "ls: 1" in summary
        assert "run: 1" in summary


class TestToolRouterRiskBasedConfirmation:
    """Test risk-based confirmation system."""

    def test_should_auto_execute_with_auto_confirm(self, tool_router):
        """Test auto-execution when auto_confirm is True."""
        tool_router.auto_confirm = True
        result = tool_router._should_auto_execute("run", {}, RiskLevel.DANGEROUS)
        assert result is True

    def test_should_auto_execute_dangerous(self, tool_router):
        """Test that DANGEROUS tools always require confirmation."""
        tool_router.auto_confirm = False
        result = tool_router._should_auto_execute("run", {}, RiskLevel.DANGEROUS)
        assert result is False

    def test_should_auto_execute_above_threshold(self, tool_router):
        """Test confirmation when above threshold."""
        tool_router.auto_confirm = False
        tool_router.risk_confirm_threshold = RiskLevel.NORMAL
        result = tool_router._should_auto_execute("run", {}, RiskLevel.RISKY)
        assert result is False

    def test_should_auto_execute_below_threshold(self, tool_router):
        """Test auto-execution when below threshold."""
        tool_router.auto_confirm = False
        tool_router.risk_confirm_threshold = RiskLevel.RISKY
        result = tool_router._should_auto_execute("ls", {}, RiskLevel.SAFE)
        assert result is True

    def test_confirm_tool_execution_with_io(self, tool_router, mock_io):
        """Test confirmation with IO confirm_ask."""
        mock_io.confirm_ask.return_value = True
        
        result = tool_router._confirm_tool_execution(
            "run", {"command": "ls"}, RiskLevel.RISKY
        )
        
        assert result is True
        mock_io.confirm_ask.assert_called_once()
        call_args = mock_io.confirm_ask.call_args
        assert "RISKY" in call_args[0][0]
        assert "run" in call_args[0][0]

    def test_confirm_tool_execution_fallback(self, tool_router, mock_io):
        """Test confirmation fallback to input()."""
        del mock_io.confirm_ask
        
        with patch('builtins.input', return_value='y'):
            result = tool_router._confirm_tool_execution(
                "run", {"command": "ls"}, RiskLevel.RISKY
            )
        
        assert result is True


class TestToolRouterHandlers:
    """Test individual tool handlers."""

    def test_exec_run_no_command(self, tool_router):
        """Test run with no command."""
        result = tool_router._exec_run({})
        assert result.success is False
        assert "No command provided" in result.error

    def test_exec_run_success(self, tool_router):
        """Test successful command execution."""
        with patch.object(tool_router.sandbox, 'run', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "command output"
            result = tool_router._exec_run({"command": "echo hello"})
        
        assert result.success is True
        assert result.output == "command output"

    def test_exec_run_timeout(self, tool_router):
        """Test command timeout."""
        with patch.object(tool_router.sandbox, 'run', new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = asyncio.TimeoutError()
            result = tool_router._exec_run({"command": "sleep 10", "timeout": 1})
        
        assert result.success is False
        assert "timed out" in result.error

    def test_exec_add_no_files(self, tool_router):
        """Test add with no files."""
        result = tool_router._exec_add({})
        assert result.success is False
        assert "No files specified" in result.error

    def test_exec_add_success(self, tool_router, mock_commands):
        """Test successful add."""
        result = tool_router._exec_add({"files": ["file1.txt", "file2.txt"]})
        
        assert result.success is True
        assert "2 file(s)" in result.output
        mock_commands.cmd_add.assert_called_once()

    def test_exec_add_string_files(self, tool_router, mock_commands):
        """Test add with single string file."""
        result = tool_router._exec_add({"files": "file.txt"})
        
        assert result.success is True
        mock_commands.cmd_add.assert_called_once()

    def test_exec_read_file_no_path(self, tool_router):
        """Test read_file with no path."""
        result = tool_router._exec_read_file({})
        assert result.success is False
        assert "No path specified" in result.error

    def test_exec_read_file_success(self, tool_router, mock_io):
        """Test successful file read."""
        mock_io.read_text.return_value = "line1\nline2\nline3"
        
        result = tool_router._exec_read_file({"path": "test.txt"})
        
        assert result.success is True
        assert "line1" in result.output

    def test_exec_read_file_not_found(self, tool_router, mock_io):
        """Test read_file with missing file."""
        mock_io.read_text.return_value = None
        
        result = tool_router._exec_read_file({"path": "missing.txt"})
        
        assert result.success is False
        assert "not found" in result.error

    def test_exec_read_file_pagination(self, tool_router, mock_io):
        """Test read_file with pagination."""
        mock_io.read_text.return_value = "\n".join([f"line{i}" for i in range(100)])
        
        result = tool_router._exec_read_file({"path": "test.txt", "offset": 10, "limit": 5})
        
        assert result.success is True
        assert "Lines 10-15 of 100" in result.output

    def test_exec_read_file_offset_past_end(self, tool_router, mock_io):
        """Test read_file with offset past end of file."""
        mock_io.read_text.return_value = "line1\nline2"
        
        result = tool_router._exec_read_file({"path": "test.txt", "offset": 10})
        
        assert result.success is True
        assert "offset 10 is past end" in result.output

    def test_exec_search_no_pattern(self, tool_router):
        """Test search with no pattern."""
        result = tool_router._exec_search({})
        assert result.success is False
        assert "No search pattern" in result.error

    def test_exec_git_success(self, tool_router, mock_commands):
        """Test git command execution."""
        with patch('sys.stdout', MagicMock()) as mock_stdout:
            mock_stdout.getvalue = MagicMock(return_value="git output")
            result = tool_router._exec_git({"args": "status"})
        
        assert result.success is True
        mock_commands.cmd_git.assert_called_once_with("status")

    def test_exec_ls_success(self, tool_router, mock_coder):
        """Test ls command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_coder.root = tmpdir
            mock_coder.abs_root_path = lambda p: os.path.join(tmpdir, p)
            Path(tmpdir, "file1.txt").touch()
            Path(tmpdir, "subdir").mkdir()
            
            result = tool_router._exec_ls({"path": "."})
        
        assert result.success is True
        assert "file1.txt" in result.output
        assert "subdir/" in result.output

    def test_exec_ls_not_directory(self, tool_router, mock_coder):
        """Test ls with non-directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_coder.root = tmpdir
            mock_coder.abs_root_path = lambda p: os.path.join(tmpdir, p)
            Path(tmpdir, "file.txt").touch()
            
            result = tool_router._exec_ls({"path": "file.txt"})
        
        assert result.success is False
        assert "Not a directory" in result.error

    def test_exec_drop_no_files(self, tool_router, mock_commands):
        """Test drop all files."""
        result = tool_router._exec_drop({})
        
        assert result.success is True
        assert "Dropped all files" in result.output
        mock_commands.cmd_drop.assert_called_once_with("")

    def test_exec_drop_with_files(self, tool_router, mock_commands):
        """Test drop specific files."""
        result = tool_router._exec_drop({"files": ["file1.txt"]})
        
        assert result.success is True
        assert "1 file(s)" in result.output
        mock_commands.cmd_drop.assert_called_once()

    def test_exec_commit_success(self, tool_router, mock_commands):
        """Test commit command."""
        result = tool_router._exec_commit({"message": "test commit"})
        
        assert result.success is True
        assert "Committed" in result.output
        mock_commands.cmd_commit.assert_called_once_with("test commit")


class TestToolRouterSearch:
    """Test search functionality."""

    def test_exec_search_with_ripgrep(self, tool_router, mock_coder):
        """Test search using ripgrep."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_coder.root = tmpdir
            mock_coder.abs_root_path = lambda p: os.path.join(tmpdir, p)
            Path(tmpdir, "test.txt").write_text("hello world\ntest pattern")
            
            with patch.object(tool_router, '_command_exists', return_value=True):
                with patch('asyncio.create_subprocess_exec') as mock_exec:
                    mock_proc = AsyncMock()
                    mock_proc.returncode = 0
                    mock_proc.communicate.return_value = (b"test.txt:1:hello world", b"")
                    mock_exec.return_value = mock_proc
                    
                    result = tool_router._exec_search({"pattern": "hello"})
        
        assert result.success is True

    def test_exec_search_with_git_grep(self, tool_router, mock_coder):
        """Test search falling back to git grep."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_coder.root = tmpdir
            mock_coder.abs_root_path = lambda p: os.path.join(tmpdir, p)
            
            with patch.object(tool_router, '_command_exists', return_value=False):
                with patch('asyncio.create_subprocess_exec') as mock_exec:
                    mock_proc = AsyncMock()
                    mock_proc.returncode = 0
                    mock_proc.communicate.return_value = (b"test.txt:1:hello", b"")
                    mock_exec.return_value = mock_proc
                    
                    result = tool_router._exec_search({"pattern": "hello"})
        
        assert result.success is True

    def test_exec_search_no_matches(self, tool_router, mock_coder):
        """Test search with no matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_coder.root = tmpdir
            mock_coder.abs_root_path = lambda p: os.path.join(tmpdir, p)
            
            with patch.object(tool_router, '_command_exists', return_value=True):
                with patch('asyncio.create_subprocess_exec') as mock_exec:
                    mock_proc = AsyncMock()
                    mock_proc.returncode = 1  # No matches
                    mock_proc.communicate.return_value = (b"", b"")
                    mock_exec.return_value = mock_proc
                    
                    result = tool_router._exec_search({"pattern": "xyz"})
        
        assert result.success is True
        assert "No matches" in result.output


class TestToolRouterVerboseLogging:
    """Test verbose logging behavior."""

    def test_log_call_verbose_output(self, tool_router, mock_io, mock_coder):
        """Test that verbose mode outputs to io."""
        mock_coder.verbose = True
        
        record = ToolCallRecord(
            call_id="test_1",
            timestamp=0.0,
            tool_name="ls",
            parameters={},
            risk_level=RiskLevel.SAFE,
            success=True,
            execution_time=0.5
        )
        tool_router._log_call(record)
        
        mock_io.tool_output.assert_called_once()
        call_args = mock_io.tool_output.call_args[0][0]
        assert "ls" in call_args
        assert "0.50s" in call_args

    def test_log_call_non_verbose_no_output(self, tool_router, mock_io, mock_coder):
        """Test that non-verbose mode doesn't output."""
        mock_coder.verbose = False
        
        record = ToolCallRecord(
            call_id="test_1",
            timestamp=0.0,
            tool_name="ls",
            parameters={},
            risk_level=RiskLevel.SAFE,
            success=True,
            execution_time=0.5
        )
        tool_router._log_call(record)
        
        mock_io.tool_output.assert_not_called()


class TestToolRouterErrorHandling:
    """Test error handling in various scenarios."""

    def test_handler_not_found(self, tool_router):
        """Test error when handler not found - returns failed result."""
        result = tool_router.execute("nonexistent_tool", {})
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_exec_run_sandbox_error(self, tool_router):
        """Test run with sandbox error."""
        with patch.object(tool_router.sandbox, 'run', new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = Exception("Sandbox failed")
            result = tool_router._exec_run({"command": "ls"})
        
        assert result.success is False
        assert "Sandbox execution failed" in result.error

    def test_exec_add_exception(self, tool_router, mock_commands):
        """Test add with exception."""
        mock_commands.cmd_add.side_effect = Exception("Add failed")
        
        result = tool_router._exec_add({"files": ["test.txt"]})
        
        assert result.success is False
        assert "Add failed" in result.error

    def test_exec_read_file_exception(self, tool_router, mock_coder):
        """Test read_file with exception."""
        mock_coder.abs_root_path.side_effect = Exception("Path error")
        
        result = tool_router._exec_read_file({"path": "test.txt"})
        
        assert result.success is False
        assert "Failed to read file" in result.error


class TestToolRouterCallCounter:
    """Test call counter increment."""

    def test_call_counter_increments(self, tool_router):
        """Test that call counter increments with each call."""
        with patch.object(tool_router, '_exec_ls', return_value=ToolResult(
            success=True, output="", execution_time=0.1
        )):
            tool_router.execute("ls", {})
            tool_router.execute("ls", {})
            tool_router.execute("ls", {})
        
        assert tool_router._call_counter == 3
        assert tool_router.call_history[0].call_id == "ls_1"
        assert tool_router.call_history[1].call_id == "ls_2"
        assert tool_router.call_history[2].call_id == "ls_3"


class TestToolRouterOutputPreview:
    """Test output preview in audit log."""

    def test_output_preview_truncated(self, tool_router):
        """Test that output preview is truncated in audit log."""
        long_output = "x" * 500
        
        with patch.object(tool_router, '_exec_ls', return_value=ToolResult(
            success=True, output=long_output, execution_time=0.1
        )):
            tool_router.execute("ls", {})
        
        record = tool_router.call_history[0]
        assert len(record.output_preview) <= 200
        assert record.output_preview == long_output[:200]

    def test_output_preview_empty(self, tool_router):
        """Test output preview with empty output."""
        with patch.object(tool_router, '_exec_ls', return_value=ToolResult(
            success=True, output="", execution_time=0.1
        )):
            tool_router.execute("ls", {})
        
        record = tool_router.call_history[0]
        assert record.output_preview == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
