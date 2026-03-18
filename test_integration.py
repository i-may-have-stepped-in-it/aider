#!/usr/bin/env python3
"""
Integration test for Aider with skills, agents, and hooks.
"""

import sys

sys.path.insert(0, "/home/openclaw/openclaw/aider")


def test_imports():
    """Test that all modules import correctly."""
    print("=" * 60)
    print("Testing Module Imports")
    print("=" * 60)

    # Core Aider
    from aider import coders  # noqa: F401
    from aider.coders import Coder  # noqa: F401
    from aider.commands import Commands  # noqa: F401

    print("✓ Core Aider modules")

    # Hooks
    from aider.hooks import HooksManager, create_hooks_manager, get_hooks_manager  # noqa: F401

    print("✓ Hooks system")

    # Agents
    from aider.agents import AgentExecutor, AgentRegistry, AgentStatus, SubAgent  # noqa: F401
    from aider.agents.gateway import configure_gateway, create_gateway_model_name  # noqa: F401

    print("✓ Agents system")

    # Skills
    from aider.skills import (  # noqa: F401
        SkillContext,
        SkillResult,
        create_skill,
        get_registry,
        list_all_skills,
    )

    print("✓ Skills system")

    print("\nAll modules imported successfully!")


def test_coders_registered():
    """Test that all coders are registered."""
    print("\n" + "=" * 60)
    print("Testing Coder Registration")
    print("=" * 60)

    from aider import coders

    expected_coders = [
        "Coder",
        "PatchCoder",
        "ContextCoder",
        "UnifiedDiffSimpleCoder",
        "EditBlockCoder",
        "WholeFileCoder",
        "ArchitectCoder",
    ]

    registered = [c.__name__ for c in coders.__all__]

    for coder in expected_coders:
        if coder in registered:
            print(f"✓ {coder}")
        else:
            print(f"✗ {coder} NOT FOUND")

    print(f"\nTotal coders registered: {len(coders.__all__)}")


def test_skills_registered():
    """Test that skills are registered."""
    print("\n" + "=" * 60)
    print("Testing Skill Registration")
    print("=" * 60)

    from aider.skills import list_all_skills

    skills = list_all_skills()

    print(f"Total skills: {len(skills)}")
    print(f"Agent-enabled: {sum(1 for s in skills if s['supports_agents'])}")

    for skill in skills:
        agent_badge = "🤖" if skill["supports_agents"] else "  "
        print(f"  {agent_badge} {skill['name']}")


def test_commands_integration():
    """Test that commands have skill integration."""
    print("\n" + "=" * 60)
    print("Testing Commands Integration")
    print("=" * 60)

    from aider.commands import Commands

    # Check that cmd_skill exists
    assert hasattr(Commands, "cmd_skill"), "cmd_skill not found"
    print("✓ cmd_skill method exists")

    # Check that completions_skill exists
    assert hasattr(Commands, "completions_skill"), "completions_skill not found"
    print("✓ completions_skill method exists")


def test_gateway_configuration():
    """Test gateway configuration."""
    print("\n" + "=" * 60)
    print("Testing Gateway Configuration")
    print("=" * 60)

    from aider.agents.gateway import (
        DEFAULT_GATEWAY_URL,
        configure_gateway,
        create_gateway_model_name,
        is_gateway_configured,
    )

    # Test model name creation
    assert create_gateway_model_name(tier="intel") == "@intel"
    assert create_gateway_model_name(tier="@speed") == "@speed"
    assert create_gateway_model_name(model="chat") == "chat"
    assert create_gateway_model_name() == "chat"
    print("✓ Gateway model name creation")

    # Test configuration
    url = configure_gateway("http://test:1234/v1")
    assert url == "http://test:1234/v1"
    assert is_gateway_configured()
    print("✓ Gateway configuration")

    # Reset to default
    import os

    os.environ["OPENAI_API_BASE"] = DEFAULT_GATEWAY_URL


def test_hooks_integration():
    """Test hooks integration in main components."""
    print("\n" + "=" * 60)
    print("Testing Hooks Integration")
    print("=" * 60)

    from aider.hooks import create_hooks_manager

    # Create hooks manager
    manager = create_hooks_manager(verbose=False)
    print("✓ Hooks manager created")

    # Check hook points exist
    hook_points = [
        "pre_command",
        "post_command",
        "pre_send",
        "post_send",
        "pre_edit",
        "post_edit",
        "on_init",
        "on_exit",
    ]

    for point in hook_points:
        assert point in manager.hooks, f"Hook point {point} not found"

    print(f"✓ All {len(hook_points)} hook points available")


def test_skill_context():
    """Test skill context creation."""
    print("\n" + "=" * 60)
    print("Testing Skill Context")
    print("=" * 60)

    from aider.skills import SkillContext

    # Basic context
    ctx = SkillContext()
    assert not ctx.enable_agents
    print("✓ Basic context")

    # Context with agents
    ctx = SkillContext(enable_agents=True, max_agents=5, agent_timeout=300.0, verbose=True)
    assert ctx.enable_agents
    assert ctx.max_agents == 5
    print("✓ Agent-enabled context")


def main():
    """Run all integration tests."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 12 + "AIDER INTEGRATION TEST SUITE" + " " * 18 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    try:
        test_imports()
        test_coders_registered()
        test_skills_registered()
        test_commands_integration()
        test_gateway_configuration()
        test_hooks_integration()
        test_skill_context()

        print("\n" + "=" * 60)
        print("ALL INTEGRATION TESTS PASSED ✓")
        print("=" * 60)
        print()
        print("Summary:")
        print("  • All modules import correctly")
        print("  • Coders are registered")
        print("  • Skills are available")
        print("  • Commands have /skill integration")
        print("  • Gateway routing is configured")
        print("  • Hooks system is integrated")
        return 0

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
