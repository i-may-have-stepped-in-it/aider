"""
Aider Tool System v2 - Production-Ready Agent Infrastructure

This package provides a complete, production-grade tool system for Aider
enabling autonomous agent behavior with:

- Secure sandboxed execution
- Accurate cost tracking with overhead
- Circuit breakers and rate limiting
- Semantic output compression
- Comprehensive observability

Key Components:
    AsyncExecutor: Proper async/sync boundary management
    Sandbox: Secure command execution (firejail/unshare)
    ToolRouterV2: Resilient tool routing with full error handling
    AccurateCostTracker: Production-grade cost management
    CircuitBreaker: Failure isolation and recovery
    SmartCompressor: Semantic output compression

Usage:
    from aider.tools_v2 import ToolRouterV2, create_sandbox
    
    router = ToolRouterV2(commands, io, coder)
    result = router.execute("run", {"command": "pytest"})

Migration from v1:
    v1: from aider.tools import ToolRouter
    v2: from aider.tools_v2 import ToolRouterV2
    
    v2 is a complete rewrite with incompatible but improved API.
"""

from .async_executor import (
    AsyncExecutor,
    async_context,
    run_async,
    CancellableTask,
    ExecutionTimeoutError,
    AsyncExecutionError,
)
from .sandbox import (
    create_sandbox,
    Sandbox,
    SandboxResult,
    
    FirejailSandbox,
    AdvancedUnshareSandbox,
    UnshareSandbox,
    MinimalSandbox,
)
from .router import ToolRouterV2, ToolExecutionResult
from .cost_tracker import AccurateCostTracker, CostBreakdown
from .circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    TokenBucket,
    ExponentialBackoff,
    ResilientExecutor,
)
from .compression import (
    SmartCompressor,
    CompressionResult,
    OutputType,
    OutputCompressor,
)

__version__ = "2.0.0"

__all__ = [
    # Async execution
    "AsyncExecutor",
    "async_context",
    "run_async",
    "CancellableTask",
    "ExecutionTimeoutError",
    "AsyncExecutionError",
    
    # Sandboxing
    "Sandbox",
    "SandboxResult",
    "create_sandbox",
    
    "FirejailSandbox",
    "AdvancedUnshareSandbox",
    "UnshareSandbox",
    "MinimalSandbox",
    
    # Tool routing
    "ToolRouterV2",
    "ToolExecutionResult",
    
    # Cost tracking
    "AccurateCostTracker",
    "CostBreakdown",
    
    # Resilience
    "CircuitBreaker",
    "CircuitState",
    "TokenBucket",
    "ExponentialBackoff",
    "ResilientExecutor",
    
    # Compression
    "SmartCompressor",
    "CompressionResult",
    "OutputType",
    "OutputCompressor",
]
