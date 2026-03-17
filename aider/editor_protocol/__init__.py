"""ACP (Agent Client Protocol) support for Aider editor integration."""

from .agent import AiderAcpAgent, run_acp_mode, ACP_AVAILABLE

__all__ = [
    "AiderAcpAgent",
    "run_acp_mode",
    "ACP_AVAILABLE",
]
