#!/usr/bin/env python
"""
Test script for the multi-agent system.
"""

import asyncio
import sys

sys.path.insert(0, "/home/openclaw/openclaw/aider")

from aider.agents.agent import AgentResult, AgentStatus, SubAgent  # noqa: E402
from aider.agents.registry import AgentRegistry  # noqa: E402


async def test_registry():
    """Test the agent registry."""
    print("Testing AgentRegistry...")

    registry = AgentRegistry(max_concurrent=3)

    # Create test agents
    agent1 = SubAgent(
        id="test_1",
        name="Test Agent 1",
        task="Test task 1",
        model="claude-sonnet",
        files=["test1.py"],
        status=AgentStatus.PENDING,
    )

    agent2 = SubAgent(
        id="test_2",
        name="Test Agent 2",
        task="Test task 2",
        model="gpt-4o",
        files=["test2.py"],
        status=AgentStatus.PENDING,
    )

    # Test registration
    await registry.register(agent1)
    await registry.register(agent2)
    print("  ✓ Registered 2 agents")

    # Test get
    retrieved = await registry.get("test_1")
    assert retrieved.name == "Test Agent 1"
    print("  ✓ Get agent by ID works")

    # Test list_agents
    all_agents = await registry.list_agents()
    assert len(all_agents) == 2
    print("  ✓ List agents works")

    # Test status update (direct property access)
    result = AgentResult(success=True, output="Test output", files_modified=["test1.py"])
    agent1.status = AgentStatus.COMPLETED
    agent1.result = result
    agent1.completed_at = agent1.created_at + 1.0

    retrieved = await registry.get("test_1")
    assert retrieved.status == AgentStatus.COMPLETED
    assert retrieved.result.output == "Test output"
    print("  ✓ Update status works")

    # Test list_active
    active = await registry.list_active()
    assert len(active) == 1
    assert active[0].id == "test_2"
    print("  ✓ List active agents works")

    # Test statistics
    stats = await registry.get_stats()
    assert stats["total"] == 2
    assert stats["completed"] == 1
    assert stats["pending"] == 1
    print("  ✓ Statistics works")

    print("AgentRegistry tests passed!\n")


async def test_integration():
    """Test the integration module."""
    print("Testing integration helpers...")

    import argparse

    from aider.agents.integration import add_cli_args

    parser = argparse.ArgumentParser()
    add_cli_args(parser)

    # Parse test args
    args = parser.parse_args(["--enable-agents", "--max-agents", "10"])

    assert args.enable_agents is True
    assert args.max_agents == 10
    assert args.agent_timeout == 300.0  # default

    print("  ✓ CLI args parsing works")
    print("Integration tests passed!\n")


async def test_commands():
    """Test the commands module."""
    print("Testing AgentCommands...")

    from aider.agents.commands import AgentCommands

    # Create a mock commands object
    class MockCoder:
        def __init__(self):
            self.main_model = type("obj", (object,), {"name": "test-model"})()

    class MockCommands:
        def __init__(self):
            self.coder = MockCoder()
            self.io = type(
                "obj",
                (object,),
                {
                    "tool_output": lambda *args: print(f"  > {' '.join(map(str, args))}"),
                    "tool_error": lambda *args: print(f"  ERROR: {' '.join(map(str, args))}"),
                },
            )()

    mock_commands = MockCommands()
    agent_cmds = AgentCommands(mock_commands)

    # Test agent spawning (without actually running)
    print("  ✓ AgentCommands initialized")

    # Test help text
    assert "spawn" in agent_cmds.cmd_agent.__doc__
    assert "list" in agent_cmds.cmd_agent.__doc__
    assert "status" in agent_cmds.cmd_agent.__doc__
    print("  ✓ Help text is correct")

    print("AgentCommands tests passed!\n")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Aider Multi-Agent System Tests")
    print("=" * 60)
    print()

    try:
        await test_registry()
        await test_integration()
        await test_commands()

        print("=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
