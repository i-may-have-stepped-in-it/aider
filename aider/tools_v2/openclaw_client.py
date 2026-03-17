import os
import requests
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class OpenClawToolClient:
    """
    Client for delegating tool-like tasks to the OpenClaw Gateway using the OpenResponses API.
    This allows Aider to leverage the 'Brain' of the upstream agent.
    Ref: https://docs.openclaw.ai/gateway/openresponses-http-api
    """
    
    def __init__(self):
        self.api_base = os.environ.get("OPENAI_API_BASE", "https://api.openclaw.ai/v1")
        self.api_key = os.environ.get("OPENAI_API_KEY")
        
        # Normalize API base for the responses endpoint
        if "/chat/completions" in self.api_base:
            self.api_base = self.api_base.replace("/chat/completions", "")
        
        self.responses_url = f"{self.api_base.rstrip('/')}/responses"

    def invoke(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delegate a task to the OpenClaw agent via the OpenResponses API.
        We transform the tool call into a natural language request for the upstream agent.
        """
        if not self.api_key:
            return {"success": False, "error": "OPENAI_API_KEY not set"}

        # Define specialized prompts for different delegated tasks
        if tool_name == "search_web":
            prompt = f"Please perform a web search for: '{parameters.get('query')}' and provide a technical summary."
            agent_id = "search"
        elif tool_name == "scrape_web":
            prompt = f"Please visit and extract the technical content from this URL: {parameters.get('url')}"
            agent_id = "browse"
        elif tool_name == "browser_action":
            prompt = f"Please perform the following interactive browser action: {parameters.get('action')} on {parameters.get('url', 'the current page')} with selector {parameters.get('selector', 'none')}."
            agent_id = "browse"
        else:
            prompt = f"Task Request: {tool_name} with parameters {parameters}"
            agent_id = "main"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-OpenClaw-Agent-Id": agent_id
        }

        payload = {
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }

        try:
            logger.info(f"Delegating {tool_name} to OpenClaw Agent: {agent_id}")
            response = requests.post(
                self.responses_url,
                json=payload,
                headers=headers,
                timeout=90 # Agentic loops need more time
            )
            response.raise_for_status()
            
            data = response.json()
            # The OpenResponses API returns a message list or a simplified response object
            # We extract the 'content' from the assistant's response
            if "choices" in data:
                output = data["choices"][0]["message"]["content"]
            elif "output" in data:
                output = data["output"]
            else:
                output = str(data)

            return {"success": True, "output": output}
            
        except Exception as e:
            logger.error(f"OpenClaw delegation failed: {e}")
            return {"success": False, "error": str(e)}
