# Aider Hooks System

This document describes the hooks system added to Aider, which allows users to extend Aider's functionality by executing custom code at specific points in the lifecycle.

> **Note**: As of v2.1.0, hooks are unified in `aider/hooks_manager.py`. The `aider/hooks.py` module is now a compatibility shim that preserves the legacy API. For advanced hooks with OpenClaw integration, type-safe enums, and configuration options, see `aider/hooks_manager.py` and `AGENTS.md`.

## Overview

The hooks system provides a flexible way to customize Aider's behavior without modifying core code. Hooks can:
- Log and audit commands and edits
- Modify messages before sending to LLM
- Pre-process or post-process edits
- Integrate with external tools
- Implement custom workflows

## CLI Arguments

The following new command-line arguments have been added:

| Argument | Description |
|----------|-------------|
| `--hooks-dir DIR` | Directory containing hook files to load at startup |
| `--enable-skills` | Enable the skills system for reusable functionality |
| `--skill-path PATH` | Path to skills file or directory (requires `--enable-skills`) |

## Available Hook Points

### Command Hooks
- `pre_command` - Called before a command is executed
  - Arguments: `cmd_name`, `args`, `io`
  - Can return: `{"args": new_args}` to modify command arguments
  
- `post_command` - Called after a command is executed
  - Arguments: `cmd_name`, `args`, `result`, `io`

### Message/LLM Hooks
- `pre_send` - Called before sending a message to the LLM
  - Arguments: `message`, `coder`
  - Can return: `{"message": new_message}` to modify the message
  
- `post_send` - Called after receiving a response from the LLM
  - Arguments: `message`, `response`, `coder`

### Edit Hooks
- `pre_edit` - Called before applying edits to files
  - Arguments: `edits`, `coder`
  - Can return: `{"edits": new_edits}` to modify the edits
  
- `post_edit` - Called after applying edits to files
  - Arguments: `edited_files`, `coder`

### Summarization Hooks
- `pre_summarize` - Called before chat history summarization
  - Arguments: `messages`, `coder`
  
- `post_summarize` - Called after chat history summarization
  - Arguments: `original_messages`, `summary`, `coder`

### Lifecycle Hooks
- `on_init` - Called when Aider initializes
  - Arguments: `args`, `io`
  
- `on_exit` - Called when Aider is about to exit
  - Arguments: `coder`

## Creating Hook Files

Hook files are Python files that define a `register_hooks` function. Here's a basic example:

```python
def register_hooks(hooks_manager):
    """Register hooks with the manager."""
    hooks_manager.register("pre_command", my_pre_command_hook)
    hooks_manager.register("post_edit", my_post_edit_hook)

def my_pre_command_hook(cmd_name, args, io, **kwargs):
    """Called before each command."""
    io.tool_output(f"Executing command: {cmd_name}")
    return None

def my_post_edit_hook(edited_files, coder, **kwargs):
    """Called after files are edited."""
    if coder.io and edited_files:
        coder.io.tool_output(f"Edited: {', '.join(edited_files)}")
```

## Usage Examples

### Example 1: Command Logging

Create `~/.aider/hooks/command_logger.py`:

```python
import datetime
from pathlib import Path

def register_hooks(hooks_manager):
    hooks_manager.register("pre_command", log_command)

def log_command(cmd_name, args, io, **kwargs):
    log_dir = Path.home() / ".aider" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    with open(log_dir / "commands.log", "a") as f:
        timestamp = datetime.datetime.now().isoformat()
        f.write(f"{timestamp} - {cmd_name}: {args}\n")
```

Run Aider with:
```bash
aider --hooks-dir ~/.aider/hooks/
```

### Example 2: Auto-format Edits

Create `~/.aider/hooks/auto_format.py`:

```python
def register_hooks(hooks_manager):
    hooks_manager.register("pre_edit", format_edits)

def format_edits(edits, coder, **kwargs):
    formatted = []
    for path, original, updated in edits:
        if path and path.endswith(".py"):
            # Strip trailing whitespace
            updated = "\n".join(line.rstrip() for line in updated.split("\n"))
        formatted.append((path, original, updated))
    return {"edits": formatted}
```

### Example 3: Message Monitoring

Create `~/.aider/hooks/message_monitor.py`:

```python
def register_hooks(hooks_manager):
    hooks_manager.register("pre_send", monitor_send)
    hooks_manager.register("post_send", monitor_receive)

def monitor_send(message, coder, **kwargs):
    if coder.io:
        coder.io.tool_output(f"Sending {len(message)} chars to LLM")
    return None

def monitor_receive(message, response, coder, **kwargs):
    if coder.io and response:
        coder.io.tool_output(f"Received {len(response)} chars from LLM")
```

## API Reference

### HooksManager

The `HooksManager` class manages hook registration and execution.

#### Methods

- `register(hook_name, callback)` - Register a callback for a hook
- `unregister(hook_name, callback)` - Unregister a callback
- `execute(hook_name, *args, **kwargs)` - Execute all callbacks for a hook
- `load_hooks_from_file(file_path)` - Load hooks from a Python file
- `load_hooks_from_directory(dir_path)` - Load all hooks from a directory
- `is_hook_enabled(hook_name)` - Check if a hook has registered callbacks

#### Properties

- `hooks` - Dictionary of all hook names and their callbacks
- `loaded_modules` - List of loaded hook module paths
- `verbose` - Enable verbose logging of hook operations

### Error Handling

Hooks are executed in a try-except block to prevent hook failures from crashing Aider:

- If a hook raises an exception, it's logged (if verbose mode is enabled)
- Other hooks continue to execute
- Aider's normal operation continues

To debug hooks, run Aider with `-v` or `--verbose` flag.

## Best Practices

1. **Keep hooks lightweight** - Hooks should execute quickly to avoid slowing down Aider
2. **Handle errors gracefully** - Use try-except blocks in your hooks
3. **Respect the return contract** - Only return data when the hook supports it
4. **Use verbose mode for debugging** - Enable `--verbose` to see hook execution logs
5. **Organize hooks by functionality** - Create separate files for different purposes

## File Locations

- **Unified hooks**: `aider/hooks_manager.py` (v2.1.0)
- **Configuration**: `aider/hooks_config.py` - `HookConfig`, `HookPoint` enum, priority/timeout/retry settings
- **Legacy compatibility**: `aider/hooks.py` (shim)
- **Bootstrap**: `aider/hooks_bootstrap.py` (v2.1.0)
- **Example hooks**: `aider/hooks_example.py`

### Hook Implementations (`hooks/`)

- **`hooks/__init__.py`** - Package exports
- **`hooks/cli_agent_hook.py`** - CLI agent lifecycle hooks (pre/post spawn callbacks)
- **`hooks/gateway_tier_hook.py`** - Gateway tier management hooks (routing decisions)

### Integration Points

- **CLI arguments**: `aider/args.py`
- **Command integration**: `aider/commands.py` (via runtime)
- **Coder integration**: `aider/coders/base_coder.py` (via runtime)
- **Initialization**: `aider/main.py` (creates runtime)

## Compatibility

The hooks system is designed to be:
- **Non-breaking** - Aider works normally without any hooks
- **Optional** - Hooks are only loaded when explicitly requested
- **Safe** - Hook failures don't crash Aider
- **Flexible** - Multiple hooks can be registered for the same hook point
