"""
Agent commands for Aider (/agent spawn, /agent list, etc.)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from aider.async_utils import run_async_safely

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_run_async_safely = run_async_safely


class AgentCommands:
    """
    Commands for managing sub-agents.

    Adds:
    - /agent spawn <task> [--model MODEL] [--files FILES]
    - /agent list [--status STATUS]
    - /agent status <id>
    - /agent result <id> [--wait]
    - /agent wait <id>
    - /agent cancel <id>
    """

    def __init__(self, commands):
        self.commands = commands
        self.io = commands.io
        self._registry = None
        self._registry_owner = None
        self._executor = None
        self._executor_owner = None

    def _show_usage(self, error=None):
        if hasattr(self.commands, "show_command_usage"):
            self.commands.show_command_usage("agent", error=error)
        elif error:
            self.io.tool_error(error)

    def _show_subcommand_usage(self, usage, error=None):
        if error:
            self.io.tool_error(error)
        self.io.tool_output(f"Usage: {usage}")

    @property
    def coder(self):
        """Get the coder from commands (set dynamically)."""
        return self.commands.coder

    @property
    def registry(self):
        """Get the agent registry from the coder."""
        runtime = getattr(self.coder, "runtime", None) if self.coder else None
        if runtime and getattr(runtime, "agent_service", None):
            owner = runtime.agent_service.registry
        elif self.coder and hasattr(self.coder, "agent_registry") and self.coder.agent_registry:
            owner = self.coder.agent_registry
        else:
            owner = None

        if self._registry is not None and self._registry_owner is not owner:
            self._registry = None
            self._registry_owner = None

        if self._registry is None:
            if owner is not None:
                self._registry = owner
            else:
                # Lazy initialization
                from .service import AgentService

                service = AgentService(io=self.io)
                self._registry = service.registry
                if self.coder:
                    self.coder.agent_registry = self._registry
            self._registry_owner = self._registry
        return self._registry

    @property
    def executor(self):
        """Get the agent executor."""
        runtime = getattr(self.coder, "runtime", None) if self.coder else None
        owner = getattr(getattr(runtime, "agent_service", None), "executor", None)

        if self._executor is not None and self._executor_owner is not owner:
            self._executor = None
            self._executor_owner = None

        if self._executor is None:
            if owner is not None:
                self._executor = owner
            else:
                from .executor import AgentExecutor

                self._executor = AgentExecutor(self.registry, self.io)
            self._executor_owner = self._executor
        return self._executor

    def cmd_agent(self, args: str) -> Optional[str]:
        """
        Manage sub-agents for parallel task execution.

        Usage:
        /agent spawn <task> [--model MODEL] [--files FILES] [--readonly FILES]
        /agent list [--status pending|running|completed|error|cancelled]
        /agent status <id>
        /agent result <id> [--wait]
        /agent wait <id>
        /agent cancel <id>
        /agent clear

        Examples:
        /agent spawn "Review auth.py for security issues" --model claude-sonnet
        /agent spawn "Add tests for user.py" --files user.py --readonly test_base.py
        /agent spawn "Audit this design" --character my-venice-character
        /agent list --status running
        /agent wait abc123
        """
        if not args.strip():
            self._show_usage()
            return None

        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0] if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        handler = getattr(self, f"_handle_{subcmd}", None)
        if handler:
            return handler(subargs)
        else:
            self._show_usage(f"Unknown agent subcommand: {subcmd}")
            return None

    def _handle_spawn(self, args: str) -> str:
        """Handle /agent spawn"""
        import shlex

        # Parse arguments
        try:
            parser_args = shlex.split(args) if args else []
        except ValueError as err:
            self._show_subcommand_usage(
                "/agent spawn <task> [--model MODEL] [--files FILES] [--readonly FILES]",
                f"Unable to parse /agent spawn arguments: {err}",
            )
            return None

        task = ""
        model = None
        files = []
        readonly_files = []
        name = None
        character = None

        i = 0
        while i < len(parser_args):
            arg = parser_args[i]
            if arg == "--model":
                if i + 1 >= len(parser_args):
                    self._show_subcommand_usage(
                        "/agent spawn <task> [--model MODEL] [--files FILES] [--readonly FILES]",
                        "Option --model requires a value.",
                    )
                    return None
                model = parser_args[i + 1]
                i += 2
            elif arg == "--files":
                if i + 1 >= len(parser_args):
                    self._show_subcommand_usage(
                        "/agent spawn <task> [--model MODEL] [--files FILES] [--readonly FILES]",
                        "Option --files requires a value.",
                    )
                    return None
                files = parser_args[i + 1].split(",")
                i += 2
            elif arg == "--readonly":
                if i + 1 >= len(parser_args):
                    self._show_subcommand_usage(
                        "/agent spawn <task> [--model MODEL] [--files FILES] [--readonly FILES]",
                        "Option --readonly requires a value.",
                    )
                    return None
                readonly_files = parser_args[i + 1].split(",")
                i += 2
            elif arg == "--character":
                if i + 1 >= len(parser_args):
                    self._show_subcommand_usage(
                        "/agent spawn <task> --character SLUG [--model venice/MODEL]",
                        "Option --character requires a Venice character slug.",
                    )
                    return None
                character = parser_args[i + 1]
                i += 2
            elif arg == "--name":
                if i + 1 >= len(parser_args):
                    self._show_subcommand_usage(
                        "/agent spawn <task> [--model MODEL] [--files FILES] [--readonly FILES]",
                        "Option --name requires a value.",
                    )
                    return None
                name = parser_args[i + 1]
                i += 2
            elif arg.startswith("--"):
                self._show_subcommand_usage(
                    "/agent spawn <task> [--model MODEL] [--files FILES] [--readonly FILES]",
                    f"Unknown /agent spawn option: {arg}",
                )
                return None
            else:
                task = " ".join(parser_args[i:])
                break

        if not task:
            self._show_subcommand_usage(
                "/agent spawn <task> [--model MODEL] [--files FILES] [--readonly FILES]",
                "Task required.",
            )
            return None

        if character:
            # A Venice character is an agent hosted by Venice: attach it to a Venice model
            from aider.models import MODEL_ALIASES

            base = MODEL_ALIASES.get(model or "venice", model or "venice")
            if not base.lower().startswith("venice/"):
                base = MODEL_ALIASES["venice"]
            model = f"{base.split('@')[0]}@{character}"

        # Spawn agent
        async def do_spawn():
            agent = await self.executor.spawn(
                parent_coder=self.coder,
                task=task,
                name=name,
                model=model,
                files=files,
                readonly_files=readonly_files,
            )
            return agent

        try:
            agent = _run_async_safely(do_spawn())
            self.io.tool_output(f"Spawned agent {agent.id} ({agent.name})")
            self.io.tool_output(f"Task: {task[:100]}{'...' if len(task) > 100 else ''}")
            if model:
                self.io.tool_output(f"Model: {model}")
            if files:
                self.io.tool_output(f"Files: {', '.join(files)}")
            return f"Agent {agent.id} spawned successfully"
        except Exception as e:
            self.io.tool_error(f"Failed to spawn agent: {e}")
            return None

    def _handle_list(self, args: str) -> str:
        """Handle /agent list"""
        status_filter = None
        if "--status" in args:
            parts = args.split("--status", 1)
            if len(parts) > 1:
                remainder = parts[1].strip()
                if not remainder:
                    self._show_subcommand_usage(
                        "/agent list [--status pending|running|completed|error|cancelled]",
                        "Option --status requires a value.",
                    )
                    return None
                status_str = remainder.split()[0].upper()
                from .agent import AgentStatus

                try:
                    status_filter = AgentStatus[status_str]
                except KeyError:
                    self.io.tool_error(f"Invalid status: {status_str}")
                    return None

        async def do_list():
            return await self.registry.list_agents(status_filter)

        try:
            agents = _run_async_safely(do_list())
            if not agents:
                return "No agents found"

            lines = [f"{'ID':<10} {'Name':<20} {'Status':<12} {'Task':<40}"]
            lines.append("-" * 82)
            for agent in agents:
                task_short = agent.task[:37] + "..." if len(agent.task) > 40 else agent.task
                lines.append(
                    f"{agent.id:<10} {agent.name:<20} {agent.status.name:<12} {task_short}"
                )

            return "\n".join(lines)
        except Exception as e:
            self.io.tool_error(f"Failed to list agents: {e}")
            return None

    def _handle_status(self, args: str) -> str:
        """Handle /agent status"""
        agent_id = args.strip()
        if not agent_id:
            self._show_subcommand_usage("/agent status <id>", "Agent ID required.")
            return None

        async def do_status():
            return await self.registry.get(agent_id)

        try:
            agent = _run_async_safely(do_status())
            if not agent:
                return f"Agent {agent_id} not found"

            lines = [
                f"Agent: {agent.id} ({agent.name})",
                f"Status: {agent.status.name}",
                f"Task: {agent.task}",
            ]
            if agent.model:
                lines.append(f"Model: {agent.model}")
            if agent.files:
                lines.append(f"Files: {', '.join(agent.files)}")
            lines.append(f"Execution time: {agent.execution_time:.1f}s")
            if agent.progress:
                lines.append(f"Progress: {agent.progress}")
            if agent.error:
                lines.append(f"Error: {agent.error}")

            return "\n".join(lines)
        except Exception as e:
            self.io.tool_error(f"Failed to get status: {e}")
            return None

    def _handle_result(self, args: str) -> Optional[str]:
        """Handle /agent result"""
        parts = args.strip().split()
        if not parts:
            self._show_subcommand_usage("/agent result <id> [--wait]", "Agent ID required.")
            return None

        agent_id = parts[0]
        should_wait = "--wait" in args

        async def do_result():
            if should_wait:
                await self.registry.wait_for_completion(agent_id)
            return await self.registry.get(agent_id)

        try:
            agent = _run_async_safely(do_result())
            if not agent:
                return f"Agent {agent_id} not found"

            if agent.status.name in ("PENDING", "RUNNING") and not should_wait:
                return (
                    f"Agent {agent_id} is still {agent.status.name}. "
                    "Use --wait to wait for completion."
                )

            if agent.result:
                lines = [
                    f"Result for agent {agent_id}:",
                    f"Success: {agent.result.success}",
                    f"Execution time: {agent.result.execution_time:.1f}s",
                ]
                if agent.result.output:
                    lines.append(f"\nOutput:\n{agent.result.output}")
                if agent.result.files_modified:
                    lines.append(f"\nFiles modified: {', '.join(agent.result.files_modified)}")
                if agent.result.error:
                    lines.append(f"\nError: {agent.result.error}")
                return "\n".join(lines)
            else:
                return f"Agent {agent_id} has no result yet (status: {agent.status.name})"
        except Exception as e:
            self.io.tool_error(f"Failed to get result: {e}")
            return None

    def _handle_wait(self, args: str) -> str:
        """Handle /agent wait"""
        agent_id = args.strip()
        if not agent_id:
            self._show_subcommand_usage("/agent wait <id>", "Agent ID required.")
            return None

        self.io.tool_output(f"Waiting for agent {agent_id}...")

        async def do_wait():
            return await self.registry.wait_for_completion(agent_id)

        try:
            agent = _run_async_safely(do_wait())
            return f"Agent {agent_id} completed with status: {agent.status.name}"
        except Exception as e:
            self.io.tool_error(f"Failed to wait for agent: {e}")
            return None

    def _handle_cancel(self, args: str) -> str:
        """Handle /agent cancel"""
        agent_id = args.strip()
        if not agent_id:
            self._show_subcommand_usage("/agent cancel <id>", "Agent ID required.")
            return None

        async def do_cancel():
            return await self.registry.cancel(agent_id)

        try:
            cancelled = _run_async_safely(do_cancel())
            if cancelled:
                return f"Agent {agent_id} cancelled"
            else:
                return f"Agent {agent_id} not found or not running"
        except Exception as e:
            self.io.tool_error(f"Failed to cancel agent: {e}")
            return None

    def _handle_clear(self, args: str) -> str:
        """Handle /agent clear"""

        async def do_clear():
            # Cancel all active agents
            cancelled = await self.registry.cancel_all()
            # Clear completed agents from registry
            agents = await self.registry.list_agents()
            for agent in agents:
                if not agent.is_active:
                    await self.registry.unregister(agent.id)
            return cancelled

        try:
            cancelled = _run_async_safely(do_clear())
            return f"Cleared {len(cancelled)} active agents and removed completed agents"
        except Exception as e:
            self.io.tool_error(f"Failed to clear agents: {e}")
            return None

    def completions_agent(self, document, complete_event):
        """Tab completion for /agent command"""
        from prompt_toolkit.completion import Completion

        text = document.text.lower()
        subcommands = ["spawn", "list", "status", "result", "wait", "cancel", "clear"]

        for cmd in subcommands:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))


def install_agent_commands(commands):
    """
    Install agent commands into Aider's command system.

    Call this from aider/commands.py or during Coder initialization.
    """
    agent_cmds = AgentCommands(commands)

    # Add cmd_agent method to Commands class
    commands.cmd_agent = agent_cmds.cmd_agent
    commands.completions_agent = agent_cmds.completions_agent

    # Store references for access
    commands._agent_commands = agent_cmds

    logger.info("Agent commands installed")
