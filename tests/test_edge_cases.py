#!/usr/bin/env python3
"""
Edge case tests for Aider codebase - PHASE 5 VERification

Addresses Issue 22: Missing edge case tests
"""

import asyncio
import pytest
import time
from aider.skills.base import Skill, SkillContext, SkillResult


class EdgeCaseSkill(Skill):
    """Skill for testing edge cases."""
    name = "edge-case-skill"
    description = "Edge case test skill"

    def _get_required_params(self):
        return ["input_file"]

    def _validate_parameters(self, params):
        errors = []
        if "count" in params and params["count"] < 0:
            errors.append("Parameter 'count' must be non-negative")
        return errors

    async def _execute_impl(self, **kwargs):
        return SkillResult(
            success=True,
            output=f"Processed {kwargs['input_file']}"
        )


# === Edge Case Tests ===

async def test_skill_with_zero_count():
    """Test skill handles zero count."""
    skill = EdgeCaseSkill()
    result = await skill.execute(input_file="test.txt", count=0)
    assert result.success == True


async def test_skill_with_negative_count():
    """Test skill rejects negative count."""
    skill = EdgeCaseSkill()
    result = await skill.execute(input_file="test.txt", count=-1)
    assert result.success == False
    assert "non-negative" in result.error


async def test_skill_with_empty_string():
    """Test skill handles empty string."""
    skill = EdgeCaseSkill()
    result = await skill.execute(input_file="")
    assert result.success == True  # Empty string is valid


async def test_skill_with_unicode():
    """Test skill handles unicode."""
    skill = EdgeCaseSkill()
    result = await skill.execute(input_file="测试文件.txt")
    assert result.success == True


async def test_skill_with_very_long_filename():
    """Test skill handles very long filename."""
    skill = EdgeCaseSkill()
    long_name = "a" * 1000 + ".txt"
    result = await skill.execute(input_file=long_name)
    assert result.success == True


async def test_skill_with_special_characters():
    """Test skill handles special characters."""
    skill = EdgeCaseSkill()
    result = await skill.execute(input_file="file with spaces & symbols !@#.txt")
    assert result.success == True


async def test_skill_with_max_int():
    """Test skill handles maximum integer."""
    skill = EdgeCaseSkill()
    result = await skill.execute(input_file="test.txt", count=2**31 - 1)
    assert result.success == True


async def test_skill_cancellation_during_execution():
    """Test skill respects cancellation token."""
    context = SkillContext()
    context.cancellation_token = asyncio.Event()
    context.cancellation_token.set()  # Cancel immediately
    
    skill = EdgeCaseSkill(context)
    result = await skill.execute(input_file="test.txt")
    
    assert result.success == False
    assert "cancelled" in result.error.lower()


async def test_skill_with_many_progress_updates():
    """Test skill with many progress updates."""
    skill = EdgeCaseSkill()
    
    # Add 100 progress updates
    for i in range(100):
        skill.update_progress(f"Step {i}", progress=i/100)
    
    progress = skill.get_progress()
    assert len(progress) == 100


async def test_skill_progress_overflow():
    """Test skill handles progress > 1.0."""
    skill = EdgeCaseSkill()
    skill.update_progress("Overflow", progress=1.5)
    
    progress = skill.get_progress()
    assert len(progress) == 1
    # Note: Progress validation is optional


async def test_skill_concurrent_progress_updates():
    """Test concurrent progress updates."""
    skill = EdgeCaseSkill()
    
    async def add_progress(i):
        skill.update_progress(f"Concurrent {i}")
    
    # Run 50 concurrent progress updates
    await asyncio.gather(*[add_progress(i) for i in range(50)])
    
    progress = skill.get_progress()
    assert len(progress) == 50


async def test_skill_with_multiple_warnings():
    """Test skill accumulates multiple warnings."""
    skill = EdgeCaseSkill()
    
    for i in range(10):
        skill.add_warning(f"Warning {i}")
    
    result = await skill.execute(input_file="test.txt")
    
    assert len(result.warnings) == 10


async def test_skill_clear_progress():
    """Test clearing progress history."""
    skill = EdgeCaseSkill()
    
    skill.update_progress("Step 1")
    skill.update_progress("Step 2")
    assert len(skill.get_progress()) == 2
    
    skill.clear_progress()
    assert len(skill.get_progress()) == 0


async def test_skill_with_none_values():
    """Test skill handles None values in parameters."""
    skill = EdgeCaseSkill()
    result = await skill.execute(input_file="test.txt", optional_param=None)
    assert result.success == True


async def test_skill_with_dict_and_list_params():
    """Test skill handles complex parameter types."""
    skill = EdgeCaseSkill()
    result = await skill.execute(
        input_file="test.txt",
        config={"key": "value"},
        items=["item1", "item2", "item3"]
    )
    assert result.success == True


async def test_skill_timeout_at_boundary():
    """Test skill timeout at exact boundary."""
    context = SkillContext(timeout=0.0)
    skill = EdgeCaseSkill(context)
    
    start = time.time()
    result = await skill.execute(input_file="test.txt")
    elapsed = time.time() - start
    
    assert result.success == True  # Should complete within 1 second
    assert elapsed < 1.0


if __name__ == "__main__":
    asyncio.run(test_skill_with_zero_count())
    asyncio.run(test_skill_with_negative_count())
    asyncio.run(test_skill_with_empty_string())
    asyncio.run(test_skill_with_unicode())
    asyncio.run(test_skill_with_very_long_filename())
    asyncio.run(test_skill_with_special_characters())
    asyncio.run(test_skill_with_max_int())
    asyncio.run(test_skill_cancellation_during_execution())
    asyncio.run(test_skill_with_many_progress_updates())
    asyncio.run(test_skill_progress_overflow())
    asyncio.run(test_skill_concurrent_progress_updates())
    asyncio.run(test_skill_with_multiple_warnings())
    asyncio.run(test_skill_clear_progress())
    asyncio.run(test_skill_with_none_values())
    asyncio.run(test_skill_with_dict_and_list_params())
    asyncio.run(test_skill_timeout_at_boundary())
    print("✅ All edge case tests passed")
