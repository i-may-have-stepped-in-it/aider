"""A2A (Agent-to-Agent) protocol for subagent collaboration."""
import logging

from .agent import A2AEnabledAgent
from .bus import A2AMessageBus
from .commands import A2ACommands, install_a2a_commands
from .types import A2ACapability, A2AContentType, A2AMessage, A2AMessageType

logger = logging.getLogger(__name__)

__all__ = [
    "A2AMessage",
    "A2AMessageType",
    "A2AContentType",
    "A2ACapability",
    "A2ARequest",
    "A2AResponse",
    "A2AMessageBus",
    "A2AEnabledAgent",
    "A2ACommands",
    "install_a2a_commands",
]
