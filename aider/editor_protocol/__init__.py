"""ACP (Agent Client Protocol) support for Aider editor integration."""

from .agent import ACP_AVAILABLE, AiderAcpAgent, run_acp_mode

__all__ = [
    "AiderAcpAgent",
    "run_acp_mode",
    "ACP_AVAILABLE",
]
