"""
Hook loading and singleton/bootstrap helpers separated from HooksManager.
"""

import importlib.util
import sys
import traceback
from pathlib import Path
from typing import Optional

from aider.openclaw_bridge import OpenClawBridge

from .hooks_manager import HooksManager

_hooks_manager_instance: Optional[HooksManager] = None


def load_hooks_from_file(manager: HooksManager, file_path: str) -> bool:
    """Load legacy hook definitions from a Python file into a manager."""
    path = Path(file_path)
    if not path.exists():
        manager.log(f"Hooks file not found: {file_path}", error=True)
        return False

    if path.suffix != ".py":
        manager.log(f"Hooks file must be a Python file: {file_path}", error=True)
        return False

    try:
        spec = importlib.util.spec_from_file_location(f"aider_hooks_{path.stem}", str(path))
        if spec is None or spec.loader is None:
            manager.log(f"Failed to create module spec for: {file_path}", error=True)
            return False

        module = importlib.util.module_from_spec(spec)
        module_dir = str(path.parent)
        added_to_path = False
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
            added_to_path = True

        try:
            spec.loader.exec_module(module)
        finally:
            if added_to_path:
                sys.path.remove(module_dir)

        register_func = getattr(module, "register_hooks", None)
        if not callable(register_func):
            manager.log(f"No register_hooks function found in: {file_path}", error=True)
            return False

        register_func(manager)
        manager.loaded_modules.append(str(path))
        manager.log(f"Loaded hooks from: {file_path}")
        return True
    except Exception as err:
        manager.log(f"Failed to load hooks from {file_path}: {err}", error=True)
        if manager.verbose:
            manager.log(traceback.format_exc(), error=True)
        return False


def load_hooks_from_directory(manager: HooksManager, dir_path: str) -> int:
    """Load all legacy hook files from a directory."""
    path = Path(dir_path)
    if not path.exists():
        manager.log(f"Hooks directory not found: {dir_path}", error=True)
        return 0

    if not path.is_dir():
        manager.log(f"Hooks path is not a directory: {dir_path}", error=True)
        return 0

    loaded_count = 0
    for py_file in sorted(path.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        if load_hooks_from_file(manager, str(py_file)):
            loaded_count += 1

    manager.log(f"Loaded {loaded_count} hook files from {dir_path}")
    return loaded_count


def load_skills(manager: HooksManager, skills_path: str) -> bool:
    """Legacy skill-loading compatibility path for hook-style skill files."""
    path = Path(skills_path)
    if not path.exists():
        manager.log(f"Skills path not found: {skills_path}", error=True)
        return False

    manager.skills_enabled = True
    manager.skills_path = skills_path
    if path.is_dir():
        load_hooks_from_directory(manager, skills_path)
    elif path.is_file() and path.suffix == ".py":
        load_hooks_from_file(manager, skills_path)
    else:
        manager.log(f"Invalid skills path: {skills_path}", error=True)
        return False

    return True


def get_hooks_manager(bridge: Optional[OpenClawBridge] = None) -> HooksManager:
    """Get or create the singleton HooksManager instance."""
    global _hooks_manager_instance
    if _hooks_manager_instance is None:
        _hooks_manager_instance = HooksManager(bridge)
    return _hooks_manager_instance


def set_hooks_manager(manager: Optional[HooksManager]):
    """Set the singleton HooksManager instance."""
    global _hooks_manager_instance
    _hooks_manager_instance = manager


def create_hooks_manager(io=None, verbose: bool = False, bridge: Optional[OpenClawBridge] = None):
    """Create and install a configured singleton HooksManager."""
    manager = HooksManager(bridge=bridge, io=io, verbose=verbose)
    set_hooks_manager(manager)
    return manager


def reset_hooks_manager():
    """Reset the singleton instance (useful for testing)."""
    global _hooks_manager_instance
    _hooks_manager_instance = None
