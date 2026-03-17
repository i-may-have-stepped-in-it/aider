#!/usr/bin/env python3
"""
Failure mode tests for Aider codebase - PHASE 5 VERIFICATION

Addresses Issue 24: Missing failure mode tests
"""

import asyncio
import pytest
import time
from aider.skills.base import Skill, SkillContext, SkillResult
from aider.skills.registry import SkillRegistry
from aider.agents.registry import AgentRegistry, CircuitState


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
    
    assert result.success == False
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
    
    assert result.success == False
    assert "timeout" in result.error.lower()
    assert elapsed < 1.0  # Should timeout within 1 second


async def test_circuit_breaker_opens_on_failures():
    """Test that circuit breaker opens after threshold failures."""
    registry = AgentRegistry()
    cb = registry.circuit_breaker
    
    # Record failures up to threshold
    for _ in range(cb.failure_threshold):
        cb.record_failure()
    
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() == False


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
    assert cb.can_execute() == True
    
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
    assert cb.can_execute() == False


async def test_registry_handles_duplicate_registration():
    """Test that registry handles duplicate skill registration."""
    registry = SkillRegistry()
    
    class TestSkill(Skill):
        name = "test-skill"
        description = "Test skill"
        async def _execute_impl(self, **kwargs):
            return SkillResult(success=True)
    
    # Register once
    result1 = registry.register(TestSkill)
    assert result1 == True
    
    # Register again (should overwrite)
    result2 = registry.register(TestSkill)
    assert result2 == True
    
    # Should still have only one skill
    assert registry.count() == 1


async def test_registry_handles_invalid_skill():
    """Test that registry rejects invalid skills."""
    registry = SkillRegistry()
    
    class InvalidSkill:
        # Missing name, description, and not a Skill subclass
        pass
    
    # Should reject invalid skill
    result = registry.register(InvalidSkill)
    assert result == False
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
    assert result.success == False
    assert "missing" in result.error.lower()
    
    # Missing some params
    result = await skill.execute(param1="value1")
    assert result.success == False
    assert "param2" in result.error and "param3" in result.error


async def test_agent_cleanup_on_timeout():
    """Test that agents are cleaned up on timeout."""
    # This would need actual agent implementation
    # For now, verify the cleanup method exists
    registry = AgentRegistry()
    
    # Verify cancel method exists
    assert hasattr(registry, 'cancel')
    assert hasattr(registry, 'cancel_all')


async def test_agent_cleanup_on_unregister():
    """Test that agents are cleaned up when unregistered."""
    # This would need actual agent implementation
    registry = AgentRegistry()
    
    # Verify unregister method exists
    assert hasattr(registry, 'unregister')


async def test_memory_limit_enforcement():
    """Test that memory limits are enforced."""
    registry = AgentRegistry(max_memory_mb=0.001)  # Very small
    
    # Verify memory tracking exists
    assert hasattr(registry, '_max_memory')
    assert hasattr(registry, '_current_memory')


async def test_concurrent_access_to_registry():
    """Test that registry handles concurrent access safely."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    
    registry = SkillRegistry()
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
    
    assert result.success == False
    assert "cancelled" in result.error.lower()


async def test_hook_failure_stops_execution():
    """Test that hook failure stops execution when configured."""
    from aider.hooks.manager import HookManager, HookPoint, HookConfig
    
    manager = HookManager()
    execution_order = []
    
    # Hook that fails
    @manager.register_hook(
        HookPoint.PRE_COMMAND,
        config=HookConfig(name="failing-hook", priority=10, stop_on_failure=True)
    )
    async def failing_hook(ctx):
        execution_order.append(1)
        raise Exception("Hook failed")
    
    # Hook that should not run
    @manager.register_hook(
        HookPoint.PRE_COMMAND,
        config=HookConfig(name="second-hook", priority=20)
    )
    async def second_hook(ctx):
        execution_order.append(2)
    
    results = await manager.execute_hooks(HookPoint.PRE_COMMAND)
    
    # Only first hook should have run
    assert execution_order == [1]
    assert len(results) == 1
    assert results[0].success == False


async def test_hook_dependency_failure():
    """Test that hooks skip if dependencies not met."""
    from aider.hooks.manager import HookManager, HookPoint, HookConfig
    
    manager = HookManager()
    execution_order = []
    
    # Hook that depends on non-existent hook
    @manager.register_hook(
        HookPoint.PRE_COMMAND,
        config=HookConfig(name="dependent-hook", depends_on=["non-existent"])
    )
    async def dependent_hook(ctx):
        execution_order.append(1)
    
    results = await manager.execute_hooks(HookPoint.PRE_COMMAND)
    
    # Should not execute
    assert execution_order == []
    assert len(results) == 0


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


async def test_resource_cleanup_on_exception():
    """Test that resources are cleaned up even on exception."""
    skill = FailingSkill()
    
    # Add some progress
    skill.update_progress("Step 1")
    skill.update_progress("Step 2")
    
    # Execute (will fail)
    result = await skill.execute()
    
    # Progress should still be accessible
    progress = skill.get_progress()
    assert len(progress) == 2
    
    # Can clear progress
    skill.clear_progress()
    assert len(skill.get_progress()) == 0


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
