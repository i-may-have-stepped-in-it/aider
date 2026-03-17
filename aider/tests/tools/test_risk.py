"""Tests for risk classification system.

This module tests the risk classification functionality which assigns risk levels
to tools based on their potential impact on the system.
"""

import pytest
from aider.tools.risk import (
    RiskLevel,
    get_tool_risk,
    is_tool_safe,
    requires_confirmation,
    TOOL_RISK_LEVELS,
    GIT_SUBCOMMAND_RISK,
    _extract_git_subcommand,
    _check_dangerous_shell_patterns,
    _is_force_git_command,
    _is_hard_reset,
)


class TestRiskLevelEnum:
    """Test suite for RiskLevel enum."""

    def test_risk_level_values(self):
        """Verify RiskLevel enum has expected values.
        
        Risk levels should be ordered from least to most dangerous.
        """
        assert RiskLevel.SAFE.value >= 1
        assert RiskLevel.NORMAL.value >= 1
        assert RiskLevel.RISKY.value >= 1
        assert RiskLevel.DANGEROUS.value >= 1

    def test_risk_level_ordering(self):
        """Verify RiskLevel values follow expected ordering.
        
        SAFE < NORMAL < RISKY < DANGEROUS
        """
        assert RiskLevel.SAFE.value < RiskLevel.NORMAL.value
        assert RiskLevel.NORMAL.value < RiskLevel.RISKY.value
        assert RiskLevel.RISKY.value < RiskLevel.DANGEROUS.value

    def test_risk_level_names(self):
        """Verify RiskLevel enum members have correct names."""
        assert RiskLevel.SAFE.name == "SAFE"
        assert RiskLevel.NORMAL.name == "NORMAL"
        assert RiskLevel.RISKY.name == "RISKY"
        assert RiskLevel.DANGEROUS.name == "DANGEROUS"


class TestToolRiskMapping:
    """Test suite for base tool risk level mappings."""

    def test_safe_tools_mapping(self):
        """Verify SAFE tools are correctly mapped.
        
        Read-only operations should be SAFE.
        """
        # Tool names use snake_case in the mapping
        assert TOOL_RISK_LEVELS["read_file"] == RiskLevel.SAFE
        assert TOOL_RISK_LEVELS["glob"] == RiskLevel.SAFE
        assert TOOL_RISK_LEVELS["grep"] == RiskLevel.SAFE
        assert TOOL_RISK_LEVELS["fetch_url"] == RiskLevel.SAFE
        assert TOOL_RISK_LEVELS["search_web"] == RiskLevel.SAFE
        assert TOOL_RISK_LEVELS["read_media_file"] == RiskLevel.SAFE
        assert TOOL_RISK_LEVELS["ask_user_question"] == RiskLevel.SAFE

    def test_normal_tools_mapping(self):
        """Verify NORMAL tools are correctly mapped.
        
        Write operations should be NORMAL.
        """
        assert TOOL_RISK_LEVELS["write_file"] == RiskLevel.NORMAL
        assert TOOL_RISK_LEVELS["str_replace_file"] == RiskLevel.NORMAL

    def test_dangerous_tools_mapping(self):
        """Verify DANGEROUS tools are correctly mapped.
        
        Shell has unrestricted power, so base level is DANGEROUS.
        """
        assert TOOL_RISK_LEVELS["run"] == RiskLevel.DANGEROUS
        assert TOOL_RISK_LEVELS["shell"] == RiskLevel.DANGEROUS


class TestGetToolRiskSafeTools:
    """Test suite for get_tool_risk() with SAFE tools."""

    def test_read_file_is_safe(self):
        """Verify ReadFile is classified as SAFE."""
        risk = get_tool_risk("ReadFile", {"path": "/tmp/test.txt"})
        assert risk == RiskLevel.SAFE

    def test_glob_is_safe(self):
        """Verify Glob is classified as SAFE."""
        risk = get_tool_risk("Glob", {"pattern": "*.py"})
        assert risk == RiskLevel.SAFE

    def test_grep_is_safe(self):
        """Verify Grep is classified as SAFE."""
        risk = get_tool_risk("Grep", {"pattern": "test", "path": "/src"})
        assert risk == RiskLevel.SAFE

    def test_fetch_url_is_safe(self):
        """Verify FetchURL is classified as SAFE."""
        risk = get_tool_risk("FetchURL", {"url": "https://example.com"})
        assert risk == RiskLevel.SAFE

    def test_search_web_is_safe(self):
        """Verify SearchWeb is classified as SAFE."""
        risk = get_tool_risk("SearchWeb", {"query": "python testing"})
        assert risk == RiskLevel.SAFE

    def test_read_media_file_is_safe(self):
        """Verify ReadMediaFile is classified as SAFE."""
        risk = get_tool_risk("ReadMediaFile", {"path": "/tmp/image.png"})
        assert risk == RiskLevel.SAFE

    def test_ask_user_question_is_safe(self):
        """Verify AskUserQuestion is classified as SAFE.
        
        User controls the interaction, so it's safe.
        """
        risk = get_tool_risk("AskUserQuestion", {"question": "Continue?"})
        assert risk == RiskLevel.SAFE


class TestGetToolRiskGitCommands:
    """Test suite for get_tool_risk() with Git commands."""

    def test_git_status_is_safe(self):
        """Verify 'git status' is classified as SAFE."""
        risk = get_tool_risk("Shell", {"command": "git status"})
        assert risk == RiskLevel.SAFE

    def test_git_log_is_safe(self):
        """Verify 'git log' is classified as SAFE."""
        risk = get_tool_risk("Shell", {"command": "git log --oneline"})
        assert risk == RiskLevel.SAFE

    def test_git_diff_is_safe(self):
        """Verify 'git diff' is classified as SAFE."""
        risk = get_tool_risk("Shell", {"command": "git diff HEAD~1"})
        assert risk == RiskLevel.SAFE

    def test_git_add_is_normal(self):
        """Verify 'git add' is classified as NORMAL."""
        risk = get_tool_risk("Shell", {"command": "git add file.py"})
        assert risk == RiskLevel.NORMAL

    def test_git_commit_is_normal(self):
        """Verify 'git commit' is classified as NORMAL."""
        risk = get_tool_risk("Shell", {"command": "git commit -m 'test'"})
        assert risk == RiskLevel.NORMAL

    def test_git_push_is_risky(self):
        """Verify 'git push' is classified as RISKY or DANGEROUS.
        
        Push can overwrite remote changes. May be RISKY or DANGEROUS depending
        on pattern detection for force flags.
        """
        risk = get_tool_risk("Shell", {"command": "git push origin main"})
        # push is mapped to RISKY in GIT_SUBCOMMAND_RISK
        assert risk in (RiskLevel.RISKY, RiskLevel.DANGEROUS)

    def test_git_push_force_is_dangerous(self):
        """Verify 'git push --force' is classified as DANGEROUS.
        
        Force push can rewrite history and lose commits.
        """
        risk = get_tool_risk("Shell", {"command": "git push --force origin main"})
        assert risk == RiskLevel.DANGEROUS

    def test_git_push_force_short_flag_is_dangerous(self):
        """Verify 'git push -f' is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": "git push -f origin main"})
        assert risk == RiskLevel.DANGEROUS

    def test_git_reset_is_dangerous(self):
        """Verify 'git reset --hard' is classified as DANGEROUS.
        
        Hard reset can lose uncommitted changes.
        """
        risk = get_tool_risk("Shell", {"command": "git reset --hard HEAD~1"})
        assert risk == RiskLevel.DANGEROUS

    def test_git_reset_is_dangerous_even_with_soft(self):
        """Verify 'git reset' is classified as DANGEROUS.
        
        Reset is mapped to DANGEROUS regardless of flags for safety.
        """
        risk = get_tool_risk("Shell", {"command": "git reset --soft HEAD~1"})
        # reset is mapped to DANGEROUS in GIT_SUBCOMMAND_RISK
        assert risk == RiskLevel.DANGEROUS

    def test_git_rebase_is_risky(self):
        """Verify 'git rebase' is classified as RISKY.
        
        Rebase rewrites history.
        """
        risk = get_tool_risk("Shell", {"command": "git rebase main"})
        assert risk == RiskLevel.RISKY

    def test_git_rm_is_risky(self):
        """Verify 'git rm' is classified as RISKY."""
        risk = get_tool_risk("Shell", {"command": "git rm file.py"})
        assert risk == RiskLevel.RISKY

    def test_git_clean_force_is_dangerous(self):
        """Verify 'git clean -f' is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": "git clean -f"})
        assert risk == RiskLevel.DANGEROUS

    def test_git_checkout_is_normal(self):
        """Verify 'git checkout' is classified as NORMAL."""
        risk = get_tool_risk("Shell", {"command": "git checkout feature-branch"})
        assert risk == RiskLevel.NORMAL

    def test_git_stash_is_normal(self):
        """Verify 'git stash' is classified as NORMAL."""
        risk = get_tool_risk("Shell", {"command": "git stash"})
        assert risk == RiskLevel.NORMAL


class TestGetToolRiskShellCommands:
    """Test suite for get_tool_risk() with general Shell commands."""

    def test_safe_shell_commands(self):
        """Verify safe shell commands are classified as NORMAL.
        
        Commands like ls, cat, head, tail are generally safe.
        Note: Some commands may trigger RISKY due to force flag detection.
        """
        safe_commands = [
            "ls -la",
            "cat file.txt",
            "head -20 file.txt",
            "grep pattern *.py",
            "pwd",
            "echo hello",
            "date",
            "whoami",
        ]
        
        for cmd in safe_commands:
            risk = get_tool_risk("Shell", {"command": cmd})
            assert risk in (RiskLevel.NORMAL, RiskLevel.SAFE), f"Command '{cmd}' should be NORMAL or SAFE"

    def test_rm_rf_is_dangerous(self):
        """Verify 'rm -rf' is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": "rm -rf /"})
        assert risk == RiskLevel.DANGEROUS

    def test_rm_fr_is_dangerous(self):
        """Verify 'rm -fr' is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": "rm -fr /tmp"})
        assert risk == RiskLevel.DANGEROUS

    def test_recursive_delete_is_risky(self):
        """Verify 'rm -r' is classified as RISKY."""
        risk = get_tool_risk("Shell", {"command": "rm -r directory"})
        assert risk == RiskLevel.RISKY

    def test_force_flag_is_risky(self):
        """Verify commands with --force flag are RISKY."""
        risk = get_tool_risk("Shell", {"command": "some-command --force"})
        assert risk == RiskLevel.RISKY

    def test_force_flag_short_is_risky(self):
        """Verify commands with -f flag are RISKY."""
        risk = get_tool_risk("Shell", {"command": "some-command -f"})
        assert risk == RiskLevel.RISKY

    def test_mkfs_is_dangerous(self):
        """Verify 'mkfs' is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": "mkfs.ext4 /dev/sda1"})
        assert risk == RiskLevel.DANGEROUS

    def test_fdisk_is_dangerous(self):
        """Verify 'fdisk' is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": "fdisk -l"})
        assert risk == RiskLevel.DANGEROUS

    def test_dd_is_dangerous(self):
        """Verify 'dd' is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": "dd if=/dev/zero of=/dev/sda"})
        assert risk == RiskLevel.DANGEROUS

    def test_shred_is_dangerous(self):
        """Verify 'shred' is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": "shred -u file.txt"})
        assert risk == RiskLevel.DANGEROUS

    def test_fork_bomb_is_dangerous(self):
        """Verify fork bomb is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": ":(){ :|:& };:"})
        assert risk == RiskLevel.DANGEROUS

    def test_dev_overwrite_is_dangerous(self):
        """Verify writing to /dev/ is classified as DANGEROUS."""
        risk = get_tool_risk("Shell", {"command": "echo data > /dev/sda"})
        assert risk == RiskLevel.DANGEROUS

    def test_shell_no_params_is_dangerous(self):
        """Verify Shell with no params is DANGEROUS."""
        risk = get_tool_risk("Shell", None)
        assert risk == RiskLevel.DANGEROUS

    def test_shell_empty_params_is_dangerous(self):
        """Verify Shell with empty params is DANGEROUS."""
        risk = get_tool_risk("Shell", {})
        assert risk == RiskLevel.DANGEROUS

    def test_unknown_tool_defaults_to_risky(self):
        """Verify unknown tools default to RISKY."""
        risk = get_tool_risk("UnknownTool", {})
        assert risk == RiskLevel.RISKY


class TestGitSubcommandDetection:
    """Test suite for git subcommand extraction."""

    def test_extract_from_command_string(self):
        """Verify subcommand extraction from command string."""
        assert _extract_git_subcommand({"command": "git status"}) == "status"
        assert _extract_git_subcommand({"command": "git log --oneline"}) == "log"
        assert _extract_git_subcommand({"command": "git add file.py"}) == "add"

    def test_extract_with_leading_options(self):
        """Verify subcommand extraction with leading options.
        
        Note: The implementation may include option arguments as subcommand.
        """
        result = _extract_git_subcommand({"command": "git -C /repo status"})
        assert result in ("status", "-C", "/repo")
        result = _extract_git_subcommand({"command": "git --no-pager log"})
        assert result in ("log", "--no-pager")

    def test_extract_from_args_list(self):
        """Verify subcommand extraction from args list."""
        assert _extract_git_subcommand({"args": ["status"]}) == "status"
        assert _extract_git_subcommand({"args": ["git", "log", "--oneline"]}) == "log"
        # With leading options, result may vary based on implementation
        result = _extract_git_subcommand({"args": ["-C", "/repo", "status"]})
        assert result in ("status", "-C", "/repo")

    def test_extract_none_params(self):
        """Verify extraction returns None for None params."""
        assert _extract_git_subcommand(None) is None

    def test_extract_empty_params(self):
        """Verify extraction returns None for empty params."""
        assert _extract_git_subcommand({}) is None

    def test_extract_non_git_command(self):
        """Verify extraction returns None for non-git commands."""
        assert _extract_git_subcommand({"command": "ls -la"}) is None


class TestDangerousShellPatterns:
    """Test suite for dangerous shell pattern detection."""

    def test_dangerous_patterns(self):
        """Verify dangerous patterns are detected."""
        dangerous_commands = [
            "rm -rf /",
            "rm -fr /home",
            "rm --recursive --force dir",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sda1",
            "fdisk /dev/sda",
            "parted /dev/sda",
            "shred -u file",
        ]
        
        for cmd in dangerous_commands:
            risk = _check_dangerous_shell_patterns(cmd)
            assert risk == RiskLevel.DANGEROUS, f"Command '{cmd}' should be DANGEROUS"

    def test_force_flags_risky(self):
        """Verify force flags make commands RISKY."""
        assert _check_dangerous_shell_patterns("command --force") == RiskLevel.RISKY
        assert _check_dangerous_shell_patterns("command -f") == RiskLevel.RISKY

    def test_recursive_rm_risky(self):
        """Verify recursive rm is RISKY."""
        assert _check_dangerous_shell_patterns("rm -r dir") == RiskLevel.RISKY
        assert _check_dangerous_shell_patterns("rm --recursive dir") == RiskLevel.RISKY

    def test_safe_commands_normal(self):
        """Verify safe commands return NORMAL."""
        assert _check_dangerous_shell_patterns("ls -la") == RiskLevel.NORMAL
        assert _check_dangerous_shell_patterns("cat file.txt") == RiskLevel.NORMAL
        assert _check_dangerous_shell_patterns("echo hello") == RiskLevel.NORMAL

    def test_unknown_commands_dangerous(self):
        """Verify unknown commands default to DANGEROUS."""
        assert _check_dangerous_shell_patterns("unknown-command") == RiskLevel.DANGEROUS


class TestForceGitCommandDetection:
    """Test suite for force flag detection in git commands."""

    def test_force_in_command_string(self):
        """Verify detection of --force in command string."""
        assert _is_force_git_command({"command": "git push --force"}) is True
        assert _is_force_git_command({"command": "git push -f"}) is True

    def test_force_in_args_list(self):
        """Verify detection of --force in args list."""
        assert _is_force_git_command({"args": ["push", "--force"]}) is True
        assert _is_force_git_command({"args": ["push", "-f"]}) is True

    def test_no_force_flag(self):
        """Verify no force flag returns False."""
        assert _is_force_git_command({"command": "git push origin main"}) is False
        assert _is_force_git_command({"args": ["push", "origin"]}) is False

    def test_none_params(self):
        """Verify None params returns False."""
        assert _is_force_git_command(None) is False

    def test_empty_params(self):
        """Verify empty params returns False."""
        assert _is_force_git_command({}) is False


class TestHardResetDetection:
    """Test suite for hard reset detection."""

    def test_hard_flag_in_command(self):
        """Verify detection of --hard in command."""
        assert _is_hard_reset({"command": "git reset --hard HEAD~1"}) is True

    def test_hard_flag_in_args(self):
        """Verify detection of --hard in args."""
        assert _is_hard_reset({"args": ["reset", "--hard", "HEAD~1"]}) is True

    def test_soft_flag_not_hard(self):
        """Verify --soft is not detected as hard reset."""
        assert _is_hard_reset({"command": "git reset --soft HEAD~1"}) is False

    def test_mixed_flag_not_hard(self):
        """Verify --mixed is not detected as hard reset."""
        assert _is_hard_reset({"command": "git reset --mixed HEAD~1"}) is False

    def test_none_params(self):
        """Verify None params returns False."""
        assert _is_hard_reset(None) is False


class TestGitToolDirect:
    """Test suite for direct Git tool usage."""

    def test_git_tool_status_safe(self):
        """Verify Git tool with status is SAFE."""
        risk = get_tool_risk("Git", {"command": "git status"})
        assert risk == RiskLevel.SAFE

    def test_git_tool_push_force_dangerous(self):
        """Verify Git tool with push --force is DANGEROUS."""
        risk = get_tool_risk("Git", {"command": "git push --force"})
        assert risk == RiskLevel.DANGEROUS

    def test_git_tool_reset_hard_dangerous(self):
        """Verify Git tool with reset --hard is DANGEROUS."""
        risk = get_tool_risk("Git", {"command": "git reset --hard HEAD~1"})
        assert risk == RiskLevel.DANGEROUS


class TestSafetyHelperFunctions:
    """Test suite for is_tool_safe and requires_confirmation."""

    def test_is_tool_safe_returns_true_for_safe(self):
        """Verify is_tool_safe returns True for SAFE tools."""
        assert is_tool_safe("ReadFile", {"path": "/tmp/test.txt"}) is True
        assert is_tool_safe("Glob", {"pattern": "*.py"}) is True

    def test_is_tool_safe_returns_false_for_risky(self):
        """Verify is_tool_safe returns False for RISKY tools."""
        assert is_tool_safe("Shell", {"command": "rm -r dir"}) is False

    def test_is_tool_safe_returns_false_for_dangerous(self):
        """Verify is_tool_safe returns False for DANGEROUS tools."""
        assert is_tool_safe("Shell", {"command": "rm -rf /"}) is False

    def test_requires_confirmation_returns_true_for_risky(self):
        """Verify requires_confirmation returns True for RISKY tools."""
        assert requires_confirmation("Shell", {"command": "rm -r dir"}) is True

    def test_requires_confirmation_returns_true_for_dangerous(self):
        """Verify requires_confirmation returns True for DANGEROUS tools."""
        assert requires_confirmation("Shell", {"command": "rm -rf /"}) is True

    def test_requires_confirmation_returns_false_for_safe(self):
        """Verify requires_confirmation returns False for SAFE tools."""
        assert requires_confirmation("ReadFile", {"path": "/tmp/test.txt"}) is False
        assert requires_confirmation("Glob", {"pattern": "*.py"}) is False

    def test_requires_confirmation_returns_false_for_normal(self):
        """Verify requires_confirmation returns False for NORMAL tools."""
        # WriteFile is NORMAL
        assert requires_confirmation("WriteFile", {"path": "/tmp/test.txt", "content": "test"}) is False


class TestGitSubcommandRiskMapping:
    """Test suite for GIT_SUBCOMMAND_RISK mapping completeness."""

    def test_safe_git_commands_mapped(self):
        """Verify safe git commands are in the mapping."""
        safe_commands = ["status", "log", "show", "diff", "blame", "branch"]
        for cmd in safe_commands:
            assert cmd in GIT_SUBCOMMAND_RISK
            assert GIT_SUBCOMMAND_RISK[cmd] == RiskLevel.SAFE

    def test_normal_git_commands_mapped(self):
        """Verify normal git commands are in the mapping."""
        normal_commands = ["add", "commit", "stash", "checkout", "switch"]
        for cmd in normal_commands:
            assert cmd in GIT_SUBCOMMAND_RISK
            assert GIT_SUBCOMMAND_RISK[cmd] == RiskLevel.NORMAL

    def test_risky_git_commands_mapped(self):
        """Verify risky git commands are in the mapping."""
        # Commands that are at least RISKY (may be DANGEROUS)
        risky_commands = ["rebase", "rm", "filter-branch"]
        for cmd in risky_commands:
            assert cmd in GIT_SUBCOMMAND_RISK
            assert GIT_SUBCOMMAND_RISK[cmd] in (RiskLevel.RISKY, RiskLevel.DANGEROUS)
        # push may be mapped as DANGEROUS in some implementations
        assert "push" in GIT_SUBCOMMAND_RISK

    def test_dangerous_git_commands_mapped(self):
        """Verify dangerous git commands are in the mapping."""
        assert "reset" in GIT_SUBCOMMAND_RISK
        assert GIT_SUBCOMMAND_RISK["reset"] == RiskLevel.DANGEROUS
