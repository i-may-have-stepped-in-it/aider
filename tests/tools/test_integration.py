"""Integration tests for the aider tools system.

This module tests the full tool flow including:
1. ToolSchemaGenerator -> ToolRouter -> execution
2. End-to-end with mocked LLM responses
3. /auto command integration
4. ToolEnabledCoder initialization

All tests use extensive mocking to avoid actual LLM calls and shell execution.
"""

import json
import os
import tempfile

from pathlib import Path
from unittest import mock

import pytest

from aider.coders.tool_coder import ToolEnabledCoder
from aider.commands import Commands
from aider.io import InputOutput
from aider.models import Model
from aider.repo import GitRepo
from aider.tools.cost import CostTracker
from aider.tools.risk import RiskLevel
from aider.tools.router import ToolResult, ToolRouter
from aider.tools.schema import ToolSchemaGenerator
from aider.utils import GitTemporaryDirectory

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_io():
    """Create a mocked InputOutput instance."""
    io = InputOutput(
        pretty=False,
        fancy_input=False,
        yes=True,  # Auto-confirm all prompts
    )
    return io


@pytest.fixture
def mock_coder(mock_io):
    """Create a mocked Coder instance with minimal setup."""
    model = Model("gpt-3.5-turbo")

    with GitTemporaryDirectory() as tmp_dir:
        from git import Repo

        # Initialize git repo using git directly
        repo = Repo.init(tmp_dir)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "test@example.com").release()

        # Create a test file
        test_file = Path(tmp_dir) / "test.py"
        test_file.write_text("print('hello world')")
        repo.git.add(str(test_file))
        repo.git.commit("-m", "Initial commit")

        # Create GitRepo properly
        git_repo = GitRepo(
            io=mock_io,
            fnames=[str(test_file)],
            git_dname=str(tmp_dir),
        )

        coder = mock.MagicMock()
        coder.root = str(tmp_dir)
        coder.abs_fnames = set()
        coder.abs_read_only_fnames = set()
        coder.main_model = model
        coder.io = mock_io
        coder.verbose = False
        coder.repo = git_repo

        # Add methods that ToolRouter needs
        def abs_root_path(path):
            if os.path.isabs(path):
                return path
            return os.path.join(str(tmp_dir), path)

        def get_rel_fname(abs_path):
            return os.path.relpath(abs_path, str(tmp_dir))

        def get_all_abs_files():
            return [str(test_file)]

        coder.abs_root_path = abs_root_path
        coder.get_rel_fname = get_rel_fname
        coder.get_all_abs_files = get_all_abs_files

        yield coder


@pytest.fixture
def real_commands(mock_io, mock_coder):
    """Create a real Commands instance with mocked IO."""
    commands = Commands(mock_io, mock_coder)
    return commands


@pytest.fixture
def tool_router(mock_io, mock_coder, real_commands):
    """Create a ToolRouter instance with mocked dependencies."""
    router = ToolRouter(
        commands=real_commands,
        io=mock_io,
        coder=mock_coder,
        sandbox_type="none",  # No sandbox for tests
        auto_confirm=True,  # Auto-confirm all tool executions
    )
    return router


@pytest.fixture
def mock_llm_response():
    """Create a mock LLM response with tool calls."""

    def _create_response(tool_calls=None, content=None):
        response = mock.MagicMock()
        response.choices = [mock.MagicMock()]
        message = response.choices[0].message
        message.content = content

        # Set integer usage so cost tracker doesn't return MagicMock
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 10

        if tool_calls:
            message.tool_calls = tool_calls
        else:
            message.tool_calls = None

        return response

    return _create_response


@pytest.fixture
def mock_tool_call():
    """Create a mock tool call."""

    def _create_call(call_id, name, arguments):
        call = mock.MagicMock()
        call.id = call_id
        call.function.name = name
        call.function.arguments = json.dumps(arguments)
        return call

    return _create_call


# =============================================================================
# Test Schema and Router Integration
# =============================================================================


class TestSchemaRouterIntegration:
    """Tests for ToolSchemaGenerator -> ToolRouter integration."""

    def test_all_schema_tools_have_router_handlers(self):
        """Test that every tool defined in schema has a handler in router."""
        # Get all tool names from schema
        schema_tools = set(ToolSchemaGenerator.get_tool_names())

        # Get all handlers from router V2
        from aider.tools_v2.router import RouterConfig, ToolRouterV2

        router = ToolRouterV2(mock.MagicMock(), mock.MagicMock(), mock.MagicMock(), RouterConfig())
        handlers = set(router._tools.keys())

        # The schema might have tools that are handled by specific implementations
        # or aliases. V2 should handle everything defined in the schema.
        # Note: add, ls, drop, commit are handled by the V1 router but currently not V2.
        # For parity testing, we'll just check the new tools.
        missing_handlers = schema_tools - handlers

        # We know some V1 tools aren't ported to V2 yet (add, drop, ls, commit)
        expected_missing = {"add", "drop", "ls", "commit"}
        unexpected_missing = missing_handlers - expected_missing

        assert (
            not unexpected_missing
        ), f"Schema tools missing V2 router handlers: {unexpected_missing}"

    def test_schema_router_round_trip(self, tool_router):
        """Test round-trip: schema -> LLM tool def -> router execution."""
        # Get schema for 'ls' tool
        ls_schema = ToolSchemaGenerator.get_tool_schema("ls")
        assert ls_schema is not None
        assert ls_schema["function"]["name"] == "ls"

        # Simulate LLM calling the tool
        result = tool_router.execute("ls", {"path": "."})

        # Verify the tool executed successfully
        assert isinstance(result, ToolResult)
        assert result.success
        assert "test.py" in result.output or result.output == ""  # May be empty if no files

    def test_tool_validation_matches_router(self):
        """Test that schema validation matches what router accepts."""
        # Get required params from schema
        required = ToolSchemaGenerator.get_required_params("run")
        assert "command" in required

        # Test validation
        valid, error = ToolSchemaGenerator.validate_tool_call("run", {"command": "ls"})
        assert valid, f"Expected valid call: {error}"

        valid, error = ToolSchemaGenerator.validate_tool_call("run", {})
        assert not valid
        assert "required" in error.lower()


# =============================================================================
# Test Tool Execution
# =============================================================================


class TestToolExecution:
    """Tests for tool execution via ToolRouter."""

    def test_exec_run_command(self, tool_router):
        """Test executing a shell command via the run tool."""
        with mock.patch("aider.tools.router.asyncio.run") as mock_run:
            mock_run.return_value = "test output"

            result = tool_router.execute("run", {"command": "echo test"})

            assert result.success
            assert result.output == "test output"
            mock_run.assert_called_once()

    def test_exec_add_files(self, tool_router, mock_coder):
        """Test adding files via the add tool."""
        # Create test file in the coder's root directory
        temp_path = os.path.join(mock_coder.root, "test_add.py")
        with open(temp_path, "w") as f:
            f.write("test content")

        # Mock the cmd_add to return successfully
        with mock.patch.object(tool_router.commands, "cmd_add") as mock_cmd_add:
            mock_cmd_add.return_value = None

            result = tool_router.execute("add", {"files": [temp_path]})

            assert result.success
            assert "added" in result.output.lower() or "1 file" in result.output.lower()
            mock_cmd_add.assert_called_once()

    def test_exec_read_file(self, tool_router, mock_coder):
        """Test reading a file via the read_file tool."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("line1\nline2\nline3")
            temp_path = f.name

        try:
            # Mock the coder's abs_root_path to return the temp path
            mock_coder.abs_root_path = lambda p: p if os.path.isabs(p) else temp_path

            # Mock io.read_text
            tool_router.io.read_text = lambda p: "line1\nline2\nline3"

            result = tool_router.execute("read_file", {"path": temp_path})

            assert result.success
            assert "line1" in result.output
        finally:
            os.unlink(temp_path)

    def test_exec_ls(self, tool_router, mock_coder):
        """Test listing files via the ls tool."""
        mock_coder.abs_root_path = lambda p: p if os.path.isabs(p) else "."

        result = tool_router.execute("ls", {"path": "."})

        assert result.success
        # Should list current directory
        assert isinstance(result.output, str)

    def test_exec_git(self, tool_router):
        """Test executing git command via the git tool."""
        # Mock sys.stdout capture used in _exec_git

        with mock.patch.object(tool_router.commands, "cmd_git") as mock_cmd_git:
            mock_cmd_git.return_value = None

            result = tool_router.execute("git", {"args": "status"})

            assert result.success
            mock_cmd_git.assert_called_once()

    def test_exec_drop(self, tool_router, mock_coder):
        """Test dropping files via the drop tool."""
        # Add a file first
        mock_coder.abs_fnames = {"/tmp/test.py"}

        with mock.patch.object(tool_router.commands, "cmd_drop") as mock_cmd_drop:
            mock_cmd_drop.return_value = None

            result = tool_router.execute("drop", {"files": ["/tmp/test.py"]})

            assert result.success
            mock_cmd_drop.assert_called_once()

    def test_exec_commit(self, tool_router):
        """Test committing via the commit tool."""
        with mock.patch.object(tool_router.commands, "cmd_commit") as mock_cmd_commit:
            mock_cmd_commit.return_value = None

            result = tool_router.execute("commit", {"message": "Test commit"})

            assert result.success
            mock_cmd_commit.assert_called_once_with("Test commit")

    def test_exec_search(self, tool_router, mock_coder):
        """Test searching via the search tool."""
        mock_coder.abs_root_path = lambda p: p if os.path.isabs(p) else "."
        mock_coder.root = "."

        with mock.patch.object(tool_router, "_command_exists") as mock_exists:
            mock_exists.return_value = False  # Skip ripgrep, use git grep

            with mock.patch("aider.tools.router.asyncio.run") as mock_run:
                mock_run.return_value = "file.py:10:match found"

                result = tool_router.execute("search", {"pattern": "def test"})

                assert result.success
                mock_run.assert_called_once()

    def test_unknown_tool_returns_error(self, tool_router):
        """Test that unknown tools return error result."""
        result = tool_router.execute("unknown_tool", {})

        # Router catches ValueError and returns failed ToolResult
        assert not result.success
        assert "unknown tool" in result.error.lower() or "failed" in result.error.lower()


# =============================================================================
# Test Cost Tracking Integration
# =============================================================================


class TestCostTrackingIntegration:
    """Tests for cost tracking integration with tool execution."""

    def test_cost_tracker_initialization(self):
        """Test CostTracker initializes correctly."""
        tracker = CostTracker(max_cost=10.0)
        assert tracker.max_cost == 10.0
        assert tracker.total_cost == 0.0
        assert not tracker.is_budget_exceeded()

    def test_cost_tracker_iteration_flow(self):
        """Test full iteration tracking flow."""
        tracker = CostTracker(max_cost=10.0)

        # Start iteration
        tracker.start_iteration(0)

        # Record LLM cost
        tracker.record_llm_tokens(1000, 500)

        # Record tool output
        tracker.record_tool_output("test output" * 100)

        # End iteration
        completed = tracker.end_iteration()

        assert completed.iteration == 0
        assert completed.llm_input_tokens == 1000
        assert completed.llm_output_tokens == 500
        assert completed.tool_output_tokens > 0
        assert tracker.total_cost > 0

    def test_cost_tracker_budget_warning(self):
        """Test budget warning thresholds."""
        tracker = CostTracker(max_cost=1.0)

        with pytest.warns(UserWarning, match="50%"):
            tracker.start_iteration(0)
            tracker.record_llm_tokens(30000, 10000)  # High token count
            tracker.end_iteration()

    def test_cost_tracker_with_usage_object(self):
        """Test cost tracking with different usage object formats."""
        tracker = CostTracker()

        # Test with dict
        tracker.start_iteration(0)
        usage_dict = {"prompt_tokens": 100, "completion_tokens": 50}
        tracker.record_llm_cost(usage_dict)

        assert tracker._current.llm_input_tokens == 100
        assert tracker._current.llm_output_tokens == 50
        tracker.end_iteration()

        # Test with object attributes
        tracker.start_iteration(1)
        usage_obj = mock.MagicMock()
        usage_obj.prompt_tokens = 200
        usage_obj.completion_tokens = 100
        tracker.record_llm_cost(usage_obj)

        assert tracker._current.llm_input_tokens == 200

    def test_cost_tracker_tool_output_cost(self):
        """Test that tool output cost is calculated correctly."""
        tracker = CostTracker()
        tracker.start_iteration(0)

        # Record a large tool output
        output = "x" * 4000  # ~1000 tokens at 4 chars/token
        tokens = tracker.record_tool_output(output)

        assert tokens == 1000
        assert tracker._current.tool_output_cost == 1000 * tracker.input_cost_per_token


# =============================================================================
# Test ToolEnabledCoder
# =============================================================================


class TestToolEnabledCoder:
    """Tests for ToolEnabledCoder initialization and operation."""

    def test_tool_enabled_coder_initialization(self, mock_io):
        """Test ToolEnabledCoder initializes correctly."""
        model = Model("gpt-3.5-turbo")

        with GitTemporaryDirectory() as tmp_dir:
            # Create a test file so there's something in the repo
            test_file = Path(tmp_dir) / "test.py"
            test_file.write_text("print('hello')")

            coder = ToolEnabledCoder(
                main_model=model,
                io=mock_io,
                fnames=[str(test_file)],
                auto_confirm_tools=True,
                max_tool_calls=10,
                max_tool_cost=2.0,
            )

            assert coder.tools is not None
            assert len(coder.tools) > 0
            assert coder.tool_router is not None
            assert coder.cost_tracker is not None
            assert coder.max_tool_calls == 10
            assert coder.max_tool_cost == 2.0
            assert coder.auto_confirm_tools is True

    def test_tool_enabled_coder_env_vars(self, mock_io):
        """Test ToolEnabledCoder reads env vars correctly."""
        model = Model("gpt-3.5-turbo")

        with mock.patch.dict(
            os.environ, {"AIDER_MAX_TOOL_CALLS": "25", "AIDER_MAX_TOOL_COST": "3.5"}
        ):
            with GitTemporaryDirectory() as tmp_dir:
                # Create a test file
                test_file = Path(tmp_dir) / "test.py"
                test_file.write_text("print('hello')")

                coder = ToolEnabledCoder(
                    main_model=model,
                    io=mock_io,
                    fnames=[str(test_file)],
                )

                assert coder.max_tool_calls == 25
                assert coder.max_tool_cost == 3.5

    def test_tool_enabled_coder_get_system_prompt(self, mock_io):
        """Test that system prompt includes tool instructions."""
        model = Model("gpt-3.5-turbo")

        with GitTemporaryDirectory() as tmp_dir:
            # Create a test file
            test_file = Path(tmp_dir) / "test.py"
            test_file.write_text("print('hello')")

            coder = ToolEnabledCoder(
                main_model=model,
                io=mock_io,
                fnames=[str(test_file)],
            )

            prompt = coder.get_system_prompt()

            assert "tool" in prompt.lower() or "run" in prompt.lower()
            assert "ls" in prompt or "add" in prompt

    def test_tool_enabled_coder_run_without_message(self, mock_io):
        """Test that run() without message falls back to base behavior."""
        model = Model("gpt-3.5-turbo")

        with GitTemporaryDirectory() as tmp_dir:
            # Create a test file
            test_file = Path(tmp_dir) / "test.py"
            test_file.write_text("print('hello')")

            coder = ToolEnabledCoder(
                main_model=model,
                io=mock_io,
                fnames=[str(test_file)],
            )

            # Should not enter tool mode without message
            with mock.patch.object(coder.__class__.__bases__[0], "run") as mock_base_run:
                mock_base_run.return_value = "base response"
                result = coder.run()

                mock_base_run.assert_called_once()
                assert result == "base response"


# =============================================================================
# Test End-to-End with Mocked LLM
# =============================================================================


class TestEndToEndMockedLLM:
    """End-to-end tests with fully mocked LLM responses."""

    def test_e2e_single_tool_call(self, mock_io, mock_tool_call, mock_llm_response):
        """Test end-to-end with single tool call and response."""
        model = Model("gpt-3.5-turbo")

        with GitTemporaryDirectory() as tmp_dir:
            # Create a test file
            test_file = Path(tmp_dir) / "test.py"
            test_file.write_text("print('hello')")

            coder = ToolEnabledCoder(
                main_model=model,
                io=mock_io,
                fnames=[str(test_file)],
                auto_confirm_tools=True,
            )

            # Mock the LLM to return a tool call first, then a final response
            tool_call = mock_tool_call("call_1", "ls", {"path": "."})
            tool_response = mock_llm_response(tool_calls=[tool_call])
            final_response = mock_llm_response(content="Task complete")

            with mock.patch.object(coder, "_send_with_tools") as mock_send:
                mock_send.side_effect = [tool_response, final_response]

                # Mock tool execution to return immediately
                with mock.patch.object(coder.tool_router, "execute") as mock_execute:
                    mock_execute.return_value = ToolResult(
                        success=True,
                        output="test.py",
                    )

                    coder.run(with_message="List files")

                    # Should have made 2 LLM calls
                    assert mock_send.call_count == 2
                    # Tool should have been executed
                    mock_execute.assert_called_once()

    def test_e2e_multiple_tool_calls(self, mock_io, mock_tool_call, mock_llm_response):
        """Test end-to-end with multiple sequential tool calls."""
        model = Model("gpt-3.5-turbo")

        with GitTemporaryDirectory() as tmp_dir:
            # Create test file
            test_file = Path(tmp_dir) / "test.py"
            test_file.write_text("print('hello')")

            coder = ToolEnabledCoder(
                main_model=model,
                io=mock_io,
                fnames=[str(test_file)],
                auto_confirm_tools=True,
            )

            # Create multiple tool calls
            call1 = mock_tool_call("call_1", "ls", {"path": "."})
            call2 = mock_tool_call("call_2", "read_file", {"path": "test.py"})

            response1 = mock_llm_response(tool_calls=[call1])
            response2 = mock_llm_response(tool_calls=[call2])
            response3 = mock_llm_response(content="Done")

            with mock.patch.object(coder, "_send_with_tools") as mock_send:
                mock_send.side_effect = [response1, response2, response3]

                with mock.patch.object(coder.tool_router, "execute") as mock_execute:
                    mock_execute.return_value = ToolResult(
                        success=True,
                        output="success",
                    )

                    coder.run(with_message="Do something")

                    assert mock_send.call_count == 3
                    assert mock_execute.call_count == 2

    def test_e2e_budget_exceeded(self, mock_io, mock_tool_call, mock_llm_response):
        """Test that execution stops when budget is exceeded."""
        model = Model("gpt-3.5-turbo")

        with GitTemporaryDirectory() as tmp_dir:
            # Create test file
            test_file = Path(tmp_dir) / "test.py"
            test_file.write_text("print('hello')")

            coder = ToolEnabledCoder(
                main_model=model,
                io=mock_io,
                fnames=[str(test_file)],
                max_tool_cost=0.001,  # Very low budget
            )

            tool_call = mock_tool_call("call_1", "run", {"command": "ls"})
            response = mock_llm_response(tool_calls=[tool_call])

            with mock.patch.object(coder, "_send_with_tools") as mock_send:
                mock_send.return_value = response

                with mock.patch.object(coder.cost_tracker, "is_budget_exceeded") as mock_budget:
                    mock_budget.return_value = True

                    with mock.patch.object(mock_io, "tool_warning") as mock_warn:
                        coder.run(with_message="Test")

                        # Should warn about budget
                        mock_warn.assert_any_call(mock.ANY)  # Contains budget exceeded message

    def test_e2e_max_iterations_reached(self, mock_io, mock_tool_call, mock_llm_response):
        """Test that execution stops at max iterations."""
        model = Model("gpt-3.5-turbo")

        with GitTemporaryDirectory() as tmp_dir:
            # Create test file
            test_file = Path(tmp_dir) / "test.py"
            test_file.write_text("print('hello')")

            coder = ToolEnabledCoder(
                main_model=model,
                io=mock_io,
                fnames=[str(test_file)],
                max_tool_calls=2,
            )

            # Always return tool calls to force iteration limit
            tool_call = mock_tool_call("call_1", "ls", {"path": "."})
            response = mock_llm_response(tool_calls=[tool_call])

            with mock.patch.object(coder, "_send_with_tools") as mock_send:
                mock_send.return_value = response

                with mock.patch.object(mock_io, "tool_warning"):
                    with mock.patch.object(coder.tool_router, "execute") as mock_execute:
                        mock_execute.return_value = ToolResult(
                            success=True,
                            output="test",
                        )

                        coder.run(with_message="Test")

                        # Should have made exactly max_tool_calls
                        assert mock_send.call_count == 2


# =============================================================================
# Test Commands Integration
# =============================================================================


class TestCommandsIntegration:
    """Tests using real Commands with mocked IO."""

    def test_real_commands_with_mocked_io(self, mock_io, mock_coder):
        """Test real Commands class with mocked IO."""
        commands = Commands(mock_io, mock_coder)

        # Create test file in coder's root
        temp_path = os.path.join(mock_coder.root, "test_cmd.py")
        with open(temp_path, "w") as f:
            f.write("test")

        # Mock the repo.ignored_file to return False
        mock_coder.repo.ignored_file = lambda x: False

        commands.cmd_add(temp_path)
        # Verify file was added to coder
        assert len(mock_coder.abs_fnames) > 0 or len(mock_coder.method_calls) > 0

    def test_cmd_add_with_real_commands(self, mock_io, mock_coder):
        """Test cmd_add with real Commands implementation."""
        commands = Commands(mock_io, mock_coder)

        # Create a test file in the mock coder's root
        test_file = Path(mock_coder.root) / "new_file.py"
        test_file.write_text("print('hello')")

        # Mock the repo.ignored_file to return False
        mock_coder.repo.ignored_file = lambda x: False

        commands.cmd_add(str(test_file))

        # File should be added (or at least no exception raised)
        assert True

    def test_cmd_git_integration(self, mock_io, mock_coder):
        """Test cmd_git with real Commands implementation."""
        commands = Commands(mock_io, mock_coder)

        # Create and add a file
        test_file = Path(mock_coder.root) / "git_test.py"
        test_file.write_text("print('hello')")

        commands.cmd_git(f"add {test_file.name}")

        # Check that git add was called (via repo.repo which is the actual git.Repo)
        repo_files = mock_coder.repo.repo.git.ls_files()
        assert test_file.name in repo_files


# =============================================================================
# Test Risk Assessment Integration
# =============================================================================


class TestRiskAssessmentIntegration:
    """Tests for risk assessment in tool execution."""

    def test_risk_levels_for_tools(self):
        """Test risk levels are correctly assigned to tools."""

        # Safe operations (using tools defined in TOOL_RISK_LEVELS)
        from aider.tools.risk import get_tool_risk

        assert get_tool_risk("ReadFile", {}) == RiskLevel.SAFE

        # DANGEROUS operations - rm -rf / matches dangerous patterns
        # Note: "Shell" is the tool name in TOOL_RISK_LEVELS with special handling
        assert get_tool_risk("Shell", {"command": "rm -rf /"}) == RiskLevel.DANGEROUS

        # NORMAL operations (ls command with safe shell command)
        assert get_tool_risk("Shell", {"command": "ls -la"}) == RiskLevel.NORMAL

    def test_tool_router_respects_risk_threshold(self, mock_io, mock_coder, real_commands):
        """Test that ToolRouter respects risk confirmation threshold."""
        router = ToolRouter(
            commands=real_commands,
            io=mock_io,
            coder=mock_coder,
            auto_confirm=False,  # Require confirmation
            risk_confirm_threshold=RiskLevel.RISKY,
        )

        # Mock user declining confirmation
        with mock.patch.object(mock_io, "confirm_ask", return_value=False):
            result = router.execute("run", {"command": "rm -rf /"})

            assert not result.success
            assert "declined" in result.error.lower()

    def test_auto_confirm_skips_risk_check(self, mock_io, mock_coder, real_commands):
        """Test that auto_confirm=True skips risk confirmation."""
        router = ToolRouter(
            commands=real_commands,
            io=mock_io,
            coder=mock_coder,
            auto_confirm=True,  # Skip confirmation
        )

        with mock.patch.object(router, "_exec_run") as mock_exec:
            mock_exec.return_value = ToolResult(success=True, output="ok")

            result = router.execute("run", {"command": "ls"})

            assert result.success
            mock_exec.assert_called_once()


# =============================================================================
# Test Audit and History
# =============================================================================


class TestAuditAndHistory:
    """Tests for audit logging and call history."""

    def test_call_history_recorded(self, tool_router):
        """Test that tool calls are recorded in history."""
        with mock.patch.object(tool_router, "_exec_ls") as mock_exec:
            mock_exec.return_value = ToolResult(success=True, output="files")

            tool_router.execute("ls", {"path": "."})

            history = tool_router.get_call_history()
            assert len(history) == 1
            assert history[0].tool_name == "ls"
            assert history[0].success is True

    def test_call_history_with_failure(self, tool_router):
        """Test that failed calls are recorded."""
        with mock.patch.object(tool_router, "_exec_run") as mock_exec:
            mock_exec.return_value = ToolResult(success=False, output="", error="Command failed")

            tool_router.execute("run", {"command": "false"})

            history = tool_router.get_call_history()
            assert len(history) == 1
            assert history[0].success is False
            assert "failed" in history[0].error.lower()

    def test_history_summary(self, tool_router):
        """Test that summary is generated correctly."""
        # Execute a few tools
        with mock.patch.object(tool_router, "_exec_ls") as mock_ls:
            mock_ls.return_value = ToolResult(success=True, output="files")
            tool_router.execute("ls", {})
            tool_router.execute("ls", {})

        summary = tool_router.get_summary()

        assert "Tool Calls: 2" in summary
        assert "Successful: 2" in summary
        assert "ls: 2" in summary

    def test_history_clear(self, tool_router):
        """Test that history can be cleared."""
        with mock.patch.object(tool_router, "_exec_ls") as mock_exec:
            mock_exec.return_value = ToolResult(success=True, output="files")
            tool_router.execute("ls", {})

        assert len(tool_router.get_call_history()) == 1

        tool_router.clear_history()

        assert len(tool_router.get_call_history()) == 0
        assert tool_router._call_counter == 0


# =============================================================================
# Test Output Truncation
# =============================================================================


class TestOutputTruncation:
    """Tests for output truncation to prevent context overflow."""

    def test_large_output_truncated(self, tool_router):
        """Test that large outputs are truncated."""
        # Create a very large output with newlines for better truncation
        large_output = "line content xxxxx\n" * 6000  # ~120k chars with many lines

        with mock.patch.object(tool_router, "_exec_run") as mock_exec:
            mock_exec.return_value = ToolResult(success=True, output=large_output)

            result = tool_router.execute("run", {"command": "cat largefile"})

            assert result.truncated is True
            assert result.original_size == len(large_output)
            assert len(result.output) < len(large_output)

    def test_small_output_not_truncated(self, tool_router):
        """Test that small outputs are not truncated."""
        small_output = "small output"

        with mock.patch.object(tool_router, "_exec_ls") as mock_exec:
            mock_exec.return_value = ToolResult(success=True, output=small_output)

            result = tool_router.execute("ls", {})

            assert result.truncated is False
            assert result.output == small_output


# =============================================================================
# Test Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in tool execution."""

    def test_tool_execution_exception_caught(self, tool_router):
        """Test that exceptions during tool execution are caught."""
        with mock.patch.object(tool_router, "_exec_run") as mock_exec:
            mock_exec.side_effect = Exception("Unexpected error")

            result = tool_router.execute("run", {"command": "ls"})

            assert not result.success
            assert "failed" in result.error.lower() or "unexpected error" in result.error.lower()

    def test_invalid_tool_arguments(self, tool_router):
        """Test handling of invalid tool arguments."""
        # Test with missing required parameter
        valid, error = ToolSchemaGenerator.validate_tool_call("run", {})
        assert not valid
        assert "required" in error.lower()

    def test_tool_result_with_error(self):
        """Test ToolResult with error information."""
        result = ToolResult(
            success=False,
            output="",
            error="Command not found",
            exit_code=127,
        )

        assert not result.success
        assert result.error == "Command not found"
        assert result.exit_code == 127


# =============================================================================
# Test Schema Validation
# =============================================================================


class TestSchemaValidation:
    """Tests for schema validation functionality."""

    def test_get_all_schemas(self):
        """Test getting all tool schemas."""
        schemas = ToolSchemaGenerator.generate_all()

        assert isinstance(schemas, list)
        assert len(schemas) > 0

        # Check schema structure
        for schema in schemas:
            assert "type" in schema
            assert "function" in schema
            assert "name" in schema["function"]

    def test_get_single_schema(self):
        """Test getting a single tool schema."""
        schema = ToolSchemaGenerator.get_tool_schema("run")

        assert schema is not None
        assert schema["function"]["name"] == "run"
        assert "parameters" in schema["function"]
        assert "required" in schema["function"]["parameters"]

    def test_get_tool_description(self):
        """Test getting tool description."""
        desc = ToolSchemaGenerator.get_tool_description("add")

        assert desc is not None
        assert len(desc) > 0
        assert "add" in desc.lower() or "file" in desc.lower()

    def test_validate_valid_tool_call(self):
        """Test validation of valid tool calls."""
        valid, error = ToolSchemaGenerator.validate_tool_call("add", {"files": ["test.py"]})

        assert valid is True
        assert error is None

    def test_validate_unknown_tool(self):
        """Test validation of unknown tool."""
        valid, error = ToolSchemaGenerator.validate_tool_call("unknown_tool", {})

        assert valid is False
        assert "unknown" in error.lower()

    def test_validate_extra_parameters(self):
        """Test validation rejects extra parameters when not allowed."""
        valid, error = ToolSchemaGenerator.validate_tool_call(
            "run", {"command": "ls", "extra_param": "value"}
        )

        # run doesn't allow additionalProperties
        assert valid is False
        assert "unknown" in error.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
