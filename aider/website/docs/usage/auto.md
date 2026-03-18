---
parent: Usage
title: Autonomous Mode
nav_order: 95
---

# Autonomous Mode

Aider's autonomous mode (`/auto`) provides full parity with Claude Code, Codex, and other autonomous coding agents.

## Overview

In autonomous mode, aider can:

- **Auto-discover files** - Find relevant files without manual `/add`
- **Plan and execute** - Multi-phase workflow with review
- **Self-correct** - Retry on test failures
- **Run autonomously** - Complete tasks with minimal guidance

## Quick Start

```bash
# Basic autonomous task
/auto "Add error handling to the auth module"

# With test verification
/auto "Fix the login bug" --test "pytest tests/test_auth.py"

# With custom model
/auto "Refactor the API" --model o1-preview
```

## Workflow

The `/auto` command uses a multi-phase workflow:

### 1. Librarian Phase

Auto-discovers relevant files in your codebase:

```
Analyzing request: "Add error handling to auth module"
Finding relevant files...
- auth.py
- models.py
- exceptions.py
```

### 2. Architect Phase

Creates a detailed implementation plan:

```
Planning changes...
1. Add try/except blocks in auth.py
2. Create custom AuthException class
3. Update error responses in API
```

### 3. Reviewer Phase

Self-critiques the plan before execution:

```
Reviewing plan...
✓ Error handling strategy looks good
⚠ Consider adding logging
✓ API changes are backward compatible
```

### 4. Editor Phase

Executes the plan with proper formatting:

```
Implementing changes...
✓ Modified auth.py
✓ Created exceptions.py
✓ Updated models.py
```

### 5. Self-Correction Phase

If tests are provided, verifies and retries:

```
Running tests...
❌ Test failed: test_auth.py::test_login
Retrying with fix...
✓ Test passed
```

## Commands

### Basic Usage

```bash
/auto "your task description"
```

### With Test Verification

```bash
# Run tests after each change
/auto "Implement feature" --test "pytest tests/"

# Specific test file
/auto "Fix bug" --test "pytest tests/test_bug.py -v"

# Custom test command
/auto "Refactor" --test "npm test"
```

### With File Constraints

```bash
# Only consider specific files
/auto "Update API" --files "api.py,models.py"

# Exclude files
/auto "Fix bug" --exclude "tests/*,docs/*"
```

### With Custom Model

```bash
# Use stronger model for planning
/auto "Design system" --model o1-preview

# Use faster model for implementation
/auto "Implement feature" --model gpt-4o
```

## Configuration

### Environment Variables

```bash
export AIDER_AUTO_MAX_ITERATIONS=10    # Max retry iterations
export AIDER_AUTO_TEST_TIMEOUT=300     # Test timeout in seconds
```

### Command Line Options

```bash
aider --auto-accept-architect    # Auto-accept architect suggestions
aider --architect               # Enable architect mode by default
```

## Tips for Best Results

### Be Specific

```bash
# Good - specific and actionable
/auto "Add input validation to the login endpoint in auth.py"

# Less specific
/auto "Improve the code"
```

### Provide Tests

```bash
# Best - with test verification
/auto "Implement user registration" --test "pytest tests/test_auth.py"

# Good - manual verification
/auto "Implement user registration"
```

### Start Small

```bash
# Good - focused task
/auto "Add email validation to User model"

# Risky - too broad
/auto "Redesign the entire application"
```

## Comparison with Other Tools

| Feature | Aider `/auto` | Claude Code | Codex |
|---------|---------------|-------------|-------|
| Auto file discovery | ✅ | ✅ | ✅ |
| Multi-phase planning | ✅ | ✅ | ✅ |
| Self-correction | ✅ | ✅ | ✅ |
| Git integration | ✅ Native | ⚠️ Via CLI | ⚠️ Via CLI |
| Test verification | ✅ Built-in | ✅ | ✅ |
| Edit formats | ✅ Multiple | Unified diff | Unified diff |
| Local models | ✅ Via OpenClaw | ❌ | ❌ |

## Limitations

- **Complex refactoring** - May need manual guidance for large architectural changes
- **Domain expertise** - Requires clear requirements for specialized domains
- **Test coverage** - Works best when tests already exist

## Troubleshooting

### Too Many Files

If `/auto` discovers too many files:

```bash
# Constrain to specific directory
/auto "Fix bug" --files "src/auth/*.py"

# Or manually add files first
/add src/auth/core.py
/auto "Fix bug"
```

### Tests Failing

If autonomous mode can't fix failing tests:

```bash
# Increase iterations
export AIDER_AUTO_MAX_ITERATIONS=20

# Or switch to manual mode
/undo
# ... manual edits
```

### Plan Not Optimal

The reviewer phase catches most issues, but you can:

```bash
# Review the plan before execution
# (Architect mode shows the plan)

# Or cancel and refine request
/undo
/auto "More specific request"
```

## See Also

- [Chat Modes](modes.html) - Architect, code, ask, help modes
- [Skills](skills.html) - High-level capabilities
- [Agents](agents.html) - Manual sub-agent control
