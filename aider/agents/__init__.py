"""
Multi-agent system for Aider - inspired by kimi-cli.

Provides sub-agent spawning and coordination for parallel task execution.
"""

from .agent import SubAgent, AgentStatus, AgentResult
from .cli_agent import CliAgent, CliAgentError, is_cli_model, run_oneshot as cli_run_oneshot
from .registry import AgentRegistry
from .executor import AgentExecutor
from .commands import AgentCommands, install_agent_commands

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
