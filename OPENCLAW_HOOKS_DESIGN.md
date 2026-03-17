# OpenClaw Hooks/Plugin System Design for Aider

## Executive Summary

This document provides a comprehensive design for integrating OpenClaw skills as a hooks/plugin system within Aider. The system enables:

1. **Hook-based extensibility** at key lifecycle points
2. **OpenClaw skill integration** as first-class plugins
3. **Configuration-driven** hook registration
4. **Bidirectional communication** between Aider and skills

## Current Implementation Status

The following components are already implemented in the Aider codebase:

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| OpenClaw Bridge | `aider/openclaw_bridge.py` | 732 | ✅ Implemented |
| Skill Command | `aider/skill_command.py` | 521 | ✅ Implemented |
| Hooks Manager (v2) | `aider/hooks_manager.py` | 546 | ✅ Implemented |
| Hooks System (v1) | `aider/hooks.py` | 337 | ✅ Implemented |
| Hooks Example | `aider/hooks_example.py` | 247 | ✅ Implemented |
| Integration | `aider/main.py`, `aider/coders/base_coder.py` | Partial | ✅ Implemented |

**Total**: ~2,383 lines of implementation code

---

## 1. Hook Architecture

### 1.1 Hook Points

The system defines hooks at the following lifecycle points:

```python
class HookPoint(Enum):
    # Pre-operation hooks
    PRE_COMMIT = auto()           # Before committing changes
    PRE_EDIT = auto()             # Before editing files
    PRE_COMMAND = auto()          # Before executing a command
    PRE_MESSAGE = auto()          # Before sending message to LLM
    PRE_SEND = auto()             # Before LLM API call
    PRE_SUMMARIZE = auto()        # Before context compaction
    
    # Post-operation hooks
    POST_COMMIT = auto()          # After committing changes
    POST_EDIT = auto()            # After editing files
    POST_COMMAND = auto()         # After executing a command
    POST_MESSAGE = auto()         # After receiving LLM response
    POST_SEND = auto()            # After LLM API call
    POST_SUMMARIZE = auto()       # After context compaction
    
    # Lifecycle hooks
    SESSION_START = auto()        # When Aider session starts
    SESSION_END = auto()          # When Aider session ends
    FILE_ADDED = auto()           # When a file is added to context
    MODEL_SWITCH = auto()         # When model is switched
    ON_INIT = auto()              # When Aider initializes
    ON_EXIT = auto()              # When Aider exits
    
    # Error hooks
    ON_ERROR = auto()             # When an error occurs
    ON_VALIDATION_FAIL = auto()   # When validation fails
```

### 1.2 Hook Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        Aider Session                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SESSION_START ─────┐                                           │
│                     ▼                                           │
│  ┌─────────────────────────────────────┐                       │
│  │         User Input Loop             │                       │
│  └─────────────────────────────────────┘                       │
│                     │                                           │
│                     ▼                                           │
│  PRE_COMMAND ──────►│──► Command Execution ──► POST_COMMAND    │
│                     │                                           │
│                     ▼                                           │
│  PRE_MESSAGE ──────►│──► Message Processing                     │
│                     │         │                                 │
│                     │         ▼                                 │
│  PRE_SEND ─────────►│──► LLM API Call ──► POST_SEND            │
│                     │         │                                 │
│                     │         ▼                                 │
│                     │    Response Received                      │
│                     │         │                                 │
│                     ▼         ▼                                 │
│  PRE_EDIT ─────────►│──► Apply Edits ──► POST_EDIT              │
│                     │         │                                 │
│                     │         ▼                                 │
│  PRE_COMMIT ───────►│──► Git Commit ──► POST_COMMIT             │
│                     │                                           │
│                     ▼                                           │
│  PRE_SUMMARIZE ────►│──► Context Compaction ──► POST_SUMMARIZE  │
│                     │                                           │
│                     └──────────────────────────────────────────►│
│                                                                 │
│  SESSION_END ◄──────────────────────────────────────────────────┘
│
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 Hook Configuration

Each hook can be configured with:

```python
@dataclass
class HookConfig:
    enabled: bool = True              # Whether hook is active
    priority: int = 100               # Execution order (lower = first)
    async_execution: bool = False     # Run asynchronously
    timeout: int = 30                 # Max execution time (seconds)
    condition: Optional[str] = None   # Conditional execution expression
    retry_count: int = 0              # Retry attempts on failure
    retry_delay: float = 1.0          # Delay between retries
```

---

## 2. OpenClaw Skills Integration

### 2.1 Skill Structure

OpenClaw skills follow a standardized structure:

```
skill-name/
├── SKILL.md              # Skill metadata and documentation (required)
├── scripts/              # Executable scripts (optional)
│   ├── run.py           # Default action
│   ├── action1.sh       # Named action
│   └── action2.py       # Another action
├── references/           # Documentation (optional)
│   └── api.md
└── assets/              # Static assets (optional)
    └── template.txt
```

### 2.2 SKILL.md Format

```yaml
---
name: skill-name
description: What this skill does and when to use it
homepage: https://github.com/org/repo
metadata:
  openclaw:
    emoji: 🛠️
    requires:
      bins: [binary1, binary2]
    install:
      - id: method1
        kind: brew
        package: package-name
        bins: [binary1]
        label: Install via Homebrew
    hooks:                      # Hook registration
      - name: pre-commit-check
        hook_point: PRE_COMMIT
        action: check
        config:
          priority: 50
          enabled: true
---

# Skill Documentation

## When to use
...

## Quick start
...
```

### 2.3 Skill Discovery

Skills are discovered from multiple sources:

1. **Environment variable**: `OPENCLAW_SKILLS_PATH`
2. **Default paths**:
   - `/home/openclaw/openclaw/skills`
   - `~/.openclaw/skills`
3. **Custom paths**: Configurable via `.aider.conf.yml`

### 2.4 Skill Execution

Skills are executed via the `/skill` command:

```bash
/skill list                    # List available skills
/skill list --verbose         # Detailed listing
/skill run <skill> [action]   # Run a skill
/skill info <skill>           # Show skill info
/skill validate [skill]       # Validate skill
/skill search <query>         # Search skills
/skill scripts <skill>        # List scripts
```

---

## 3. Configuration System

### 3.1 Configuration Files

The system supports multiple configuration methods:

1. **`.aider.conf.yml`** - Primary configuration file
2. **`.aider-hooks.yml`** - Dedicated hooks configuration
3. **Environment variables** - `AIDER_HOOKS_*`
4. **Command-line arguments** - `--hooks-dir`, `--enable-skills`

### 3.2 Configuration Schema

```yaml
# .aider.conf.yml
openclaw:
  enabled: true
  skills_path:
    - /home/openclaw/openclaw/skills
    - ~/.openclaw/skills
  
  hooks:
    # Global hook settings
    verbose: false
    timeout: 30
    
    # Registered hooks
    registry:
      - name: my-pre-commit-hook
        hook_point: PRE_COMMIT
        type: skill
        skill: skill-validator
        action: check
        config:
          priority: 100
          enabled: true
          condition: "context.get('files', [])"
      
      - name: custom-python-hook
        hook_point: POST_EDIT
        type: python
        module: ~/.aider/hooks/my_hooks.py
        function: on_post_edit
        config:
          priority: 50

# .aider-hooks.yml (alternative format)
hooks:
  pre_command:
    - name: log-commands
      type: python
      module: ./hooks/logging.py
      priority: 1
  
  post_edit:
    - name: auto-format
      type: skill
      skill: formatter
      action: format
      priority: 100
  
  pre_commit:
    - name: run-tests
      type: skill
      skill: test-runner
      action: quick-test
      condition: "*.py in files"
```

### 3.3 Hook Registration Format

```python
# Python-based hook registration
def register_hooks(hooks_manager):
    """Register hooks with Aider."""
    
    # Register a simple callback
    hooks_manager.register("pre_command", on_pre_command)
    
    # Register with configuration
    hooks_manager.register(
        "post_edit",
        on_post_edit,
        config=HookConfig(priority=50, timeout=10)
    )
    
    # Register a skill-based hook
    hooks_manager.register_skill_hooks("my-skill")
```

---

## 4. Implementation Plan

### 4.1 Core Components

```
aider/
├── openclaw_bridge.py      # Skill discovery and execution
├── skill_command.py        # /skill command implementation
├── hooks_manager.py        # Hook registration and execution
├── hooks.py                # Legacy hooks (to be consolidated)
├── hooks_example.py        # Example hooks
└── openclaw_conventions.md # Usage documentation
```

### 4.2 Integration Points

#### 4.2.1 Command Execution (`aider/commands.py`)

```python
def do_run(self, cmd_name, args):
    """Execute a command with hook support."""
    # Pre-command hook
    hooks = get_hooks_manager()
    if hooks:
        pre_result = hooks.execute("pre_command", cmd_name, args, self.io)
        if pre_result.get("cancel"):
            return
        args = pre_result.get("args", args)
    
    # Execute command
    result = cmd_method(args)
    
    # Post-command hook
    if hooks:
        hooks.execute("post_command", cmd_name, args, result, self.io)
    
    return result
```

#### 4.2.2 Message Sending (`aider/coders/base_coder.py`)

```python
def send_message(self, inp):
    """Send message with hook integration."""
    # Pre-send hook
    hooks = get_hooks_manager()
    if hooks:
        pre_result = hooks.execute("pre_send", message=inp, coder=self)
        if pre_result.get("data", {}).get("message"):
            inp = pre_result["data"]["message"]
    
    # Send to LLM
    response = yield from self.send(messages, functions=self.functions)
    
    # Post-send hook
    if hooks:
        hooks.execute("post_send", message=inp, response=response, coder=self)
```

#### 4.2.3 Edit Application (`aider/coders/base_coder.py`)

```python
def apply_updates(self):
    """Apply edits with hook support."""
    edits = self.get_edits()
    
    # Pre-edit hook
    hooks = get_hooks_manager()
    if hooks:
        pre_result = hooks.execute("pre_edit", edits=edits, coder=self)
        if pre_result.get("data", {}).get("edits"):
            edits = pre_result["data"]["edits"]
    
    # Apply edits
    self.apply_edits(edits)
    edited_files = set(edit[0] for edit in edits)
    
    # Post-edit hook
    if hooks:
        hooks.execute("post_edit", edited_files=edited_files, coder=self)
    
    return edited_files
```

#### 4.2.4 Context Compaction (`aider/history.py`)

```python
def summarize(self, messages):
    """Summarize with hook support."""
    # Pre-summarize hook
    hooks = get_hooks_manager()
    if hooks:
        pre_result = hooks.execute("pre_summarize", messages=messages)
        if pre_result.get("data", {}).get("skip"):
            return messages
    
    # Perform summarization
    summary = self.summarize_real(messages)
    
    # Post-summarize hook
    if hooks:
        hooks.execute("post_summarize", original=messages, summary=summary)
    
    return summary
```

### 4.3 New Files to Create

| File | Purpose | Lines (est.) |
|------|---------|--------------|
| `aider/hooks_config.py` | Configuration parsing and validation | 200 |
| `aider/hooks_cli.py` | CLI arguments for hooks | 150 |
| `tests/test_hooks.py` | Unit tests for hooks | 300 |
| `tests/test_openclaw_bridge.py` | Tests for OpenClaw integration | 250 |
| `.aider-hooks.yml.example` | Example configuration | 50 |

### 4.4 Files to Modify

| File | Changes |
|------|---------|
| `aider/main.py` | Add args parsing, initialize hooks manager |
| `aider/args.py` | Add `--hooks-dir`, `--enable-skills`, `--skill-path` |
| `aider/commands.py` | Add `/skill` command, hook execution |
| `aider/coders/base_coder.py` | Add hooks at key points |
| `aider/history.py` | Add pre/post summarize hooks |
| `aider/io.py` | Add hook context to IO |

---

## 5. Sample Hook Implementations

### 5.1 Logging Hook

```python
# ~/.aider/hooks/logging.py
import json
from datetime import datetime
from pathlib import Path

def register_hooks(hooks_manager):
    hooks_manager.register("pre_command", log_command)
    hooks_manager.register("post_edit", log_edit)

def log_command(cmd_name, args, io, **kwargs):
    log_dir = Path.home() / ".aider" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "hook": "pre_command",
        "command": cmd_name,
        "args": str(args),
    }
    
    with open(log_dir / "commands.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")

def log_edit(edited_files, coder, **kwargs):
    if not edited_files:
        return
    
    log_dir = Path.home() / ".aider" / "logs"
    entry = {
        "timestamp": datetime.now().isoformat(),
        "hook": "post_edit",
        "files": list(edited_files),
    }
    
    with open(log_dir / "edits.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
```

### 5.2 Auto-formatter Hook

```python
# ~/.aider/hooks/formatter.py
import subprocess
from pathlib import Path

def register_hooks(hooks_manager):
    hooks_manager.register("post_edit", auto_format)

def auto_format(edited_files, coder, **kwargs):
    """Auto-format edited files using appropriate tool."""
    for filepath in edited_files:
        path = Path(filepath)
        
        if path.suffix == ".py":
            # Format Python with black or ruff
            for tool in ["ruff", "black"]:
                if subprocess.run(["which", tool], capture_output=True).returncode == 0:
                    subprocess.run([tool, "format", str(path)], capture_output=True)
                    break
        
        elif path.suffix in (".js", ".ts", ".jsx", ".tsx"):
            # Format JavaScript/TypeScript
            for tool in ["prettier", "eslint"]:
                if subprocess.run(["which", tool], capture_output=True).returncode == 0:
                    subprocess.run([tool, "--write", str(path)], capture_output=True)
                    break
        
        elif path.suffix in (".md", ".markdown"):
            # Format Markdown
            if subprocess.run(["which", "prettier"], capture_output=True).returncode == 0:
                subprocess.run(["prettier", "--write", str(path)], capture_output=True)
```

### 5.3 Skill-Based Pre-commit Hook

```python
# ~/.aider/hooks/skill_hooks.py
from aider.openclaw_bridge import OpenClawBridge

def register_hooks(hooks_manager):
    """Register hooks that execute OpenClaw skills."""
    bridge = OpenClawBridge()
    
    # Pre-commit validation using skill-validator skill
    def pre_commit_validator(files, coder, **kwargs):
        result = bridge.execute_skill(
            "skill-validator",
            action="check",
            args=["--files"] + list(files)
        )
        
        if not result.success:
            coder.io.tool_warning(f"Validation failed: {result.stderr}")
            return {"cancel": True}
        
        return None
    
    hooks_manager.register("pre_commit", pre_commit_validator)
```

### 5.4 Conditional Hook

```python
# ~/.aider/hooks/conditional.py
import fnmatch

def register_hooks(hooks_manager):
    # Only run on Python files
    hooks_manager.register("post_edit", python_linter)

def python_linter(edited_files, coder, **kwargs):
    """Run pylint on edited Python files only."""
    python_files = [f for f in edited_files if fnmatch.fnmatch(f, "*.py")]
    
    if not python_files:
        return
    
    # Run pylint on Python files
    import subprocess
    result = subprocess.run(
        ["pylint", "--errors-only"] + python_files,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        coder.io.tool_warning("Pylint issues found:")
        coder.io.tool_output(result.stdout)
```

### 5.5 Metrics Collection Hook

```python
# ~/.aider/hooks/metrics.py
import json
import time
from collections import defaultdict
from pathlib import Path

class MetricsCollector:
    def __init__(self):
        self.metrics = defaultdict(lambda: defaultdict(int))
        self.start_times = {}
    
    def on_pre_send(self, message, coder, **kwargs):
        self.start_times["send"] = time.time()
        self.metrics["messages"]["count"] += 1
        self.metrics["messages"]["total_chars"] += len(message)
    
    def on_post_send(self, message, response, coder, **kwargs):
        if "send" in self.start_times:
            duration = time.time() - self.start_times["send"]
            self.metrics["timing"]["total_send_time"] += duration
            del self.start_times["send"]
        
        if response:
            self.metrics["responses"]["total_chars"] += len(response)
    
    def on_post_edit(self, edited_files, coder, **kwargs):
        self.metrics["edits"]["count"] += 1
        self.metrics["edits"]["total_files"] += len(edited_files)
    
    def on_exit(self, coder, **kwargs):
        # Save metrics on exit
        log_dir = Path.home() / ".aider" / "metrics"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = int(time.time())
        with open(log_dir / f"metrics_{timestamp}.json", "w") as f:
            json.dump(dict(self.metrics), f, indent=2)

def register_hooks(hooks_manager):
    collector = MetricsCollector()
    
    hooks_manager.register("pre_send", collector.on_pre_send)
    hooks_manager.register("post_send", collector.on_post_send)
    hooks_manager.register("post_edit", collector.on_post_edit)
    hooks_manager.register("on_exit", collector.on_exit)
```

---

## 6. CLI Integration

### 6.1 New Command-Line Arguments

```python
# Add to aider/args.py

def get_parser(...):
    # ... existing arguments ...
    
    group = parser.add_argument_group("Hooks and Skills")
    
    group.add_argument(
        "--hooks-dir",
        metavar="HOOKS_DIR",
        default=None,
        help="Directory containing hook Python files",
    )
    
    group.add_argument(
        "--enable-skills",
        action="store_true",
        help="Enable OpenClaw skills integration",
    )
    
    group.add_argument(
        "--skill-path",
        metavar="SKILL_PATH",
        default=None,
        help="Path to OpenClaw skills directory",
    )
    
    group.add_argument(
        "--hooks-verbose",
        action="store_true",
        help="Enable verbose hook logging",
    )
    
    group.add_argument(
        "--hooks-config",
        metavar="HOOKS_CONFIG",
        default=".aider-hooks.yml",
        help="Path to hooks configuration file",
    )
```

### 6.2 New Commands

```python
# Add to aider/commands.py

def cmd_skill(self, args):
    """Execute OpenClaw skill commands."""
    from aider.skill_command import SkillCommand
    skill_cmd = SkillCommand(self.io, self.coder)
    skill_cmd.cmd_skill(args)

def completions_skill(self):
    """Provide completions for /skill command."""
    from aider.skill_command import SkillCommand
    skill_cmd = SkillCommand(self.io, self.coder)
    return skill_cmd.completions_skill()
```

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
# tests/test_hooks.py
import pytest
from aider.hooks import HooksManager, create_hooks_manager

class TestHooksManager:
    def test_register_hook(self):
        manager = HooksManager()
        
        def callback(**kwargs):
            return {"test": True}
        
        result = manager.register("pre_command", callback)
        assert result is True
        assert len(manager.hooks["pre_command"]) == 1
    
    def test_execute_hook(self):
        manager = HooksManager()
        
        called = []
        def callback(**kwargs):
            called.append(True)
            return {"result": "ok"}
        
        manager.register("pre_command", callback)
        result = manager.execute("pre_command")
        
        assert called == [True]
        assert result["executed"] is True
        assert len(result["callbacks"]) == 1
    
    def test_hook_error_handling(self):
        manager = HooksManager(verbose=True)
        
        def failing_callback(**kwargs):
            raise ValueError("Test error")
        
        manager.register("pre_command", failing_callback)
        result = manager.execute("pre_command")
        
        assert result["executed"] is True
        assert len(result["errors"]) == 1
        assert "Test error" in result["errors"][0]["error"]
```

### 7.2 Integration Tests

```python
# tests/test_openclaw_integration.py
import pytest
from aider.openclaw_bridge import OpenClawBridge

class TestOpenClawIntegration:
    def test_skill_discovery(self):
        bridge = OpenClawBridge()
        skills = bridge.discover_skills()
        
        assert isinstance(skills, dict)
        # At least some skills should be found in test environment
    
    def test_skill_metadata_loading(self):
        bridge = OpenClawBridge()
        
        # Test with a known skill if available
        metadata = bridge.load_skill_metadata("github")
        
        if metadata:
            assert metadata.name == "github"
            assert metadata.description is not None
    
    def test_skill_execution(self):
        bridge = OpenClawBridge()
        
        # Test with a simple skill
        result = bridge.execute_skill(
            "test-skill",
            action="echo",
            args=["hello"]
        )
        
        # Should fail gracefully for non-existent skill
        assert result.success is False
        assert "not found" in result.error_message.lower()
```

---

## 8. Migration Path

### 8.1 From Existing Hooks System

The existing `aider/hooks.py` system should be consolidated into `aider/hooks_manager.py`:

```python
# Migration guide for existing hook users

# Old API (aider/hooks.py)
from aider.hooks import HooksManager
manager = HooksManager(io, verbose)
manager.register("pre_command", callback)

# New API (aider/hooks_manager.py)
from aider.hooks_manager import HooksManager, HookPoint
manager = HooksManager(bridge)
manager.register("my-hook", HookPoint.PRE_COMMAND, callback)
```

### 8.2 Backward Compatibility

The system should maintain backward compatibility:

```python
# aider/hooks.py - wrapper for backward compatibility
def create_hooks_manager(io=None, verbose=False):
    """Create hooks manager (backward compatible)."""
    from aider.hooks_manager import HooksManager, get_hooks_manager
    
    manager = get_hooks_manager()
    if manager is None:
        manager = HooksManager()
    
    # Wrap for compatibility
    return _LegacyHooksWrapper(manager, io, verbose)

class _LegacyHooksWrapper:
    def __init__(self, manager, io, verbose):
        self._manager = manager
        self.io = io
        self.verbose = verbose
    
    def register(self, hook_name, callback):
        from aider.hooks_manager import HookPoint
        hook_point = HookPoint[hook_name.upper()]
        return self._manager.register(hook_name, hook_point, callback)
    
    def execute(self, hook_name, *args, **kwargs):
        return self._manager.execute_hooks(hook_name.upper(), kwargs)
```

---

## 9. Security Considerations

### 9.1 Sandboxing

- Skill scripts execute in a subprocess with controlled environment
- No direct access to Aider's internal state
- Timeout limits prevent runaway execution

### 9.2 Permission Model

```python
# Hook permissions
class HookPermissions:
    READ_ONLY = "read_only"      # Can read context, no modifications
    MODIFY_EDITS = "modify_edits" # Can modify edit list
    CANCEL = "cancel"            # Can cancel operations
    EXECUTE = "execute"          # Can execute commands

# Register with permissions
def register_hooks(hooks_manager):
    hooks_manager.register(
        "pre_edit",
        my_callback,
        permissions=[HookPermissions.READ_ONLY, HookPermissions.MODIFY_EDITS]
    )
```

### 9.3 Safe Evaluation

```python
def _evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
    """Safely evaluate a condition expression."""
    allowed_names = {
        "context": context,
        "files": context.get("files", []),
        "message": context.get("message", ""),
        "true": True,
        "false": False,
        "none": None,
    }
    
    try:
        result = eval(condition, {"__builtins__": {}}, allowed_names)
        return bool(result)
    except Exception as e:
        logger.warning(f"Condition evaluation failed: {e}")
        return True  # Default to executing
```

---

## 10. Performance Considerations

### 10.1 Async Execution

```python
# For non-blocking hooks
import asyncio

async def async_hook(context):
    # Perform async operations
    await asyncio.sleep(1)
    return {"result": "async complete"}

# Register with async flag
manager.register(
    "post_send",
    async_hook,
    config=HookConfig(async_execution=True)
)
```

### 10.2 Caching

```python
class SkillCache:
    """Cache for skill metadata and execution results."""
    
    def __init__(self, ttl=300):
        self._cache = {}
        self._ttl = ttl
    
    def get(self, key):
        if key in self._cache:
            value, expiry = self._cache[key]
            if time.time() < expiry:
                return value
            del self._cache[key]
        return None
    
    def set(self, key, value):
        self._cache[key] = (value, time.time() + self._ttl)
```

---

## 11. Documentation

### 11.1 User Documentation

- `openclaw_conventions.md` - Usage guide (already exists)
- `hooks_example.py` - Example implementations (already exists)
- `.aider-hooks.yml.example` - Configuration examples

### 11.2 Developer Documentation

- API reference for hook registration
- Skill development guide
- Testing guidelines

---

## 12. Future Enhancements

### 12.1 Planned Features

1. **Plugin Marketplace** - Central repository for skills
2. **Web UI Integration** - Visual skill management
3. **Skill Composition** - Chain multiple skills together
4. **Remote Skills** - Load skills from URLs
5. **AI-Generated Skills** - Auto-generate skills from examples

### 12.2 Research Areas

1. **Hook Interoperability** - Standard interface across AI coding tools
2. **Distributed Hooks** - Hooks that run on remote servers
3. **ML-Optimized Hooks** - Hooks that learn from usage patterns

---

## Appendix A: File Summary

| File | Lines | Purpose |
|------|-------|---------|
| `aider/openclaw_bridge.py` | 732 | Core skill discovery and execution |
| `aider/skill_command.py` | 521 | `/skill` command implementation |
| `aider/hooks_manager.py` | 546 | Hook lifecycle management |
| `aider/hooks.py` | 337 | Legacy hooks (backward compat) |
| `aider/hooks_example.py` | 247 | Example hook implementations |
| `aider/openclaw_conventions.md` | 313 | Usage documentation |
| **Total** | **~2,700** | **Implemented** |

---

## Appendix B: Hook Context Reference

| Hook Point | Context Keys | Can Modify |
|------------|--------------|------------|
| PRE_COMMAND | cmd_name, args, io | args, cancel |
| POST_COMMAND | cmd_name, args, result, io | - |
| PRE_SEND | message, coder | message |
| POST_SEND | message, response, coder | - |
| PRE_EDIT | edits, coder | edits |
| POST_EDIT | edited_files, coder | - |
| PRE_COMMIT | files, message, coder | message, cancel |
| POST_COMMIT | files, message, hash, coder | - |
| PRE_SUMMARIZE | messages, coder | skip |
| POST_SUMMARIZE | original, summary, coder | - |
| ON_INIT | args, io | - |
| ON_EXIT | coder | - |

---

*Document Version: 1.0*
*Last Updated: 2026-03-16*
