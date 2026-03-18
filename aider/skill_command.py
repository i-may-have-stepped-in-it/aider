#!/usr/bin/env python3
"""
Skill Command - Aider command integration for OpenClaw skills.

Adds the `/skill` command to Aider, enabling:
- List available OpenClaw skills
- Run specific skills with arguments
- Show skill help and metadata
- Validate skill configuration
"""

import argparse
import json
import logging
import shlex
from pathlib import Path
from typing import List, Optional, Tuple

from aider.openclaw_bridge import OpenClawBridge, SkillExecutionResult

logger = logging.getLogger(__name__)


class SkillCommand:
    """
    Aider command integration for OpenClaw skills.

    This class provides the `/skill` command implementation that can be
    integrated into Aider's Commands class.
    """

    def __init__(self, io, coder=None, bridge: Optional[OpenClawBridge] = None):
        """
        Initialize the skill command.

        Args:
            io: Aider's IO object for output.
            coder: Optional Aider coder instance.
            bridge: Optional OpenClawBridge instance.
        """
        self.io = io
        self.coder = coder
        self.bridge = bridge or OpenClawBridge()

        # Command parser for subcommands
        self.parser = self._create_parser()

    def _create_parser(self) -> argparse.ArgumentParser:
        """Create the argument parser for skill subcommands."""
        parser = argparse.ArgumentParser(
            prog="/skill",
            description="Manage and execute OpenClaw skills",
            add_help=False,
        )

        subparsers = parser.add_subparsers(dest="action", help="Action to perform")

        # list subcommand
        list_parser = subparsers.add_parser("list", help="List available skills")
        list_parser.add_argument("--category", "-c", help="Filter by category")
        list_parser.add_argument(
            "--verbose", "-v", action="store_true", help="Show detailed information"
        )

        # run subcommand
        run_parser = subparsers.add_parser("run", help="Run a skill")
        run_parser.add_argument("skill", help="Name of the skill to run")
        run_parser.add_argument(
            "action", nargs="?", default="run", help="Action to perform (default: run)"
        )
        run_parser.add_argument("args", nargs="*", help="Additional arguments for the skill")
        run_parser.add_argument(
            "--timeout", "-t", type=int, default=300, help="Timeout in seconds (default: 300)"
        )

        # info subcommand
        info_parser = subparsers.add_parser("info", help="Show skill information")
        info_parser.add_argument("skill", help="Name of the skill")
        info_parser.add_argument("--json", action="store_true", help="Output as JSON")

        # validate subcommand
        validate_parser = subparsers.add_parser("validate", help="Validate skill configuration")
        validate_parser.add_argument(
            "skill", nargs="?", help="Name of the skill (if omitted, validates all)"
        )

        # search subcommand
        search_parser = subparsers.add_parser("search", help="Search for skills")
        search_parser.add_argument("query", help="Search query")

        # scripts subcommand
        scripts_parser = subparsers.add_parser("scripts", help="List available scripts for a skill")
        scripts_parser.add_argument("skill", help="Name of the skill")

        return parser

    def cmd_skill(self, args_str: str) -> None:
        """
        Execute the /skill command.

        This method should be called from Aider's Commands class.
        The method signature matches Aider's command pattern.

        Args:
            args_str: Command arguments as a string.
        """
        if not args_str.strip():
            self._show_help()
            return

        try:
            # Parse arguments
            args_list = shlex.split(args_str)
            args = self.parser.parse_args(args_list)
        except SystemExit:
            # argparse calls sys.exit on error or --help
            return

        # Dispatch to appropriate handler
        if args.action == "list":
            self._cmd_list(args)
        elif args.action == "run":
            self._cmd_run(args)
        elif args.action == "info":
            self._cmd_info(args)
        elif args.action == "validate":
            self._cmd_validate(args)
        elif args.action == "search":
            self._cmd_search(args)
        elif args.action == "scripts":
            self._cmd_scripts(args)
        else:
            self._show_help()

    def _show_help(self) -> None:
        """Display help information."""
        self.io.tool_output("Usage: /skill <action> [options]")
        self.io.tool_output("")
        self.io.tool_output("Actions:")
        self.io.tool_output("  list              List available OpenClaw skills")
        self.io.tool_output("  run <skill>       Run a skill with optional arguments")
        self.io.tool_output("  info <skill>      Show detailed skill information")
        self.io.tool_output("  validate [skill]  Validate skill configuration")
        self.io.tool_output("  search <query>    Search for skills by keyword")
        self.io.tool_output("  scripts <skill>   List available scripts for a skill")
        self.io.tool_output("")
        self.io.tool_output("Examples:")
        self.io.tool_output("  /skill list")
        self.io.tool_output("  /skill list --verbose")
        self.io.tool_output("  /skill run github pr-list")
        self.io.tool_output("  /skill info kimi")
        self.io.tool_output("  /skill search git")

    def _cmd_list(self, args) -> None:
        """Handle the list subcommand."""
        try:
            skills = self.bridge.list_skills(category=args.category)
        except Exception as e:
            self.io.tool_error(f"Error listing skills: {e}")
            return

        if not skills:
            self.io.tool_output("No OpenClaw skills found.")
            return

        self.io.tool_output(f"\n📦 Available OpenClaw Skills ({len(skills)}):\n")

        for metadata in skills:
            if args.verbose:
                # Detailed view
                self.io.tool_output(f"{metadata.full_name}")
                self.io.tool_output(f"  Description: {metadata.description}")
                if metadata.homepage:
                    self.io.tool_output(f"  Homepage: {metadata.homepage}")

                # Show requirements
                if metadata.requires:
                    bins = metadata.requires.get("bins", [])
                    if bins:
                        self.io.tool_output(f"  Requires: {', '.join(bins)}")

                # Show install options
                if metadata.install:
                    self.io.tool_output(f"  Install options: {len(metadata.install)}")

                self.io.tool_output("")
            else:
                # Simple view
                desc = (
                    metadata.description[:60] + "..."
                    if len(metadata.description) > 60
                    else metadata.description
                )
                self.io.tool_output(f"  {metadata.full_name:<25} - {desc}")

        if not args.verbose:
            self.io.tool_output("\nUse '/skill list --verbose' for detailed information.")
            self.io.tool_output("Use '/skill info <skill>' for full details on a specific skill.")

    def _cmd_run(self, args) -> None:
        """Handle the run subcommand."""
        skill_name = args.skill
        action = args.action
        skill_args = args.args
        timeout = args.timeout

        # Check skill exists
        if not self.bridge.get_skill_path(skill_name):
            self.io.tool_error(f"Skill '{skill_name}' not found.")
            self.io.tool_output("\nUse '/skill list' to see available skills.")
            return

        # Show what we're about to do
        self.io.tool_output(f"\n▶ Running skill: {skill_name}")
        self.io.tool_output(f"  Action: {action}")
        if skill_args:
            self.io.tool_output(f"  Args: {' '.join(skill_args)}")

        # Execute
        try:
            result = self.bridge.execute_skill(
                skill_name=skill_name,
                action=action,
                args=skill_args,
                timeout=timeout,
            )
        except Exception as e:
            self.io.tool_error(f"Error executing skill: {e}")
            return

        # Display result
        self._display_execution_result(result)

    def _cmd_info(self, args) -> None:
        """Handle the info subcommand."""
        skill_name = args.skill

        metadata = self.bridge.load_skill_metadata(skill_name)
        if not metadata:
            self.io.tool_error(f"Skill '{skill_name}' not found.")
            return

        if args.json:
            # JSON output
            info = {
                "name": metadata.name,
                "description": metadata.description,
                "emoji": metadata.emoji,
                "homepage": metadata.homepage,
                "requires": metadata.requires,
                "install": metadata.install,
            }
            self.io.tool_output(json.dumps(info, indent=2))
            return

        # Pretty output
        self.io.tool_output(f"\n{metadata.full_name}")
        self.io.tool_output("=" * 50)
        self.io.tool_output(f"\nDescription:\n  {metadata.description}")

        if metadata.homepage:
            self.io.tool_output(f"\nHomepage:\n  {metadata.homepage}")

        # Requirements
        if metadata.requires:
            self.io.tool_output("\nRequirements:")
            bins = metadata.requires.get("bins", [])
            if bins:
                for binary in bins:
                    status = "✓" if self._check_binary(binary) else "✗"
                    self.io.tool_output(f"  [{status}] {binary}")

        # Install options
        if metadata.install:
            self.io.tool_output("\nInstallation Options:")
            for install in metadata.install:
                label = install.get("label", install.get("id", "unknown"))
                kind = install.get("kind", "unknown")
                self.io.tool_output(f"  • {label} ({kind})")

        # Scripts
        scripts = self.bridge.find_skill_scripts(skill_name)
        if scripts:
            self.io.tool_output(f"\nAvailable Scripts ({len(scripts)}):")
            for script in scripts:
                self.io.tool_output(f"  • {script.name}")

        # Usage hint
        self.io.tool_output("\nUsage:")
        self.io.tool_output(f"  /skill run {skill_name} <action> [args...]")

    def _cmd_validate(self, args) -> None:
        """Handle the validate subcommand."""
        if args.skill:
            # Validate single skill
            results = [self.bridge.validate_skill(args.skill)]
        else:
            # Validate all skills
            try:
                skills = self.bridge.discover_skills()
            except Exception as e:
                self.io.tool_error(f"Error discovering skills: {e}")
                return

            self.io.tool_output(f"\n🔍 Validating {len(skills)} skills...\n")
            results = []
            for skill_name in sorted(skills.keys()):
                results.append(self.bridge.validate_skill(skill_name))

        # Display results
        valid_count = sum(1 for r in results if r["valid"])
        error_count = sum(len(r["errors"]) for r in results)
        warning_count = sum(len(r["warnings"]) for r in results)

        for result in results:
            skill = result["skill"]
            status = "✅" if result["valid"] else "❌"
            self.io.tool_output(f"{status} {skill}")

            if result["errors"]:
                for error in result["errors"]:
                    self.io.tool_output(f"   Error: {error}")

            if result["warnings"]:
                for warning in result["warnings"]:
                    self.io.tool_output(f"   Warning: {warning}")

            # Show scripts if available
            scripts = result.get("scripts", [])
            if scripts:
                self.io.tool_output(f"   Scripts: {', '.join(scripts)}")

        self.io.tool_output(f"\n{'=' * 50}")
        self.io.tool_output(f"Summary: {valid_count}/{len(results)} valid")
        self.io.tool_output(f"Errors: {error_count}, Warnings: {warning_count}")

    def _cmd_search(self, args) -> None:
        """Handle the search subcommand."""
        query = args.query

        results = self.bridge.search_skills(query)

        if not results:
            self.io.tool_output(f"No skills found matching '{query}'.")
            return

        self.io.tool_output(f"\n🔍 Search results for '{query}':\n")

        for metadata, score in results:
            relevance = int(score * 100)
            self.io.tool_output(f"  {metadata.full_name} (relevance: {relevance}%)")
            desc = (
                metadata.description[:70] + "..."
                if len(metadata.description) > 70
                else metadata.description
            )
            self.io.tool_output(f"    {desc}")

    def _cmd_scripts(self, args) -> None:
        """Handle the scripts subcommand."""
        skill_name = args.skill

        scripts = self.bridge.find_skill_scripts(skill_name)

        if not scripts:
            self.io.tool_output(f"No scripts found for skill '{skill_name}'.")
            return

        self.io.tool_output(f"\n📜 Scripts for {skill_name}:\n")

        for script in scripts:
            self.io.tool_output(f"  • {script.name}")
            # Check if executable
            if self._is_executable(script):
                self.io.tool_output("    (executable)")

    def _display_execution_result(self, result: SkillExecutionResult) -> None:
        """Display skill execution result."""
        if result.success:
            self.io.tool_output(f"\n✅ Skill executed successfully ({result.duration_ms}ms)")
        else:
            self.io.tool_error(f"\n❌ Skill failed with exit code {result.exit_code}")

        if result.stdout:
            self.io.tool_output("\n📤 Output:")
            for line in result.stdout.split("\n"):
                self.io.tool_output(f"  {line}")

        if result.stderr:
            self.io.tool_output("\n⚠️  Stderr:")
            for line in result.stderr.split("\n"):
                self.io.tool_output(f"  {line}")

        if result.error_message:
            self.io.tool_error(f"\n💥 Error: {result.error_message}")

    def _check_binary(self, binary: str) -> bool:
        """Check if a binary is available."""
        import shutil

        return shutil.which(binary) is not None

    def _is_executable(self, path: Path) -> bool:
        """Check if a file is executable."""
        import os

        return os.access(path, os.X_OK)

    # Aider command interface methods
    def completions_skill(self) -> List[Tuple[str, str]]:
        """
        Provide completions for the /skill command.

        Returns:
            List of (completion, description) tuples.
        """
        completions = []

        # Subcommands
        completions.extend(
            [
                ("list", "List available skills"),
                ("run", "Run a skill"),
                ("info", "Show skill information"),
                ("validate", "Validate skill configuration"),
                ("search", "Search for skills"),
                ("scripts", "List skill scripts"),
            ]
        )

        # Skill names
        try:
            skills = self.bridge.discover_skills()
            for skill_name in skills.keys():
                metadata = self.bridge.load_skill_metadata(skill_name)
                if metadata:
                    desc = (
                        metadata.description[:40] + "..."
                        if len(metadata.description) > 40
                        else metadata.description
                    )
                    completions.append((skill_name, desc))
        except Exception:
            pass

        return completions


def install_skill_command(commands_instance):
    """
    Install the /skill command into an Aider Commands instance.

    Usage in Aider:
        from aider.skill_command import install_skill_command

        class Commands:
            def __init__(self, ...):
                ...
                install_skill_command(self)

    Args:
        commands_instance: An instance of Aider's Commands class.
    """
    # Create skill command handler
    skill_cmd = SkillCommand(
        io=commands_instance.io,
        coder=getattr(commands_instance, "coder", None),
    )

    # Bind the command method
    commands_instance.cmd_skill = skill_cmd.cmd_skill

    # Bind completions if supported
    if hasattr(commands_instance, "completions_skill"):

        def combined_completions():
            return skill_cmd.completions_skill()

        commands_instance.completions_skill = combined_completions
    else:
        commands_instance.completions_skill = skill_cmd.completions_skill

    logger.debug("Skill command installed successfully")


# Command descriptions for Aider help
SKILL_COMMAND_HELP = """
/skill - Manage and execute OpenClaw skills

Subcommands:
  list [--verbose]           List available skills
  run <skill> [action] [args] Run a skill with arguments
  info <skill>               Show skill information
  validate [skill]           Validate skill configuration
  search <query>             Search for skills
  scripts <skill>            List skill scripts

Examples:
  /skill list
  /skill run github pr-list
  /skill info kimi
  /skill search git
"""
