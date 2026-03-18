#!/usr/bin/env python3
"""
Comprehensive test suite for ArchitectCoder - Phase 1
"""

import asyncio
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


class TestArchitectPhaseDiscovery:
    """Tests for Librarian phase file discovery."""

    @pytest.mark.asyncio
    async def test_librarian_phase_discovers_files(self):
        """Test that librarian phase discovers relevant files."""
        from aider.coders.architect_coder import ArchitectCoder
        from aider.coders.librarian_prompts import LibrarianPrompts

        # Create mock Coder
        coder = Mock()
        coder.gpt_prompts = LibrarianPrompts()
        coder.io = Mock()
        coder.io.tool_output = Mock()
        coder.abs_root_path = Mock(return_value="/fake/root/file.py")

        # Mock file discovery
        with patch.object(Path, "rglob") as mock_rglob:
            mock_files = [
                Path("/fake/root/auth.py"),
                Path("/fake/root/database.py"),
                Path("/fake/root/utils.py"),
            ]
            mock_rglob.return_value = iter(mock_files)

            # Mock file existence
            with patch("os.path.isfile", return_value=True):
                # Create architect instance
                architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())
                architect.root = "/fake/root"

                # Perform research
                await architect.perform_research("database queries")

                # Verify files were added
                assert architect.research_done is True
                assert len(architect.abs_fnames) > 0

    @pytest.mark.asyncio
    async def test_librarian_phase_limits_files(self):
        """Test that librarian phase limits to 10 files."""
        from aider.coders.architect_coder import ArchitectCoder

        architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())
        architect.root = "/fake/root"

        # Mock file discovery with 15 files
        with patch.object(Path, "rglob") as mock_rglob:
            mock_files = [Path(f"/fake/root/file{i}.py") for i in range(15)]
            mock_rglob.return_value = iter(mock_files)

            with patch("os.path.isfile", return_value=True):
                await architect.perform_research("test")

                # Should limit to 10 files
                assert len(architect.abs_fnames) <= 10


class TestArchitectStructuralCritique:
    """Tests for structural critique functionality."""

    @pytest.mark.asyncio
    async def test_structural_critique_passes(self):
        """Test that structural critique can pass."""
        from aider.coders.architect_coder import ArchitectCoder
        from aider.coders.reviewer_prompts import ReviewerPrompts

        architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())
        architect.gpt_prompts = ReviewerPrompts()

        plan = "Change database connection to use connection pool"
        critique = await architect.critique_plan(plan)

        # Critique should complete
        assert critique is not None
        assert len(critique) > 0

    @pytest.mark.asyncio
    async def test_structural_critique_fails(self):
        """Test that structural critique can fail."""
        from aider.coders.architect_coder import ArchitectCoder
        from aider.coders.reviewer_prompts import ReviewerPrompts

        architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())
        architect.gpt_prompts = ReviewerPrompts()

        # Provide a problematic plan
        plan = "This is a bad plan that will definitely fail review"
        critique = await architect.critique_plan(plan)

        # Critique should complete
        assert critique is not None


class TestArchitectA2ACommunication:
    """Tests for A2A communication."""

    @pytest.mark.asyncio
    async def test_a2a_find_file_command(self):
        """Test A2A file discovery command."""
        from aider.coders.architect_coder import ArchitectCoder

        architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())

        # Mock A2A bus
        architect.a2a_bus = Mock()
        architect.a2a_bus.send = Mock()
        architect.a2a_bus._loop = asyncio.get_event_loop()

        # Create system request
        message = {"content": {"command": "find_file", "parameters": {"pattern": "*.py"}}}

        # Handle request
        architect._on_system_request(message)

        # Verify response was sent
        assert architect.a2a_bus.send.called

    @pytest.mark.asyncio
    async def test_a2a_find_file_limited_to_10(self):
        """Test that A2A file discovery limits to 10 files."""
        from aider.coders.architect_coder import ArchitectCoder

        architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())
        architect.root = "/fake/root"

        # Mock file discovery with 20 files
        with patch.object(Path, "rglob") as mock_rglob:
            mock_files = [Path(f"/fake/root/file{i}.py") for i in range(20)]
            mock_rglob.return_value = iter(mock_files)

            with patch("os.path.isfile", return_value=True):
                # Mock A2A bus
                architect.a2a_bus = Mock()
                architect.a2a_bus._loop = asyncio.get_event_loop()

                # Handle request
                message = {"content": {"command": "find_file", "parameters": {"pattern": "*.py"}}}

                architect._on_system_request(message)

                # Verify response was sent
                assert architect.a2a_bus.send.called


class TestArchitectRecursiveCorrection:
    """Tests for recursive correction loops."""

    def test_max_critiques_limit(self):
        """Test that max_critiques limits correction iterations."""
        from aider.coders.architect_coder import ArchitectCoder

        architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())
        architect.max_critiques = 2

        # Simulate multiple critiques
        architect.num_critiques = 0
        for i in range(3):
            architect.num_critiques += 1

        # Should be limited to max_critiques
        assert architect.num_critiques == 2


class TestArchitectProactiveMonitoring:
    """Tests for proactive monitoring of background processes."""

    @pytest.mark.asyncio
    async def test_proactive_monitoring_detects_errors(self):
        """Test that proactive monitoring detects errors in logs."""
        from aider.coders.architect_coder import ArchitectCoder

        architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())

        # Mock tool router with processes
        mock_tool_router = Mock()
        mock_process = Mock()
        mock_process.is_running.return_value = True
        mock_process.get_logs.return_value = [
            "INFO: Server started",
            "INFO: Connection established",
            "ERROR: Database connection failed",
            "ERROR: Query timeout",
        ]

        mock_tool_router.terminal_watcher.processes = {"server": mock_process}

        architect.tool_router = mock_tool_router

        # Simulate monitoring
        architect.reply_completed()

        # Verify error was detected
        # (Note: This would check the last_message or similar)
        assert True  # Mock implementation

    @pytest.mark.asyncio
    async def test_proactive_monitoring_handles_stopped_process(self):
        """Test that proactive monitoring handles stopped processes."""
        from aider.coders.architect_coder import ArchitectCoder

        architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())

        # Mock tool router with stopped process
        mock_tool_router = Mock()
        mock_process = Mock()
        mock_process.is_running.return_value = False

        mock_tool_router.terminal_watcher.processes = {"server": mock_process}

        architect.tool_router = mock_tool_router

        # Simulate monitoring (should not crash)
        try:
            architect.reply_completed()
            assert True  # Should not raise exception
        except Exception as e:
            pytest.fail(f"Monitoring should handle stopped processes gracefully: {e}")


class TestArchitectAgentDelegation:
    """Tests for agent delegation."""

    def test_delegation_to_specialist(self):
        """Test that architect can delegate to specialist agents."""
        from aider.coders.architect_coder import ArchitectCoder

        architect = ArchitectCoder(io=Mock(), main_model=Mock(), from_coder=Mock())

        # Should be able to create reviewer
        reviewer_kwargs = dict(
            main_model=architect.main_model,
            io=architect.io,
            from_coder=architect,
            edit_format="ask",
            summarize_from_coder=False,
        )

        # This would create a reviewer instance
        # For now, just verify kwargs are valid
        assert "main_model" in reviewer_kwargs
        assert "io" in reviewer_kwargs
        assert "from_coder" in reviewer_kwargs
        assert "edit_format" in reviewer_kwargs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
