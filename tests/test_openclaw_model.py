#!/usr/bin/env python3
"""Tests for OpenClawModel integration."""

import os
import sys
import unittest
from unittest.mock import Mock, patch

# Ensure aider is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from aider.openclaw_model import (
    OpenClawConfig,
    OpenClawModel,
    is_openclaw_endpoint,
    create_model,
)


class TestOpenClawConfig(unittest.TestCase):
    """Test OpenClawConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = OpenClawConfig()
        self.assertEqual(config.api_base, "http://127.0.0.1:18789/v1")
        self.assertEqual(config.agent_id, "chat")
        self.assertEqual(config.mode, "auto")
        self.assertIsNone(config.api_key)
        self.assertIsNone(config.session_key)
        self.assertEqual(config.timeout, 300)

    def test_api_base_normalization(self):
        """Test API base URL normalization."""
        # Should add /v1 if missing
        config = OpenClawConfig()
        config.api_base = "http://localhost:18789"
        config.__post_init__()
        self.assertEqual(config.api_base, "http://localhost:18789/v1")

        # Should not double-add /v1
        config = OpenClawConfig()
        config.api_base = "http://localhost:18789/v1"
        config.__post_init__()
        self.assertEqual(config.api_base, "http://localhost:18789/v1")

        # Should strip trailing slash before adding /v1
        config = OpenClawConfig()
        config.api_base = "http://localhost:18789/"
        config.__post_init__()
        self.assertEqual(config.api_base, "http://localhost:18789/v1")

    def test_from_env(self):
        """Test creating config from environment variables."""
        env_vars = {
            "OPENAI_API_BASE": "http://test:18789/custom",
            "OPENAI_API_KEY": "test-key",
            "AIDER_OPENCLAW_AGENT_ID": "test-agent",
            "AIDER_OPENCLAW_MODE": "responses",
            "AIDER_OPENCLAW_SESSION_KEY": "test-session",
            "AIDER_OPENCLAW_TIMEOUT": "600",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = OpenClawConfig.from_env()
            # Note: /v1 is appended by normalization
            self.assertEqual(config.api_base, "http://test:18789/custom/v1")
            self.assertEqual(config.api_key, "test-key")
            self.assertEqual(config.agent_id, "test-agent")
            self.assertEqual(config.mode, "responses")
            self.assertEqual(config.session_key, "test-session")
            self.assertEqual(config.timeout, 600)

    def test_from_env_handles_chat_completions(self):
        """Test that litellm-style base URL is handled."""
        env_vars = {
            "OPENAI_API_BASE": "http://127.0.0.1:18789/v1/chat/completions",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = OpenClawConfig.from_env()
            self.assertEqual(config.api_base, "http://127.0.0.1:18789/v1")


class TestIsOpenClawEndpoint(unittest.TestCase):
    """Test endpoint detection."""

    def test_localhost_18789(self):
        """Test detection of default OpenClaw port."""
        self.assertTrue(is_openclaw_endpoint("http://127.0.0.1:18789/v1"))
        self.assertTrue(is_openclaw_endpoint("http://localhost:18789"))
        self.assertTrue(is_openclaw_endpoint("https://localhost:18789/v1/chat/completions"))

    def test_openclaw_domain(self):
        """Test detection of OpenClaw domains."""
        self.assertTrue(is_openclaw_endpoint("https://api.openclaw.ai/v1"))
        self.assertTrue(is_openclaw_endpoint("https://myinstance.openclaw.dev"))

    def test_non_openclaw_endpoints(self):
        """Test that non-OpenClaw endpoints return False."""
        self.assertFalse(is_openclaw_endpoint("https://api.openai.com/v1"))
        self.assertFalse(is_openclaw_endpoint("https://api.anthropic.com"))
        self.assertFalse(is_openclaw_endpoint("http://localhost:11434"))  # Ollama
        self.assertFalse(is_openclaw_endpoint(""))

    def test_env_fallback(self):
        """Test using environment variable when no URL provided."""
        with patch.dict(os.environ, {"OPENAI_API_BASE": "http://127.0.0.1:18789/v1"}):
            self.assertTrue(is_openclaw_endpoint())

        with patch.dict(os.environ, {"OPENAI_API_BASE": "https://api.openai.com/v1"}):
            self.assertFalse(is_openclaw_endpoint())


class TestOpenClawModel(unittest.TestCase):
    """Test OpenClawModel class."""

    def test_init_with_defaults(self):
        """Test model initialization with default config."""
        with patch('aider.openclaw_model.requests'):
            model = OpenClawModel("openclaw:chat")
            self.assertEqual(model.name, "openclaw:chat")
            self.assertEqual(model.config.agent_id, "chat")
            # Default mode is now "http" (responses API returns 404)
            self.assertEqual(model._resolved_mode, "http")

    def test_parse_model_name(self):
        """Test parsing agent_id from model name."""
        with patch('aider.openclaw_model.requests'):
            # Standard format
            model = OpenClawModel("openclaw:chat")
            self.assertEqual(model.config.agent_id, "chat")

            # Custom agent
            model = OpenClawModel("openclaw:kimi")
            self.assertEqual(model.config.agent_id, "kimi")

            # Non-openclaw name should use default
            model = OpenClawModel("openai/gpt-4")
            self.assertEqual(model.config.agent_id, "chat")  # default

    def test_resolve_mode(self):
        """Test mode resolution logic."""
        with patch('aider.openclaw_model.requests'):
            # Auto mode now defaults to "http" (responses API returns 404)
            model = OpenClawModel("test")
            model.config.mode = "auto"
            model._resolved_mode = model._resolve_mode()
            self.assertEqual(model._resolved_mode, "http")

            # Explicit modes
            model = OpenClawModel("test")
            model.config.mode = "responses"
            model._resolved_mode = model._resolve_mode()
            self.assertEqual(model._resolved_mode, "responses")

            model = OpenClawModel("test")
            model.config.mode = "http"
            model._resolved_mode = model._resolve_mode()
            self.assertEqual(model._resolved_mode, "http")

            # Invalid mode falls back to http (not responses)
            model = OpenClawModel("test")
            model.config.mode = "invalid"
            model._resolved_mode = model._resolve_mode()
            self.assertEqual(model._resolved_mode, "http")

    def test_get_headers(self):
        """Test header generation."""
        with patch('aider.openclaw_model.requests'):
            config = OpenClawConfig()
            config.api_key = "test-key"
            config.agent_id = "test-agent"
            config.session_key = "test-session"
            model = OpenClawModel("test", config=config)

            headers = model._get_headers()

            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            self.assertEqual(headers["X-OpenClaw-Agent-Id"], "test-agent")
            self.assertEqual(headers["X-OpenClaw-Session-Key"], "test-session")

    def test_get_headers_without_optional(self):
        """Test headers without optional fields."""
        with patch('aider.openclaw_model.requests'):
            config = OpenClawConfig()
            config.api_key = None
            config.session_key = None
            model = OpenClawModel("test", config=config)

            headers = model._get_headers()

            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertEqual(headers["X-OpenClaw-Agent-Id"], "chat")
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("X-OpenClaw-Session-Key", headers)

    @patch('aider.openclaw_model.requests.post')
    def test_send_openresponses(self, mock_post):
        """Test OpenResponses API request."""
        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {
            "output": "Test response",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        model = OpenClawModel("openclaw:chat")
        model.config.mode = "responses"
        model._resolved_mode = "responses"
        messages = [{"role": "user", "content": "Hello"}]

        hash_obj, response = model.send_completion(messages, functions=None, stream=False)

        # Verify request
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("/responses", call_args[0][0])

        # Verify response parsing - response is now SimpleNamespace (object-style access)
        self.assertEqual(response.choices[0].message.content, "Test response")

    @patch('aider.openclaw_model.requests.post')
    def test_send_http_api(self, mock_post):
        """Test HTTP API request."""
        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Test"}, "finish_reason": "stop"}],
            "usage": {}
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        model = OpenClawModel("openai/chat")
        model.config.mode = "http"
        model._resolved_mode = "http"
        messages = [{"role": "user", "content": "Hello"}]

        hash_obj, response = model.send_completion(messages, functions=None, stream=False)

        # Verify request
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("/chat/completions", call_args[0][0])

        # Verify body
        body = call_args[1]["json"]
        self.assertEqual(body["model"], "openai/chat")
        self.assertEqual(body["messages"], messages)


class TestModelIntegration(unittest.TestCase):
    """Test integration with standard Model class."""

    def test_model_aliases(self):
        """Test that openclaw aliases are defined."""
        from aider.models import MODEL_ALIASES

        self.assertIn("openclaw", MODEL_ALIASES)
        self.assertEqual(MODEL_ALIASES["openclaw"], "openclaw:chat")

        self.assertIn("openclaw-chat", MODEL_ALIASES)
        self.assertIn("openclaw-main", MODEL_ALIASES)


class TestCreateModel(unittest.TestCase):
    """Test factory function."""

    @patch('aider.openclaw_model.OpenClawModel')
    @patch('aider.openclaw_model.is_openclaw_endpoint')
    def test_create_openclaw_model_auto(self, mock_is_oc, mock_ocm):
        """Test auto-detection of OpenClaw."""
        mock_is_oc.return_value = True

        create_model("openai/chat")

        mock_ocm.assert_called_once()

    @patch('aider.openclaw_model.OpenClawModel')
    def test_create_openclaw_model_forced(self, mock_ocm):
        """Test forcing OpenClawModel."""
        create_model("openai/gpt-4", use_openclaw=True)

        mock_ocm.assert_called_once()

    @patch('aider.models.Model')
    def test_create_standard_model_forced(self, mock_model):
        """Test forcing standard Model."""
        create_model("openclaw:chat", use_openclaw=False)

        mock_model.assert_called_once()


if __name__ == "__main__":
    unittest.main()
