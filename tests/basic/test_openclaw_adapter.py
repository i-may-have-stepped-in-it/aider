import unittest
import asyncio
from unittest.mock import MagicMock, patch
from pathlib import Path
from aider.skills.openclaw_adapter import create_openclaw_skill_class
from aider.openclaw_bridge import SkillMetadata, SkillExecutionResult

class TestOpenClawAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_openclaw_skill_execution_time(self):
        # Mock metadata
        metadata = SkillMetadata(
            name="test-skill",
            description="A test skill"
        )
        
        # Mock bridge
        mock_bridge = MagicMock()
        mock_result = SkillExecutionResult(
            success=True,
            exit_code=0,
            stdout="done",
            stderr="",
            duration_ms=1500, # 1.5 seconds
            skill_name="test-skill",
            action="run"
        )
        mock_bridge.execute_skill.return_value = mock_result
        
        # Create skill class
        SkillClass = create_openclaw_skill_class("test-skill", metadata, bridge=mock_bridge)
        
        # Instantiate skill
        from aider.skills.base import SkillContext
        context = SkillContext()
        skill = SkillClass(context)
        
        # Execute skill
        result = await skill.execute()
        
        # Verify execution_time is set correctly (converted to seconds)
        self.assertEqual(result.execution_time, 1.5)
        self.assertEqual(result.output, "done")

if __name__ == "__main__":
    unittest.main()
