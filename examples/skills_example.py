#!/usr/bin/env python3
"""
Example: Using Aider Skills with Multi-Agent Support

This example demonstrates how to use skills that can spawn sub-agents
for parallel task execution.
"""

import asyncio
import sys
sys.path.insert(0, '/home/openclaw/openclaw/aider')

from aider.skills.registry import create_skill, get_registry
from aider.skills.base import SkillContext


async def example_basic_skill_usage():
    """Example: Using skills without agents (sequential mode)."""
    print("=" * 60)
    print("Example 1: Basic Skill Usage (Sequential)")
    print("=" * 60)
    print()
    
    # Create context (agents disabled)
    context = SkillContext(
        enable_agents=False,
        verbose=True
    )
    
    # Create a skill instance
    skill = create_skill("code-review", context)
    
    if skill:
        print(f"Running skill: {skill.name}")
        print(f"Description: {skill.description}")
        print()
        
        # Execute the skill
        result = await skill.execute(
            files=["auth.py", "models.py", "views.py"],
            focus="security"
        )
        
        print(f"\nResult:")
        print(f"  Success: {result.success}")
        print(f"  Files reviewed: {result.data.get('files_reviewed', 0)}")
        print(f"  Execution time: {result.execution_time:.2f}s")
    
    print()


async def example_listing_skills():
    """Example: Listing available skills."""
    print("=" * 60)
    print("Example 2: Listing Available Skills")
    print("=" * 60)
    print()
    
    registry = get_registry()
    
    # All skills
    print("All Skills:")
    all_skills = registry.list_skills()
    for skill in all_skills:
        print(f"  - {skill['name']}: {skill['description']}")
    
    print(f"\nTotal: {len(all_skills)} skills")
    
    # Agent-enabled skills
    print("\nAgent-Enabled Skills:")
    agent_skills = registry.list_skills(supports_agents=True)
    for skill in agent_skills:
        print(f"  🤖 {skill['name']} (max {skill['max_agents']} agents)")
    
    print()


async def example_skill_with_agents():
    """Example: Using skills with sub-agents enabled."""
    print("=" * 60)
    print("Example 3: Skills with Multi-Agent Support")
    print("=" * 60)
    print()
    
    # Context with agents enabled
    context = SkillContext(
        enable_agents=True,
        max_agents=5,
        agent_timeout=300.0,
        verbose=True
    )
    
    print("Agent Configuration:")
    print(f"  Enabled: {context.enable_agents}")
    print(f"  Max agents: {context.max_agents}")
    print(f"  Timeout: {context.agent_timeout}s")
    print()
    
    # Create skill
    skill = create_skill("test-generation", context)
    
    if skill:
        print(f"Running skill with agents: {skill.name}")
        print()
        
        # Note: Without a real coder instance, this will use sequential fallback
        # In real usage with Aider, this would spawn sub-agents
        result = await skill.execute(
            files=["user.py", "auth.py", "api.py"],
            test_framework="pytest",
            coverage_target=80.0
        )
        
        print(f"\nResult:")
        print(f"  Success: {result.success}")
        print(f"  Test files: {result.files_modified}")


async def example_searching_skills():
    """Example: Searching for skills."""
    print("\n" + "=" * 60)
    print("Example 4: Searching Skills")
    print("=" * 60)
    print()
    
    registry = get_registry()
    
    queries = ["test", "doc", "review"]
    
    for query in queries:
        print(f"\nSearch: '{query}'")
        results = registry.search(query)
        for skill in results:
            print(f"  - {skill['name']}")


async def example_skill_varieties():
    """Example: Different types of skills."""
    print("\n" + "=" * 60)
    print("Example 5: Different Skill Types")
    print("=" * 60)
    print()
    
    context = SkillContext(enable_agents=False)
    
    skills_to_demo = [
        ("code-review", {"files": ["main.py"], "focus": "general"}),
        ("security-audit", {"files": ["auth.py"]}),
        ("test-generation", {"files": ["user.py"], "test_framework": "pytest"}),
        ("documentation", {"files": ["api.py"], "doc_format": "google"}),
    ]
    
    for skill_name, kwargs in skills_to_demo:
        skill = create_skill(skill_name, context)
        if skill:
            print(f"\n{skill.name}")
            print(f"  {skill.description}")
            print(f"  Supports agents: {skill.supports_agents}")
            print(f"  Max agents: {getattr(skill, 'max_agents', 0)}")


async def example_map_reduce_pattern():
    """Example: Map-Reduce pattern with skills."""
    print("\n" + "=" * 60)
    print("Example 6: Map-Reduce Pattern")
    print("=" * 60)
    print()
    
    from aider.skills.agent_skill import MapReduceSkill
    
    context = SkillContext(enable_agents=False)  # Sequential for demo
    
    skill = MapReduceSkill()
    skill.context = context
    
    # Simulate map-reduce on code files
    items = ["auth.py", "models.py", "views.py", "utils.py"]
    
    print(f"Items to process: {items}")
    print(f"Map prompt template: Analyze {{item}} for complexity")
    print(f"Reduce prompt: Summarize findings")
    print()
    
    result = await skill.map_reduce(
        items=items,
        map_prompt_template="Analyze the complexity of {item}. Rate 1-10.",
        reduce_prompt="Summarize the complexity analysis and identify the most complex file.",
        context=context
    )
    
    print(f"Result:")
    print(f"  Success: {result.success}")
    print(f"  Output: {result.output[:200]}..." if len(result.output) > 200 else f"  Output: {result.output}")


async def main():
    """Run all examples."""
    await example_basic_skill_usage()
    await example_listing_skills()
    await example_skill_with_agents()
    await example_searching_skills()
    await example_skill_varieties()
    await example_map_reduce_pattern()
    
    print("\n" + "=" * 60)
    print("All Examples Completed!")
    print("=" * 60)
    print()
    print("Key Takeaways:")
    print("  • Skills provide reusable capabilities")
    print("  • Agent-enabled skills can spawn sub-agents for parallel work")
    print("  • Skills fallback to sequential mode when agents unavailable")
    print("  • Skills can be discovered, searched, and executed programmatically")


if __name__ == "__main__":
    asyncio.run(main())
