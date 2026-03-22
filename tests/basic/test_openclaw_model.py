import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from aider.openclaw_model import OpenClawModel, OpenClawConfig

class TestOpenClawModel(unittest.TestCase):
    def setUp(self):
        self.config = OpenClawConfig()
        self.config.api_key = "fake-key"
        # Mock requests to avoid real network calls during init
        with patch("aider.openclaw_model.requests") as mock_requests:
            mock_requests.options.return_value.status_code = 200
            self.model = OpenClawModel("openclaw:chat", config=self.config)

    def test_simple_send_with_retries_simplenamespace(self):
        # Create a mock response that looks like a SimpleNamespace (what send_completion returns)
        mock_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Hello from OpenClaw"
                    )
                )
            ]
        )

        with patch.object(self.model, "send_completion", return_value=(None, mock_response)):
            result = self.model.simple_send_with_retries([{"role": "user", "content": "hi"}])
            self.assertEqual(result, "Hello from OpenClaw")

    def test_simple_send_with_retries_dict(self):
        # Also test with a dict just in case
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": "Hello from dict"
                    }
                }
            ]
        }

        with patch.object(self.model, "send_completion", return_value=(None, mock_response)):
            result = self.model.simple_send_with_retries([{"role": "user", "content": "hi"}])
            self.assertEqual(result, "Hello from dict")

    def test_simple_send_with_retries_output_attr(self):
        # Test with 'output' attribute (OpenResponses style normalized)
        mock_response = SimpleNamespace(output="Hello from output")

        with patch.object(self.model, "send_completion", return_value=(None, mock_response)):
            result = self.model.simple_send_with_retries([{"role": "user", "content": "hi"}])
            self.assertEqual(result, "Hello from output")

    def test_fallback_to_http_on_responses_failure(self):
        """Test fallback when responses API fails."""
        import requests
        # Force responses mode initially
        self.model._resolved_mode = "responses"
        
        with patch.object(self.model, "_send_openresponses") as mock_resp:
            # Simulate a network error on the responses API
            mock_resp.side_effect = requests.RequestException("404 Not Found")
            with patch.object(self.model, "_send_http_api") as mock_http:
                # HTTP API should succeed
                mock_res = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="HTTP fallback"))])
                mock_http.return_value = (None, mock_res)
                
                result = self.model.send_completion([{"role": "user", "content": "hi"}], functions=[], stream=False)
                
                # Verify HTTP fallback was called
                mock_http.assert_called_once()
                self.assertEqual(result[1].choices[0].message.content, "HTTP fallback")

    def test_import_error_fallback(self):
        """Test fallback to standard Model when requests not installed."""
        # Use patch instead of sys.modules to avoid breaking other imports that need requests
        with patch("aider.openclaw_model.requests", None):
            from aider.openclaw_model import create_model
            # Model creation should still work but return standard Model
            model = create_model("gpt-4", use_openclaw=True)
            self.assertEqual(type(model).__name__, "Model")

if __name__ == "__main__":
    unittest.main()
