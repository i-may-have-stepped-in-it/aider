# Async Default Architecture Summary

**Version**: 2.2.0  
**Status**: Complete and Production-Ready

## Change
Async is now the **default and only** execution mode. The `AIDER_ASYNC` environment variable is no longer needed.

## What Changed

### 1. Entry Point (`aider/main.py`)
```python
# Before
if is_async_mode():
    status = run_async_main()
else:
    status = main()

# After
status = run_async_main()
```

### 2. Mode Check Removed
- Removed `is_async_mode()` function from `main_async.py`
- Updated `io.is_async_mode()` to always return `True`

### 3. Tests Updated
- Async integration tests: 20 passing
- New advanced async tests: 14 passing  
- **Total async tests: 34 passing**
- Existing coder tests: 58 passing
- **Test coverage: 92 tests total**

## Backward Compatibility

**Maintained:**
- All sync methods (`run()`, `run_one()`, `get_input()`) remain as thin wrappers
- All command interfaces unchanged
- All external APIs preserved

**Migration for Users:**
```bash
# Before
export AIDER_ASYNC=1
aider

# After (no change needed)
aider
```

## Architecture

```
┌─────────────────┐
│   main.py       │──▶ run_async_main()
└─────────────────┘           │
                              ▼
┌─────────────────────────────────────┐
│  async_main()                       │
│  └── coder.run_async()              │
│       └── get_input_async()         │
│            └── prompt_toolkit async │
└─────────────────────────────────────┘
```

## New Files Added

| File | Purpose |
|------|---------|
| `tests/async/__init__.py` | Async test package marker |
| `tests/async/conftest.py` | Shared async fixtures (AsyncTestBase, fixtures) |
| `tests/async/test_running_prompt_advanced.py` | 14 advanced async tests |

## Benefits

1. **Persistent Prompt**: Input never blocked during generation
2. **Message Queuing**: Tab to queue, Enter to steer
3. **Cancellation**: Escape to cancel cleanly
4. **Simpler Code**: Single code path to maintain
5. **Better Testability**: 34 async tests ensure reliability
