#!/usr/bin/env python3
"""
Hooks Configuration - Configuration parsing and validation for Aider hooks.

This module provides:
- YAML/JSON configuration file parsing
- Configuration validation against schema
- Environment variable substitution
- Configuration merging (global + project + local)
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Configuration schema version
CONFIG_VERSION = "1.0"


@dataclass
class HookRegistration:
    """Represents a single hook registration."""

    name: str
    description: str = ""
    hook_point: str = ""
    hook_type: str = "python"  # "python", "skill", "shell"

    # Python hook fields
    module: Optional[str] = None
    function: Optional[str] = None

    # Skill hook fields
    skill: Optional[str] = None
    action: Optional[str] = None

    # Shell hook fields
    command: Optional[str] = None

    # Common configuration
    priority: int = 100
    enabled: bool = True
    timeout: int = 30
    condition: Optional[str] = None
    retry_count: int = 0
    retry_delay: float = 1.0
    async_execution: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HookRegistration":
        """Create HookRegistration from dictionary."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            hook_point=data.get("hook_point", ""),
            hook_type=data.get("type", "python"),
            module=data.get("module"),
            function=data.get("function"),
            skill=data.get("skill"),
            action=data.get("action"),
            command=data.get("command"),
            priority=data.get("priority", 100),
            enabled=data.get("enabled", True),
            timeout=data.get("timeout", 30),
            condition=data.get("condition"),
            retry_count=data.get("retry_count", 0),
            retry_delay=data.get("retry_delay", 1.0),
            async_execution=data.get("async_execution", False),
        )


@dataclass
class OpenClawConfig:
    """OpenClaw skills configuration."""

    enabled: bool = True
    skills_paths: List[str] = field(default_factory=list)
    auto_discover_hooks: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenClawConfig":
        """Create OpenClawConfig from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            skills_paths=data.get("skills_paths", []),
            auto_discover_hooks=data.get("auto_discover_hooks", True),
        )


@dataclass
class HooksConfiguration:
    """Complete hooks configuration."""

    version: str = CONFIG_VERSION
    enabled: bool = True
    verbose: bool = False
    default_timeout: int = 30
    openclaw: OpenClawConfig = field(default_factory=OpenClawConfig)
    hooks: Dict[str, List[HookRegistration]] = field(default_factory=dict)
    env: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HooksConfiguration":
        """Create HooksConfiguration from dictionary."""
        # Parse OpenClaw config
        openclaw_data = data.get("openclaw", {})
        openclaw = (
            OpenClawConfig.from_dict(openclaw_data)
            if isinstance(openclaw_data, dict)
            else OpenClawConfig()
        )

        # Parse hooks
        hooks = {}
        hooks_data = data.get("hooks", {})
        for hook_point, registrations in hooks_data.items():
            hooks[hook_point] = [
                HookRegistration.from_dict(reg) for reg in registrations if isinstance(reg, dict)
            ]

        return cls(
            version=data.get("version", CONFIG_VERSION),
            enabled=data.get("enabled", True),
            verbose=data.get("verbose", False),
            default_timeout=data.get("default_timeout", 30),
            openclaw=openclaw,
            hooks=hooks,
            env=data.get("env", {}),
        )


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


class HooksConfigManager:
    """Manager for loading and validating hooks configuration."""

    # Default configuration file names
    DEFAULT_CONFIG_FILES = [
        ".aider-hooks.yml",
        ".aider-hooks.yaml",
        ".aider-hooks.json",
    ]

    # Environment variable prefix
    ENV_PREFIX = "AIDER_HOOKS_"

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the configuration manager.

        Args:
            config_path: Optional explicit path to configuration file.
        """
        self.config_path = config_path
        self._config: Optional[HooksConfiguration] = None
        self._loaded_files: List[str] = []

    def load(self) -> HooksConfiguration:
        """
        Load configuration from files.

        Configuration is merged in this order (later overrides earlier):
        1. Default configuration
        2. User global config (~/.aider-hooks.yml)
        3. Project config (./.aider-hooks.yml)
        4. Explicit config path
        5. Environment variables

        Returns:
            Merged HooksConfiguration instance.
        """
        configs = []
        self._loaded_files = []

        # 1. Start with default configuration
        configs.append(self._default_config())

        # 2. Load user global config
        global_config_path = Path.home() / ".aider-hooks.yml"
        if global_config_path.exists():
            configs.append(self._load_file(str(global_config_path)))
            self._loaded_files.append(str(global_config_path))

        # 3. Load project config
        for config_file in self.DEFAULT_CONFIG_FILES:
            project_config_path = Path.cwd() / config_file
            if project_config_path.exists():
                configs.append(self._load_file(str(project_config_path)))
                self._loaded_files.append(str(project_config_path))
                break

        # 4. Load explicit config path
        if self.config_path:
            explicit_path = Path(self.config_path)
            if explicit_path.exists():
                configs.append(self._load_file(str(explicit_path)))
                self._loaded_files.append(str(explicit_path))
            else:
                logger.warning(f"Explicit config path not found: {self.config_path}")

        # 5. Load from environment variables
        configs.append(self._load_from_env())

        # Merge configurations
        merged = self._merge_configs(configs)

        # Validate final configuration
        self._validate(merged)

        self._config = merged
        return merged

    def _default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            "version": CONFIG_VERSION,
            "enabled": True,
            "verbose": False,
            "default_timeout": 30,
            "openclaw": {
                "enabled": True,
                "skills_paths": [],
                "auto_discover_hooks": True,
            },
            "hooks": {},
            "env": {},
        }

    def _load_file(self, path: str) -> Dict[str, Any]:
        """Load configuration from a file."""
        try:
            with open(path, "r") as f:
                content = f.read()

            # Expand environment variables
            content = os.path.expandvars(content)

            # Parse based on file extension
            if path.endswith(".json"):
                return json.loads(content)
            else:
                # Assume YAML
                try:
                    import yaml

                    return yaml.safe_load(content) or {}
                except ImportError:
                    logger.error("PyYAML is required for YAML config files")
                    return {}

        except Exception as e:
            logger.error(f"Failed to load config from {path}: {e}")
            return {}

    def _load_from_env(self) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        config = {}

        for key, value in os.environ.items():
            if key.startswith(self.ENV_PREFIX):
                # Convert AIDER_HOOKS_ENABLED to config.enabled
                config_key = key[len(self.ENV_PREFIX) :].lower().replace("_", " ")

                # Try to parse as JSON, fallback to string
                try:
                    parsed_value = json.loads(value)
                except json.JSONDecodeError:
                    parsed_value = value

                # Set nested value
                parts = config_key.split("__")
                target = config
                for part in parts[:-1]:
                    if part not in target:
                        target[part] = {}
                    target = target[part]
                target[parts[-1]] = parsed_value

        return config

    def _merge_configs(self, configs: List[Dict[str, Any]]) -> HooksConfiguration:
        """Merge multiple configurations."""
        merged = {}

        for config in configs:
            merged = self._deep_merge(merged, config)

        return HooksConfiguration.from_dict(merged)

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries."""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            elif key in result and isinstance(result[key], list) and isinstance(value, list):
                # For lists, append override items
                result[key] = result[key] + value
            else:
                result[key] = value

        return result

    def _validate(self, config: HooksConfiguration) -> None:
        """Validate configuration."""
        errors = []

        # Check version
        if config.version != CONFIG_VERSION:
            errors.append(f"Unsupported config version: {config.version}")

        # Validate hook registrations
        valid_hook_points = {
            "pre_command",
            "post_command",
            "pre_send",
            "post_send",
            "pre_edit",
            "post_edit",
            "pre_commit",
            "post_commit",
            "pre_summarize",
            "post_summarize",
            "on_init",
            "on_exit",
            "on_error",
            "on_validation_fail",
            "file_added",
            "model_switch",
        }

        for hook_point, registrations in config.hooks.items():
            if hook_point not in valid_hook_points:
                errors.append(f"Invalid hook point: {hook_point}")
                continue

            for i, reg in enumerate(registrations):
                if not reg.name:
                    errors.append(f"Hook registration {i} at {hook_point} missing name")

                if reg.hook_type not in ("python", "skill", "shell"):
                    errors.append(f"Invalid hook type '{reg.hook_type}' for {reg.name}")

                # Validate type-specific fields
                if reg.hook_type == "python":
                    if not reg.module:
                        errors.append(f"Python hook {reg.name} missing module")
                    if not reg.function:
                        errors.append(f"Python hook {reg.name} missing function")

                elif reg.hook_type == "skill":
                    if not reg.skill:
                        errors.append(f"Skill hook {reg.name} missing skill name")

                elif reg.hook_type == "shell":
                    if not reg.command:
                        errors.append(f"Shell hook {reg.name} missing command")

        if errors:
            raise ConfigValidationError("Configuration validation failed:\n" + "\n".join(errors))

    def get_config(self) -> Optional[HooksConfiguration]:
        """Get loaded configuration."""
        return self._config

    def get_loaded_files(self) -> List[str]:
        """Get list of loaded configuration files."""
        return self._loaded_files.copy()

    def reload(self) -> HooksConfiguration:
        """Reload configuration from files."""
        self._config = None
        return self.load()


def load_hooks_config(config_path: Optional[str] = None) -> HooksConfiguration:
    """
    Convenience function to load hooks configuration.

    Args:
        config_path: Optional explicit path to configuration file.

    Returns:
        Loaded HooksConfiguration instance.
    """
    manager = HooksConfigManager(config_path)
    return manager.load()


def substitute_env_vars(value: str, env: Optional[Dict[str, str]] = None) -> str:
    """
    Substitute environment variables in a string.

    Supports:
    - $VAR
    - ${VAR}
    - ${VAR:-default}
    - ${VAR:=default}

    Args:
        value: String potentially containing variable references.
        env: Optional environment dictionary (defaults to os.environ).

    Returns:
        String with variables substituted.
    """
    if env is None:
        env = os.environ

    def replace_var(match):
        var_expr = match.group(1)

        # Check for default value syntax
        if ":-" in var_expr:
            var_name, default = var_expr.split(":-", 1)
            return env.get(var_name, default)

        elif ":=" in var_expr:
            var_name, default = var_expr.split(":=", 1)
            if var_name not in env:
                env[var_name] = default
            return env[var_name]

        else:
            return env.get(var_expr, "")

    # Replace ${VAR} or ${VAR:-default} patterns
    value = re.sub(r"\$\{([^}]+)\}", replace_var, value)

    # Replace $VAR patterns
    value = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", lambda m: env.get(m.group(1), ""), value)

    return value


# Singleton instance
_config_manager: Optional[HooksConfigManager] = None


def get_config_manager(config_path: Optional[str] = None) -> HooksConfigManager:
    """Get or create singleton config manager."""
    global _config_manager
    if _config_manager is None:
        _config_manager = HooksConfigManager(config_path)
    return _config_manager
