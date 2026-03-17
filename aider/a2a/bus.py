"""A2A message bus for intra-process agent communication."""
import asyncio
import logging
from typing import Dict, List, Callable, Set, Optional
from .types import A2AMessage, A2AMessageType

logger = logging.getLogger(__name__)


class A2AMessageBus:
    """
    Message bus for agent-to-agent communication.
    Always available - agents can communicate by default.
    """
    
    def __init__(self, max_history: int = 1000):
        self._handlers: Dict[str, List[Callable]] = {}
        self._topics: Dict[str, Set[str]] = {}
        self._history: List[A2AMessage] = []
        self._max_history = max_history
        self._lock = asyncio.Lock()
    
    def register(self, agent_id: str, handler: Callable[[A2AMessage], None]):
        """Register an agent to receive messages."""
        if agent_id not in self._handlers:
            self._handlers[agent_id] = []
        self._handlers[agent_id].append(handler)
        logger.debug(f"Registered agent {agent_id} on A2A bus")
    
    def unregister(self, agent_id: str):
        """Unregister an agent."""
        self._handlers.pop(agent_id, None)
        for topic, agents in self._topics.items():
            agents.discard(agent_id)
        logger.debug(f"Unregistered agent {agent_id} from A2A bus")
    
    async def send(self, message: A2AMessage) -> bool:
        """Send a message to recipient(s)."""
        async with self._lock:
            self._history.append(message)
            if len(self._history) > self._max_history:
                self._history.pop(0)
        
        if message.type == A2AMessageType.BROADCAST:
            return await self._broadcast(message)
        elif message.recipient_id:
            return await self._send_direct(message)
        else:
            return await self._broadcast(message)
    
    async def _send_direct(self, message: A2AMessage) -> bool:
        """Send to specific agent."""
        handlers = self._handlers.get(message.recipient_id, [])
        if not handlers:
            logger.warning(f"No handlers for agent {message.recipient_id}")
            return False
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.error(f"A2A handler error: {e}")
        
        return True
    
    async def _broadcast(self, message: A2AMessage) -> bool:
        """Broadcast to all agents except sender."""
        delivered = False
        for agent_id, handlers in self._handlers.items():
            if agent_id == message.sender_id:
                continue
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(message)
                    else:
                        handler(message)
                    delivered = True
                except Exception as e:
                    logger.error(f"A2A broadcast error: {e}")
        return delivered
    
    def subscribe(self, agent_id: str, topic: str):
        """Subscribe agent to a topic."""
        if topic not in self._topics:
            self._topics[topic] = set()
        self._topics[topic].add(agent_id)
    
    def get_history(self, 
                    agent_id: Optional[str] = None,
                    since: Optional[float] = None) -> List[A2AMessage]:
        """Get message history."""
        messages = self._history.copy()
        if agent_id:
            messages = [m for m in messages 
                       if m.sender_id == agent_id or m.recipient_id == agent_id]
        if since:
            messages = [m for m in messages if m.timestamp >= since]
        return messages
