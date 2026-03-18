import json
import logging
from typing import Any, Dict, List

from ..coders.base_coder import Coder

logger = logging.getLogger(__name__)


class TaskDecomposer:
    """
    Intelligent task decomposition for multi-agent missions.
    Matches the 'WBS' (Work Breakdown Structure) logic of advanced agents.
    """

    def __init__(self, parent_coder: Coder):
        self.coder = parent_coder
        self.model = parent_coder.main_model  # Use the @intel tier

    async def decompose(self, task: str) -> List[Dict[str, Any]]:
        """
        Decompose a high-level task into independent sub-tasks.
        """
        prompt = f"""You are a Lead Project Manager. Break down the following high-level task into
2-5 independent sub-tasks that can be executed in parallel by different specialist agents.

TASK:
{task}

FILES IN CONTEXT:
{self.coder.get_inchat_relative_files()}

## Requirements:
1. Each sub-task must be independent.
2. Provide a descriptive 'name' and detailed 'description' for each sub-task.
3. List the 'relevant_files' for each sub-task.
4. Respond ONLY with a valid JSON object.

FORMAT:
{{
    "subtasks": [
        {{
            "name": "Specialist Name",
            "description": "Specific task description",
            "relevant_files": ["path/to/file.py"]
        }}
    ]
}}
"""
        self.coder.io.tool_output("Decomposing high-level task into parallel sub-missions...")

        # Use simple_completion for a structured JSON response
        response = self.coder.simple_completion(prompt)

        try:
            # Clean response if LLM added markdown fences
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()

            plan = json.loads(response)
            subtasks = plan.get("subtasks", [])

            if not subtasks:
                logger.warning("Decomposer returned no subtasks. Falling back to single mission.")
                return []

            return subtasks

        except (json.JSONDecodeError, IndexError) as e:
            logger.error(f"Failed to parse decomposition plan: {e}")
            return []
