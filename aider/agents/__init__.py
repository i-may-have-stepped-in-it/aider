"""
Multi-agent system for Aider - inspired by kimi-cli.

Provides sub-agent spawning and coordination for parallel task execution.
"""

from .agent import AgentResult, AgentStatus, SubAgent
from .cli_agent import CliAgent, CliAgentError, is_cli_model
from .cli_agent import run_oneshot as cli_run_oneshot
from .commands import AgentCommands, install_agent_commands
from .executor import AgentExecutor
from .registry import AgentRegistry

__all__ = [
    "SubAgent",
    "AgentStatus",
    "AgentResult",
    "AgentRegistry",
    "AgentExecutor",
    "AgentCommands",
    "install_agent_commands",
    "CliAgent",
    "CliAgentError",
    "is_cli_model",
    "cli_run_oneshot",
]
