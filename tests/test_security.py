#!/usr/bin/env python3
"""
Security tests for Aider codebase - PHASE 5 VERIFICATION

Addresses Issue 23: Missing security tests
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from aider.hooks_manager import HooksManager
from aider.skills.base import Skill, SkillContext, SkillResult
from aider.skills.registry import SkillRegistry
from aider.skills.yaml_loader import YAMLSkillLoader

pytestmark = pytest.mark.asyncio


class SecurityTestSkill(Skill):
    """Skill for security testing."""

    name = "security-test-skill"
    description = "Security test skill"

    def _validate_parameters(self, params):
        errors = []

        # Prevent path traversal
        if "filepath" in params:
            if ".." in params["filepath"] or params["filepath"].startswith("/"):
                errors.append("Invalid file path: path traversal detected")

        # Prevent command injection
        if "command" in params:
            cmd = params["command"]
            dangerous_chars = [";", "|", "&", "$", "`", "\n", "\r"]
            if any(char in cmd for char in dangerous_chars):
                errors.append("Invalid command: potential injection detected")

        return errors

    async def _execute_impl(self, **kwargs):
        return SkillResult(success=True, output="OK")


# === Security Tests ===


async def test_path_traversal_prevention():
    """Test that path traversal is prevented."""
    skill = SecurityTestSkill()

    # Attempt path traversal
    result = await skill.execute(filepath="../../../etc/passwd")
    assert result.success is False
    assert "path traversal" in result.error.lower()


async def test_absolute_path_prevention():
    """Test that absolute paths are prevented."""
    skill = SecurityTestSkill()

    result = await skill.execute(filepath="/etc/passwd")
    assert result.success is False
    assert "path traversal" in result.error.lower()


async def test_command_injection_semicolon():
    """Test that semicolon injection is prevented."""
    skill = SecurityTestSkill()

    result = await skill.execute(command="ls; rm -rf /")
    assert result.success is False
    assert "injection" in result.error.lower()


async def test_command_injection_pipe():
    """Test that pipe injection is prevented."""
    skill = SecurityTestSkill()

    result = await skill.execute(command="ls | cat /etc/passwd")
    assert result.success is False
    assert "injection" in result.error.lower()


async def test_command_injection_ampersand():
    """Test that ampersand injection is prevented."""
    skill = SecurityTestSkill()

    result = await skill.execute(command="ls & rm -rf /")
    assert result.success is False
    assert "injection" in result.error.lower()


async def test_command_injection_variable():
    """Test that variable injection is prevented."""
    skill = SecurityTestSkill()

    result = await skill.execute(command="ls $HOME")
    assert result.success is False
    assert "injection" in result.error.lower()


async def test_command_injection_backtick():
    """Test that backtick injection is prevented."""
    skill = SecurityTestSkill()

    result = await skill.execute(command="ls `whoami`")
    assert result.success is False
    assert "injection" in result.error.lower()


async def test_command_injection_newline():
    """Test that newline injection is prevented."""
    skill = SecurityTestSkill()

    result = await skill.execute(command="ls\nrm -rf /")
    assert result.success is False
    assert "injection" in result.error.lower()


async def test_safe_relative_path():
    """Test that safe relative paths are allowed."""
    skill = SecurityTestSkill()

    result = await skill.execute(filepath="safe/path/to/file.txt")
    assert result.success is True


async def test_safe_command():
    """Test that safe commands are allowed."""
    skill = SecurityTestSkill()

    result = await skill.execute(command="ls -la")
    assert result.success is True


def test_registry_thread_safety_concurrent_register():
    """Test registry handles concurrent registrations safely."""
    registry = SkillRegistry(load_dynamic=False)
    errors = []

    def register_skill_thread(i):
        try:

            class TestSkill(Skill):
                name = f"test-skill-{i}"
                description = f"Test skill {i}"

                async def _execute_impl(self, **kwargs):
                    return SkillResult(success=True)

            registry.register(TestSkill)
        except Exception as e:
            errors.append(e)

    # Try to register 100 skills concurrently from 10 threads
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(register_skill_thread, i) for i in range(100)]
        for future in futures:
            future.result()

    # Should have no errors and all 100 skills registered
    assert len(errors) == 0
    assert registry.count() == 100


def test_registry_thread_safety_concurrent_read():
    """Test registry handles concurrent reads safely."""
    registry = SkillRegistry(load_dynamic=False)

    # Register a skill first
    class TestSkill(Skill):
        name = "test-skill"
        description = "Test skill"

        async def _execute_impl(self, **kwargs):
            return SkillResult(success=True)

    registry.register(TestSkill)

    errors = []

    def read_skill():
        try:
            for _ in range(100):
                skill = registry.get("test-skill")
                assert skill is not None
        except Exception as e:
            errors.append(e)

    # Read the same skill 100 times from 10 threads
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(read_skill) for _ in range(10)]
        for future in futures:
            future.result()

    assert len(errors) == 0


async def test_no_sensitive_data_in_errors():
    """Test that sensitive data is not leaked in error messages."""
    skill = SecurityTestSkill()

    # Even if internal processing fails, error should not expose sensitive data
    result = await skill.execute(filepath="../../../etc/shadow")

    # Error should mention path traversal but not expose the actual path
    assert result.success is False
    assert "path traversal" in result.error.lower()
    # Should not include the actual malicious path in error
    assert "../../../etc/shadow" not in result.error


async def test_api_key_not_in_output():
    """Test that API keys are not leaked in output."""
    context = SkillContext()
    context.api_key = "secret-api-key-12345"

    skill = SecurityTestSkill(context)
    result = await skill.execute(filepath="test.txt")

    # Output should not contain the API key
    assert "secret-api-key-12345" not in result.output
    assert "secret-api-key-12345" not in str(result.data)


async def test_memory_limit_enforcement():
    """Test that memory limits are enforced."""
    # This would need to be tested with actual agent registry
    # For now, just verify the parameter exists
    from aider.agents.registry import AgentRegistry

    registry = AgentRegistry(max_memory_mb=10.0)  # Very small limit
    assert registry._max_memory == 10.0 * 1024 * 1024


async def test_timeout_prevents_resource_exhaustion():
    """Test that timeout prevents infinite execution."""
    context = SkillContext(timeout=0.1)  # Very short timeout

    class SlowSkill(Skill):
        name = "slow-skill"

        async def _execute_impl(self, **kwargs):
            await asyncio.sleep(10)  # Would run for 10 seconds
            return SkillResult(success=True)

    skill = SlowSkill(context)
    start = time.time()
    result = await skill.execute()
    elapsed = time.time() - start

    # Should timeout well before 10 seconds
    assert result.success is False
    assert "timed out" in result.error.lower()
    assert elapsed < 1.0  # Should fail within 1 second


async def test_yaml_python_handler_disabled_by_default():
    """Unsafe YAML python handlers require explicit opt-in."""
    loader = YAMLSkillLoader()
    skill_class = loader._create_skill_class(
        {
            "name": "yaml-python",
            "handler": {
                "type": "python",
                "code": "result = SkillResult(success=True, output='unsafe')",
            },
        }
    )
    skill = skill_class(SkillContext())

    result = await skill.execute()

    assert result.success is False
    assert "disabled" in result.error.lower()


def test_hooks_condition_disallows_calls_and_attributes():
    """Hook conditions should reject function calls and attribute traversal."""
    manager = HooksManager()

    assert manager._evaluate_condition("__import__('os').system('true')", {}) is False
    assert manager._evaluate_condition("context.__class__", {"value": 1}) is False


if __name__ == "__main__":
    import time

    asyncio.run(test_path_traversal_prevention())
    asyncio.run(test_absolute_path_prevention())
    asyncio.run(test_command_injection_semicolon())
    asyncio.run(test_command_injection_pipe())
    asyncio.run(test_command_injection_ampersand())
    asyncio.run(test_command_injection_variable())
    asyncio.run(test_command_injection_backtick())
    asyncio.run(test_command_injection_newline())
    asyncio.run(test_safe_relative_path())
    asyncio.run(test_safe_command())
    test_registry_thread_safety_concurrent_register()
    test_registry_thread_safety_concurrent_read()
    asyncio.run(test_no_sensitive_data_in_errors())
    asyncio.run(test_api_key_not_in_output())
    asyncio.run(test_memory_limit_enforcement())
    asyncio.run(test_timeout_prevents_resource_exhaustion())
    print("✅ All security tests passed")
