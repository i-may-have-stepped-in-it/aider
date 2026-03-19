"""
Aider command integration for skills.

Extends Aider's /skill command with agent-enabled skills.
"""

import argparse
import inspect
import logging
import shlex
from typing import List, Tuple

from .base import SkillContext, _run_async_safely
from .registry import get_registry

logger = logging.getLogger(__name__)


class SkillsCommand:
    """
    Extended /skill command with agent support.

    Provides commands for running skills that can spawn sub-agents.
    """

    def __init__(self, io, coder=None, commands=None, verbose: bool = False):
        self.io = io
        self.coder = coder
        self.commands = commands
        self.verbose = verbose
        self._registry = None
        self._registry_owner = None
        self._registry_override = False
        self.parser = self._create_parser()

    def _show_usage(self, error=None):
        if self.commands and hasattr(self.commands, "show_command_usage"):
            self.commands.show_command_usage("skill", error=error)
            return
        if error:
            self.io.tool_error(error)
        self.io.tool_output("Usage: /skill list | /skill run <skill> [...] | /skill info <skill>")

    @property
    def registry(self):
        """Resolve the active skill registry dynamically from the current coder/runtime."""
        if self._registry_override:
            return self._registry

        runtime = getattr(self.coder, "runtime", None) if self.coder else None
        owner = getattr(runtime, "skill_registry", None)
        if owner is None and self.commands is not None:
            owner = getattr(self.commands, "skills_registry", None)
        if owner is None and self.coder is not None:
            owner = getattr(self.coder, "skills_registry", None)
        if owner is None:
            owner = get_registry()

        if self._registry is not None and self._registry_owner is not owner:
            self._registry = None

        if self._registry is None:
            self._registry = owner
            self._registry_owner = owner

        return self._registry

    @registry.setter
    def registry(self, value):
        """Allow direct registry injection for tests and compatibility paths."""
        self._registry = value
        self._registry_owner = value
        self._registry_override = True

    def _create_parser(self) -> argparse.ArgumentParser:
        """Create argument parser for skill commands."""
        parser = argparse.ArgumentParser(
            prog="/skill",
            description="Execute skills with optional agent support",
            add_help=False,
        )

        subparsers = parser.add_subparsers(dest="action", help="Action")

        # list
        list_parser = subparsers.add_parser("list", help="List available skills")
        list_parser.add_argument(
            "--agents", "-a", action="store_true", help="Show only agent-enabled skills"
        )
        list_parser.add_argument(
            "--verbose", "-v", action="store_true", help="Show detailed information"
        )

        # run
        run_parser = subparsers.add_parser("run", help="Run a skill")
        run_parser.add_argument("skill", help="Name of the skill to run")
        run_parser.add_argument("--files", "-f", nargs="+", help="Files to process")
        run_parser.add_argument("--model", "-m", help="Model to use")
        run_parser.add_argument(
            "--agents", action="store_true", dest="enable_agents", help="Enable sub-agents"
        )
        run_parser.add_argument(
            "--max-agents", type=int, default=5, help="Maximum concurrent agents"
        )
        run_parser.add_argument(
            "--timeout", type=float, default=300.0, help="Agent timeout in seconds"
        )
        # info
        info_parser = subparsers.add_parser("info", help="Show skill info")
        info_parser.add_argument("skill", help="Skill name")

        # search
        search_parser = subparsers.add_parser("search", help="Search skills")
        search_parser.add_argument("query", help="Search query")

        return parser

    def cmd_skill(self, args_str: str) -> None:
        """Execute the /skill command."""
        if not args_str.strip():
            self._show_usage()
            self._show_help()
            return

        try:
            args_list = shlex.split(args_str)
            args, unknown = self.parser.parse_known_args(args_list)
            args.params = unknown
        except ValueError as err:
            self._show_usage(f"Unable to parse /skill arguments: {err}")
            return
        except SystemExit:
            self._show_usage("Invalid /skill arguments.")
            return

        # Dispatch
        if args.action == "list":
            self._cmd_list(args)
        elif args.action == "run":
            _run_async_safely(self._cmd_run(args))
        elif args.action == "info":
            self._cmd_info(args)
        elif args.action == "search":
            self._cmd_search(args)
        else:
            self._show_help()

    def _show_help(self) -> None:
        """Show help information."""
        self.io.tool_output("Usage: /skill <action> [options]")
        self.io.tool_output("")
        self.io.tool_output("Actions:")
        self.io.tool_output("  list [--agents]       List available skills")
        self.io.tool_output("  run <skill> [opts]    Run a skill")
        self.io.tool_output("  info <skill>          Show skill information")
        self.io.tool_output("  search <query>        Search for skills")
        self.io.tool_output("")
        self.io.tool_output("Examples:")
        self.io.tool_output("  /skill list --agents")
        self.io.tool_output("  /skill run code-review -f auth.py models.py --agents")
        self.io.tool_output("  /skill run test-generation -f *.py --agents --max-agents 8")
        self.io.tool_output('  /skill run skill-creator name=my-linter description="Run eslint"')

    def _cmd_list(self, args) -> None:
        """Handle list command."""
        skills = self.registry.list_skills(supports_agents=args.agents if args.agents else None)

        if not skills:
            filter_msg = " (agent-enabled)" if args.agents else ""
            self.io.tool_output(f"No skills found{filter_msg}.")
            return

        filter_msg = " (agent-enabled)" if args.agents else ""
        self.io.tool_output(f"\n📦 Available Skills{filter_msg} ({len(skills)}):\n")

        for skill in skills:
            if args.verbose:
                agent_badge = "🤖" if skill["supports_agents"] else ""
                self.io.tool_output(f"{skill['name']} {agent_badge}")
                self.io.tool_output(f"  {skill['description']}")
                self.io.tool_output(f"  Version: {skill['version']}")
                if skill["supports_agents"]:
                    self.io.tool_output(f"  Max agents: {skill['max_agents']}")
                self.io.tool_output("")
            else:
                agent_badge = "🤖" if skill["supports_agents"] else "  "
                desc = (
                    skill["description"][:50] + "..."
                    if len(skill["description"]) > 50
                    else skill["description"]
                )
                self.io.tool_output(f"  {agent_badge} {skill['name']:<25} - {desc}")

        if not args.verbose:
            self.io.tool_output("\nUse '/skill list --verbose' for details.")
            self.io.tool_output("Use '/skill info <name>' for specific skill info.")

    async def _cmd_run(self, args) -> None:
        """Handle run command."""
        skill_name = args.skill
        try:
            skill_params = self._parse_skill_params(args.params)
        except ValueError as err:
            self.io.tool_error(str(err))
            self.io.tool_output(f"Use '/skill info {skill_name}' to see supported parameters.")
            return
        metadata = self.registry.get_metadata(skill_name)

        # Create context
        context = SkillContext(
            coder=self.coder,
            io=self.io,
            verbose=self.verbose,
            enable_agents=args.enable_agents,
            max_agents=args.max_agents,
            agent_timeout=args.timeout,
        )

        # Check if skill exists
        skill = self.registry.create(skill_name, context)
        if not skill or not metadata:
            self.io.tool_error(f"Skill '{skill_name}' not found.")
            self.io.tool_output("Use '/skill list' to see available skills.")
            return

        validation_errors = self._validate_skill_params(metadata, skill_params)
        if validation_errors:
            for error in validation_errors:
                self.io.tool_error(error)
            self.io.tool_output(f"Use '/skill info {skill_name}' to see supported parameters.")
            return

        self.io.tool_output(f"\n▶ Running skill: {skill_name}")
        if args.enable_agents:
            self.io.tool_output(f"  Agents enabled: max={args.max_agents}, timeout={args.timeout}s")
        if args.model:
            self.io.tool_output(f"  Model: {args.model}")

        # Run the skill
        try:
            result = skill.execute(
                files=args.files or [],
                model=args.model,
                **skill_params,
            )
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            self.io.tool_error(f"Skill execution failed: {e}")
            if self.verbose:
                import traceback

                self.io.tool_output(traceback.format_exc())
            return

        # Display result
        self._display_result(result)

    def _parse_skill_params(self, params: List[str]) -> dict:
        """Parse trailing skill arguments of the form key=value."""
        parsed = {}
        for param in params:
            if "=" not in param:
                raise ValueError(f"Invalid skill parameter: {param!r}. Expected key=value.")
            key, value = param.split("=", 1)
            key = key.strip()
            if not key:
                raise ValueError("Invalid skill parameter: empty key.")
            parsed[key] = self._coerce_param_value(value.strip())
        return parsed

    def _validate_skill_params(self, metadata: dict, provided: dict) -> List[str]:
        """Validate provided key=value params against declared skill parameters."""
        params = metadata.get("parameters") or {}
        if not params:
            return []

        errors = []
        unknown = sorted(set(provided) - set(params))
        if unknown:
            errors.append(f"Unknown skill parameters: {', '.join(unknown)}")

        for name, spec in params.items():
            if name in provided:
                if spec.get("enum") and provided[name] not in spec["enum"]:
                    errors.append(
                        f"Invalid value for '{name}': {provided[name]!r}. "
                        f"Allowed: {', '.join(map(str, spec['enum']))}"
                    )
                continue
            if "default" not in spec:
                errors.append(f"Missing required skill parameter: {name}")

        return errors

    def _coerce_param_value(self, value: str):
        """Coerce CLI string values into simple Python scalars/lists."""
        lower = value.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        if lower == "null" or lower == "none":
            return None

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                return []
            return [self._coerce_param_value(item.strip()) for item in inner.split(",")]

        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _cmd_info(self, args) -> None:
        """Handle info command."""
        metadata = self.registry.get_metadata(args.skill)
        if not metadata:
            self.io.tool_error(f"Skill '{args.skill}' not found.")
            return

        self.io.tool_output(f"\n{args.skill}")
        self.io.tool_output("=" * 50)
        self.io.tool_output(f"\n{metadata['description']}")
        self.io.tool_output(f"\nVersion: {metadata['version']}")
        self.io.tool_output(f"Source: {metadata['source']}")
        if metadata.get("homepage"):
            self.io.tool_output(f"Homepage: {metadata['homepage']}")

        if metadata["supports_agents"]:
            self.io.tool_output("\n🤖 Agent Support: Yes")
            self.io.tool_output(f"   Max agents: {metadata['max_agents']}")
        else:
            self.io.tool_output("\n🤖 Agent Support: No")

        requires = metadata.get("requires") or {}
        if requires:
            bins = requires.get("bins") or []
            if bins:
                self.io.tool_output("\nRequirements:")
                self.io.tool_output(f"  Binaries: {', '.join(bins)}")

        install = metadata.get("install") or []
        if install:
            self.io.tool_output("\nInstall Options:")
            self.io.tool_output(f"  {len(install)} available")

        parameters = metadata.get("parameters") or {}
        if parameters:
            self.io.tool_output("\nParameters:")
            for name, spec in parameters.items():
                required = "required" if "default" not in spec else f"default={spec['default']!r}"
                desc = spec.get("description", "")
                self.io.tool_output(f"  {name}: {required}")
                if desc:
                    self.io.tool_output(f"    {desc}")
                if spec.get("enum"):
                    self.io.tool_output(f"    Allowed: {', '.join(map(str, spec['enum']))}")

        self.io.tool_output("\nUsage:")
        self.io.tool_output(f"  /skill run {args.skill} -f <files> [--agents] key=value ...")

    def _cmd_search(self, args) -> None:
        """Handle search command."""
        results = self.registry.search(args.query)

        if not results:
            self.io.tool_output(f"No skills found matching '{args.query}'.")
            return

        self.io.tool_output(f"\n🔍 Results for '{args.query}':\n")

        for skill in results:
            agent_badge = "🤖" if skill["supports_agents"] else "  "
            self.io.tool_output(f"  {agent_badge} {skill['name']}")
            self.io.tool_output(f"      {skill['description']}")

    def _display_result(self, result) -> None:
        """Display skill execution result."""
        if result.success:
            self.io.tool_output("\n✅ Skill completed successfully")
        else:
            self.io.tool_error("\n❌ Skill failed")

        if result.execution_time:
            self.io.tool_output(f"   Time: {result.execution_time:.2f}s")

        if result.output:
            self.io.tool_output("\n📤 Output:")
            for line in result.output.split("\n")[:50]:  # Limit output
                self.io.tool_output(f"  {line}")

            if len(result.output.split("\n")) > 50:
                self.io.tool_output("  ... (output truncated)")

        if result.error:
            self.io.tool_error(f"\n⚠️  Error: {result.error}")

        if result.files_modified:
            self.io.tool_output(f"\n📝 Files modified ({len(result.files_modified)}):")
            for f in result.files_modified:
                self.io.tool_output(f"  - {f}")

        # Show agent results summary if available
        if result.agent_results:
            successful = sum(1 for r in result.agent_results if r.get("success"))
            total = len(result.agent_results)
            self.io.tool_output(f"\n🤖 Agent results: {successful}/{total} successful")

    def completions_skill(self) -> List[Tuple[str, str]]:
        """Provide completions for /skill command."""
        completions = [
            ("list", "List available skills"),
            ("run", "Run a skill"),
            ("info", "Show skill info"),
            ("search", "Search skills"),
            ("--agents", "Enable sub-agents"),
            ("--max-agents", "Set max concurrent agents"),
            ("--files", "Specify files"),
            ("--model", "Specify model"),
        ]

        # Add skill names
        for skill in self.registry.list_skills():
            agent_note = " (supports agents)" if skill["supports_agents"] else ""
            completions.append((skill["name"], f"{skill['description']}{agent_note}"))

        return completions


def install_skills_command(commands_instance):
    """
    Install the enhanced /skill command.

    Args:
        commands_instance: Aider's Commands instance
    """
    skill_cmd = SkillsCommand(
        io=commands_instance.io,
        coder=getattr(commands_instance, "coder", None),
        verbose=getattr(commands_instance, "verbose", False),
    )

    # Bind command
    commands_instance.cmd_skill = skill_cmd.cmd_skill

    # Bind completions
    commands_instance.completions_skill = skill_cmd.completions_skill
