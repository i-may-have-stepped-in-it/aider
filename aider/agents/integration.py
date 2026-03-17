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
    Monkey-patch the Coder class to add agent registry support.
    
    This is a temporary measure until the changes are merged upstream.
    """
    from aider.coders.base_coder import Coder
    
    # Store original __init__
    original_init = Coder.__init__
    
    def new_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Add agent registry
        from .registry import AgentRegistry
        self.agent_registry: Optional[AgentRegistry] = None
    
    Coder.__init__ = new_init
    logger.debug("Patched Coder class with agent_registry attribute")


def install_in_commands(commands_module=None):
    """
    Install agent commands into Aider's commands module.
    
    Args:
        commands_module: The aider.commands module (auto-imported if None)
    """
    if commands_module is None:
        from aider import commands as commands_module
    
    from .commands import AgentCommands
    
    # Store reference to original Commands class
    original_commands_cls = commands_module.Commands
    
    class CommandsWithAgents(original_commands_cls):
        """Extended Commands class with agent support."""
        
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._agent_commands = AgentCommands(self)
        
        def cmd_agent(self, args: str):
            """Manage sub-agents for parallel task execution."""
            return self._agent_commands.cmd_agent(args)
        
        def completions_agent(self, document, complete_event):
            """Tab completion for /agent command."""
            return self._agent_commands.completions_agent(document, complete_event)
    
    # Replace Commands class
    commands_module.Commands = CommandsWithAgents
    logger.info("Installed agent commands into aider.commands")


def initialize_agents(coder, max_concurrent: int = 5):
    """
    Initialize agent support for a Coder instance.
    
    Args:
        coder: The Coder instance to initialize
        max_concurrent: Maximum concurrent agents
    """
    from .registry import AgentRegistry
    
    if not hasattr(coder, 'agent_registry') or coder.agent_registry is None:
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
    if getattr(args, 'enable_agents', False):
        max_concurrent = getattr(args, 'max_agents', 5)
        initialize_agents(coder, max_concurrent=max_concurrent)
        logger.info(f"Agents enabled with max_concurrent={max_concurrent}")


# Auto-patch on import
try:
    patch_coder_class()
except Exception as e:
    logger.warning(f"Failed to patch Coder class: {e}")
