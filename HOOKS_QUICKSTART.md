# OpenClaw Hooks Quickstart Guide

## Installation

The hooks system is built into Aider. No additional installation is required.

## Enabling Hooks

### 1. Create a Hooks Directory

```bash
mkdir -p ~/.aider/hooks
```

### 2. Start Aider with Hooks Enabled

```bash
# Enable hooks from a directory
aider --hooks-dir ~/.aider/hooks

# Enable OpenClaw skills
aider --enable-skills --skill-path ~/.openclaw/skills

# Both
aider --hooks-dir ~/.aider/hooks --enable-skills
```

### 3. Or Use Configuration File

Create `.aider-hooks.yml` in your project or home directory:

```yaml
enabled: true
verbose: false

hooks:
  post_edit:
    - name: my-formatter
      type: python
      module: ~/.aider/hooks/formatter.py
      function: format_files
      priority: 100
```

## Your First Hook

Create `~/.aider/hooks/my_first_hook.py`:

```python
"""My first Aider hook."""

from datetime import datetime
from pathlib import Path


def register_hooks(hooks_manager):
    """Register hooks with Aider."""
    hooks_manager.register("post_edit", log_edit)
    hooks_manager.register("pre_command", log_command)


def log_edit(edited_files, coder, **kwargs):
    """Log edited files."""
    if not edited_files:
        return
    
    coder.io.tool_output(f"[my_hook] Edited {len(edited_files)} files:")
    for f in edited_files:
        coder.io.tool_output(f"  - {f}")
    
    # Save to log file
    log_dir = Path.home() / ".aider" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    with open(log_dir / "edits.log", "a") as fh:
        fh.write(f"{datetime.now().isoformat()}: {list(edited_files)}\n")


def log_command(cmd_name, args, io, **kwargs):
    """Log commands."""
    io.tool_output(f"[my_hook] Executing /{cmd_name} {args}")
```

Run Aider with your hook:

```bash
aider --hooks-dir ~/.aider/hooks
```

## Available Hook Points

| Hook Point | When Fired | Context Variables |
|------------|------------|-------------------|
| `pre_command` | Before Aider command | `cmd_name`, `args`, `io` |
| `post_command` | After Aider command | `cmd_name`, `args`, `result`, `io` |
| `pre_send` | Before LLM API call | `message`, `coder` |
| `post_send` | After LLM response | `message`, `response`, `coder` |
| `pre_edit` | Before file edits | `edits`, `coder` |
| `post_edit` | After file edits | `edited_files`, `coder` |
| `pre_commit` | Before git commit | `files`, `message`, `coder` |
| `post_commit` | After git commit | `files`, `message`, `hash`, `coder` |
| `on_init` | When Aider starts | `args`, `io` |
| `on_exit` | When Aider exits | `coder` |

## Using OpenClaw Skills

### List Available Skills

```bash
/skill list
/skill list --verbose
```

### Run a Skill

```bash
/skill run github pr-list
/skill run kimi
/skill run comfyui status
```

### Get Skill Info

```bash
/skill info kimi
```

### Register Skill as Hook

Add to `.aider-hooks.yml`:

```yaml
hooks:
  pre_commit:
    - name: run-tests
      type: skill
      skill: test-runner
      action: quick-test
      timeout: 120
```

## Common Hook Patterns

### Auto-formatter

```python
def register_hooks(hooks_manager):
    hooks_manager.register("post_edit", auto_format)

def auto_format(edited_files, coder, **kwargs):
    import subprocess
    import shutil
    
    for filepath in edited_files:
        if filepath.endswith(".py"):
            # Try ruff first, then black
            for tool in ["ruff", "black"]:
                if shutil.which(tool):
                    subprocess.run([tool, "format", filepath], capture_output=True)
                    break
```

### Conditional Hook

```python
def register_hooks(hooks_manager):
    hooks_manager.register("post_edit", python_linter)

def python_linter(edited_files, coder, **kwargs):
    """Only run on Python files."""
    python_files = [f for f in edited_files if f.endswith(".py")]
    
    if not python_files:
        return
    
    # Run linter...
```

### Modify Behavior

```python
def register_hooks(hooks_manager):
    hooks_manager.register("pre_edit", add_copyright)

def add_copyright(edits, coder, **kwargs):
    """Add copyright header to new files."""
    modified_edits = []
    
    for edit in edits:
        path, original, updated = edit
        
        # If file is new (original is empty), add copyright
        if not original and path.endswith(".py"):
            copyright = "# Copyright 2026\n\n"
            updated = copyright + updated
        
        modified_edits.append((path, original, updated))
    
    # Return modified edits
    return {"edits": modified_edits}
```

## Configuration Options

### Hook Configuration

```yaml
hooks:
  post_edit:
    - name: my-hook
      type: python
      module: ./hooks/my_hook.py
      function: my_function
      priority: 100           # Lower = earlier execution
      enabled: true
      timeout: 30             # Seconds
      retry_count: 3          # Retries on failure
      retry_delay: 1.0        # Seconds between retries
      condition: "len(edited_files) > 0"  # Conditional execution
```

### Condition Expressions

```yaml
# Only run for Python files
condition: "any(f.endswith('.py') for f in edited_files)"

# Only run for specific commands
condition: "cmd_name == 'commit'"

# Only run if files were edited
condition: "len(edited_files) > 0"

# Complex condition
condition: "any(f.endswith('.py') for f in edited_files) and len(edited_files) < 10"
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AIDER_HOOKS_ENABLED` | Enable/disable all hooks |
| `AIDER_HOOKS_VERBOSE` | Enable verbose logging |
| `AIDER_HOOKS_CONFIG` | Path to config file |
| `OPENCLAW_SKILLS_PATH` | Additional skill search paths |

## Debugging Hooks

### Enable Verbose Mode

```bash
aider --hooks-dir ~/.aider/hooks --hooks-verbose
```

### Add Logging

```python
def my_hook(coder, **kwargs):
    coder.io.tool_output(f"[debug] Hook called with: {kwargs}")
    # ... hook logic
```

### Check Hook Execution

```python
def register_hooks(hooks_manager):
    print(f"[debug] Registering hooks with: {hooks_manager}")
    hooks_manager.register("post_edit", my_hook)
```

## Best Practices

1. **Keep hooks fast** - Use timeouts, avoid blocking operations
2. **Handle errors gracefully** - Don't crash Aider if your hook fails
3. **Use conditions** - Only run when needed
4. **Log actions** - Help users understand what's happening
5. **Test thoroughly** - Hooks run automatically, test before enabling

## Examples Repository

See `aider/hooks_example.py` for complete examples including:
- Command logging
- Auto-formatting
- Metrics collection
- Custom skills

## Troubleshooting

### Hook Not Running

1. Check hook is registered: Add print in `register_hooks`
2. Check hook is enabled: Verify in config file
3. Check condition: Ensure condition evaluates to True
4. Check verbose output: Run with `--hooks-verbose`

### Skill Not Found

1. Check skill path: `/skill list` should show it
2. Check SKILL.md exists in skill directory
3. Check scripts are executable: `chmod +x scripts/*`
4. Check requirements: `/skill info <skill>`

### Hook Crashes

1. Add try/except around hook logic
2. Log errors to file
3. Use `coder.io.tool_error()` to show errors
4. Set `retry_count` in config for transient failures

## Getting Help

- Documentation: `aider/openclaw_conventions.md`
- Design Doc: `aider/OPENCLAW_HOOKS_DESIGN.md`
- Examples: `aider/hooks_example.py`
- Config Example: `aider/.aider-hooks.yml.example`
