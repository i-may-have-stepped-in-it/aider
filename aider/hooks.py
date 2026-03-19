"""
Compatibility shim for the unified hooks manager.

This module preserves the historical `aider.hooks` import surface while routing
all hook behavior through `aider.hooks_manager`.
"""

from .hooks_bootstrap import (
    create_hooks_manager,
    get_hooks_manager,
    reset_hooks_manager,
    set_hooks_manager,
)
from .hooks_manager import (
    Hook,
    HookConfig,
    HookPoint,
    HooksManager,
    hookable,
    hooks_disabled,
)

__all__ = [
    "Hook",
    "HookConfig",
    "HookPoint",
    "HooksManager",
    "create_hooks_manager",
    "get_hooks_manager",
    "hookable",
    "hooks_disabled",
    "reset_hooks_manager",
    "set_hooks_manager",
]
