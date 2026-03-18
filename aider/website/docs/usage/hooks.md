---
parent: Usage
title: Hooks
nav_order: 110
---

# Hooks

Hooks allow you to extend aider's functionality by registering custom callbacks at specific lifecycle points.

## Overview

Aider provides two hook systems:

1. **Basic Hooks** - Simple callback-based system
2. **Advanced Hooks** - Type-safe system with configuration

## Basic Hooks

### Available Hook Points

| Hook Point | When Triggered |
|------------|----------------|
| `pre_command` | Before executing a command |
| `post_command` | After executing a command |
| `pre_send` | Before sending messages to LLM |
| `post_send` | After receiving LLM response |
| `pre_edit` | Before applying file edits |
| `post_edit` | After applying file edits |
| `pre_summarize` | Before summarizing chat |
| `post_summarize` | After summarizing chat |
| `on_init` | When aider initializes |
| `on_exit` | When aider exits |

### Using Basic Hooks

Create a hooks file (e.g., `~/.aider/hooks/my_hooks.py`):

```python
def register_hooks(hooks_manager):
    """Register all hooks."""
    hooks_manager.register("pre_command", on_pre_command)
    hooks_manager.register("post_edit", on_post_edit)

def on_pre_command(command, args):
    """Called before any command executes."""
    print(f"About to execute: {command}")
    # Return None to allow, or (False, "message") to block
    return None

def on_post_edit(filepath, content):
    """Called after file edits are applied."""
    print(f"File edited: {filepath}")
```

### Loading Hooks

Aider automatically loads hooks from:
- `~/.aider/hooks/*.py`
- `AIDER_HOOKS_DIR` environment variable

```bash
export AIDER_HOOKS_DIR=/path/to/hooks
aider
```

## Advanced Hooks

Advanced hooks provide type safety, configuration, and execution history.

### Hook Points

```python
from aider.hooks_manager import HookPoint

HookPoint.PRE_COMMAND      # Before command execution
HookPoint.POST_COMMAND     # After command execution
HookPoint.PRE_SEND         # Before LLM request
HookPoint.POST_SEND        # After LLM response
HookPoint.PRE_EDIT         # Before file edit
HookPoint.POST_EDIT        # After file edit
HookPoint.PRE_COMMIT       # Before git commit
HookPoint.POST_COMMIT      # After git commit
```

### Using Advanced Hooks

```python
from aider.hooks_manager import HooksManager, HookPoint, HookConfig

manager = HooksManager()

# Register with configuration
manager.register_hook(
    name="my-validation-hook",
    hook_point=HookPoint.PRE_EDIT,
    callback=validate_edit,
    config=HookConfig(
        priority=100,           # Higher = earlier execution
        async_execution=False,  # Run synchronously
        timeout=30.0,          # Timeout in seconds
        retries=3,             # Retry on failure
    )
)

def validate_edit(filepath, content, **kwargs):
    """Validate edits before they're applied."""
    if "password" in content.lower():
        return False, "Cannot commit passwords"
    return True, None
```

## Example Hooks

### Validate Commit Messages

```python
def on_pre_commit(message, files):
    """Ensure commit messages follow conventions."""
    if not message.startswith(("feat:", "fix:", "docs:")):
        return False, "Commit message must start with feat:/fix:/docs:"
    return True, None
```

### Log All Edits

```python
import json
from datetime import datetime

def on_post_edit(filepath, content, **kwargs):
    """Log all edits to a file."""
    with open("/tmp/aider-edits.log", "a") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "file": filepath,
            "size": len(content),
        }) + "\n")
```

### Notify on Long Operations

```python
import time

start_time = None

def on_pre_send(messages, **kwargs):
    """Track when LLM calls start."""
    global start_time
    start_time = time.time()

def on_post_send(response, **kwargs):
    """Notify if LLM call took a long time."""
    global start_time
    if start_time:
        elapsed = time.time() - start_time
        if elapsed > 60:
            print(f"⚠️  LLM call took {elapsed:.1f}s")
```

## Configuration File

Create `.aider-hooks.yml` in your project root:

```yaml
hooks:
  - name: security-check
    hook_point: PRE_COMMIT
    module: hooks.security
    function: check_secrets
    config:
      priority: 100
      timeout: 10

  - name: format-check
    hook_point: PRE_EDIT
    module: hooks.formatting
    function: validate_format
    config:
      priority: 50
```

## Hook Execution Order

Hooks execute by priority (higher first):

```
Priority 100: Security checks
Priority 90:  Validation
Priority 50:  Logging
Priority 10:  Notifications
```

## Error Handling

Hooks are wrapped in try-except blocks:

```python
def safe_hook(callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except Exception as e:
        print(f"Hook error: {e}")
        # Hooks don't crash aider
```

## Performance Considerations

- Keep hooks fast (< 100ms)
- Use async hooks for I/O operations
- Set appropriate timeouts
- Consider using `async_execution=True` for non-blocking hooks

## See Also

- [Configuration](/docs/config.html) - General configuration
- [Scripting](/docs/scripting.html) - Scripting aider
