"""
Compatibility shim for the unified hooks manager.

This package-level import path mirrors `aider.hooks` and keeps older imports
working while using the single implementation in `aider.hooks_manager`.
"""

from ..hooks_manager import (
    Hook,
    HookConfig,
    HookPoint,
    HooksManager,
    create_hooks_manager,
    get_hooks_manager,
    hookable,
    hooks_disabled,
    reset_hooks_manager,
    set_hooks_manager,
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
