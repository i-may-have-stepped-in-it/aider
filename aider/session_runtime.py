"""
Shared runtime services for a single aider session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from weakref import WeakSet

from aider.agents.service import AgentService
from aider.tools_v2.async_executor import AsyncExecutor


@dataclass
class ToolServices:
    """Session-owned tool infrastructure shared across routers."""

    async_executor: object
    compressor: object
    openclaw_client: object
    mcp_manager: object
    terminal_watcher: object
    resilient_executor: object
    sandbox: object
    cost_tracker: object
    sandbox_type: str = "auto"


@dataclass
class SessionRuntime:
    """Container for session-scoped shared services."""

    is_session_runtime = True

    io: object = None
    analytics: object = None
    hooks_manager: object = None
    skill_registry: object = None
    agent_service: object = None
    agent_registry: object = None
    a2a_bus: object = None
    async_executor: object = None
    tool_services: object = None
    semantic_index_service: object = None
    _bound_coders: object = None
    max_budget: float = 5.0

    def __post_init__(self):
        if self._bound_coders is None:
            self._bound_coders = WeakSet()
        if self.agent_service is None:
            self.agent_service = AgentService(io=self.io, registry=self.agent_registry)
        self.agent_registry = self.agent_service.registry
        if self.a2a_bus is None:
            self.a2a_bus = self.agent_service.a2a_bus
        if self.async_executor is None:
            self.async_executor = AsyncExecutor()
        self.bind_hooks_manager(self.hooks_manager)
        self.bind_skill_registry(self.skill_registry)
        self.bind_io(self.io)
        self.bind_analytics(self.analytics)

    @classmethod
    def create(
        cls,
        io=None,
        analytics=None,
        hooks_manager=None,
        skill_registry=None,
        async_executor=None,
        resolve_defaults=True,
        max_budget=5.0,
    ):
        """Create a session runtime with explicit default shared services."""
        if hooks_manager is None and resolve_defaults:
            from aider.hooks_manager import get_hooks_manager

            hooks_manager = get_hooks_manager()
        if skill_registry is None and resolve_defaults:
            from aider.skills.registry import get_registry

            skill_registry = get_registry()
        if async_executor is None:
            async_executor = AsyncExecutor()
        return cls(
            io=io,
            analytics=analytics,
            hooks_manager=hooks_manager,
            skill_registry=skill_registry,
            async_executor=async_executor,
            max_budget=max_budget,
        )

    def get_tool_services(self, sandbox_type="auto"):
        """Get or create the shared tool-service bundle for this session."""
        if self.tool_services is not None and getattr(self.tool_services, "sandbox_type", None) in (
            None,
            sandbox_type,
        ):
            return self.tool_services

        from aider.tools_v2.circuit_breaker import (
            BackoffStrategies,
            CircuitBreakers,
            RateLimiters,
            ResilientExecutor,
        )
        from aider.tools_v2.compression import SmartCompressor
        from aider.tools_v2.cost_tracker import AccurateCostTracker
        from aider.tools_v2.mcp_manager import MCPManager
        from aider.tools_v2.openclaw_client import OpenClawToolClient
        from aider.tools_v2.sandbox import create_sandbox
        from aider.tools_v2.terminal_watcher import TerminalWatcher

        services = ToolServices(
            async_executor=self.async_executor,
            compressor=SmartCompressor(),
            openclaw_client=OpenClawToolClient(),
            mcp_manager=MCPManager(),
            terminal_watcher=TerminalWatcher(),
            resilient_executor=ResilientExecutor(
            circuit_breaker=CircuitBreakers.tool_execution(),
            rate_limiter=RateLimiters.aggressive(),
            backoff=BackoffStrategies.standard(),
            ),
            sandbox=create_sandbox(sandbox_type),
            cost_tracker=AccurateCostTracker(
                max_budget=self.max_budget,
                hooks=self.hooks_manager,
            ),
            sandbox_type=sandbox_type,
        )
        self.tool_services = services
        return services

    def configure_agents(self, max_concurrent: Optional[int] = None):
        """Configure the shared agent service for this session."""
        self.agent_service.configure(max_concurrent=max_concurrent)
        self.agent_registry = self.agent_service.registry
        self.a2a_bus = self.agent_service.a2a_bus
        self.bind_io(self.io)
        self._sync_bound_coders()
        return self.agent_service

    def bind_io(self, io):
        """Bind the active session IO object across runtime-owned services."""
        self.io = io

        if self.hooks_manager is not None:
            self.hooks_manager.io = io

        if self.agent_service is not None:
            self.agent_service.io = io
            if getattr(self.agent_service, "executor", None) is not None:
                self.agent_service.executor.io = io

        if self.tool_services is not None and getattr(self.tool_services, "cost_tracker", None) is not None:
            self.tool_services.cost_tracker.hooks = self.hooks_manager

        self._sync_bound_coders()

        return io

    def bind_analytics(self, analytics):
        """Bind the active session analytics object for this runtime."""
        self.analytics = analytics
        self._sync_bound_coders()
        return analytics

    def bind_hooks_manager(self, hooks_manager):
        """Bind the active hooks manager for this runtime."""
        self.hooks_manager = hooks_manager
        if self.hooks_manager is not None:
            self.hooks_manager.io = self.io
        if self.tool_services is not None and getattr(self.tool_services, "cost_tracker", None) is not None:
            self.tool_services.cost_tracker.hooks = hooks_manager
        self._sync_bound_coders()
        return hooks_manager

    def bind_skill_registry(self, skill_registry):
        """Bind the active skill registry for this runtime."""
        self.skill_registry = skill_registry
        self._sync_bound_coders()
        return skill_registry

    def bind_coder(self, coder):
        """Register a coder that should track this runtime's shared services."""
        self._bound_coders.add(coder)
        self._sync_coder(coder)
        return coder

    def _sync_bound_coders(self):
        for coder in list(self._bound_coders):
            self._sync_coder(coder)

    def _sync_coder(self, coder):
        sync = getattr(coder, "_sync_runtime_services", None)
        if callable(sync):
            sync()

    def get_tool_router(self, commands, io, coder, config=None):
        """
        Get or create a ToolRouterV2 instance bound to this runtime.

        This method ensures that the tool router consumes runtime-owned services
        rather than assembling its own infrastructure.

        Args:
            commands: The Commands instance
            io: The InputOutput instance
            coder: The Coder instance
            config: Optional RouterConfig

        Returns:
            ToolRouterV2 instance
        """
        from aider.tools_v2.router import ToolRouterV2

        return ToolRouterV2(
            commands=commands,
            io=io,
            coder=coder,
            config=config,
            runtime=self,
        )
