"""Risk classification for tool execution.

This module provides risk classification for tools to enable safety decisions
in the execution environment. Each tool is mapped to a risk level based on
its potential impact on the system, data, or environment.

Risk Levels:
    SAFE: Read-only operations with no side effects
    NORMAL: Standard operations with minimal risk
    RISKY: Destructive operations that can modify or delete data
    DANGEROUS: Operations that can cause irreversible data loss or system damage

Example:
    >>> from aider.tools.risk import get_tool_risk, RiskLevel
    >>> get_tool_risk("ReadFile", {"path": "/tmp/test.txt"})
    <RiskLevel.SAFE: 1>
    >>> get_tool_risk("Shell", {"command": "rm -rf /"})
    <RiskLevel.DANGEROUS: 4>
"""

from enum import Enum, auto
from typing import Optional


class RiskLevel(Enum):
    """Risk levels for tool execution.

    The risk levels are ordered from least to most dangerous:

    Attributes:
        SAFE: Read-only operations with no side effects.
            Examples: reading files, listing directories, getting system info
        NORMAL: Standard operations with minimal risk.
            Examples: writing to existing files, creating new files
        RISKY: Destructive operations that can modify or delete data.
            Examples: deleting files, force operations, moving files
        DANGEROUS: Operations that can cause irreversible data loss or system damage.
            Examples: git reset, force pushes, recursive deletes, system modifications
    """

    SAFE = auto()  # Read-only operations
    NORMAL = auto()  # Standard operations
    RISKY = auto()  # Destructive operations
    DANGEROUS = auto()  # Irreversible data loss possible


# Tool to risk level mapping
# Maps tool names to their base risk level
# Tool names use lowercase_with_underscores to match router.py
TOOL_RISK_LEVELS: dict[str, RiskLevel] = {
    # File operations - Read (SAFE)
    "read_file": RiskLevel.SAFE,
    "glob": RiskLevel.SAFE,
    "grep": RiskLevel.SAFE,
    # File operations - Write (NORMAL)
    "write_file": RiskLevel.NORMAL,
    "str_replace_file": RiskLevel.NORMAL,
    # Information gathering (SAFE)
    "fetch_url": RiskLevel.SAFE,
    "search_web": RiskLevel.SAFE,
    "read_media_file": RiskLevel.SAFE,
    # User interaction (SAFE - user controls the interaction)
    "ask_user_question": RiskLevel.SAFE,
    # Aider-specific tools
    "ls": RiskLevel.SAFE,
    "search": RiskLevel.SAFE,
    "add": RiskLevel.NORMAL,
    "drop": RiskLevel.NORMAL,
    "git": RiskLevel.RISKY,  # Depends on subcommand
    "commit": RiskLevel.RISKY,
    # Shell - base level is DANGEROUS due to unrestricted power
    # Subcommands are analyzed separately for Shell
    "run": RiskLevel.DANGEROUS,
    "shell": RiskLevel.DANGEROUS,
}

# Git subcommand risk mapping
# Maps git subcommands to their risk level
GIT_SUBCOMMAND_RISK: dict[str, RiskLevel] = {
    # Information/Read-only commands (SAFE)
    "status": RiskLevel.SAFE,
    "log": RiskLevel.SAFE,
    "show": RiskLevel.SAFE,
    "diff": RiskLevel.SAFE,
    "blame": RiskLevel.SAFE,
    "branch": RiskLevel.SAFE,  # listing branches
    "tag": RiskLevel.SAFE,  # listing tags
    "remote": RiskLevel.SAFE,  # listing remotes
    "config": RiskLevel.SAFE,  # reading config (git config --get)
    "ls-files": RiskLevel.SAFE,
    "ls-remote": RiskLevel.SAFE,
    "cat-file": RiskLevel.SAFE,
    "rev-parse": RiskLevel.SAFE,
    "describe": RiskLevel.SAFE,
    # Standard operations (NORMAL)
    "add": RiskLevel.NORMAL,
    "commit": RiskLevel.NORMAL,
    "stash": RiskLevel.NORMAL,  # stashing changes
    "checkout": RiskLevel.NORMAL,  # switching branches (safe if no uncommitted changes)
    "switch": RiskLevel.NORMAL,
    "restore": RiskLevel.NORMAL,  # restoring working tree files
    "clean": RiskLevel.NORMAL,  # with -n (dry-run) is safe, without is RISKY
    "mv": RiskLevel.NORMAL,
    "rm": RiskLevel.RISKY,  # removing tracked files
    "merge": RiskLevel.NORMAL,
    "pull": RiskLevel.NORMAL,
    "fetch": RiskLevel.NORMAL,
    "push": RiskLevel.RISKY,  # can overwrite remote
    "rebase": RiskLevel.RISKY,  # rewriting history
    "cherry-pick": RiskLevel.NORMAL,
    "apply": RiskLevel.NORMAL,  # applying patches
    "am": RiskLevel.NORMAL,  # applying mailbox patches
    "bisect": RiskLevel.NORMAL,
    "worktree": RiskLevel.NORMAL,
    "submodule": RiskLevel.NORMAL,
    # Destructive/Risky operations (RISKY)
    "filter-branch": RiskLevel.RISKY,
    "filter-repo": RiskLevel.RISKY,
    "gc": RiskLevel.RISKY,  # garbage collection
    "prune": RiskLevel.RISKY,  # pruning unreachable objects
    "reflog": RiskLevel.RISKY,  # expire reflog
    "update-ref": RiskLevel.RISKY,
    "symbolic-ref": RiskLevel.RISKY,
    # Dangerous operations (DANGEROUS)
    "reset": RiskLevel.DANGEROUS,  # can lose commits
    "revert": RiskLevel.DANGEROUS,  # creating inverse commits can be confusing
    # push and clean risk is handled dynamically by force-flag checks in get_tool_risk
}

# Shell command patterns that indicate high risk
DANGEROUS_SHELL_PATTERNS: list[str] = [
    "rm -rf",
    "rm -fr",
    "rm --recursive --force",
    "> /dev/",
    "dd if=",
    "mkfs",
    "fdisk",
    "parted",
    "shred",
    ":(){ :|:& };:",  # fork bomb
]

# Shell commands that are generally safe
SAFE_SHELL_COMMANDS: set[str] = {
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "find",
    "echo",
    "pwd",
    "which",
    "whoami",
    "date",
    "uname",
    "wc",
    "sort",
    "uniq",
    "diff",
    "file",
    "stat",
}


def _extract_git_subcommand(params: Optional[dict]) -> Optional[str]:
    """Extract the git subcommand from parameters.

    Args:
        params: Tool parameters dictionary containing the command or arguments.

    Returns:
        The git subcommand if found, None otherwise.

    Example:
        >>> _extract_git_subcommand({"command": "git status"})
        'status'
        >>> _extract_git_subcommand({"args": ["status", "--short"]})
        'status'
        >>> _extract_git_subcommand({"command": "ls -la"})
        None
    """
    if params is None:
        return None

    # Check for direct command string
    command = params.get("command", "")
    if command:
        parts = command.strip().split()
        # Must start with "git" to be a git command
        if len(parts) < 1 or parts[0] != "git":
            return None
        # Skip leading "git" prefix, find the first non-option subcommand
        for part in parts[1:]:
            if not part.startswith("-"):
                return part

    # Check for args list
    args = params.get("args", [])
    if args and len(args) >= 1:
        # Skip git binary name if present
        start_idx = 0
        if args[0] == "git":
            start_idx = 1
        # Find first non-option argument
        for arg in args[start_idx:]:
            if not arg.startswith("-"):
                return arg

    return None


def _check_dangerous_shell_patterns(command: str) -> RiskLevel:
    """Check if a shell command contains dangerous patterns.

    Args:
        command: The shell command to check.

    Returns:
        DANGEROUS if dangerous patterns found, RISKY if potentially risky,
        otherwise the base risk level for shell commands.
    """
    command_lower = command.lower()

    # Check for dangerous patterns
    for pattern in DANGEROUS_SHELL_PATTERNS:
        if pattern in command_lower:
            return RiskLevel.DANGEROUS

    # Check for force flags
    force_flags = [" -f", " --force", "--force ", " -f ", "'--force'", '"--force"']
    if any(flag in command for flag in force_flags):
        return RiskLevel.RISKY

    # Check for recursive deletion
    if "rm" in command_lower and (" -r" in command or " --recursive" in command):
        return RiskLevel.RISKY

    # Check for safe commands
    parts = command.strip().split()
    if parts:
        base_cmd = parts[0].lower()
        if base_cmd in SAFE_SHELL_COMMANDS:
            return RiskLevel.NORMAL

    return RiskLevel.DANGEROUS


def _is_force_git_command(params: Optional[dict]) -> bool:
    """Check if a git command includes force flags.

    Args:
        params: Tool parameters dictionary.

    Returns:
        True if the command includes force flags, False otherwise.
    """
    if params is None:
        return False

    command = params.get("command", "")
    args = params.get("args", [])

    # Check in command string
    if "--force" in command or " -f" in command:
        return True

    # Check in args list
    if "--force" in args or "-f" in args:
        return True

    return False


def _is_hard_reset(params: Optional[dict]) -> bool:
    """Check if a git reset command is a hard reset.

    Args:
        params: Tool parameters.

    Returns:
        True if it's a hard reset, False otherwise.
    """
    if params is None:
        return False

    command = params.get("command", "")
    args = params.get("args", [])

    # Check for --hard in command or args
    if "--hard" in command or "--hard" in args:
        return True

    return False


def get_tool_risk(tool_name: str, params: Optional[dict] = None) -> RiskLevel:
    """Get the risk level for a tool call.

        This function determines the risk level of a tool execution based on the
    tool name and its parameters. For most tools, it returns a pre-defined base
    risk level. For tools like Shell and Git commands, it performs additional
    analysis of the parameters to determine the actual risk.

        Args:
            tool_name: Name of the tool to check.
            params: Optional dictionary of tool parameters. Used for dynamic
                risk assessment based on command arguments, flags, etc.

        Returns:
            The RiskLevel enum value for this tool call.

        Examples:
            >>> get_tool_risk("read_file")
            <RiskLevel.SAFE: 1>

            >>> get_tool_risk("run", {"command": "ls -la"})
            <RiskLevel.NORMAL: 2>

            >>> get_tool_risk("run", {"command": "git status"})
            <RiskLevel.SAFE: 1>

            >>> get_tool_risk("run", {"command": "rm -rf /"})
            <RiskLevel.DANGEROUS: 4>

            >>> get_tool_risk("run", {"command": "git reset --hard HEAD"})
            <RiskLevel.DANGEROUS: 4>
    """
    # Normalize tool name: convert CamelCase to snake_case and lowercase
    # This handles both "ReadFile" and "read_file" style names
    import re

    def camel_to_snake(name: str) -> str:
        """Convert CamelCase to snake_case, handling consecutive capitals."""
        # Insert _ between lowercase/number and uppercase
        s1 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
        # Insert _ between consecutive capitals followed by lowercase
        s2 = re.sub("([A-Z]+)([A-Z][a-z])", r"\1_\2", s1)
        return s2.lower()

    normalized = camel_to_snake(tool_name)

    # Also try simple lowercase as fallback (for "shell" vs "Shell")
    simple_lower = tool_name.lower()

    # Try normalized first, then simple lowercase, then original, default to RISKY
    base_risk = TOOL_RISK_LEVELS.get(normalized)
    if base_risk is None:
        base_risk = TOOL_RISK_LEVELS.get(simple_lower)
    if base_risk is None:
        base_risk = TOOL_RISK_LEVELS.get(tool_name, RiskLevel.RISKY)

    # Special handling for Shell/run tool
    if normalized in ("shell", "run"):
        if params is None:
            return RiskLevel.DANGEROUS

        command = params.get("command", "")

        # Check if it's a git command
        if command.strip().startswith("git "):
            subcommand = _extract_git_subcommand(params)
            if subcommand:
                risk = GIT_SUBCOMMAND_RISK.get(subcommand, RiskLevel.NORMAL)

                # Check for force flags that elevate risk
                if _is_force_git_command(params):
                    if subcommand in ("push", "clean"):
                        return RiskLevel.DANGEROUS
                    return RiskLevel.RISKY

                # Check for hard reset
                if subcommand == "reset" and _is_hard_reset(params):
                    return RiskLevel.DANGEROUS

                return risk

        # Analyze shell command for dangerous patterns
        return _check_dangerous_shell_patterns(command)

    # For git subcommand analysis (if tool is specifically for git)
    if normalized == "git":
        subcommand = _extract_git_subcommand(params)
        if subcommand:
            risk = GIT_SUBCOMMAND_RISK.get(subcommand, RiskLevel.NORMAL)

            # Check for force flags
            if _is_force_git_command(params):
                if subcommand in ("push", "clean"):
                    return RiskLevel.DANGEROUS
                return RiskLevel.RISKY

            # Check for hard reset
            if subcommand == "reset" and _is_hard_reset(params):
                return RiskLevel.DANGEROUS

            return risk

    return base_risk


def is_tool_safe(tool_name: str, params: Optional[dict] = None) -> bool:
    """Check if a tool is safe to execute without confirmation.

    Args:
        tool_name: Name of the tool.
        params: Optional tool parameters.

    Returns:
        True if the tool is SAFE, False otherwise.
    """
    return get_tool_risk(tool_name, params) == RiskLevel.SAFE


def requires_confirmation(tool_name: str, params: Optional[dict] = None) -> bool:
    """Check if a tool requires user confirmation before execution.

    Args:
        tool_name: Name of the tool.
        params: Optional tool parameters.

    Returns:
        True if the tool is RISKY or DANGEROUS, False otherwise.
    """
    risk = get_tool_risk(tool_name, params)
    return risk in (RiskLevel.RISKY, RiskLevel.DANGEROUS)
