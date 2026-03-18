---
parent: Usage
title: Skills
nav_order: 100
---

# Skills

Skills are reusable, composable capabilities that can leverage aider's multi-agent system for parallel task execution.

## Overview

Skills provide high-level capabilities for common development tasks:

- **Parallel execution** - Run tasks on multiple files simultaneously using sub-agents
- **Sequential fallback** - Work without agents when they're unavailable
- **Built-in workflows** - Pre-configured for common tasks like code review, testing, and documentation

## Built-in Skills

| Skill | Description | Parallel |
|-------|-------------|----------|
| `code-review` | Parallel code review | ✅ |
| `security-audit` | Security-focused review | ✅ |
| `performance-review` | Performance analysis | ✅ |
| `test-generation` | Generate tests | ✅ |
| `refactoring` | Parallel refactoring | ✅ |
| `documentation` | Generate documentation | ✅ |
| `architecture-docs` | Architecture documentation | ✅ |
| `coverage-analysis` | Analyze test coverage | ✅ |

## Using Skills

### List Available Skills

```bash
/skill list
```

### Run a Skill

```bash
# Basic usage
/skill run code-review -f auth.py models.py

# With sub-agents (parallel execution)
/skill run code-review -f auth.py models.py --agents

# Limit concurrent agents
/skill run code-review -f *.py --agents --max-agents 5
```

### Get Skill Information

```bash
/skill info test-generation
```

### Search for Skills

```bash
/skill search test
```

## Skill Examples

### Code Review

Review multiple files in parallel:

```bash
/skill run code-review -f auth.py models.py api.py --agents --focus security
```

Focus options:
- `security` - Security vulnerabilities
- `performance` - Performance issues
- `general` - General code quality (default)

### Test Generation

Generate tests for your code:

```bash
/skill run test-generation -f user.py auth.py --agents
```

### Documentation

Generate documentation:

```bash
/skill run documentation -f main.py utils.py --format google
```

Format options: `google`, `numpy`, `restructuredtext`

## Configuration

### Environment Variables

```bash
export AIDER_ENABLE_AGENTS=true      # Enable sub-agents
export AIDER_MAX_AGENTS=10           # Default max concurrent agents
export AIDER_AGENT_TIMEOUT=300       # Agent timeout in seconds
```

### Command Line

```bash
aider --enable-agents --max-agents 5
```

## How It Works

1. **Agent Check** - Skill checks if agents are available
2. **Parallel Mode** - If agents available, spawns sub-agents for each file
3. **Sequential Mode** - Falls back to sequential processing if agents unavailable
4. **Result Aggregation** - Combines results from all workers

## Creating Custom Skills

See [SKILLS.md](https://github.com/i-may-have-stepped-in-it/aider/blob/main/SKILLS.md) in the repository for detailed information on creating custom skills.

Basic example:

```python
from aider.skills import Skill, SkillContext, SkillResult

class MySkill(Skill):
    name = "my-skill"
    description = "Does something useful"
    
    async def execute(self, files: List[str], **kwargs) -> SkillResult:
        # Your logic here
        return SkillResult(
            success=True,
            output="Done!",
        )
```

## See Also

- [Agents](agents.html) - Sub-agent system for parallel execution
- [Multi-Agent Mode]({{ '/docs/usage/agents.html' | relative_url }}) - Spawn agents manually
