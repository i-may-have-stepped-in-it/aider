"""
Agent commands for Aider (/agent spawn, /agent list, etc.)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _run_async_safely(coro, timeout=30.0):
    """
    Safely run an async coroutine from synchronous code.

    Handles both cases:
    - No event loop running: uses asyncio.run()
    - Event loop already running: uses ThreadPoolExecutor with new event loop
    """
    try:
        # Check if we're already in an event loop
        asyncio.get_running_loop()

        # Already in async context - run in separate thread with new loop
        def run_in_new_loop():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_in_new_loop)
            return future.result(timeout=timeout)
    except RuntimeError:
        # No event loop running - safe to use asyncio.run
        return asyncio.run(coro)


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
        self.coder = commands.coder
        self.io = commands.io
        self._registry = None
        self._executor = None

    @property
    def registry(self):
        """Get the agent registry from the coder."""
        if self._registry is None:
            if hasattr(self.coder, "agent_registry"):
                self._registry = self.coder.agent_registry
            else:
                # Lazy initialization
                from .registry import AgentRegistry

                self._registry = AgentRegistry()
                self.coder.agent_registry = self._registry
        return self._registry

    @property
    def executor(self):
        """Get the agent executor."""
        if self._executor is None:
            from .executor import AgentExecutor

            self._executor = AgentExecutor(self.registry, self.io)
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
        /agent list --status running
        /agent wait abc123
        """
        if not args.strip():
            return self.cmd_agent.__doc__

        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0] if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        handler = getattr(self, f"_handle_{subcmd}", None)
        if handler:
            return handler(subargs)
        else:
            self.io.tool_error(f"Unknown agent subcommand: {subcmd}")
            return self.cmd_agent.__doc__

    def _handle_spawn(self, args: str) -> str:
        """Handle /agent spawn"""
        import shlex

        # Parse arguments
        parser_args = shlex.split(args) if args else []

        task = ""
        model = None
        files = []
        readonly_files = []
        name = None

        i = 0
        while i < len(parser_args):
            arg = parser_args[i]
            if arg == "--model" and i + 1 < len(parser_args):
                model = parser_args[i + 1]
                i += 2
            elif arg == "--files" and i + 1 < len(parser_args):
                files = parser_args[i + 1].split(",")
                i += 2
            elif arg == "--readonly" and i + 1 < len(parser_args):
                readonly_files = parser_args[i + 1].split(",")
                i += 2
            elif arg == "--name" and i + 1 < len(parser_args):
                name = parser_args[i + 1]
                i += 2
            else:
                task = " ".join(parser_args[i:])
                break

        if not task:
            return "Error: Task required. Usage: /agent spawn <task> [--model MODEL]"

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
            parts = args.split("--status")
            if len(parts) > 1:
                status_str = parts[1].strip().split()[0].upper()
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
            return "Error: Agent ID required"

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
            return "Error: Agent ID required"

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
            return "Error: Agent ID required"

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
            return "Error: Agent ID required"

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
