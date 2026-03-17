"""
Aider command integration for skills.

Extends Aider's /skill command with agent-enabled skills.
"""

import argparse
import asyncio
import shlex
from typing import List, Optional, Tuple

from .registry import get_registry
from .base import SkillContext


class SkillsCommand:
    """
    Extended /skill command with agent support.
    
    Provides commands for running skills that can spawn sub-agents.
    """
    
    def __init__(self, io, coder=None, verbose: bool = False):
        self.io = io
        self.coder = coder
        self.verbose = verbose
        self.registry = get_registry()
        self.parser = self._create_parser()
    
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
            "--agents", "-a",
            action="store_true",
            help="Show only agent-enabled skills"
        )
        list_parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help="Show detailed information"
        )
        
        # run
        run_parser = subparsers.add_parser("run", help="Run a skill")
        run_parser.add_argument(
            "skill",
            help="Name of the skill to run"
        )
        run_parser.add_argument(
            "--files", "-f",
            nargs="+",
            help="Files to process"
        )
        run_parser.add_argument(
            "--model", "-m",
            help="Model to use"
        )
        run_parser.add_argument(
            "--agents",
            action="store_true",
            dest="enable_agents",
            help="Enable sub-agents"
        )
        run_parser.add_argument(
            "--max-agents",
            type=int,
            default=5,
            help="Maximum concurrent agents"
        )
        run_parser.add_argument(
            "--timeout",
            type=float,
            default=300.0,
            help="Agent timeout in seconds"
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
            self._show_help()
            return
        
        try:
            args_list = shlex.split(args_str)
            args = self.parser.parse_args(args_list)
        except SystemExit:
            return
        
        # Dispatch
        if args.action == "list":
            self._cmd_list(args)
        elif args.action == "run":
            asyncio.run(self._cmd_run(args))
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
    
    def _cmd_list(self, args) -> None:
        """Handle list command."""
        skills = self.registry.list_skills(
            supports_agents=args.agents if args.agents else None
        )
        
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
                desc = skill['description'][:50] + "..." if len(skill['description']) > 50 else skill['description']
                self.io.tool_output(f"  {agent_badge} {skill['name']:<25} - {desc}")
        
        if not args.verbose:
            self.io.tool_output("\nUse '/skill list --verbose' for details.")
            self.io.tool_output("Use '/skill info <name>' for specific skill info.")
    
    async def _cmd_run(self, args) -> None:
        """Handle run command."""
        skill_name = args.skill
        
        # Check if skill exists
        skill_class = self.registry.get(skill_name)
        if not skill_class:
            self.io.tool_error(f"Skill '{skill_name}' not found.")
            self.io.tool_output("Use '/skill list' to see available skills.")
            return
        
        # Create context
        context = SkillContext(
            coder=self.coder,
            io=self.io,
            verbose=self.verbose,
            enable_agents=args.enable_agents,
            max_agents=args.max_agents,
            agent_timeout=args.timeout,
        )
        
        # Create skill instance
        skill = skill_class(context)
        
        self.io.tool_output(f"\n▶ Running skill: {skill_name}")
        if args.enable_agents:
            self.io.tool_output(f"  Agents enabled: max={args.max_agents}, timeout={args.timeout}s")
        if args.model:
            self.io.tool_output(f"  Model: {args.model}")
        
        # Run the skill
        try:
            result = await skill.execute(
                files=args.files or [],
                model=args.model,
            )
        except Exception as e:
            self.io.tool_error(f"Skill execution failed: {e}")
            if self.verbose:
                import traceback
                self.io.tool_output(traceback.format_exc())
            return
        
        # Display result
        self._display_result(result)
    
    def _cmd_info(self, args) -> None:
        """Handle info command."""
        skill_class = self.registry.get(args.skill)
        if not skill_class:
            self.io.tool_error(f"Skill '{args.skill}' not found.")
            return
        
        self.io.tool_output(f"\n{args.skill}")
        self.io.tool_output("=" * 50)
        self.io.tool_output(f"\n{skill_class.description}")
        self.io.tool_output(f"\nVersion: {getattr(skill_class, 'version', '1.0.0')}")
        
        if skill_class.supports_agents:
            self.io.tool_output("\n🤖 Agent Support: Yes")
            self.io.tool_output(f"   Max agents: {getattr(skill_class, 'max_agents', 5)}")
        else:
            self.io.tool_output("\n🤖 Agent Support: No")
        
        self.io.tool_output(f"\nUsage:")
        self.io.tool_output(f"  /skill run {args.skill} -f <files> [--agents]")
    
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
            self.io.tool_output(f"\n✅ Skill completed successfully")
        else:
            self.io.tool_error(f"\n❌ Skill failed")
        
        if result.execution_time:
            self.io.tool_output(f"   Time: {result.execution_time:.2f}s")
        
        if result.output:
            self.io.tool_output("\n📤 Output:")
            for line in result.output.split('\n')[:50]:  # Limit output
                self.io.tool_output(f"  {line}")
            
            if len(result.output.split('\n')) > 50:
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
            completions.append((
                skill["name"],
                f"{skill['description']}{agent_note}"
            ))
        
        return completions


def install_skills_command(commands_instance):
    """
    Install the enhanced /skill command.
    
    Args:
        commands_instance: Aider's Commands instance
    """
    skill_cmd = SkillsCommand(
        io=commands_instance.io,
        coder=getattr(commands_instance, 'coder', None),
        verbose=getattr(commands_instance, 'verbose', False),
    )
    
    # Bind command
    commands_instance.cmd_skill = skill_cmd.cmd_skill
    
    # Bind completions
    commands_instance.completions_skill = skill_cmd.completions_skill
