"""A2A (Agent-to-Agent) protocol types."""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Callable
import time


class A2AMessageType(Enum):
    """A2A message types."""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    EVENT = "event"
    DELEGATE = "delegate"
    BROADCAST = "broadcast"
    HANDSHAKE = "handshake"
    HEARTBEAT = "heartbeat"


class A2AContentType(Enum):
    """Content types for A2A messages."""
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CONTEXT = "context"
    ERROR = "error"


@dataclass
class A2AMessage:
    """Agent-to-agent message."""
    id: str
    type: A2AMessageType
    sender_id: str
    content: Any
    content_type: A2AContentType = A2AContentType.TEXT
    recipient_id: Optional[str] = None
    reply_to: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    shared_context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    ttl: int = 10


@dataclass
class A2ACapability:
    """Agent capability advertisement."""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    returns: Dict[str, Any] = field(default_factory=dict)
    handler: Optional[Callable] = None


@dataclass
class A2ARequest:
    """Structured request content."""
    capability: str
    parameters: Dict[str, Any]
    timeout: float = 30.0


@dataclass
class A2AResponse:
    """Structured response content."""
    success: bool
    result: Any = None
    error: Optional[str] = None
