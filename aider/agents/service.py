"""
Shared agent service for session-scoped agent execution.
"""

from __future__ import annotations

from typing import Optional

from .executor import AgentExecutor
from .registry import AgentRegistry


class AutonomousAgentHandle:
    """Compatibility facade that routes autonomous work through AgentService."""

    def __init__(self, service, coder, max_turns: int = 5, max_cost: float = 2.0):
        self.service = service
        self.coder = coder
        self.max_turns = max_turns
        self.max_cost = max_cost

    def run_task(self, instruction, test_command=None):
        return self.service.run_autonomous_task(
            self.coder,
            instruction,
            test_command=test_command,
            max_turns=self.max_turns,
            max_cost=self.max_cost,
        )


class AgentService:
    """Owns the shared registry/executor pair for a session."""

    def __init__(self, io=None, registry: Optional[AgentRegistry] = None, max_concurrent: int = 5):
        self.io = io
        self.registry = registry or AgentRegistry(max_concurrent=max_concurrent)
        self.executor = AgentExecutor(self.registry, io)

    def configure(self, max_concurrent: Optional[int] = None):
        """Reconfigure the shared agent registry/executor for this session."""
        if max_concurrent is None or self.registry.max_concurrent == max_concurrent:
            return self

        self.registry = AgentRegistry(max_concurrent=max_concurrent)
        self.executor = AgentExecutor(self.registry, self.io)
        return self

    @property
    def a2a_bus(self):
        return self.registry.a2a_bus

    def create_autonomous_agent(self, coder, max_turns: int = 5, max_cost: float = 2.0):
        return AutonomousAgentHandle(
            self,
            coder,
            max_turns=max_turns,
            max_cost=max_cost,
        )

    def _build_autonomous_agent(self, coder, max_turns: int = 5, max_cost: float = 2.0):
        from .loop import AutonomousAgent

        return AutonomousAgent(coder, max_turns=max_turns, max_cost=max_cost)

    def run_autonomous_task(
        self,
        coder,
        instruction,
        test_command=None,
        max_turns: int = 5,
        max_cost: float = 2.0,
    ):
        """Run an autonomous task through the session-owned agent service."""
        agent = self._build_autonomous_agent(coder, max_turns=max_turns, max_cost=max_cost)
        return agent.run_task(instruction, test_command=test_command)
