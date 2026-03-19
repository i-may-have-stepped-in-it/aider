"""
Legacy experimental startup alias.

This module is intentionally no longer an independent startup path.
The canonical entrypoint is `aider.main.main`.
"""

from aider.main import importlib_resources, load_dotenv_files, main

__all__ = ["main", "importlib_resources", "load_dotenv_files"]
