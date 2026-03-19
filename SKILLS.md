# Aider Skills with Multi-Agent Support

> **Related Docs**: [Documentation Index](DOCUMENTATION_INDEX.md) | [OpenClaw Integration](OPENCLAW_INTEGRATION.md) | [AGENTS.md](AGENTS.md)

This document describes the skills system for Aider, which provides reusable, composable capabilities that can leverage the multi-agent system for parallel task execution.

## Overview

Skills are high-level capabilities that can:
- Run sequentially or in parallel using sub-agents
- Be discovered and executed via the `/skill` command
- Be composed together for complex workflows
- Fall back to sequential mode when agents are unavailable

## Built-in Skills

| Skill | Description | Agents | Max Agents |
|-------|-------------|--------|------------|
| `code-review` | Parallel code review | ✅ | 10 |
| `security-audit` | Security-focused review | ✅ | 10 |
| `performance-review` | Performance analysis | ✅ | 10 |
| `test-generation` | Generate tests in parallel | ✅ | 8 |
| `coverage-analysis` | Analyze coverage gaps | ✅ | - |
| `refactoring` | Parallel refactoring | ✅ | 6 |
| `code-modernization` | Modernize legacy code | ✅ | 6 |
| `documentation` | Generate documentation | ✅ | 8 |
| `architecture-docs` | Generate architecture docs | ✅ | - |

## Auto-Discovery

Skills are **automatically discovered** from multiple sources:

1. **Python Skills** (`aider/skills/*.py`) - Classes inheriting from `Skill`
2. **ACP Agents** (`~/.acpx/config.json`) - Dynamic agent delegation skills
3. **YAML Skills** (`~/.config/aider/skills/*.yaml`) - User-defined skills
4. **OpenClaw Skills** (`~/.openclaw/skills/`) - External skill definitions

No registry edits needed - just drop files in the appropriate directory!

```bash
# View all discovered skills
/skill list

# Should show 100+ skills including:
# - Built-in Python skills
# - ACP agent skills (acp-claude, acp-codex, etc.)
# - YAML-defined skills
# - OpenClaw skills
```

## Usage

### CLI Commands

```bash
# List all skills
/skill list

# List only agent-enabled skills
/skill list --agents

# Run a skill
/skill run code-review -f auth.py models.py

# Run with sub-agents
/skill run code-review -f auth.py models.py --agents --max-agents 5

# Get skill info
/skill info test-generation

# Search for skills
/skill search test
```

### Programmatic Usage

```python
from aider.skills import create_skill, SkillContext

# Create context
context = SkillContext(
    coder=my_coder,
    io=my_io,
    enable_agents=True,
    max_agents=5,
)

# Create and run skill
skill = create_skill("code-review", context)
result = await skill.execute(
    files=["auth.py", "models.py"],
    focus="security"
)

print(f"Success: {result.success}")
print(f"Output: {result.output}")
```

## Creating Custom Skills

### Basic Skill

```python
from aider.skills import Skill, SkillContext, SkillResult

class MySkill(Skill):
    name = "my-skill"
    description = "Does something useful"
    version = "1.0.0"
    
    async def execute(self, files: List[str], **kwargs) -> SkillResult:
        # Your logic here
        return SkillResult(
            success=True,
            output="Done!",
        )
```

### Agent-Enabled Skill

```python
from aider.skills import Skill, SkillContext, SkillResult, AgentSkillMixin

class ParallelSkill(Skill, AgentSkillMixin):
    name = "parallel-processor"
    description = "Processes files in parallel"
    supports_agents = True
    max_agents = 5
    
    def __init__(self, context=None):
        Skill.__init__(self, context)
        AgentSkillMixin.__init__(self)
    
    async def execute(self, files: List[str], **kwargs) -> SkillResult:
        # Initialize agents
        if not self.init_agents(self.context):
            # Fallback to sequential
            return await self._sequential_process(files)
        
        # Spawn agents for each file
        tasks = [
            {"name": f"process_{i}", "prompt": f"Process {f}"}
            for i, f in enumerate(files)
        ]
        
        agent_ids = await self.spawn_agents(tasks)
        results = await self.wait_for_all()
        
        # Aggregate results
        return SkillResult(
            success=all(r.get("success") for r in results),
            output="Processed all files",
        )
```

### Using Map-Reduce Pattern

```python
from aider.skills import MapReduceSkill, SkillContext

class AnalysisSkill(MapReduceSkill):
    name = "code-analysis"
    description = "Analyze code with map-reduce"
    
    async def execute(self, files: List[str], **kwargs):
        self.init_agents(self.context)
        
        return await self.map_reduce(
            items=files,
            map_prompt_template="Analyze complexity of {item}",
            reduce_prompt="Summarize findings",
            max_workers=5,
            context=self.context
        )
```

### YAML-Defined Skills

Skills can be defined entirely in YAML without Python code:

```yaml
# ~/.config/aider/skills/hello-world.yaml
name: hello-world
description: A simple example skill
version: "1.0.0"
author: user

handler:
  type: shell
  command: echo "Hello, {{ name | default('World') }}!"

parameters:
  name:
    type: string
    description: Name to greet
    required: false
```

Handler types:
- `shell` - Execute shell commands
- `python` - Execute Python code
- `composite` - Chain multiple operations

## Skill Architecture

### Core Classes

```
aider/skills/
├── __init__.py          # Package exports
├── base.py              # Skill, SkillContext, SkillResult
├── agent_skill.py       # AgentSkillMixin, MapReduceSkill
├── registry.py          # SkillRegistry (auto-discovery)
├── discovery.py         # Dynamic skill discovery
├── command.py           # /skill command integration
├── code_review.py       # Code review skills
├── test_generation.py   # Test generation skills
├── refactoring.py       # Refactoring skills
├── documentation.py     # Documentation skills
├── dynamic_loader.py    # ACP agent skill loader
├── yaml_loader.py       # YAML skill loader
└── openclaw_adapter.py  # OpenClaw skill adapter
```

### Class Hierarchy

```
Skill (ABC)
├── execute() -> SkillResult
├── run() -> SkillResult (sync wrapper)
└── get_agent_registry() -> AgentRegistry

AgentSkillMixin
├── init_agents() -> bool
├── spawn_agent() -> str (agent_id)
├── spawn_agents() -> List[str]
├── wait_for_agent() -> Dict
├── wait_for_all() -> List[Dict]
├── cancel_agent() -> bool
└── to_skill_result() -> SkillResult

ParallelSkill(Skill, AgentSkillMixin)
└── execute_parallel() -> List[SkillResult]

MapReduceSkill(AgentSkillMixin)
└── map_reduce() -> SkillResult
```

## Configuration

### Environment Variables

```bash
export AIDER_ENABLE_AGENTS=true
export AIDER_MAX_AGENTS=10
export AIDER_AGENT_TIMEOUT=300
```

### Skill Context

```python
context = SkillContext(
    coder=my_coder,           # Aider Coder instance
    io=my_io,                 # Aider IO instance
    args={},                  # Additional arguments
    verbose=True,             # Verbose logging
    enable_agents=True,       # Enable sub-agents
    max_agents=5,             # Max concurrent agents
    agent_timeout=300.0,      # Agent timeout (seconds)
)
```

## Examples

### Parallel Code Review

```python
# Review multiple files in parallel
skill = create_skill("code-review", context)
result = await skill.execute(
    files=["auth.py", "models.py", "api.py", "utils.py"],
    focus="security",
    model="claude-3-5-sonnet"
)

# Results include findings from all agents
for agent_result in result.agent_results:
    print(f"{agent_result['name']}: {agent_result['output']}")
```

### Multi-Model Workflow

```python
# Architecture with Kimi
architect = create_skill("architecture-docs", context)
architect.context.enable_agents = True

# Implementation with Claude  
impl = create_skill("refactoring", context)
impl.context.max_agents = 3

# Tests with lightweight model
tests = create_skill("test-generation", context)
```

### Batch Processing

```python
from aider.skills.agent_skill import MapReduceSkill

skill = MapReduceSkill()
skill.context = context
skill.init_agents(context)

# Process 100 files with 10 workers
results = await skill.map_reduce(
    items=large_file_list,
    map_prompt_template="Analyze {item}",
    reduce_prompt="Summarize all findings",
    max_workers=10
)
```

## Integration with Aider

### Installation

The skills command is automatically available when using Aider:

```python
# In Aider's commands.py
from aider.skills.command import install_skills_command

class Commands:
    def __init__(self, ...):
        ...
        install_skills_command(self)
```

### Hook Integration

Skills can also be triggered via hooks:

```python
# In a hook file
def register_hooks(hooks_manager):
    hooks_manager.register("pre_command", on_pre_command)

def on_pre_command(command, args):
    if command == "/review":
        # Trigger code review skill
        skill = create_skill("code-review")
        # ... execute skill
```

## Testing

Run the skills test suite:

```bash
cd /home/openclaw/openclaw/aider
python3 test_skills.py
```

Run the examples:

```bash
python3 examples/skills_example.py
```

## Best Practices

1. **Always check agent availability**: Use `init_agents()` and provide sequential fallback
2. **Respect max_agents**: Don't spawn more agents than the system can handle
3. **Handle timeouts**: Set appropriate timeouts for long-running tasks
4. **Aggregate results**: Combine agent outputs meaningfully
5. **Report progress**: Use progress callbacks for long operations
6. **Clean up**: Cancel agents if the main task is cancelled

## Future Enhancements

- [ ] Skill composition/pipelines
- [ ] Skill marketplace/discovery
- [ ] Web UI for skill monitoring
- [ ] Skill result caching
- [ ] Automatic skill selection based on task
- [ ] Skill versioning and dependencies
