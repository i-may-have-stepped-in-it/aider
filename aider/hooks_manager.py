#!/usr/bin/env python3
"""
Hooks Manager - Hook system for OpenClaw skills integration with Aider.

Provides a flexible hook system that allows OpenClaw skills to:
- Register hooks at various lifecycle points
- Execute custom code before/after Aider operations
- Configure hook behavior via metadata
"""

import collections
import functools
import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set

from aider.openclaw_bridge import OpenClawBridge, SkillExecutionResult

logger = logging.getLogger(__name__)


class HookPoint(Enum):
    """Lifecycle points where hooks can be registered."""

    # Pre-operation hooks
    PRE_COMMIT = auto()  # Before committing changes
    PRE_EDIT = auto()  # Before editing files
    PRE_COMMAND = auto()  # Before executing a command
    PRE_MESSAGE = auto()  # Before sending message to LLM
    PRE_SUMMARIZE = auto()  # Before summarizing chat history

    # Post-operation hooks
    POST_COMMIT = auto()  # After committing changes
    POST_EDIT = auto()  # After editing files
    POST_COMMAND = auto()  # After executing a command
    POST_MESSAGE = auto()  # After receiving LLM response
    POST_SUMMARIZE = auto()  # After summarizing chat history

    # Lifecycle hooks
    SESSION_START = auto()  # When Aider session starts
    SESSION_END = auto()  # When Aider session ends
    FILE_ADDED = auto()  # When a file is added to context
    MODEL_SWITCH = auto()  # When model is switched

    # Error hooks
    ON_ERROR = auto()  # When an error occurs
    ON_VALIDATION_FAIL = auto()  # When validation fails

    # UI Hooks (Event-Driven UX)
    UI_PHASE_UPDATE = auto()  # Autonomous phase change (Librarian, Architect, etc.)
    UI_COST_UPDATE = auto()  # Real-time cost change
    UI_AGENT_HEARTBEAT = auto()  # Sub-agent status update
    UI_TOOL_PROGRESS = auto()  # Granular tool progress update
    UI_POLICY_CHECK = auto()  # Security policy scan result


@dataclass
class HookConfig:
    """Configuration for a hook."""

    enabled: bool = True
    priority: int = 100  # Lower numbers run first
    async_execution: bool = False  # Whether to run asynchronously
    timeout: int = 30  # Timeout in seconds
    condition: Optional[str] = None  # Optional condition expression
    retry_count: int = 0  # Number of retries on failure
    retry_delay: float = 1.0  # Delay between retries
    name: Optional[str] = None  # Hook name for identification
    stop_on_failure: bool = False  # Stop execution if this hook fails
    depends_on: Optional[list] = None  # List of hook names this depends on

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HookConfig":
        """Create HookConfig from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            priority=data.get("priority", 100),
            async_execution=data.get("async_execution", False),
            timeout=data.get("timeout", 30),
            condition=data.get("condition"),
            retry_count=data.get("retry_count", 0),
            retry_delay=data.get("retry_delay", 1.0),
        )


@dataclass
class Hook:
    """Represents a registered hook."""

    name: str
    hook_point: HookPoint
    callback: Callable[..., Any]
    config: HookConfig
    skill_name: Optional[str] = None
    description: str = ""

    def __post_init__(self):
        """Validate hook configuration."""
        if not callable(self.callback):
            raise ValueError(f"Hook callback must be callable: {self.callback}")


class HooksManager:
    """
    Manager for OpenClaw skill hooks in Aider.

    Handles registration, configuration, and execution of hooks from skills.
    """

    def __init__(
        self,
        bridge: Optional[OpenClawBridge] = None,
        io=None,
        verbose: bool = False,
    ):
        """
        Initialize the hooks manager.

        Args:
            bridge: Optional OpenClawBridge instance.
        """
        self.bridge = bridge or OpenClawBridge()
        self.io = io
        self.verbose = verbose
        self._hooks: Dict[HookPoint, List[Hook]] = {hp: [] for hp in HookPoint}
        self._skill_hooks: Dict[str, Set[str]] = {}  # skill_name -> hook_names
        self._execution_history: collections.deque = collections.deque(maxlen=500)
        self._enabled = True
        self.loaded_modules: List[str] = []
        self.skills_enabled = False
        self.skills_path: Optional[str] = None

        logger.debug("HooksManager initialized")

    def log(self, message: str, error: bool = False):
        """Log a message if verbose mode is enabled."""
        if self.verbose and self.io:
            if error:
                self.io.tool_error(f"[hooks] {message}")
            else:
                self.io.tool_output(f"[hooks] {message}")

    def _hook_point_from_name(self, hook_name: str) -> HookPoint:
        """Map legacy hook names to HookPoint values."""
        hook_map = {
            "pre_command": HookPoint.PRE_COMMAND,
            "post_command": HookPoint.POST_COMMAND,
            "pre_edit": HookPoint.PRE_EDIT,
            "post_edit": HookPoint.POST_EDIT,
            "on_init": HookPoint.SESSION_START,
            "on_exit": HookPoint.SESSION_END,
            "pre_send": HookPoint.PRE_MESSAGE,
            "post_send": HookPoint.POST_MESSAGE,
            "pre_summarize": HookPoint.PRE_SUMMARIZE,
            "post_summarize": HookPoint.POST_SUMMARIZE,
        }
        return hook_map[hook_name]

    def register(self, hook_name: str, callback: Callable) -> bool:
        """Legacy registration API used by hook files."""
        try:
            hook_point = self._hook_point_from_name(hook_name)
        except KeyError:
            self.log(f"Unknown hook: {hook_name}", error=True)
            return False

        try:
            self.register_hook(
                name=(
                    f"{hook_name}:{getattr(callback, '__module__', 'unknown')}:"
                    f"{getattr(callback, '__qualname__', getattr(callback, '__name__', 'callback'))}:"
                    f"{id(callback)}"
                ),
                hook_point=hook_point,
                callback=callback,
                config=HookConfig(name=hook_name),
            )
        except ValueError as err:
            self.log(str(err), error=True)
            return False

        self.log(f"Registered callback for {hook_name}")
        return True

    def unregister(self, hook_name: str, callback: Callable) -> bool:
        """Legacy unregister API used by hook files."""
        try:
            hook_point = self._hook_point_from_name(hook_name)
        except KeyError:
            return False

        hooks = self._hooks.get(hook_point, [])
        for index, hook in enumerate(hooks):
            if hook.callback == callback:
                hooks.pop(index)
                self.log(f"Unregistered callback from {hook_name}")
                return True

        return False

    def register_hook(
        self,
        name: str,
        hook_point: HookPoint,
        callback: Callable[..., Any],
        config: Optional[HookConfig] = None,
        skill_name: Optional[str] = None,
        description: str = "",
    ) -> Hook:
        """
        Register a new hook.

        Args:
            name: Unique name for the hook.
            hook_point: Lifecycle point to hook into.
            callback: Function to call when hook fires.
            config: Optional hook configuration.
            skill_name: Optional source skill name.
            description: Optional description.

        Returns:
            The registered Hook object.

        Raises:
            ValueError: If hook with same name already registered.
        """
        # Check for duplicates
        for hooks in self._hooks.values():
            for hook in hooks:
                if hook.name == name:
                    raise ValueError(f"Hook '{name}' already registered")

        hook = Hook(
            name=name,
            hook_point=hook_point,
            callback=callback,
            config=config or HookConfig(),
            skill_name=skill_name,
            description=description,
        )

        self._hooks[hook_point].append(hook)

        # Sort by priority
        self._hooks[hook_point].sort(key=lambda h: h.config.priority)

        # Track skill hooks
        if skill_name:
            if skill_name not in self._skill_hooks:
                self._skill_hooks[skill_name] = set()
            self._skill_hooks[skill_name].add(name)

        logger.debug(f"Registered hook '{name}' at {hook_point.name}")
        return hook

    def register_ui_observer(self, observer: Any) -> None:
        """
        Register a TerminalUIObserver to handle UI-specific events.

        Args:
            observer: Object implementing TerminalUIObserver interface.
        """
        from .hooks_manager import HookConfig

        # 1. Phase Updates
        if hasattr(observer, "on_phase_change"):
            self.register_hook(
                name=f"ui:phase:{id(observer)}",
                hook_point=HookPoint.UI_PHASE_UPDATE,
                callback=observer.on_phase_change,
            )

        # 2. Cost Updates
        if hasattr(observer, "on_cost_update"):
            self.register_hook(
                name=f"ui:cost:{id(observer)}",
                hook_point=HookPoint.UI_COST_UPDATE,
                callback=observer.on_cost_update,
            )

        # 3. Agent Updates
        if hasattr(observer, "on_agent_status"):
            self.register_hook(
                name=f"ui:agent:{id(observer)}",
                hook_point=HookPoint.UI_AGENT_HEARTBEAT,
                callback=observer.on_agent_status,
            )

        # 4. Tool Progress
        if hasattr(observer, "on_tool_progress"):
            self.register_hook(
                name=f"ui:tool:{id(observer)}",
                hook_point=HookPoint.UI_TOOL_PROGRESS,
                callback=observer.on_tool_progress,
            )

        # 5. Policy Checks
        if hasattr(observer, "on_policy_check"):
            self.register_hook(
                name=f"ui:policy:{id(observer)}",
                hook_point=HookPoint.UI_POLICY_CHECK,
                callback=observer.on_policy_check,
            )

    def unregister_hook(self, name: str) -> bool:
        """
        Unregister a hook by name.

        Args:
            name: Name of the hook to unregister.

        Returns:
            True if hook was found and removed.
        """
        for hook_point, hooks in self._hooks.items():
            for i, hook in enumerate(hooks):
                if hook.name == name:
                    hooks.pop(i)

                    # Update skill tracking
                    if hook.skill_name and hook.skill_name in self._skill_hooks:
                        self._skill_hooks[hook.skill_name].discard(name)

                    logger.debug(f"Unregistered hook '{name}'")
                    return True

        return False

    def unregister_skill_hooks(self, skill_name: str) -> int:
        """
        Unregister all hooks from a specific skill.

        Args:
            skill_name: Name of the skill.

        Returns:
            Number of hooks unregistered.
        """
        count = 0

        for hooks in self._hooks.values():
            to_remove = [h for h in hooks if h.skill_name == skill_name]
            for hook in to_remove:
                hooks.remove(hook)
                count += 1

        if skill_name in self._skill_hooks:
            del self._skill_hooks[skill_name]

        logger.debug(f"Unregistered {count} hooks from skill '{skill_name}'")
        return count

    def execute_hooks(
        self,
        hook_point: HookPoint,
        context: Optional[Dict[str, Any]] = None,
        stop_on_error: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Execute all hooks at a given hook point.

        Args:
            hook_point: The lifecycle point.
            context: Optional context data to pass to hooks.
            stop_on_error: Whether to stop on first error.

        Returns:
            List of execution results for each hook.
        """
        if not self._enabled:
            return []

        context = context or {}
        results = []
        hooks = self._hooks.get(hook_point, [])
        executed_hooks = set()  # Track executed hook names for dependencies

        for hook in hooks:
            if not hook.config.enabled:
                continue

            # Check dependencies
            if hook.config.depends_on:
                deps_satisfied = all(dep in executed_hooks for dep in hook.config.depends_on)
                if not deps_satisfied:
                    continue

            # Check condition
            if hook.config.condition and not self._evaluate_condition(
                hook.config.condition, context
            ):
                continue

            result = self._execute_hook(hook, context)
            results.append(result)

            # Track executed hook by name
            if hook.config.name:
                executed_hooks.add(hook.config.name)

            # Check stop conditions
            if not result.get("success"):
                if stop_on_error or hook.config.stop_on_failure:
                    break

        return results

    def execute(self, hook_name: str, *args, **kwargs) -> Dict[str, Any]:
        """
        Compatibility wrapper matching the legacy hooks API.

        Returns:
            Aggregated result dictionary compatible with aider/hooks.py.
        """
        results = {
            "hook_name": hook_name,
            "executed": False,
            "callbacks": [],
            "errors": [],
            "data": {},
        }

        try:
            hook_point = self._hook_point_from_name(hook_name)
        except KeyError:
            if self.verbose and self.io:
                self.io.tool_error(f"[hooks] Unknown hook: {hook_name}")
            return results

        context = kwargs.copy()
        if args:
            context["args"] = args

        hook_results = self.execute_hooks(hook_point, context)
        if not hook_results:
            return results

        results["executed"] = True
        for result in hook_results:
            results["callbacks"].append(result)
            if result.get("success"):
                callback_result = result.get("result")
                if isinstance(callback_result, dict):
                    results["data"].update(callback_result)
            else:
                results["errors"].append(
                    {
                        "error": result.get("error"),
                        "hook_name": result.get("hook_name"),
                    }
                )

        return results

    def load_hooks_from_file(self, file_path: str) -> bool:
        """Compatibility wrapper for legacy hook loading."""
        from .hooks_bootstrap import load_hooks_from_file

        return load_hooks_from_file(self, file_path)

    def load_hooks_from_directory(self, dir_path: str) -> int:
        """Compatibility wrapper for legacy hook directory loading."""
        from .hooks_bootstrap import load_hooks_from_directory

        return load_hooks_from_directory(self, dir_path)

    def load_skills(self, skills_path: str) -> bool:
        """Compatibility wrapper for legacy hook-style skill loading."""
        from .hooks_bootstrap import load_skills

        return load_skills(self, skills_path)

    def get_loaded_modules(self) -> List[str]:
        """Return list of loaded legacy hook module paths."""
        return self.loaded_modules.copy()

    def is_hook_enabled(self, hook_name: str) -> bool:
        """Legacy hook availability check."""
        try:
            hook_point = self._hook_point_from_name(hook_name)
        except KeyError:
            return False

        return bool(self._hooks.get(hook_point))

    def _execute_hook(
        self,
        hook: Hook,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a single hook with retry logic."""
        import time

        start_time = time.time()
        last_error = None

        for attempt in range(hook.config.retry_count + 1):
            try:
                if hook.config.async_execution:
                    # For async hooks, we'd use asyncio - simplified here
                    result = hook.callback(context)
                else:
                    result = hook.callback(context)

                execution_result = {
                    "hook_name": hook.name,
                    "hook_point": hook.hook_point.name,
                    "success": True,
                    "result": result,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "attempt": attempt + 1,
                }

                self._execution_history.append(execution_result)
                logger.debug(f"Hook '{hook.name}' executed successfully")
                return execution_result

            except Exception as e:
                last_error = e
                logger.warning(f"Hook '{hook.name}' failed (attempt {attempt + 1}): {e}")

                if attempt < hook.config.retry_count:
                    time.sleep(hook.config.retry_delay)

        # All attempts failed
        execution_result = {
            "hook_name": hook.name,
            "hook_point": hook.hook_point.name,
            "success": False,
            "error": str(last_error),
            "duration_ms": int((time.time() - start_time) * 1000),
            "attempt": hook.config.retry_count + 1,
        }

        self._execution_history.append(execution_result)
        return execution_result

    def _evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """Evaluate a condition expression using safe AST parsing.

        SECURITY: Uses AST parsing instead of eval() to prevent code injection.
        """
        import ast

        # Allowed AST node types for safe expression evaluation
        ALLOWED_NODES = (
            ast.Expression,
            ast.BoolOp,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
            ast.Name,
            ast.Constant,
            ast.Load,
            ast.And,
            ast.Or,
            ast.Not,
            ast.Eq,
            ast.NotEq,
            ast.Lt,
            ast.LtE,
            ast.Gt,
            ast.GtE,
            ast.In,
            ast.NotIn,
            ast.Is,
            ast.IsNot,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.Mod,
            ast.List,
            ast.Tuple,
            ast.Dict,
            ast.Subscript,
            ast.IfExp,
        )

        try:
            tree = ast.parse(condition, mode="eval")

            # Validate only allowed node types
            for node in ast.walk(tree):
                if not isinstance(node, ALLOWED_NODES):
                    logger.warning(f"Disallowed node type in condition: {type(node).__name__}")
                    return False  # Fail closed

            # Create restricted namespace with context
            namespace = {
                "__builtins__": {},
                "context": context,
            }

            result = eval(compile(tree, "<condition>", "eval"), namespace, {})
            return bool(result)

        except Exception as e:
            logger.warning(f"Condition evaluation failed: {e}")
            return False  # Fail closed - don't execute if condition can't be evaluated

    def register_skill_hooks(self, skill_name: str) -> List[Hook]:
        """
        Auto-register hooks from a skill's metadata.

        Args:
            skill_name: Name of the skill.

        Returns:
            List of registered hooks.
        """
        metadata = self.bridge.load_skill_metadata(skill_name)
        if not metadata:
            logger.warning(f"Cannot register hooks for unknown skill: {skill_name}")
            return []

        hooks = []
        raw_hooks = metadata.raw_metadata.get("hooks", [])

        if not raw_hooks:
            return hooks

        for hook_def in raw_hooks:
            try:
                hook_point = HookPoint[hook_def.get("hook_point", "PRE_COMMAND")]
                action = hook_def.get("action", "run")

                # Create a callback that executes the skill
                def make_callback(skill: str, act: str):
                    def callback(context: Dict[str, Any]) -> SkillExecutionResult:
                        return self.bridge.execute_skill(
                            skill,
                            act,
                            env_vars={
                                "HOOK_CONTEXT": str(context),
                            },
                        )

                    return callback

                config = HookConfig.from_dict(hook_def.get("config", {}))

                hook = self.register_hook(
                    name=f"{skill_name}:{hook_def.get('name', action)}",
                    hook_point=hook_point,
                    callback=make_callback(skill_name, action),
                    config=config,
                    skill_name=skill_name,
                    description=hook_def.get("description", ""),
                )
                hooks.append(hook)

            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to register hook from {skill_name}: {e}")

        return hooks

    def get_hooks(self, hook_point: Optional[HookPoint] = None) -> List[Hook]:
        """
        Get registered hooks.

        Args:
            hook_point: Optional filter by hook point.

        Returns:
            List of hooks.
        """
        if hook_point:
            return self._hooks.get(hook_point, []).copy()

        all_hooks = []
        for hooks in self._hooks.values():
            all_hooks.extend(hooks)
        return all_hooks

    def get_skill_hooks(self, skill_name: str) -> List[Hook]:
        """
        Get all hooks registered by a specific skill.

        Args:
            skill_name: Name of the skill.

        Returns:
            List of hooks from that skill.
        """
        return [
            hook
            for hooks in self._hooks.values()
            for hook in hooks
            if hook.skill_name == skill_name
        ]

    def enable(self):
        """Enable hook execution."""
        self._enabled = True
        logger.debug("HooksManager enabled")

    def disable(self):
        """Disable hook execution."""
        self._enabled = False
        logger.debug("HooksManager disabled")

    def is_enabled(self) -> bool:
        """Check if hooks are enabled."""
        return self._enabled

    def get_execution_history(self) -> List[Dict[str, Any]]:
        """Get history of hook executions."""
        return self._execution_history.copy()

    def clear_execution_history(self):
        """Clear execution history."""
        self._execution_history.clear()

    def create_decorator(
        self,
        hook_point: HookPoint,
        config: Optional[HookConfig] = None,
        **kwargs,
    ):
        """
        Create a decorator for registering function hooks.

        Args:
            hook_point: The lifecycle point.
            config: Optional hook configuration.
            **kwargs: Additional hook attributes.

        Returns:
            Decorator function.
        """

        def decorator(func: Callable) -> Callable:
            hook_name = kwargs.get("name", func.__name__)

            self.register_hook(
                name=hook_name,
                hook_point=hook_point,
                callback=func,
                config=config,
                description=kwargs.get("description", func.__doc__ or ""),
            )

            return func

        return decorator


# Context manager for temporary hook disabling
class hooks_disabled:
    """Context manager to temporarily disable hooks."""

    def __init__(self, manager: HooksManager):
        self.manager = manager

    def __enter__(self):
        self.was_enabled = self.manager.is_enabled()
        self.manager.disable()
        return self

    def __exit__(self, *args):
        if self.was_enabled:
            self.manager.enable()
        return False


# Decorator for hooking functions
def hookable(
    hook_point_pre: Optional[HookPoint] = None,
    hook_point_post: Optional[HookPoint] = None,
):
    """
    Decorator to make a function hookable.

    Args:
        hook_point_pre: Hook point to trigger before execution.
        hook_point_post: Hook point to trigger after execution.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get hooks manager from args or global
            manager = kwargs.pop("_hooks_manager", None)

            context = {
                "function": func.__name__,
                "args": args,
                "kwargs": kwargs,
            }

            # Pre-hook
            if manager and hook_point_pre:
                manager.execute_hooks(hook_point_pre, context)

            # Execute function
            result = func(*args, **kwargs)
            context["result"] = result

            # Post-hook
            if manager and hook_point_post:
                manager.execute_hooks(hook_point_post, context)

            return result

        return wrapper

    return decorator


def get_hooks_manager(bridge: Optional[OpenClawBridge] = None) -> HooksManager:
    """Compatibility export for the hook bootstrap singleton."""
    from .hooks_bootstrap import get_hooks_manager

    return get_hooks_manager(bridge)


def set_hooks_manager(manager: Optional[HooksManager]):
    """Compatibility export for the hook bootstrap singleton."""
    from .hooks_bootstrap import set_hooks_manager

    return set_hooks_manager(manager)


def create_hooks_manager(io=None, verbose: bool = False, bridge: Optional[OpenClawBridge] = None):
    """Compatibility export for the hook bootstrap singleton."""
    from .hooks_bootstrap import create_hooks_manager

    return create_hooks_manager(io=io, verbose=verbose, bridge=bridge)


def reset_hooks_manager():
    """Compatibility export for the hook bootstrap singleton."""
    from .hooks_bootstrap import reset_hooks_manager

    return reset_hooks_manager()
