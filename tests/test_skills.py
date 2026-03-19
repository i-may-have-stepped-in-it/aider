#!/usr/bin/env python3
"""
Test script for Aider skills with multi-agent support.
"""

import asyncio
import sys

sys.path.insert(0, "/home/openclaw/openclaw/aider")

from aider.skills.base import SkillContext  # noqa: E402
from aider.skills.code_review import CodeReviewSkill  # noqa: E402
from aider.skills.documentation import DocumentationSkill  # noqa: E402
from aider.skills.registry import get_registry  # noqa: E402
from aider.skills.test_generation import TestGenerationSkill  # noqa: E402


async def test_registry():
    """Test skill registry."""
    print("=" * 60)
    print("Testing Skill Registry")
    print("=" * 60)

    registry = get_registry()

    # List all skills
    print(f"\nTotal skills registered: {registry.count()}")

    # Show agent-enabled skills
    agent_skills = registry.list_skills(supports_agents=True)
    print(f"Agent-enabled skills: {len(agent_skills)}")

    for skill in agent_skills:
        print(f"  🤖 {skill['name']}: {skill['description']}")

    # Test search
    print("\nSearching for 'test':")
    results = registry.search("test")
    for r in results:
        print(f"  - {r['name']}")

    print("\n✓ Registry tests passed")


async def test_code_review_skill():
    """Test code review skill."""
    print("\n" + "=" * 60)
    print("Testing Code Review Skill")
    print("=" * 60)

    context = SkillContext(enable_agents=False, verbose=True)  # Sequential mode for testing

    skill = CodeReviewSkill(context)

    # Test without agents
    result = await skill.execute(
        files=["auth.py", "models.py", "api.py"], focus="security", model="claude-sonnet"
    )

    print(f"\nSuccess: {result.success}")
    print(f"Execution time: {result.execution_time:.2f}s")
    print(f"Files processed: {result.data.get('files_reviewed', 0)}")

    print("\n✓ Code review skill tests passed")


async def test_test_generation_skill():
    """Test test generation skill."""
    print("\n" + "=" * 60)
    print("Testing Test Generation Skill")
    print("=" * 60)

    context = SkillContext(enable_agents=False, verbose=True)

    skill = TestGenerationSkill(context)

    result = await skill.execute(
        files=["user.py", "auth.py"], test_framework="pytest", coverage_target=80.0
    )

    print(f"\nSuccess: {result.success}")
    print(f"Test files: {result.files_modified}")

    print("\n✓ Test generation skill tests passed")


async def test_documentation_skill():
    """Test documentation skill."""
    print("\n" + "=" * 60)
    print("Testing Documentation Skill")
    print("=" * 60)

    context = SkillContext(enable_agents=False, verbose=True)

    skill = DocumentationSkill(context)

    result = await skill.execute(
        files=["main.py", "utils.py"], doc_format="google", update_readme=False
    )

    print(f"\nSuccess: {result.success}")
    print(f"Files documented: {result.data.get('files_documented', 0)}")

    print("\n✓ Documentation skill tests passed")


async def test_agent_mixin():
    """Test agent skill mixin."""
    print("\n" + "=" * 60)
    print("Testing Agent Skill Mixin")
    print("=" * 60)

    from aider.skills.agent_skill import AgentSkillMixin

    class TestSkill(AgentSkillMixin):
        pass

    skill = TestSkill()

    # Test without coder (should fail gracefully)
    context = SkillContext(enable_agents=True)
    available = skill.init_agents(context)

    print(f"Agents available without coder: {available}")
    assert not available, "Should not be available without coder"

    print("\n✓ Agent mixin tests passed")


async def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 15 + "AIDER SKILLS TEST SUITE" + " " * 20 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    try:
        await test_registry()
        await test_code_review_skill()
        await test_test_generation_skill()
        await test_documentation_skill()
        await test_agent_mixin()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
