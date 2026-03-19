"""
Integration helpers for wiring multi-agent support into Aider.

This file provides the glue code needed to integrate the multi-agent system
with Aider's existing codebase.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def patch_coder_class():
    """
    Compatibility shim retained for older integration code.

    The core Commands class now exposes /agent directly and agent registries
    are attached explicitly or lazily, so no Coder mutation is needed here.
    """
    logger.debug("patch_coder_class() is now a no-op compatibility shim")


def install_in_commands(commands_module=None):
    """
    Install agent commands into Aider's commands module.

    Args:
        commands_module: The aider.commands module (auto-imported if None)
    """
    if commands_module is None:
        from aider import commands as commands_module

    if hasattr(commands_module.Commands, "cmd_agent"):
        logger.debug("Commands already exposes cmd_agent; install_in_commands is a no-op")
        return commands_module.Commands

    from .commands import AgentCommands

    original_commands_cls = commands_module.Commands

    class CommandsWithAgents(original_commands_cls):
        """Compatibility wrapper for older command installations."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._agent_commands = AgentCommands(self)

        def cmd_agent(self, args: str):
            return self._agent_commands.cmd_agent(args)

        def completions_agent(self, document, complete_event):
            return self._agent_commands.completions_agent(document, complete_event)

    commands_module.Commands = CommandsWithAgents
    logger.info("Installed compatibility agent commands into aider.commands")
    return commands_module.Commands


def initialize_agents(coder, max_concurrent: int = 5):
    """
    Initialize agent support for a Coder instance.

    Args:
        coder: The Coder instance to initialize
        max_concurrent: Maximum concurrent agents
    """
    runtime = getattr(coder, "runtime", None)
    if runtime and hasattr(runtime, "configure_agents"):
        agent_service = runtime.configure_agents(max_concurrent=max_concurrent)
        coder.agent_service = agent_service
        coder.agent_registry = runtime.agent_registry
        coder.a2a_bus = runtime.a2a_bus
        logger.info(
            "Initialized agent service for coder runtime (max_concurrent=%s)", max_concurrent
        )
        return

    from .registry import AgentRegistry

    if not hasattr(coder, "agent_registry") or coder.agent_registry is None:
        coder.agent_registry = AgentRegistry(max_concurrent=max_concurrent)
        logger.info(f"Initialized agent registry for coder (max_concurrent={max_concurrent})")


def add_cli_args(parser):
    """
    Add agent-related CLI arguments to Aider's argument parser.

    Args:
        parser: The ArgumentParser instance
    """
    group = parser.add_argument_group("Multi-agent Options")

    group.add_argument(
        "--enable-agents",
        action="store_true",
        help="Enable multi-agent support",
        default=False,
    )

    group.add_argument(
        "--max-agents",
        type=int,
        default=5,
        help="Maximum concurrent agents (default: 5)",
    )

    group.add_argument(
        "--agent-timeout",
        type=float,
        default=300.0,
        help="Default agent timeout in seconds (default: 300)",
    )

    return parser


def setup_from_args(coder, args):
    """
    Setup agent support based on CLI arguments.

    Args:
        coder: The Coder instance
        args: Parsed arguments
    """
    if getattr(args, "enable_agents", False):
        max_concurrent = getattr(args, "max_agents", 5)
        initialize_agents(coder, max_concurrent=max_concurrent)
        logger.info(f"Agents enabled with max_concurrent={max_concurrent}")
