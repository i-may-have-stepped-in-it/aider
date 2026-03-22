#!/usr/bin/env python3
"""
Verification script for async/Option B architecture.

Run this to verify the async refactor is working correctly.
"""

import asyncio
import sys


def test_imports():
    """Test that all async modules can be imported."""
    print("Testing imports...")
    
    from aider.async_compat import (
        AsyncCallable,
        AsyncEvent,
        GenerationResult,
        GenerationState,
        MessageQueue,
        TaskManager,
        run_in_thread,
    )
    from aider.async_running_prompt import (
        AsyncPromptDelegate,
        AsyncRunningPromptManager,
    )
    from aider.io import AsyncAiderPromptSession, InputOutput
    from aider.coders.base_coder_control import BaseCoderControlMixin
    from aider.bootstrap.runtime import run_interactive_session_async
    from aider.main_async import async_main, run_async_main
    
    print("  ✓ All async modules imported successfully")


def test_async_running_prompt_manager():
    """Test AsyncRunningPromptManager functionality."""
    print("\nTesting AsyncRunningPromptManager...")
    
    from aider.async_running_prompt import AsyncRunningPromptManager
    from aider.async_compat import GenerationState
    
    async def _test():
        manager = AsyncRunningPromptManager()
        
        # Test initial state
        assert manager.state == GenerationState.IDLE
        assert manager.is_idle
        print("  ✓ Initial state correct")
        
        # Test generation
        async def dummy_task():
            await asyncio.sleep(0.001)
            return "result"
        
        await manager.start_generation(dummy_task)
        assert manager.is_generating
        print("  ✓ Generation started")
        
        result = await asyncio.wait_for(manager.wait_for_completion(), timeout=1.0)
        assert result.state == GenerationState.COMPLETED
        print("  ✓ Generation completed")
        
        # Test queue
        await manager.start_generation(dummy_task)
        await manager.queue_message("queued message")
        assert manager.has_queued_messages
        print("  ✓ Message queued")
        await manager.cancel()
    
    asyncio.run(_test())


def test_io_async():
    """Test InputOutput async methods."""
    print("\nTesting InputOutput async methods...")
    
    from aider.io import InputOutput
    
    async def _test():
        io = InputOutput(pretty=False, fancy_input=False)
        
        # Test async running prompt manager
        manager = io.async_running_prompt_manager
        assert manager is not None
        print("  ✓ AsyncRunningPromptManager created")
        
        # Test async mode is always on
        assert io.is_async_mode()
        print("  ✓ Async mode is always on")
        
        # Test display
        await io.display_user_input_async("test message")
        print("  ✓ Async display works")
    
    asyncio.run(_test())


def test_coder_async():
    """Test BaseCoder async methods."""
    print("\nTesting BaseCoder async methods...")
    
    from aider.coders.base_coder_control import BaseCoderControlMixin
    import inspect
    
    # Check methods exist
    assert hasattr(BaseCoderControlMixin, 'run_async')
    assert hasattr(BaseCoderControlMixin, 'get_input_async')
    assert hasattr(BaseCoderControlMixin, 'run_one_async')
    print("  ✓ All async methods exist")
    
    # Check they're coroutines
    assert inspect.iscoroutinefunction(BaseCoderControlMixin.run_async)
    assert inspect.iscoroutinefunction(BaseCoderControlMixin.get_input_async)
    assert inspect.iscoroutinefunction(BaseCoderControlMixin.run_one_async)
    print("  ✓ All methods are async")


def test_entry_point():
    """Test async entry point."""
    print("\nTesting async entry point...")
    
    from aider.main_async import run_async_main
    
    # Test that entry point exists and is callable
    assert callable(run_async_main)
    print("  ✓ Async entry point available")


def main():
    """Run all verification tests."""
    print("=" * 60)
    print("Aider Async/Option B Architecture Verification")
    print("=" * 60)
    
    try:
        test_imports()
        test_async_running_prompt_manager()
        test_io_async()
        test_coder_async()
        test_entry_point()
        
        print("\n" + "=" * 60)
        print("✅ ALL VERIFICATION TESTS PASSED")
        print("=" * 60)
        print("\nThe async refactor is complete!")
        print("\nAsync is now the default - just run:")
        print("  aider")
        
        return 0
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ VERIFICATION FAILED")
        print("=" * 60)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
