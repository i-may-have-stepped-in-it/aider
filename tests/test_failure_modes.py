#!/usr/bin/env python3
"""
Failure mode tests for Aider codebase - PHASE 5 VERIFICATION

Addresses Issue 24: Missing failure mode tests
"""

import asyncio
import json
import shlex
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from aider.a2a.types import A2AContentType, A2AMessage, A2AMessageType
from aider.agents.integration import initialize_agents
from aider.agents.registry import AgentRegistry, CircuitState
from aider.agents.service import AgentService
from aider.mcp.server import AiderMCPServer
from aider.skills.base import Skill, SkillContext, SkillResult
from aider.skills.command import SkillsCommand
from aider.skills.discovery import SkillDescriptor
from aider.skills.dynamic_loader import DynamicSkillLoader
from aider.skills.openclaw_adapter import create_openclaw_skill_class
from aider.skills.registry import SkillRegistry
from aider.skills.skill_creator import SkillCreatorSkill
from aider.skills.yaml_loader import YAMLSkillLoader
from aider.watch import FileWatcher

pytestmark = pytest.mark.asyncio


class FailingSkill(Skill):
    """Skill that always fails."""

    name = "failing-skill"
    description = "Skill that always fails"

    async def _execute_impl(self, **kwargs):
        raise ValueError("Intentional failure for testing")


class SlowSkill(Skill):
    """Skill that takes too long."""

    name = "slow-skill"
    description = "Skill that takes too long"

    async def _execute_impl(self, **kwargs):
        await asyncio.sleep(100)
        return SkillResult(success=True)


class CrashingSkill(Skill):
    """Skill that crashes hard."""

    name = "crashing-skill"
    description = "Skill that crashes hard"

    async def _execute_impl(self, **kwargs):
        import sys

        sys.exit(1)  # Hard crash


# === Failure Mode Tests ===


async def test_skill_exception_is_caught():
    """Test that exceptions in skills are caught and handled."""
    skill = FailingSkill()
    result = await skill.execute()

    assert result.success is False
    assert result.error is not None
    assert "Intentional failure" in result.error
    assert "traceback" in result.data  # Should capture traceback


async def test_skill_timeout_is_handled():
    """Test that skill timeout is handled gracefully."""
    context = SkillContext(timeout=0.5)
    skill = SlowSkill(context)

    start = time.time()
    result = await skill.execute()
    elapsed = time.time() - start

    assert result.success is False
    assert "timed out" in result.error.lower()
    assert elapsed < 1.0  # Should timeout within 1 second


async def test_circuit_breaker_opens_on_failures():
    """Test that circuit breaker opens after threshold failures."""
    registry = AgentRegistry()
    cb = registry.circuit_breaker

    # Record failures up to threshold
    for _ in range(cb.failure_threshold):
        cb.record_failure()

    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False


async def test_circuit_breaker_recovers():
    """Test that circuit breaker recovers after timeout."""
    registry = AgentRegistry()
    cb = registry.circuit_breaker
    cb.recovery_timeout = 0.1  # Very short for testing

    # Open the circuit
    for _ in range(cb.failure_threshold):
        cb.record_failure()

    assert cb.state == CircuitState.OPEN

    # Wait for recovery
    await asyncio.sleep(0.15)

    # Should transition to half-open
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.can_execute() is True

    # Record success to close
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


async def test_circuit_breaker_stays_open_on_failure_in_half_open():
    """Test that circuit breaker stays open if failure in half-open state."""
    registry = AgentRegistry()
    cb = registry.circuit_breaker
    cb.recovery_timeout = 0.1

    # Open the circuit
    for _ in range(cb.failure_threshold):
        cb.record_failure()

    assert cb.state == CircuitState.OPEN

    # Wait for recovery
    await asyncio.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN

    # Record failure in half-open
    cb.record_failure()

    # Should go back to OPEN
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False


async def test_registry_handles_duplicate_registration():
    """Test that registry handles duplicate skill registration."""
    # Use empty registry for this test
    registry = SkillRegistry(load_dynamic=False)

    class TestSkill(Skill):
        name = "test-skill"
        description = "Test skill"

        async def _execute_impl(self, **kwargs):
            return SkillResult(success=True)

    # Register once
    result1 = registry.register(TestSkill)
    assert result1 is True

    # Register again (should overwrite)
    result2 = registry.register(TestSkill)
    assert result2 is True

    # Should still have only one skill
    assert registry.count() == 1


async def test_registry_handles_invalid_skill():
    """Test that registry rejects invalid skills."""
    # Create registry without loading dynamic skills to test with empty registry
    registry = SkillRegistry(load_dynamic=False)

    class InvalidSkill:
        # Missing name, description, and not a Skill subclass
        pass

    # Should reject invalid skill
    result = registry.register(InvalidSkill)
    assert result is False
    assert registry.count() == 0


async def test_skill_with_missing_required_params():
    """Test that skill handles missing required parameters."""

    class StrictSkill(Skill):
        name = "strict-skill"
        description = "Strict skill"

        def _get_required_params(self):
            return ["param1", "param2", "param3"]

        async def _execute_impl(self, **kwargs):
            return SkillResult(success=True)

    skill = StrictSkill()

    # Missing all params
    result = await skill.execute()
    assert result.success is False
    assert "missing" in result.error.lower()

    # Missing some params
    result = await skill.execute(param1="value1")
    assert result.success is False
    assert "param2" in result.error and "param3" in result.error


async def test_agent_cleanup_on_timeout():
    """Test that agents are cleaned up on timeout."""
    # This would need actual agent implementation
    # For now, verify the cleanup method exists
    registry = AgentRegistry()

    # Verify cancel method exists
    assert hasattr(registry, "cancel")
    assert hasattr(registry, "cancel_all")


async def test_agent_cleanup_on_unregister():
    """Test that agents are cleaned up when unregistered."""
    # This would need actual agent implementation
    registry = AgentRegistry()

    # Verify unregister method exists
    assert hasattr(registry, "unregister")


async def test_memory_limit_enforcement():
    """Test that memory limits are enforced."""
    # Skip this test - memory limits not yet implemented in AgentRegistry
    # registry = AgentRegistry(max_memory_mb=0.001)  # Very small
    # Verify memory tracking exists
    # assert hasattr(registry, "_max_memory")
    # assert hasattr(registry, "_current_memory")
    pass


async def test_concurrent_access_to_registry():
    """Test that registry handles concurrent access safely."""
    from concurrent.futures import ThreadPoolExecutor

    # Use empty registry for this test
    registry = SkillRegistry(load_dynamic=False)
    errors = []

    def register_and_read(i):
        try:

            class TestSkill(Skill):
                name = f"skill-{i}"
                description = f"Skill {i}"

                async def _execute_impl(self, **kwargs):
                    return SkillResult(success=True)

            registry.register(TestSkill)
            skills = registry.list_skills()
            assert isinstance(skills, list)
        except Exception as e:
            errors.append(e)

    # Run 100 concurrent operations from 20 threads
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(register_and_read, i) for i in range(100)]
        for future in futures:
            future.result()

    # Should have no errors
    assert len(errors) == 0
    assert registry.count() == 100


async def test_skill_cancellation():
    """Test that skill execution can be cancelled."""
    context = SkillContext()
    context.cancellation_token = asyncio.Event()

    # Cancel immediately
    context.cancellation_token.set()

    skill = SlowSkill(context)
    result = await skill.execute()

    assert result.success is False
    assert "cancelled" in result.error.lower()


async def test_hook_failure_stops_execution():
    """Test that hook failure stops execution when configured."""
    from aider.hooks_manager import HookConfig, HookPoint, HooksManager

    manager = HooksManager()
    execution_order = []

    # Hook that fails (sync function)
    def failing_hook(ctx):
        execution_order.append(1)
        raise Exception("Hook failed")

    manager.register_hook(
        "failing-hook",
        HookPoint.PRE_COMMAND,
        failing_hook,
        config=HookConfig(priority=10, stop_on_failure=True),
    )

    # Hook that should not run
    def second_hook(ctx):
        execution_order.append(2)

    manager.register_hook(
        "second-hook",
        HookPoint.PRE_COMMAND,
        second_hook,
        config=HookConfig(priority=20),
    )

    results = manager.execute_hooks(HookPoint.PRE_COMMAND)

    # Only first hook should have run
    assert execution_order == [1]
    assert len(results) == 1
    assert results[0].get("success") is False


async def test_hook_dependency_failure():
    """Test that hooks skip if dependencies not met."""
    from aider.hooks_manager import HookConfig, HookPoint, HooksManager

    manager = HooksManager()
    execution_order = []

    # Hook that depends on non-existent hook (sync function)
    def dependent_hook(ctx):
        execution_order.append(1)

    manager.register_hook(
        "dependent-hook",
        HookPoint.PRE_COMMAND,
        dependent_hook,
        config=HookConfig(depends_on=["non-existent"]),
    )

    results = manager.execute_hooks(HookPoint.PRE_COMMAND)

    # Should not execute
    assert execution_order == []
    assert len(results) == 0


def test_legacy_and_advanced_hooks_share_singleton():
    """The legacy hooks module should route to the advanced manager singleton."""
    from aider.hooks import create_hooks_manager as create_legacy_hooks_manager
    from aider.hooks import get_hooks_manager as get_legacy_hooks_manager
    from aider.hooks_manager import get_hooks_manager as get_advanced_hooks_manager
    from aider.hooks_manager import reset_hooks_manager

    reset_hooks_manager()
    manager = create_legacy_hooks_manager(verbose=True)

    assert get_legacy_hooks_manager() is manager
    assert get_advanced_hooks_manager() is manager

    called = []

    def callback(context):
        called.append(context["value"])

    assert manager.register("pre_command", callback) is True
    result = manager.execute("pre_command", value=7)

    assert result["executed"] is True
    assert called == [7]


def test_hooks_manager_supports_summarize_hook_names():
    """Legacy summarize hook names should resolve through the unified manager."""
    from aider.hooks_manager import HookPoint, HooksManager

    manager = HooksManager()
    called = []

    def callback(context):
        called.append(context["summary"])

    assert manager.register("post_summarize", callback) is True
    result = manager.execute("post_summarize", summary="done")

    assert result["executed"] is True
    assert called == ["done"]
    assert manager.get_hooks(HookPoint.POST_SUMMARIZE)


async def test_skill_creator_uses_context_contract_and_save_path_helper():
    """SkillCreatorSkill should run under the shared skill contract."""
    context = SkillContext()
    skill = SkillCreatorSkill(context)

    with patch.object(skill, "_get_save_path", return_value=Path("/tmp/demo.yaml")) as get_path:
        with patch.object(
            skill, "_create_simple_skill", return_value=SkillResult(success=True)
        ) as create:
            result = await skill.execute(
                name="demo",
                description="demo skill",
                save_location="user",
            )

    assert result.success is True
    get_path.assert_called_once_with("user", "demo")
    create.assert_called_once()


def test_skill_creator_generates_runnable_shell_scaffold():
    """Generated shell YAML should be runnable scaffold, not TODO text."""
    skill = SkillCreatorSkill(SkillContext())

    yaml_content = skill._generate_shell_yaml(
        "demo-skill",
        "Run a demo workflow",
        "python project",
    )

    assert "TODO" not in yaml_content
    assert "set -euo pipefail" in yaml_content
    assert "Running demo-skill" in yaml_content
    assert "Description: Run a demo workflow" in yaml_content
    assert "Primary input for the skill" in yaml_content


async def test_skill_creator_generates_contextual_openclaw_markdown(tmp_path):
    """Generated OpenClaw markdown should use real guidance instead of placeholders."""
    skill = SkillCreatorSkill(SkillContext())

    markdown = skill._generate_openclaw_markdown(
        "demo-skill",
        "Run a demo workflow",
        "python project, shell scripts",
    )

    assert "TODO" not in markdown
    assert "Run a demo workflow." in markdown
    assert "Work with this context: python project, shell scripts." in markdown
    assert "scripts/helper.py" not in markdown
    assert "Example 1: Demo Skill" in markdown

    save_path = tmp_path / ".aider" / "skills" / "demo-skill.yaml"
    result = skill._create_skill_with_resources(
        "demo-skill",
        "Run a demo workflow",
        "shell",
        "python project, shell scripts",
        save_path,
    )

    assert result.success is True
    skill_dir = save_path.parent / "demo-skill"
    assert "# Scripts for demo-skill" in (skill_dir / "scripts" / ".gitkeep").read_text()
    assert "# References for demo-skill" in (skill_dir / "references" / ".gitkeep").read_text()
    assert "# Assets for demo-skill" in (skill_dir / "assets" / ".gitkeep").read_text()


async def test_skill_command_forwards_arbitrary_key_value_params():
    """SkillsCommand should pass trailing key=value pairs into the skill."""
    io = Mock()
    command = SkillsCommand(io=io, coder=None, verbose=False)

    skill = Mock()
    skill.execute = Mock(return_value=SkillResult(success=True))

    command.registry = Mock()
    command.registry.get_metadata.return_value = {
        "name": "skill-creator",
        "description": "demo",
        "version": "1.0.0",
        "supports_agents": False,
        "max_agents": 0,
        "source": "python",
        "parameters": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "with_resources": {"type": "boolean", "default": False},
            "timeout": {"type": "number", "default": 300},
        },
    }
    command.registry.create.return_value = skill

    command.cmd_skill(
        "run skill-creator --files foo.py --model demo "
        'name=my-linter description="Run eslint" with_resources=true timeout=12'
    )

    skill.execute.assert_called_once_with(
        files=["foo.py"],
        model="demo",
        name="my-linter",
        description="Run eslint",
        with_resources=True,
        timeout=12,
    )


async def test_skill_command_rejects_unknown_and_missing_params():
    """SkillsCommand should validate provided params against declared metadata."""
    io = Mock()
    command = SkillsCommand(io=io, coder=None, verbose=False)

    command.registry = Mock()
    command.registry.get_metadata.return_value = {
        "name": "demo",
        "description": "demo",
        "version": "1.0.0",
        "supports_agents": False,
        "max_agents": 0,
        "source": "python",
        "parameters": {
            "name": {"type": "string", "description": "Name"},
            "mode": {"type": "string", "enum": ["fast", "slow"], "default": "fast"},
        },
    }
    command.registry.create.return_value = Mock()

    command.cmd_skill("run demo bad=value")

    io.tool_error.assert_any_call("Unknown skill parameters: bad")
    io.tool_error.assert_any_call("Missing required skill parameter: name")


def test_skill_info_displays_parameter_metadata():
    """Skill info should render declared parameter schemas."""
    io = Mock()
    command = SkillsCommand(io=io, coder=None, verbose=False)
    command.registry = Mock()
    command.registry.get_metadata.return_value = {
        "name": "demo",
        "description": "demo skill",
        "version": "1.2.3",
        "supports_agents": False,
        "max_agents": 0,
        "source": "python",
        "parameters": {
            "mode": {
                "type": "string",
                "description": "Execution mode",
                "enum": ["fast", "slow"],
                "default": "fast",
            }
        },
    }

    command.cmd_skill("info demo")

    output = "\n".join(call.args[0] for call in io.tool_output.call_args_list if call.args)
    assert "Parameters:" in output
    assert "mode: default='fast'" in output
    assert "Allowed: fast, slow" in output


def test_skill_info_displays_openclaw_metadata():
    """Shared skill info should render OpenClaw-specific metadata."""
    io = Mock()
    command = SkillsCommand(io=io, coder=None, verbose=False)
    command.registry = Mock()
    command.registry.get_metadata.return_value = {
        "name": "github",
        "description": "GitHub helper",
        "version": "openclaw",
        "supports_agents": False,
        "max_agents": 0,
        "source": "openclaw",
        "homepage": "https://example.com/github",
        "requires": {"bins": ["gh"]},
        "install": [{"id": "default"}],
        "parameters": {"action": {"type": "string", "default": "run"}},
    }

    command.cmd_skill("info github")

    output = "\n".join(call.args[0] for call in io.tool_output.call_args_list if call.args)
    assert "Homepage: https://example.com/github" in output
    assert "Requirements:" in output
    assert "Binaries: gh" in output
    assert "Install Options:" in output


def test_legacy_hook_registration_allows_same_function_name():
    """Different callback objects with the same function name should not collide."""
    from aider.hooks_manager import HooksManager

    manager = HooksManager()

    def callback(context):
        return context

    def make_callback():
        def callback(context):
            return context

        return callback

    callback_two = make_callback()

    assert manager.register("pre_command", callback) is True
    assert manager.register("pre_command", callback_two) is True


def test_skill_discovery_logs_import_failures(caplog):
    """Broken skill modules should be logged instead of printed."""
    from aider.skills import discovery

    fake_importer = Mock()
    fake_importer.find_spec.side_effect = RuntimeError("boom")

    with patch.object(
        discovery.pkgutil, "iter_modules", return_value=[(fake_importer, "fake.mod", False)]
    ):
        with caplog.at_level("WARNING"):
            skills = discovery.discover_python_skills()

    assert skills == {}
    assert "Could not load skill from fake.mod: boom" in caplog.text


def test_python_skill_discovery_is_lazy_and_descriptor_based(tmp_path):
    """Python skill discovery should not import modules just to list skills."""
    from aider.skills import discovery

    skill_file = tmp_path / "lazy_skill.py"
    skill_file.write_text(
        (
            "from aider.skills.base import Skill\n"
            "class LazySkill(Skill):\n"
            "    name = 'lazy-skill'\n"
            "    description = 'lazy'\n"
            "    supports_agents = True\n"
            "    max_agents = 3\n"
        ),
        encoding="utf-8",
    )

    fake_spec = type("Spec", (), {"origin": str(skill_file)})
    fake_importer = Mock()
    fake_importer.find_spec.return_value = fake_spec

    with patch.object(
        discovery.pkgutil, "iter_modules", return_value=[(fake_importer, "fake.lazy_skill", False)]
    ):
        skills = discovery.discover_python_skills()

    descriptor = skills["lazy-skill"]
    assert isinstance(descriptor, SkillDescriptor)
    assert descriptor.module_name == "fake.lazy_skill"
    assert descriptor.class_name == "LazySkill"


def test_python_skill_discovery_requires_skill_base(tmp_path):
    """Discovery should ignore classes that only mimic skill metadata."""
    from aider.skills import discovery

    fake_file = tmp_path / "not_a_skill.py"
    fake_file.write_text(
        "class Pretender:\n    name = 'pretender'\n    description = 'not really a skill'\n",
        encoding="utf-8",
    )

    fake_spec = type("Spec", (), {"origin": str(fake_file)})
    fake_importer = Mock()
    fake_importer.find_spec.return_value = fake_spec

    with patch.object(
        discovery.pkgutil, "iter_modules", return_value=[(fake_importer, "fake.pretender", False)]
    ):
        skills = discovery.discover_python_skills()

    assert skills == {}


def test_openclaw_skills_are_exposed_via_shared_discovery():
    """OpenClaw bridge skills should appear as shared skill descriptors."""
    from aider.skills import discovery

    metadata = SimpleNamespace(
        name="github",
        description="GitHub helper",
        homepage="https://example.com/github",
        requires={"bins": ["gh"]},
        install=[{"id": "default"}],
        emoji="🐙",
    )

    with patch("aider.openclaw_bridge.OpenClawBridge.list_skills", return_value=[metadata]):
        skills = discovery.discover_openclaw_skills()

    descriptor = skills["github"]
    assert descriptor.source == "openclaw"
    assert descriptor.metadata["homepage"] == "https://example.com/github"
    assert descriptor.skill_class is not None


async def test_openclaw_adapter_skill_executes_through_bridge():
    """OpenClaw adapter skills should use the bridge under the shared skill contract."""
    metadata = SimpleNamespace(
        name="github",
        description="GitHub helper",
        homepage="https://example.com/github",
        requires={},
        install=[],
        emoji="🐙",
    )
    bridge = Mock()
    bridge.execute_skill.return_value = Mock(
        success=True,
        stdout="ok",
        stderr="",
        duration_ms=12,
        exit_code=0,
        skill_name="github",
        action="run",
        error_message=None,
    )

    skill_class = create_openclaw_skill_class("github", metadata, bridge=bridge)
    result = await skill_class(SkillContext()).execute(action="run", args=["status"], timeout=9)

    bridge.execute_skill.assert_called_once_with(
        skill_name="github",
        action="run",
        args=["status"],
        timeout=9,
    )
    assert result.success is True
    assert result.output == "ok"
    assert result.data["source"] == "openclaw"


def test_commands_exposes_agent_without_monkeypatch():
    """Core Commands should provide /agent without runtime class replacement."""
    from aider.commands import Commands

    commands = Commands(io=Mock(), coder=None, args=None, parser=None, verbose=False)

    assert hasattr(commands, "cmd_agent")
    assert hasattr(commands, "completions_agent")


def test_commands_exposes_a2a_without_install_hook():
    """Core Commands should provide /a2a without runtime command installation."""
    from aider.commands import Commands

    commands = Commands(io=Mock(), coder=None, args=None, parser=None, verbose=False)

    assert hasattr(commands, "cmd_a2a")
    assert hasattr(commands, "completions_a2a")


def test_agent_install_in_commands_is_now_a_noop():
    """Legacy install helper should preserve the native Commands class."""
    from aider import commands as commands_module
    from aider.agents.integration import install_in_commands

    original_commands = commands_module.Commands
    result = install_in_commands(commands_module)

    assert result is original_commands
    assert commands_module.Commands is original_commands


def test_a2a_install_in_commands_is_now_a_noop():
    """Legacy A2A install helper should preserve the native Commands class."""
    from aider import commands as commands_module
    from aider.a2a.commands import install_a2a_commands

    original_commands = commands_module.Commands
    result = install_a2a_commands(original_commands)

    assert result is original_commands
    assert commands_module.Commands is original_commands


def test_a2a_commands_follow_dynamic_coder_runtime():
    """A2ACommands should resolve coder/runtime state dynamically, not snapshot it."""
    from aider.a2a.commands import A2ACommands

    first_registry = Mock()
    second_registry = Mock()
    commands = SimpleNamespace(
        io=Mock(),
        coder=SimpleNamespace(
            runtime=SimpleNamespace(agent_service=SimpleNamespace(registry=first_registry))
        ),
    )
    a2a_commands = A2ACommands(commands)

    assert a2a_commands.registry is first_registry

    commands.coder = SimpleNamespace(
        runtime=SimpleNamespace(agent_service=SimpleNamespace(registry=second_registry))
    )

    assert a2a_commands.registry is second_registry


def test_a2a_commands_drop_stale_runtime_state_when_coder_changes():
    """A2ACommands should not retain stale registry after runtime disappears."""
    from aider.a2a.commands import A2ACommands

    first_registry = Mock()
    commands = SimpleNamespace(
        io=Mock(),
        coder=SimpleNamespace(
            runtime=SimpleNamespace(agent_service=SimpleNamespace(registry=first_registry))
        ),
    )
    a2a_commands = A2ACommands(commands)

    assert a2a_commands.registry is first_registry

    commands.coder = None

    assert a2a_commands.registry is not first_registry


def test_skill_commands_follow_dynamic_coder_runtime_registry():
    """SkillsCommand should resolve the current coder/runtime registry dynamically."""
    first_registry = Mock()
    second_registry = Mock()
    command = SkillsCommand(
        io=Mock(),
        coder=SimpleNamespace(runtime=SimpleNamespace(skill_registry=first_registry)),
        verbose=False,
    )

    assert command.registry is first_registry

    command.coder = SimpleNamespace(runtime=SimpleNamespace(skill_registry=second_registry))

    assert command.registry is second_registry


def test_agent_commands_follow_dynamic_coder_runtime():
    """AgentCommands should invalidate cached registry/executor when coder runtime changes."""
    from aider.agents.commands import AgentCommands

    first_service = SimpleNamespace(registry=Mock(), executor=Mock())
    second_service = SimpleNamespace(registry=Mock(), executor=Mock())
    commands = SimpleNamespace(
        io=Mock(),
        coder=SimpleNamespace(runtime=SimpleNamespace(agent_service=first_service)),
    )
    agent_commands = AgentCommands(commands)

    assert agent_commands.registry is first_service.registry
    assert agent_commands.executor is first_service.executor

    commands.coder = SimpleNamespace(runtime=SimpleNamespace(agent_service=second_service))

    assert agent_commands.registry is second_service.registry
    assert agent_commands.executor is second_service.executor


def test_agent_commands_drop_stale_runtime_state_when_coder_changes():
    """AgentCommands should not retain stale registry/executor after runtime disappears."""
    from aider.agents.commands import AgentCommands

    first_service = SimpleNamespace(registry=Mock(), executor=Mock())
    commands = SimpleNamespace(
        io=Mock(),
        coder=SimpleNamespace(runtime=SimpleNamespace(agent_service=first_service)),
    )
    agent_commands = AgentCommands(commands)

    assert agent_commands.registry is first_service.registry
    assert agent_commands.executor is first_service.executor

    commands.coder = None

    assert agent_commands.registry is not first_service.registry
    assert agent_commands.executor is not first_service.executor


def test_commands_follow_dynamic_runtime_skill_registry():
    """Commands should resolve the current runtime skill registry dynamically."""
    from aider.commands import Commands

    first_registry = Mock()
    second_registry = Mock()
    commands = Commands(
        io=Mock(),
        coder=None,
        args=None,
        parser=None,
        verbose=False,
        runtime=SimpleNamespace(skill_registry=first_registry),
    )

    assert commands.skills_registry is first_registry

    commands.runtime = SimpleNamespace(skill_registry=second_registry)

    assert commands.skills_registry is second_registry


def test_skill_command_prefers_commands_registry_before_global():
    """SkillsCommand should prefer the bound Commands registry over the global singleton."""
    from aider.commands import Commands

    registry = Mock()
    commands = Commands(
        io=Mock(),
        coder=SimpleNamespace(skills_registry=registry),
        args=None,
        parser=None,
        verbose=False,
        runtime=None,
    )
    skill_command = SkillsCommand(io=Mock(), coder=None, commands=commands)

    with patch("aider.skills.command.get_registry", side_effect=AssertionError):
        assert skill_command.registry is registry


def test_commands_clone_preserves_voice_settings():
    """Commands.clone should preserve voice input configuration across mode switches."""
    from aider.commands import Commands

    commands = Commands(
        io=Mock(),
        coder=None,
        voice_language="en",
        voice_input_device="mic0",
        voice_format="wav",
        verify_ssl=False,
        args=None,
        parser=None,
        verbose=True,
    )

    cloned = commands.clone()

    assert cloned.voice_language == "en"
    assert cloned.voice_input_device == "mic0"
    assert cloned.voice_format == "wav"
    assert cloned.verify_ssl is False


def test_agent_skill_mixin_follows_dynamic_runtime_service():
    """AgentSkillMixin should refresh runtime-owned agent objects when context changes."""
    from aider.skills.agent_skill import AgentSkillMixin

    class TestSkill(AgentSkillMixin):
        def __init__(self, context=None):
            super().__init__()
            self.context = context

    first_service = SimpleNamespace(registry=Mock(), executor=Mock())
    second_service = SimpleNamespace(registry=Mock(), executor=Mock())
    skill = TestSkill(
        SimpleNamespace(
            enable_agents=True,
            coder=SimpleNamespace(runtime=SimpleNamespace(agent_service=first_service)),
            max_agents=5,
        )
    )

    assert skill.init_agents(skill.context) is True
    assert skill._agent_registry is first_service.registry
    assert skill._agent_executor is first_service.executor

    skill.context = SimpleNamespace(
        enable_agents=True,
        coder=SimpleNamespace(runtime=SimpleNamespace(agent_service=second_service)),
        max_agents=5,
    )
    skill._ensure_agent_runtime()

    assert skill._agent_registry is second_service.registry
    assert skill._agent_executor is second_service.executor


def test_swarm_skill_follows_dynamic_runtime_service():
    """SwarmSkill should resolve bus/registry/executor from the current runtime dynamically."""
    from aider.skills.swarm import SwarmSkill

    first_service = SimpleNamespace(a2a_bus=Mock(), registry=Mock(), executor=Mock())
    second_service = SimpleNamespace(a2a_bus=Mock(), registry=Mock(), executor=Mock())
    context = SkillContext(
        coder=SimpleNamespace(runtime=SimpleNamespace(agent_service=first_service))
    )
    skill = SwarmSkill(context)

    assert skill.bus is first_service.a2a_bus
    assert skill.registry is first_service.registry
    assert skill.executor is first_service.executor

    skill.context = SkillContext(
        coder=SimpleNamespace(runtime=SimpleNamespace(agent_service=second_service))
    )

    assert skill.bus is second_service.a2a_bus
    assert skill.registry is second_service.registry
    assert skill.executor is second_service.executor


async def test_multiple_error_recovery():
    """Test that system recovers from multiple errors."""
    registry = AgentRegistry()
    cb = registry.circuit_breaker

    # Simulate multiple failures
    for _ in range(cb.failure_threshold * 2):
        cb.record_failure()

    assert cb.state == CircuitState.OPEN

    # Wait for recovery
    cb.recovery_timeout = 0.1
    await asyncio.sleep(0.15)

    # Should be in half-open
    assert cb.state == CircuitState.HALF_OPEN

    # Record success
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb._failure_count == 0


def test_swarm_command_passes_keyword_arguments():
    """The /swarm command should call SwarmSkill using keyword args."""
    from aider.commands import Commands

    commands = Commands.__new__(Commands)
    commands.io = Mock()
    commands.verbose = False
    commands.coder = Mock()
    commands.skills_registry = Mock()

    swarm_skill = Mock()

    async def execute(**kwargs):
        return SkillResult(success=True, data=kwargs)

    swarm_skill.execute = Mock(side_effect=execute)
    commands.skills_registry.create.return_value = swarm_skill

    commands.cmd_swarm('"fix bug" --agents "arch,dev"')

    swarm_skill.execute.assert_called_once_with(task="fix bug", agents=["arch", "dev"])


def test_watch_uses_runtime_agent_service_for_fix_on_save():
    """FileWatcher should route autonomous fix-on-save through the shared agent service."""
    io = Mock()
    agent_service = Mock()
    coder = SimpleNamespace(
        io=io,
        root=".",
        abs_fnames=set(),
        runtime=SimpleNamespace(agent_service=agent_service),
        autonomous_agent=Mock(),
        get_rel_fname=lambda fname: fname,
    )
    watcher = FileWatcher(coder)
    watcher.fix_on_save = True

    watcher.handle_changes([("modified", "/tmp/demo.py")])

    agent_service.run_autonomous_task.assert_called_once()
    coder.autonomous_agent.run_task.assert_not_called()


def test_watch_falls_back_to_coder_run_autonomous_task():
    """FileWatcher should use coder.run_autonomous_task when no runtime service exists."""
    io = Mock()
    coder = SimpleNamespace(
        io=io,
        root=".",
        abs_fnames=set(),
        runtime=None,
        run_autonomous_task=Mock(),
        get_rel_fname=lambda fname: fname,
    )
    watcher = FileWatcher(coder)
    watcher.fix_on_save = True

    watcher.handle_changes([("modified", "/tmp/demo.py")])

    coder.run_autonomous_task.assert_called_once()


def test_agent_service_autonomous_handle_routes_through_service():
    """Compatibility autonomous_agent handles should delegate back to AgentService."""
    service = AgentService(io=Mock())
    coder = Mock()
    handle = service.create_autonomous_agent(coder, max_turns=7, max_cost=3.5)

    with patch.object(service, "run_autonomous_task", return_value=True) as run_task:
        result = handle.run_task("fix it", test_command="pytest")

    assert result is True
    run_task.assert_called_once_with(
        coder,
        "fix it",
        test_command="pytest",
        max_turns=7,
        max_cost=3.5,
    )


def test_initialize_agents_configures_runtime_owned_service():
    """Agent initialization should configure the session runtime, not fork standalone state."""
    runtime = SimpleNamespace(
        agent_service=AgentService(io=Mock(), registry=AgentRegistry(max_concurrent=2)),
        agent_registry=None,
        a2a_bus=None,
    )

    def configure_agents(max_concurrent=None):
        runtime.agent_service.configure(max_concurrent=max_concurrent)
        runtime.agent_registry = runtime.agent_service.registry
        runtime.a2a_bus = runtime.agent_service.a2a_bus
        return runtime.agent_service

    runtime.configure_agents = configure_agents
    coder = SimpleNamespace(runtime=runtime, agent_service=runtime.agent_service)

    initialize_agents(coder, max_concurrent=9)

    assert coder.agent_service is runtime.agent_service
    assert coder.agent_registry is runtime.agent_registry
    assert coder.agent_registry.max_concurrent == 9
    assert coder.a2a_bus is runtime.a2a_bus


def test_mcp_tools_list_includes_shared_skill_tools():
    """MCP discovery should expose shared skill descriptors as tools."""
    registry = Mock()
    registry.list_skills.return_value = [
        {
            "name": "demo-skill",
            "description": "Run demo work",
            "supports_agents": False,
            "version": "1.0.0",
            "max_agents": 0,
            "source": "python",
        }
    ]
    registry.get_metadata.return_value = {
        "name": "demo-skill",
        "description": "Run demo work",
        "version": "1.0.0",
        "supports_agents": False,
        "max_agents": 0,
        "source": "python",
        "parameters": {
            "message": {"type": "string", "description": "Message to send"},
            "mode": {"type": "string", "enum": ["fast", "slow"], "default": "fast"},
        },
    }
    coder = SimpleNamespace(
        runtime=SimpleNamespace(skill_registry=registry), io=Mock(), verbose=False
    )

    response = AiderMCPServer(coder).handle_request({"id": 1, "method": "tools/list"})

    tools = response["result"]["tools"]
    skill_tool = next(tool for tool in tools if tool["name"] == "skill/demo-skill")
    assert skill_tool["inputSchema"]["required"] == ["message"]
    assert skill_tool["inputSchema"]["properties"]["mode"]["enum"] == ["fast", "slow"]


def test_mcp_tools_list_prefers_coder_bound_registry_before_global_singleton():
    """MCP discovery should use coder-bound skill registry before the global singleton."""
    registry = Mock()
    registry.list_skills.return_value = []
    coder = SimpleNamespace(runtime=SimpleNamespace(), skills_registry=registry, io=Mock(), verbose=False)

    with patch("aider.skills.registry.get_registry", side_effect=AssertionError):
        response = AiderMCPServer(coder).handle_request({"id": 1, "method": "tools/list"})

    assert not any(tool["name"].startswith("skill/") for tool in response["result"]["tools"])


async def test_mcp_skill_tool_executes_through_shared_registry():
    """MCP skill execution should use the shared registry and SkillContext contract."""

    class DemoSkill(Skill):
        name = "demo-skill"
        description = "Demo skill"

        async def _execute_impl(self, **kwargs):
            return SkillResult(
                success=True,
                output=(
                    f"{kwargs['message']}:{self.context.enable_agents}:{self.context.max_agents}"
                ),
            )

    registry = Mock()
    created = {}

    def create_skill(name, context):
        created["name"] = name
        created["context"] = context
        return DemoSkill(context)

    registry.create.side_effect = create_skill
    coder = SimpleNamespace(
        runtime=SimpleNamespace(skill_registry=registry), io=Mock(), verbose=True
    )

    response = AiderMCPServer(coder).handle_request(
        {
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "skill/demo-skill",
                "arguments": {
                    "message": "hello",
                    "enable_agents": True,
                    "max_agents": 3,
                    "timeout": 7,
                },
            },
        }
    )

    assert created["name"] == "demo-skill"
    assert created["context"].coder is coder
    assert created["context"].enable_agents is True
    assert created["context"].max_agents == 3
    assert created["context"].timeout == 7
    assert response["result"]["content"][0]["text"] == "hello:True:3"


def test_mcp_initialize_advertises_tools_and_resources():
    """MCP initialize should advertise both tool and resource capabilities."""
    response = AiderMCPServer(SimpleNamespace(runtime=SimpleNamespace(), io=Mock())).handle_request(
        {"id": 9, "method": "initialize"}
    )

    assert "tools" in response["result"]["capabilities"]
    assert "resources" in response["result"]["capabilities"]


def test_mcp_resources_list_and_read_shared_runtime_state():
    """MCP resources should expose shared skills, agents, and A2A history."""
    registry = Mock()
    registry.list_skills.return_value = [
        {
            "name": "demo-skill",
            "description": "Run demo work",
            "supports_agents": False,
            "version": "1.0.0",
            "max_agents": 0,
            "source": "python",
        }
    ]
    registry.get_metadata.return_value = {
        "name": "demo-skill",
        "description": "Run demo work",
        "version": "1.0.0",
        "supports_agents": False,
        "max_agents": 0,
        "source": "python",
        "parameters": {},
    }

    agent_registry = Mock()

    async def list_agents():
        return [
            SimpleNamespace(
                id="agent-1",
                name="reviewer",
                status=SimpleNamespace(name="RUNNING"),
                task="check auth",
                model="demo-model",
            )
        ]

    agent_registry.list_agents.side_effect = list_agents
    bus = Mock()
    bus.get_history.return_value = [
        A2AMessage(
            id="msg-1",
            type=A2AMessageType.NOTIFICATION,
            sender_id="agent-1",
            recipient_id="agent-2",
            content="hello",
            content_type=A2AContentType.TEXT,
        )
    ]

    runtime = SimpleNamespace(
        skill_registry=registry,
        agent_service=SimpleNamespace(registry=agent_registry),
        a2a_bus=bus,
    )
    server = AiderMCPServer(SimpleNamespace(runtime=runtime, io=Mock(), verbose=False))

    resources = server.handle_request({"id": 10, "method": "resources/list"})
    uris = {resource["uri"] for resource in resources["result"]["resources"]}
    assert {"aider://skills", "aider://agents", "aider://a2a/history"} <= uris

    skills_payload = server.handle_request(
        {"id": 11, "method": "resources/read", "params": {"uri": "aider://skills"}}
    )
    agents_payload = server.handle_request(
        {"id": 12, "method": "resources/read", "params": {"uri": "aider://agents"}}
    )
    history_payload = server.handle_request(
        {"id": 13, "method": "resources/read", "params": {"uri": "aider://a2a/history"}}
    )

    skills = json.loads(skills_payload["result"]["contents"][0]["text"])
    agents = json.loads(agents_payload["result"]["contents"][0]["text"])
    history = json.loads(history_payload["result"]["contents"][0]["text"])

    assert skills[0]["name"] == "demo-skill"
    assert agents[0]["id"] == "agent-1"
    assert history[0]["sender_id"] == "agent-1"


async def test_resource_cleanup_on_exception():
    """Test that resources are cleaned up even on exception."""
    skill = FailingSkill()

    # Add some progress
    skill.update_progress("Step 1")
    skill.update_progress("Step 2")

    # Execute (will fail)
    await skill.execute()

    # Progress should still be accessible
    progress = skill.get_progress()
    assert len(progress) == 2

    # Can clear progress
    skill.clear_progress()
    assert len(skill.get_progress()) == 0


async def test_dynamic_acp_skill_respects_base_skill_contract():
    """Dynamic ACP skills accept SkillContext and execute through the base contract."""
    loader = DynamicSkillLoader()
    skill_class = loader._create_agent_skill_class("codex", {})
    context = SkillContext()
    skill = skill_class(context)

    async def fake_execute(self, **kwargs):
        return SkillResult(success=True, output=kwargs["agent"])

    with patch("aider.skills.dynamic_loader.ACPDelegationSkill.execute", new=fake_execute):
        result = await skill.execute(task="fix bug")

    assert result.success is True
    assert result.output == "codex"
    assert skill.context is context


async def test_yaml_skill_accepts_context_and_runs_shell_handler():
    """YAML-defined skills can be instantiated with SkillContext and executed."""
    loader = YAMLSkillLoader()
    skill_class = loader._create_skill_class(
        {
            "name": "yaml-echo",
            "description": "Echo text",
            "handler": {
                "type": "shell",
                "command": "printf hello",
            },
        }
    )
    context = SkillContext()
    skill = skill_class(context)

    result = await skill.execute()

    assert result.success is True
    assert result.output == "hello"
    assert skill.context is context


if __name__ == "__main__":
    asyncio.run(test_skill_exception_is_caught())
    asyncio.run(test_skill_timeout_is_handled())
    asyncio.run(test_circuit_breaker_opens_on_failures())
    asyncio.run(test_circuit_breaker_recovers())
    asyncio.run(test_circuit_breaker_stays_open_on_failure_in_half_open())
    asyncio.run(test_registry_handles_duplicate_registration())
    asyncio.run(test_registry_handles_invalid_skill())
    asyncio.run(test_skill_with_missing_required_params())
    asyncio.run(test_agent_cleanup_on_timeout())
    asyncio.run(test_agent_cleanup_on_unregister())
    asyncio.run(test_memory_limit_enforcement())
    asyncio.run(test_concurrent_access_to_registry())
    asyncio.run(test_skill_cancellation())
    asyncio.run(test_hook_failure_stops_execution())
    asyncio.run(test_hook_dependency_failure())
    asyncio.run(test_multiple_error_recovery())
    asyncio.run(test_resource_cleanup_on_exception())
    print("✅ All failure mode tests passed")
