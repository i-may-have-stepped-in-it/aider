"""
Hooks system for Aider.

This module provides a hooks framework that allows users to extend Aider's
functionality by executing custom code at specific points in the lifecycle.

Hooks can be loaded from directories or individual files and are executed
in a sandboxed manner with proper error handling.
"""

import importlib.util
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class HookError(Exception):
    """Exception raised when a hook fails to execute."""

    pass


class HooksManager:
    """
    Manager for Aider hooks.

    Provides lifecycle hooks at key points:
    - Command execution (before/after)
    - Message sending (before LLM call)
    - Edit application (before/after)
    - Chat summarization (before/after)
    """

    def __init__(self, io=None, verbose: bool = False):
        """
        Initialize the hooks manager.

        Args:
            io: InputOutput instance for logging
            verbose: Enable verbose logging
        """
        self.io = io
        self.verbose = verbose
        self.hooks: Dict[str, List[Callable]] = {
            # Command hooks
            "pre_command": [],
            "post_command": [],
            # Message/LLM hooks
            "pre_send": [],
            "post_send": [],
            # Edit hooks
            "pre_edit": [],
            "post_edit": [],
            # Summarization hooks
            "pre_summarize": [],
            "post_summarize": [],
            # Initialization hooks
            "on_init": [],
            "on_exit": [],
        }
        self.loaded_modules: List[str] = []
        self.skills_enabled = False
        self.skills_path: Optional[str] = None

    def log(self, message: str, error: bool = False):
        """Log a message if verbose mode is enabled."""
        if self.verbose and self.io:
            if error:
                self.io.tool_error(f"[hooks] {message}")
            else:
                self.io.tool_output(f"[hooks] {message}")

    def register(self, hook_name: str, callback: Callable) -> bool:
        """
        Register a callback for a specific hook.

        Args:
            hook_name: Name of the hook point
            callback: Function to call when hook is triggered

        Returns:
            True if registration succeeded, False otherwise
        """
        if hook_name not in self.hooks:
            self.log(f"Unknown hook: {hook_name}", error=True)
            return False

        if not callable(callback):
            self.log(f"Hook callback must be callable: {callback}", error=True)
            return False

        self.hooks[hook_name].append(callback)
        self.log(f"Registered callback for {hook_name}")
        return True

    def unregister(self, hook_name: str, callback: Callable) -> bool:
        """
        Unregister a callback from a hook.

        Args:
            hook_name: Name of the hook point
            callback: Function to remove

        Returns:
            True if unregistration succeeded, False otherwise
        """
        if hook_name not in self.hooks:
            return False

        if callback in self.hooks[hook_name]:
            self.hooks[hook_name].remove(callback)
            self.log(f"Unregistered callback from {hook_name}")
            return True
        return False

    def execute(self, hook_name: str, *args, **kwargs) -> Dict[str, Any]:
        """
        Execute all callbacks registered for a hook.

        Args:
            hook_name: Name of the hook point to execute
            *args: Positional arguments to pass to callbacks
            **kwargs: Keyword arguments to pass to callbacks

        Returns:
            Dictionary with results from all callbacks
        """
        results = {
            "hook_name": hook_name,
            "executed": False,
            "callbacks": [],
            "errors": [],
            "data": {},
        }

        if hook_name not in self.hooks:
            self.log(f"Unknown hook: {hook_name}", error=True)
            return results

        callbacks = self.hooks[hook_name]
        if not callbacks:
            return results

        results["executed"] = True
        self.log(f"Executing {len(callbacks)} callbacks for {hook_name}")

        for i, callback in enumerate(callbacks):
            try:
                callback_result = callback(*args, **kwargs)
                results["callbacks"].append(
                    {
                        "index": i,
                        "success": True,
                        "result": callback_result,
                    }
                )
                # Store the result if it's a dict for easy access
                if isinstance(callback_result, dict):
                    results["data"].update(callback_result)
            except Exception as e:
                error_msg = str(e)
                tb = traceback.format_exc()
                self.log(f"Hook {hook_name} callback {i} failed: {error_msg}", error=True)
                if self.verbose:
                    self.log(tb, error=True)
                results["errors"].append(
                    {
                        "index": i,
                        "error": error_msg,
                        "traceback": tb if self.verbose else None,
                    }
                )

        return results

    def load_hooks_from_file(self, file_path: str) -> bool:
        """
        Load hooks from a Python file.

        Args:
            file_path: Path to the Python file containing hooks

        Returns:
            True if loading succeeded, False otherwise
        """
        path = Path(file_path)
        if not path.exists():
            self.log(f"Hooks file not found: {file_path}", error=True)
            return False

        if not path.suffix == ".py":
            self.log(f"Hooks file must be a Python file: {file_path}", error=True)
            return False

        try:
            # Create a module spec and load the module
            spec = importlib.util.spec_from_file_location(f"aider_hooks_{path.stem}", str(path))
            if spec is None or spec.loader is None:
                self.log(f"Failed to create module spec for: {file_path}", error=True)
                return False

            module = importlib.util.module_from_spec(spec)

            # Add the module's directory to sys.path temporarily for imports
            module_dir = str(path.parent)
            if module_dir not in sys.path:
                sys.path.insert(0, module_dir)
                added_to_path = True
            else:
                added_to_path = False

            try:
                spec.loader.exec_module(module)
            finally:
                if added_to_path:
                    sys.path.remove(module_dir)

            # Look for register_hooks function and call it
            if hasattr(module, "register_hooks"):
                register_func = getattr(module, "register_hooks")
                if callable(register_func):
                    register_func(self)
                    self.loaded_modules.append(str(path))
                    self.log(f"Loaded hooks from: {file_path}")
                    return True
                else:
                    self.log(f"register_hooks is not callable in: {file_path}", error=True)
                    return False
            else:
                self.log(f"No register_hooks function found in: {file_path}", error=True)
                return False

        except Exception as e:
            self.log(f"Failed to load hooks from {file_path}: {e}", error=True)
            if self.verbose:
                self.log(traceback.format_exc(), error=True)
            return False

    def load_hooks_from_directory(self, dir_path: str) -> int:
        """
        Load all hook files from a directory.

        Args:
            dir_path: Path to the directory containing hook files

        Returns:
            Number of hook files successfully loaded
        """
        path = Path(dir_path)
        if not path.exists():
            self.log(f"Hooks directory not found: {dir_path}", error=True)
            return 0

        if not path.is_dir():
            self.log(f"Hooks path is not a directory: {dir_path}", error=True)
            return 0

        loaded_count = 0
        # Load all .py files in the directory
        for py_file in sorted(path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue  # Skip private modules
            if self.load_hooks_from_file(str(py_file)):
                loaded_count += 1

        self.log(f"Loaded {loaded_count} hook files from {dir_path}")
        return loaded_count

    def load_skills(self, skills_path: str) -> bool:
        """
        Load skills from the specified path.

        Skills are a special type of hook that provide reusable functionality.

        Args:
            skills_path: Path to the skills directory or file

        Returns:
            True if loading succeeded, False otherwise
        """
        if not self.skills_enabled:
            return False

        path = Path(skills_path)
        if not path.exists():
            self.log(f"Skills path not found: {skills_path}", error=True)
            return False

        self.skills_path = skills_path

        if path.is_dir():
            self.load_hooks_from_directory(skills_path)
        elif path.is_file() and path.suffix == ".py":
            self.load_hooks_from_file(skills_path)
        else:
            self.log(f"Invalid skills path: {skills_path}", error=True)
            return False

        return True

    def get_loaded_modules(self) -> List[str]:
        """Return list of loaded hook module paths."""
        return self.loaded_modules.copy()

    def is_hook_enabled(self, hook_name: str) -> bool:
        """Check if any callbacks are registered for a hook."""
        return hook_name in self.hooks and len(self.hooks[hook_name]) > 0


# Global hooks manager instance (set during initialization)
_hooks_manager: Optional[HooksManager] = None


def get_hooks_manager() -> Optional[HooksManager]:
    """Get the global hooks manager instance."""
    return _hooks_manager


def set_hooks_manager(manager: HooksManager):
    """Set the global hooks manager instance."""
    global _hooks_manager
    _hooks_manager = manager


def create_hooks_manager(io=None, verbose: bool = False) -> HooksManager:
    """
    Create and configure a new hooks manager.

    Args:
        io: InputOutput instance for logging
        verbose: Enable verbose logging

    Returns:
        Configured HooksManager instance
    """
    manager = HooksManager(io=io, verbose=verbose)
    set_hooks_manager(manager)
    return manager
