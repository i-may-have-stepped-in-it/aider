"""
Agent registry for tracking and managing sub-agents.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .agent import SubAgent, AgentStatus

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()



class CircuitBreaker:
    """Circuit breaker for agent execution - Issue 15."""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
    
    @property
    def state(self):
        if self._state == CircuitState.OPEN and (time.time() - self._last_failure_time >= self.recovery_timeout):
            self._state = CircuitState.HALF_OPEN
        return self._state
    
    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.HALF_OPEN:
            return True
        return False
    
    def record_success(self):
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
    
    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

class AgentRegistry:
    """
    Thread-safe registry for tracking sub-agents.
    
    Similar to kimi-cli's LaborMarket but adapted for Aider's architecture.
    A2A is always enabled - no flag needed.
    """
    
    def __init__(self, max_concurrent: int = 5, enable_acp: bool = False):
        self._agents: dict[str, SubAgent] = {}
        self._lock = asyncio.Lock()
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        
        # A2A is always available
        from ..a2a.bus import A2AMessageBus
        self._a2a_bus = A2AMessageBus()
        
        # ACP support (editor integration) - optional
        self._acp_server = None
    
    @property
    def a2a_bus(self):
        """A2A bus is always available."""
        return self._a2a_bus
    
    async def register(self, agent: SubAgent) -> None:
        """Register a new sub-agent."""
        async with self._lock:
            self._agents[agent.id] = agent
            logger.debug(f"Registered agent {agent.id}")
    
    async def unregister(self, agent_id: str) -> Optional[SubAgent]:
        """Unregister a sub-agent."""
        async with self._lock:
            agent = self._agents.pop(agent_id, None)
            if agent:
                logger.debug(f"Unregistered agent {agent_id}")
            return agent
    
    async def get(self, agent_id: str) -> Optional[SubAgent]:
        """Get a sub-agent by ID."""
        async with self._lock:
            return self._agents.get(agent_id)
    
    async def list_agents(
        self,
        status: Optional[AgentStatus] = None,
    ) -> list[SubAgent]:
        """List all agents, optionally filtered by status."""
        async with self._lock:
            agents = list(self._agents.values())
            if status:
                agents = [a for a in agents if a.status == status]
            return agents
    
    async def list_active(self) -> list[SubAgent]:
        """List all active (pending or running) agents."""
        from .agent import AgentStatus
        async with self._lock:
            return [
                a for a in self._agents.values()
                if a.status in (AgentStatus.PENDING, AgentStatus.RUNNING)
            ]
    
    async def count(self, status: Optional[AgentStatus] = None) -> int:
        """Count agents, optionally filtered by status."""
        agents = await self.list_agents(status)
        return len(agents)
    
    async def wait_for_completion(
        self,
        agent_id: str,
        timeout: Optional[float] = None,
        poll_interval: float = 0.5,
    ) -> SubAgent:
        """
        Wait for an agent to complete.
        
        Args:
            agent_id: ID of agent to wait for
            timeout: Maximum time to wait (None = forever)
            poll_interval: How often to check status
            
        Returns:
            The completed agent
            
        Raises:
            TimeoutError: If timeout is reached
        """
        start_time = time.time()
        
        while True:
            agent = await self.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")
            
            if not agent.is_active:
                return agent
            
            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(f"Timeout waiting for agent {agent_id}")
            
            await asyncio.sleep(poll_interval)
    
    async def wait_for_all(
        self,
        timeout: Optional[float] = None,
        poll_interval: float = 0.5,
    ) -> list[SubAgent]:
        """Wait for all active agents to complete."""
        start_time = time.time()
        
        while True:
            active = await self.list_active()
            if not active:
                return await self.list_agents()
            
            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError("Timeout waiting for agents")
            
            await asyncio.sleep(poll_interval)
    
    async def cancel(self, agent_id: str) -> bool:
        """Cancel a running agent."""
        agent = await self.get(agent_id)
        if not agent:
            return False
        
        from .agent import AgentStatus
        if agent.status != AgentStatus.RUNNING:
            return False
        
        # Cancel the agent's task if it has one
        if hasattr(agent, '_task') and agent._task:
            agent._task.cancel()
            try:
                await agent._task
            except asyncio.CancelledError:
                pass
        
        agent.status = AgentStatus.CANCELLED
        agent.completed_at = time.time()
        logger.info(f"Cancelled agent {agent_id}")
        return True
    
    async def cancel_all(self) -> list[str]:
        """Cancel all active agents. Returns list of cancelled IDs."""
        active = await self.list_active()
        cancelled = []
        for agent in active:
            if await self.cancel(agent.id):
                cancelled.append(agent.id)
        return cancelled
    
    def acquire_slot(self) -> asyncio.Semaphore:
        """Acquire a slot for concurrent execution."""
        return self._semaphore
    
    @property
    def max_concurrent(self) -> int:
        """Get maximum concurrent agents."""
        return self._max_concurrent
    
    async def get_stats(self) -> dict:
        """Get registry statistics."""
        from .agent import AgentStatus
        return {
            "total": await self.count(),
            "pending": await self.count(AgentStatus.PENDING),
            "running": await self.count(AgentStatus.RUNNING),
            "completed": await self.count(AgentStatus.COMPLETED),
            "error": await self.count(AgentStatus.ERROR),
            "cancelled": await self.count(AgentStatus.CANCELLED),
            "max_concurrent": self._max_concurrent,
        }
