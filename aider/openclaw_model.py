#!/usr/bin/env python3
"""
OpenClaw Model - Direct integration with OpenClaw Gateway.

This module provides an alternative to litellm for OpenClaw Gateway connections,
supporting both:
- OpenResponses API (preferred for agent-native interactions)
- OpenAI-compatible HTTP API with custom headers (fallback)

Configuration via environment variables:
- AIDER_OPENCLAW_MODE=responses|http|auto (default: auto)
- AIDER_OPENCLAW_AGENT_ID=chat (default: chat)
- AIDER_OPENCLAW_SESSION_KEY=... (optional, for session continuity)
"""

import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace

# Try to import requests, provide helpful error if missing
try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)


@dataclass
class OpenClawConfig:
    """Configuration for OpenClaw connection."""

    api_base = "http://127.0.0.1:18789"
    api_key = None
    agent_id = "chat"
    mode = "auto"  # "responses", "http", or "auto"
    session_key = None
    timeout = 300

    def __post_init__(self):
        # Normalize API base URL
        self.api_base = self.api_base.rstrip("/")
        if "/v1" not in self.api_base:
            self.api_base = "{}/v1".format(self.api_base)

    @classmethod
    def from_env(cls):
        """Create config from environment variables."""
        api_base = os.environ.get("OPENAI_API_BASE", "http://127.0.0.1:18789/v1")

        # Handle litellm-style base URL
        if "/chat/completions" in api_base:
            api_base = api_base.replace("/chat/completions", "")

        instance = cls()
        instance.api_base = api_base
        instance.api_key = os.environ.get("OPENAI_API_KEY")
        instance.agent_id = os.environ.get("AIDER_OPENCLAW_AGENT_ID", "chat")
        instance.mode = os.environ.get("AIDER_OPENCLAW_MODE", "auto")
        instance.session_key = os.environ.get("AIDER_OPENCLAW_SESSION_KEY")
        instance.timeout = int(os.environ.get("AIDER_OPENCLAW_TIMEOUT", "300"))
        instance.__post_init__()
        return instance


class OpenClawModel:
    """
    Model class that connects directly to OpenClaw Gateway.

    This bypasses litellm for OpenClaw-specific features:
    - Direct agent selection via headers
    - OpenResponses API support
    - Session continuity
    - No BOOTSTRAP.md issues when using 'chat' agent
    """

    def __init__(self, name, config=None, verbose=False):
        """
        Initialize OpenClaw model.

        Args:
            name: Model name (e.g., "openclaw:chat", "openai/gpt-4")
            config: OpenClaw configuration (or auto-from-env if None)
            verbose: Enable verbose logging
        """
        if requests is None:
            raise ImportError(
                "OpenClawModel requires 'requests' package. Install with: pip install requests"
            )

        self.name = name
        self.config = config or OpenClawConfig.from_env()
        self.verbose = verbose

        # Determine which mode to use
        self._resolved_mode = self._resolve_mode()

        # Parse agent_id from model name if present (openclaw:<agent_id>)
        self._parse_model_name(name)

        if self.verbose:
            logger.info("OpenClawModel initialized:")
            logger.info("  Name: {}".format(self.name))
            logger.info("  Mode: {}".format(self._resolved_mode))
            logger.info("  Agent: {}".format(self.config.agent_id))
            logger.info("  API Base: {}".format(self.config.api_base))

    def _parse_model_name(self, name):
        """Extract agent_id from model name like 'openclaw:chat'."""
        if name.startswith("openclaw:"):
            agent_id = name.split(":", 1)[1]
            if agent_id:
                self.config.agent_id = agent_id
                if self.verbose:
                    logger.info("  Parsed agent_id from model name: {}".format(agent_id))

    def _resolve_mode(self):
        """Determine which API mode to use."""
        mode = self.config.mode.lower()

        if mode == "auto":
            # Check if responses API is available, otherwise use http
            if self._check_responses_api_available():
                return "responses"
            return "http"
        elif mode in ("responses", "http"):
            return mode
        else:
            logger.warning("Unknown mode '{}', using 'http'".format(mode))
            return "http"

    def _check_responses_api_available(self):
        """Check if the OpenResponses API is available."""
        try:
            import requests

            url = "{}/responses".format(self.config.api_base.replace("/v1", ""))
            response = requests.options(url, timeout=5)
            return response.status_code != 404
        except Exception:
            return False

    def _get_headers(self):
        """Build request headers."""
        headers = {
            "Content-Type": "application/json",
        }

        if self.config.api_key:
            headers["Authorization"] = "Bearer {}".format(self.config.api_key)

        # Always add agent_id header to ensure correct agent selection
        headers["X-OpenClaw-Agent-Id"] = self.config.agent_id

        # Add session key if provided (for continuity)
        if self.config.session_key:
            headers["X-OpenClaw-Session-Key"] = self.config.session_key

        return headers

    def send_completion(self, messages, functions, stream, temperature=None):
        """
        Send completion request to OpenClaw Gateway.

        Args:
            messages: List of message dicts with 'role' and 'content'
            functions: Optional list of function definitions
            stream: Whether to stream the response
            temperature: Sampling temperature

        Returns:
            Tuple of (request_hash, response)
            Response is either:
            - Iterator[Dict] for streaming
            - Dict for non-streaming
        """
        # Build kwargs for hashing (consistent with original Model class)
        kwargs = {
            "model": self.name,
            "stream": stream,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature

        key = json.dumps(kwargs, sort_keys=True).encode()
        hash_object = hashlib.sha1(key)

        try:
            if self._resolved_mode == "responses":
                return self._send_openresponses(messages, stream, temperature, hash_object)
            else:
                return self._send_http_api(messages, functions, stream, temperature, hash_object)
        except requests.RequestException as e:
            logger.error("OpenClaw request failed: {}".format(e))
            # Fallback to HTTP API if responses API fails
            if self._resolved_mode == "responses":
                logger.info("Falling back to HTTP API")
                return self._send_http_api(messages, functions, stream, temperature, hash_object)
            raise

    def _send_openresponses(self, messages, stream, temperature, hash_object):
        """Send request using OpenResponses API."""
        url = "{}/responses".format(self.config.api_base.replace("/v1", ""))

        payload = {
            "messages": messages,
            "stream": stream,
        }

        if temperature is not None:
            payload["temperature"] = temperature

        if self.verbose:
            logger.info("OpenResponses API: POST {}".format(url))
            logger.info("  Agent: {}".format(self.config.agent_id))
            logger.info("  Stream: {}".format(stream))

        response = requests.post(
            url,
            json=payload,
            headers=self._get_headers(),
            timeout=self.config.timeout,
            stream=stream,
        )
        response.raise_for_status()

        if stream:
            return hash_object, self._stream_openresponses(response)
        else:
            return hash_object, self._dict_to_namespace(
                self._parse_openresponses_response(response.json())
            )

    def _send_http_api(self, messages, functions, stream, temperature, hash_object):
        """Send request using OpenAI-compatible HTTP API."""
        url = "{}/chat/completions".format(self.config.api_base)

        payload = {
            "model": self.name,
            "messages": messages,
            "stream": stream,
        }

        if temperature is not None:
            payload["temperature"] = temperature

        if functions:
            # Convert Aider function format to OpenAI tools format
            payload["tools"] = [{"type": "function", "function": f} for f in functions]
            payload["tool_choice"] = "auto"

        if self.verbose:
            logger.info("HTTP API: POST {}".format(url))
            logger.info("  Agent: {}".format(self.config.agent_id))
            logger.info("  Stream: {}".format(stream))

        response = requests.post(
            url,
            json=payload,
            headers=self._get_headers(),
            timeout=self.config.timeout,
            stream=stream,
        )
        response.raise_for_status()

        if stream:
            return hash_object, self._stream_http_api(response)
        else:
            return hash_object, self._dict_to_namespace(response.json())

    def _stream_openresponses(self, response):
        """Stream OpenResponses API response."""
        for line in response.iter_lines():
            if not line:
                continue

            line_str = line.decode("utf-8")

            # Handle SSE format
            if line_str.startswith("data: "):
                data = line_str[6:]
                if data == "[DONE]":
                    break
                try:
                    yield self._dict_to_namespace(json.loads(data))
                except json.JSONDecodeError:
                    continue
            else:
                try:
                    yield self._dict_to_namespace(json.loads(line_str))
                except json.JSONDecodeError:
                    continue

    def _dict_to_namespace(self, d):
        """Recursively convert dict to SimpleNamespace for attribute access."""
        if isinstance(d, dict):
            for key, value in d.items():
                if isinstance(value, dict):
                    d[key] = self._dict_to_namespace(value)
                elif isinstance(value, list):
                    d[key] = [
                        self._dict_to_namespace(item) if isinstance(item, dict) else item
                        for item in value
                    ]
            return SimpleNamespace(**d)
        return d

    def _stream_http_api(self, response):
        """Stream OpenAI-compatible HTTP API response."""
        for line in response.iter_lines():
            if not line:
                continue

            line_str = line.decode("utf-8")

            # Handle SSE format
            if line_str.startswith("data: "):
                data = line_str[6:]
                if data == "[DONE]":
                    break
                try:
                    # Convert dict to SimpleNamespace for attribute access
                    yield self._dict_to_namespace(json.loads(data))
                except json.JSONDecodeError:
                    continue

    def _parse_openresponses_response(self, data):
        """Convert OpenResponses format to OpenAI-compatible format."""
        # OpenResponses has different format, normalize it
        if "output" in data:
            # Simple text output
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": data["output"],
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": data.get("usage", {}),
            }
        elif "messages" in data:
            # Full message list
            messages = data["messages"]
            if messages:
                last_msg = messages[-1]
                return {
                    "choices": [
                        {
                            "message": last_msg,
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": data.get("usage", {}),
                }

        # Passthrough if already in expected format
        return data

    def simple_send_with_retries(self, messages):
        """
        Simple non-streaming send with basic retry logic.

        Args:
            messages: List of message dicts

        Returns:
            Response content string
        """
        import time

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                _, response = self.send_completion(messages, stream=False)

                # Extract content from response
                if isinstance(response, dict):
                    if "choices" in response and response["choices"]:
                        choice = response["choices"][0]
                        if "message" in choice:
                            return choice["message"].get("content", "")
                        elif "text" in choice:
                            return choice["text"]
                    elif "output" in response:
                        return response["output"]

                return str(response)

            except Exception as e:
                last_error = e
                logger.warning("Attempt {} failed: {}".format(attempt + 1, e))
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)  # Exponential backoff

        raise last_error or RuntimeError("All retries failed")


def is_openclaw_endpoint(url=None):
    """
    Check if the configured endpoint is OpenClaw Gateway.

    Args:
        url: URL to check (defaults to OPENAI_API_BASE env var)

    Returns:
        True if endpoint appears to be OpenClaw
    """
    if url is None:
        url = os.environ.get("OPENAI_API_BASE", "")

    url_lower = url.lower()
    indicators = [
        "127.0.0.1:18789",
        "localhost:18789",
        ":18789",  # OpenClaw default port
        "openclaw",
        ".openclaw.ai",
    ]

    return any(ind in url_lower for ind in indicators)


def create_model(name, use_openclaw=None, **kwargs):
    """
    Factory function to create appropriate model instance.

    Args:
        name: Model name
        use_openclaw: Force OpenClawModel (True), force standard Model (False),
                     or auto-detect (None)
        **kwargs: Additional arguments passed to model constructor

    Returns:
        Model instance (OpenClawModel or standard Model)
    """
    # Check if we should use OpenClawModel
    if use_openclaw is None:
        # Auto-detect based on endpoint
        use_openclaw = is_openclaw_endpoint()

    if use_openclaw:
        try:
            return OpenClawModel(name, **kwargs)
        except ImportError as e:
            logger.warning("Could not create OpenClawModel: {}".format(e))
            logger.warning("Falling back to standard Model")

    # Fall back to standard Model class
    from aider.models import Model

    return Model(name, **kwargs)


# Convenience function for direct usage
def send_to_openclaw(messages, agent_id="chat", stream=False, **kwargs):
    """
    Convenience function to send messages to OpenClaw Gateway.

    Args:
        messages: List of message dicts
        agent_id: Agent ID to use (default: chat)
        stream: Whether to stream response
        **kwargs: Additional options for OpenClawConfig

    Returns:
        Response dict (non-streaming) or iterator (streaming)
    """
    config = OpenClawConfig.from_env()
    config.agent_id = agent_id

    # Apply any overrides
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)

    model = OpenClawModel("openclaw", config=config)
    _, response = model.send_completion(messages, stream=stream)
    return response
