"""A2A commands for Aider (/a2a send, /a2a request, etc.)"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from aider.async_utils import run_async_safely

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_run_async_safely = run_async_safely


class A2ACommands:
    """
    Commands for agent-to-agent communication.

    Adds:
    - /a2a send <agent-id> <message>
    - /a2a request <agent-id> <capability> [args...]
    - /a2a broadcast <message>
    - /a2a delegate <agent-id> <task>
    - /a2a list
    - /a2a history [<agent-id>]
    """

    def __init__(self, commands):
        self.commands = commands
        self.io = commands.io
        self._registry = None
        self._registry_owner = None

    def _show_usage(self, error=None):
        if hasattr(self.commands, "show_command_usage"):
            self.commands.show_command_usage("a2a", error=error)
        elif error:
            self.io.tool_error(error)

    def _show_subcommand_usage(self, usage, error=None):
        if error:
            self.io.tool_error(error)
        self.io.tool_output(f"Usage: {usage}")

    @property
    def coder(self):
        """Get the coder from commands dynamically."""
        return self.commands.coder

    @property
    def registry(self):
        """Get the agent registry from the coder."""
        runtime = getattr(self.coder, "runtime", None) if self.coder else None
        if runtime and getattr(runtime, "agent_service", None):
            owner = runtime.agent_service.registry
        elif self.coder and hasattr(self.coder, "agent_registry"):
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
                from ..agents.service import AgentService

                service = AgentService(io=self.io)
                self._registry = service.registry
                if self.coder:
                    self.coder.agent_registry = self._registry
            self._registry_owner = self._registry
        return self._registry

    def cmd_a2a(self, args: str) -> Optional[str]:
        """
        Agent-to-agent communication commands.

        Usage:
        /a2a send <agent-id> <message>
        /a2a request <agent-id> <capability> [--param key=value ...]
        /a2a broadcast <message>
        /a2a delegate <agent-id> <task>
        /a2a list
        /a2a history [<agent-id>]

        Examples:
        /a2a send abc123 "Hello from main agent"
        /a2a request abc123 review_code --param file=auth.py
        /a2a broadcast "All agents report status"
        /a2a delegate abc123 "Refactor user.py to use async"
        /a2a list
        /a2a history abc123
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
            self._show_usage(f"Unknown a2a subcommand: {subcmd}")
            return None

    def _handle_send(self, args: str) -> str:
        """Handle /a2a send"""
        import shlex

        try:
            parts = shlex.split(args) if args else []
        except ValueError as err:
            self._show_subcommand_usage(
                "/a2a send <agent-id> <message>",
                f"Unable to parse /a2a send arguments: {err}",
            )
            return None
        if len(parts) < 2:
            self._show_subcommand_usage("/a2a send <agent-id> <message>", "Message required.")
            return None

        agent_id = parts[0]
        message = " ".join(parts[1:])

        async def do_send():
            from ..a2a.types import A2AContentType, A2AMessageType

            # Get the agent from registry
            agent = await self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            # Check if agent supports A2A
            if not hasattr(agent, "send"):
                raise ValueError(f"Agent {agent_id} does not support A2A")

            await agent.send(
                recipient_id=agent_id,
                content=message,
                msg_type=A2AMessageType.NOTIFICATION,
                content_type=A2AContentType.TEXT,
            )
            return True

        try:
            _run_async_safely(do_send())
            return f"Message sent to agent {agent_id}"
        except Exception as e:
            self.io.tool_error(f"Failed to send message: {e}")
            return None

    def _handle_request(self, args: str) -> str:
        """Handle /a2a request"""
        import shlex

        try:
            parts = shlex.split(args) if args else []
        except ValueError as err:
            self._show_subcommand_usage(
                "/a2a request <agent-id> <capability> [--param key=value ...]",
                f"Unable to parse /a2a request arguments: {err}",
            )
            return None
        if len(parts) < 2:
            self._show_subcommand_usage(
                "/a2a request <agent-id> <capability> [--param key=value ...]",
                "Agent ID and capability required.",
            )
            return None

        agent_id = parts[0]
        capability = parts[1]

        # Parse parameters
        params = {}
        i = 2
        while i < len(parts):
            if parts[i] == "--param" and i + 1 < len(parts):
                param_str = parts[i + 1]
                if "=" not in param_str:
                    self._show_subcommand_usage(
                        "/a2a request <agent-id> <capability> [--param key=value ...]",
                        f"Invalid --param value: {param_str!r}. Expected key=value.",
                    )
                    return None
                key, value = param_str.split("=", 1)
                params[key] = value
                i += 2
            elif parts[i] == "--param":
                self._show_subcommand_usage(
                    "/a2a request <agent-id> <capability> [--param key=value ...]",
                    "Option --param requires a value.",
                )
                return None
            elif parts[i].startswith("--"):
                self._show_subcommand_usage(
                    "/a2a request <agent-id> <capability> [--param key=value ...]",
                    f"Unknown /a2a request option: {parts[i]}",
                )
                return None
            else:
                self._show_subcommand_usage(
                    "/a2a request <agent-id> <capability> [--param key=value ...]",
                    f"Unexpected argument: {parts[i]!r}",
                )
                return None

        async def do_request():
            # Get the agent from registry
            agent = await self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            # Check if agent supports A2A
            if not hasattr(agent, "request"):
                raise ValueError(f"Agent {agent_id} does not support A2A requests")

            result = await agent.request(
                recipient_id=agent_id,
                capability=capability,
                parameters=params,
            )
            return result

        try:
            self.io.tool_output(f"Requesting '{capability}' from agent {agent_id}...")
            result = _run_async_safely(do_request())
            return f"Response from {agent_id}:\n{result}"
        except Exception as e:
            self.io.tool_error(f"Request failed: {e}")
            return None

    def _handle_broadcast(self, args: str) -> str:
        """Handle /a2a broadcast"""
        if not args.strip():
            self._show_subcommand_usage("/a2a broadcast <message>", "Message required.")
            return None

        message = args.strip()

        async def do_broadcast():
            from ..a2a.types import A2AContentType

            # Get all A2A-enabled agents and broadcast from the first one
            agents = await self.registry.list_agents()
            a2a_agents = [a for a in agents if hasattr(a, "broadcast")]

            if not a2a_agents:
                raise ValueError("No A2A-enabled agents found")

            # Use the first agent to broadcast
            await a2a_agents[0].broadcast(
                content=message,
                content_type=A2AContentType.TEXT,
            )
            return True

        try:
            _run_async_safely(do_broadcast())
            return "Broadcast sent to all agents"
        except Exception as e:
            self.io.tool_error(f"Failed to broadcast: {e}")
            return None

    def _handle_delegate(self, args: str) -> str:
        """Handle /a2a delegate"""
        import shlex

        try:
            parts = shlex.split(args) if args else []
        except ValueError as err:
            self._show_subcommand_usage(
                "/a2a delegate <agent-id> <task>",
                f"Unable to parse /a2a delegate arguments: {err}",
            )
            return None
        if len(parts) < 2:
            self._show_subcommand_usage(
                "/a2a delegate <agent-id> <task>", "Agent ID and task required."
            )
            return None

        agent_id = parts[0]
        task = " ".join(parts[1:])

        async def do_delegate():
            # Get the agent from registry
            agent = await self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            # Check if agent supports A2A
            if not hasattr(agent, "delegate"):
                raise ValueError(f"Agent {agent_id} does not support A2A delegation")

            await agent.delegate(
                recipient_id=agent_id,
                task=task,
            )
            return True

        try:
            _run_async_safely(do_delegate())
            return f"Task delegated to agent {agent_id}"
        except Exception as e:
            self.io.tool_error(f"Failed to delegate: {e}")
            return None

    def _handle_list(self, args: str) -> str:
        """Handle /a2a list"""

        async def do_list():
            agents = await self.registry.list_agents()
            return agents

        try:
            agents = _run_async_safely(do_list())
            if not agents:
                return "No agents found"

            lines = [f"{'ID':<10} {'Name':<20} {'A2A':<5} {'Task':<40}"]
            lines.append("-" * 80)
            for agent in agents:
                task_short = agent.task[:37] + "..." if len(agent.task) > 40 else agent.task
                has_a2a = "Yes" if hasattr(agent, "send") else "No"
                lines.append(f"{agent.id:<10} {agent.name:<20} {has_a2a:<5} {task_short}")

            return "\n".join(lines)
        except Exception as e:
            self.io.tool_error(f"Failed to list agents: {e}")
            return None

    def _handle_history(self, args: str) -> str:
        """Handle /a2a history"""
        agent_id = args.strip() if args else None

        async def do_history():
            # Get history from bus
            if not self.registry.a2a_bus:
                return []
            history = self.registry.a2a_bus.get_history(agent_id=agent_id)
            return history

        try:
            history = _run_async_safely(do_history())
            if not history:
                return "No A2A messages found"

            lines = []
            for msg in history[-20:]:  # Last 20 messages
                recipient = msg.recipient_id or "all"
                lines.append(
                    f"[{msg.timestamp:.0f}] {msg.type.value}: {msg.sender_id} -> {recipient}"
                )
                lines.append(f"  Content: {str(msg.content)[:100]}")

            return "\n".join(lines)
        except Exception as e:
            self.io.tool_error(f"Failed to get history: {e}")
            return None

    def completions_a2a(self, document, complete_event):
        """Tab completion for /a2a command"""
        from prompt_toolkit.completion import Completion

        text = document.text.lower()
        subcommands = ["send", "request", "broadcast", "delegate", "list", "history"]

        for cmd in subcommands:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))


def install_a2a_commands(commands):
    """
    Install A2A commands into Aider's command system.

    Call this from aider/commands.py or during Coder initialization.
    """
    if hasattr(commands, "cmd_a2a"):
        logger.debug("Commands already exposes cmd_a2a; install_a2a_commands is a no-op")
        return commands

    a2a_cmds = A2ACommands(commands)
    commands.cmd_a2a = a2a_cmds.cmd_a2a
    commands.completions_a2a = a2a_cmds.completions_a2a
    commands._a2a_commands = a2a_cmds
    logger.info("Installed compatibility A2A commands")
    return commands
