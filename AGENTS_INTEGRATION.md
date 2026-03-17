# Aider Multi-Agent System Integration

This document describes the multi-agent system integration for Aider, inspired by kimi-cli's agent architecture.

## Overview

The multi-agent system allows Aider to spawn sub-agents for parallel task execution. Each sub-agent:
- Runs with isolated context (no parent conversation history)
- Can use a different model than the parent
- Works on a specific set of files
- Reports results back to the parent

## Architecture

### Core Components

```
aider/agents/
├── __init__.py       # Package exports
├── agent.py          # SubAgent, AgentStatus, AgentResult types
├── registry.py       # AgentRegistry for tracking agents
├── executor.py       # AgentExecutor for spawning agents
├── commands.py       # CLI commands (/agent subcommands)
├── integration.py    # Integration helpers for Aider
└── patch_args.py     # CLI argument patches
```

### Component Details

#### 1. Agent Types (`agent.py`)

```python
@dataclass
class SubAgent:
    id: str
    name: str
    task: str
    status: AgentStatus
    model: Optional[str] = None
    files: list[str] = field(default_factory=list)
    result: Optional[AgentResult] = None
    # ... more fields

class AgentStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    ERROR = auto()
    CANCELLED = auto()
```

#### 2. Agent Registry (`registry.py`)

Thread-safe registry for tracking agents:

```python
registry = AgentRegistry(max_concurrent=5)

# Register an agent
await registry.register(agent)

# Get agent by ID
agent = await registry.get("agent_id")

# List agents
agents = await registry.list_agents()
active = await registry.list_active()

# Wait for completion
completed = await registry.wait_for_completion("agent_id")

# Cancel agents
await registry.cancel("agent_id")
cancelled = await registry.cancel_all()

# Get statistics
stats = await registry.get_stats()
```

#### 3. Agent Executor (`executor.py`)

Spawns and manages agent execution:

```python
executor = AgentExecutor(parent_coder, registry)

# Spawn an agent
agent = await executor.spawn(
    name="Code Review",
    task="Review auth.py for security issues",
    model="claude-3-5-sonnet",
    files=["auth.py"]
)

# Wait for all agents
await executor.wait_for_all()
```

#### 4. CLI Commands (`commands.py`)

Provides `/agent` subcommands:

```
/agent spawn <name> [task] [--model MODEL] [--files FILES]
/agent list [--status STATUS]
/agent status <id>
/agent result <id> [--wait]
/agent wait <id>
/agent cancel <id>
/agent clear
```

## Usage Examples

### Parallel Code Review

Spawn multiple agents to review different files simultaneously:

```bash
# Spawn review agents
/agent spawn "Review auth.py for security issues" --files auth.py --model claude-sonnet
/agent spawn "Review user.py for SQL injection" --files user.py --model claude-sonnet
/agent spawn "Check test coverage" --files tests/ --model gpt-4o-mini

# Monitor progress
/agent list

# Collect results
/agent result <agent_id>
```

### Multi-Model Workflow

Use different models for different aspects:

```bash
# Architecture with Kimi
/agent spawn "Design the API" --model kimi-k2.5 --name api-design

# Implementation with Claude
/agent spawn "Implement the API" --model claude-3.5-sonnet --name implementation

# Testing with lightweight model
/agent spawn "Write tests" --model gpt-4o-mini --files payment.py --name tests
```

### Programmatic Usage

```python
import asyncio
from aider.agents import AgentRegistry, AgentExecutor
from aider.agents.agent import SubAgent, AgentStatus

async def main():
    # Create registry and executor
    registry = AgentRegistry(max_concurrent=5)
    executor = AgentExecutor(parent_coder, registry)
    
    # Spawn multiple agents
    agents = []
    for filename in ["auth.py", "models.py", "api.py"]:
        agent = await executor.spawn(
            name=f"Review {filename}",
            task=f"Review {filename} for issues",
            files=[filename]
        )
        agents.append(agent)
    
    # Wait for all to complete
    await executor.wait_for_all()
    
    # Collect results
    for agent in agents:
        if agent.result:
            print(f"{agent.name}: {agent.result.output}")

asyncio.run(main())
```

## Integration with Aider

### CLI Arguments

Add to `args.py`:

```python
group = parser.add_argument_group("Multi-agent Options")

group.add_argument(
    "--enable-agents",
    action="store_true",
    help="Enable multi-agent support",
    default=False,
)

group.add_argument(
    "--max-agents",
    type=int,
    default=5,
    help="Maximum concurrent agents",
)
```

### Initialization

In `main.py`, after Coder creation:

```python
if args.enable_agents:
    from aider.agents.integration import initialize_agents
    initialize_agents(coder, max_concurrent=args.max_agents)
```

### Command Registration

The commands are automatically registered when the Commands class is instantiated with a coder that has an agent_registry attribute.

## Configuration

### Environment Variables

```bash
export AIDER_ENABLE_AGENTS=true
export AIDER_MAX_AGENTS=10
export AIDER_AGENT_TIMEOUT=600
```

### Config File

Add to `.aider.conf.yml`:

```yaml
enable-agents: true
max-agents: 5
agent-timeout: 300
```

## Testing

Run the test suite:

```bash
cd /home/openclaw/openclaw/aider
python3 test_agents.py
```

Run the examples:

```bash
python3 examples/multi_agent_example.py
```

## Differences from kimi-cli

While inspired by kimi-cli, this implementation:
- Uses Aider's existing Coder system for sub-agents
- Integrates with Aider's commands infrastructure
- Leverages Aider's model switching capabilities
- Maintains Aider's file handling semantics
- Uses asyncio for concurrency (kimi uses threading)

## Future Enhancements

Potential improvements:
- Agent-to-agent messaging
- Automatic task decomposition
- Agent workflows/pipelines
- Result aggregation tools
- Agent templates
- Web UI for monitoring

## Files Added

```
aider/agents/__init__.py       # Package exports
aider/agents/agent.py          # Core types
aider/agents/registry.py       # Agent tracking
aider/agents/executor.py       # Agent execution
aider/agents/commands.py       # CLI commands
aider/agents/integration.py    # Aider integration
aider/agents/patch_args.py     # CLI arg patches
aider/agents/README.md         # Documentation
aider/test_agents.py           # Test suite
aider/examples/multi_agent_example.py  # Usage examples
```

## Integration Status

- ✅ Core agent types (SubAgent, AgentStatus, AgentResult)
- ✅ AgentRegistry with thread-safe operations
- ✅ AgentExecutor for spawning agents
- ✅ CLI commands (/agent subcommands)
- ✅ Integration helpers
- ✅ Test suite
- ✅ Usage examples
- ⏳ Full Aider integration (args.py, main.py modifications)
- ⏳ Real agent execution (currently simulated)
