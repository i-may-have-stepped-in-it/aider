"""
OpenClaw Gateway integration for sub-agents.

This module provides utilities for routing sub-agent calls through
the OpenClaw gateway instead of direct provider APIs.
"""

import os
from typing import Optional

# Default OpenClaw gateway endpoint
DEFAULT_GATEWAY_URL = "http://127.0.0.1:18789/v1"


def configure_gateway(url: Optional[str] = None) -> str:
    """
    Configure environment to use OpenClaw gateway.

    Args:
        url: Gateway URL (defaults to http://127.0.0.1:18789/v1)

    Returns:
        The configured gateway URL
    """
    gateway_url = url or os.environ.get("OPENCLAW_GATEWAY_URL", DEFAULT_GATEWAY_URL)

    # Set OpenAI-compatible API base
    os.environ["OPENAI_API_BASE"] = gateway_url

    # Ensure we don't use direct API keys - gateway handles auth
    # Keep any existing keys for non-gateway usage

    return gateway_url


def is_gateway_configured() -> bool:
    """Check if gateway is configured."""
    return bool(os.environ.get("OPENAI_API_BASE"))


def get_gateway_url() -> Optional[str]:
    """Get the configured gateway URL."""
    return os.environ.get("OPENAI_API_BASE")


def create_gateway_model_name(tier: Optional[str] = None, model: Optional[str] = None) -> str:
    """
    Create a model name for the gateway.

    The gateway accepts:
    - "chat" - Use default chat model
    - "@intel", "@speed", "@uncen" - Tier pool prefixes
    - Specific model names like "zai/glm-5" (routed by gateway)

    Args:
        tier: Tier prefix (@intel, @speed, @uncen)
        model: Specific model name

    Returns:
        Model name for gateway
    """
    if tier:
        return tier if tier.startswith("@") else f"@{tier}"

    if model:
        return model

    return "chat"


class GatewayConfig:
    """Configuration for OpenClaw gateway."""

    def __init__(
        self,
        url: str = DEFAULT_GATEWAY_URL,
        timeout: float = 300.0,
        retries: int = 3,
    ):
        self.url = url
        self.timeout = timeout
        self.retries = retries

    def apply(self):
        """Apply configuration to environment."""
        configure_gateway(self.url)

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        """Create config from environment variables."""
        return cls(
            url=os.environ.get("OPENCLAW_GATEWAY_URL", DEFAULT_GATEWAY_URL),
            timeout=float(os.environ.get("OPENCLAW_TIMEOUT", "300")),
            retries=int(os.environ.get("OPENCLAW_RETRIES", "3")),
        )


# Global config instance
_config: Optional[GatewayConfig] = None


def get_config() -> GatewayConfig:
    """Get global gateway config."""
    global _config
    if _config is None:
        _config = GatewayConfig.from_env()
    return _config


def set_config(config: GatewayConfig):
    """Set global gateway config."""
    global _config
    _config = config
