# Aider Multi-Agent System

Multi-agent support for Aider, inspired by kimi-cli's agent system.

## Overview

This module adds multi-agent capabilities to Aider, allowing you to:

- Spawn sub-agents for parallel task execution
- Coordinate multiple agents working on different parts of a project
- Aggregate results from multiple agents
- Manage agent lifecycle (spawn, monitor, cancel, collect results)

## Installation

The multi-agent system is integrated into Aider. Simply install Aider as usual:

```bash
pip install -e /home/openclaw/openclaw/aider
```

Enable agents with:

```bash
aider --enable-agents --max-agents 5
```

## Commands

### `/agent spawn <task> [options]`

Spawn a new sub-agent to work on a task.

```bash
# Basic usage
/agent spawn "Review auth.py for security issues"

# With specific model
/agent spawn "Add tests for user.py" --model claude-3-5-sonnet

# With file context
/agent spawn "Refactor database.py" --files database.py,models.py --readonly config.py

# Named agent
/agent spawn "Update README" --name readme-update --model gpt-4o-mini
```

Options:
- `--model MODEL`: Use specific model for this agent
- `--files FILES`: Comma-separated list of files to include
- `--readonly FILES`: Comma-separated list of read-only files
- `--name NAME`: Give the agent a descriptive name

### `/agent list [options]`

List all agents and their status.

```bash
# List all agents
/agent list

# Filter by status
/agent list --status running
/agent list --status completed
```

### `/agent status <id>`

Show detailed status of a specific agent.

```bash
/agent status abc123
```

### `/agent result <id> [--wait]`

Get the result from a completed agent.

```bash
# Get result immediately
/agent result abc123

# Wait for completion and then get result
/agent result abc123 --wait
```

### `/agent wait <id>`

Wait for an agent to complete.

```bash
/agent wait abc123
```

### `/agent cancel <id>`

Cancel a running agent.

```bash
/agent cancel abc123
```

### `/agent clear`

Cancel all active agents and clear completed ones.

```bash
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

# Wait and collect results
/agent list --status running
# ... wait ...
/agent result <id1>
/agent result <id2>
```

### Multi-Model Architecture

Use different models for different aspects:

```bash
# Kimi for planning
/agent spawn "Design the API for payment processing" --model kimi-k2.5 --name api-design

# Claude for implementation
/agent wait <design-agent-id>
/agent spawn "Implement the payment API based on: $(/agent result <id>)" --model claude-3.5-sonnet

# GPT-4o-mini for tests
/agent spawn "Write tests for payment API" --model gpt-4o-mini --files payment.py
```

### Parallel Implementation

Implement multiple features in parallel:

```bash
# Spawn agents for different features
/agent spawn "Implement user authentication" --files auth.py,user.py --name auth-feature
/agent spawn "Add email notifications" --files email.py,user.py --name email-feature
/agent spawn "Create admin dashboard" --files admin.py,dashboard.py --name admin-feature

# Monitor progress
/agent list

# Collect results
/agent result auth-feature --wait
/agent result email-feature --wait
/agent result admin-feature --wait
```

## Architecture

The multi-agent system consists of:

1. **AgentRegistry**: Thread-safe registry for tracking agents
2. **AgentExecutor**: Spawns and manages agent execution
3. **AgentCommands**: CLI commands for agent management
4. **SubAgent**: Data class representing an agent instance

### Agent Lifecycle

```
PENDING → RUNNING → COMPLETED/ERROR/CANCELLED
```

### Context Isolation

Each sub-agent gets:
- Isolated conversation context (no parent history)
- Specified files added to context
- Independent model configuration
- Separate token tracking

### Concurrency

- Maximum concurrent agents controlled by `--max-agents`
- Semaphore-based resource limiting
- Async execution for efficiency

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

## Implementation Details

### Key Files

- `aider/agents/agent.py`: Core agent types
- `aider/agents/registry.py`: Agent tracking
- `aider/agents/executor.py`: Agent execution
- `aider/agents/commands.py`: CLI commands
- `aider/agents/integration.py`: Aider integration
- `aider/agents/service.py`: AgentService for runtime integration (v2.1.0)

### Integration Points

The system integrates with Aider via:
- Commands system (`/agent` commands)
- SessionRuntime (agent_service, agent_registry)
- CLI arguments (`--enable-agents`, `--max-agents`)
- Bootstrap initialization (no monkeypatching in v2.1.0)

## Differences from kimi-cli

While inspired by kimi-cli, this implementation:
- Uses Aider's existing Coder system for sub-agents
- Integrates with Aider's commands infrastructure
- Leverages Aider's model switching
- Maintains Aider's file handling semantics

## Limitations

- Sub-agents cannot spawn sub-agents (to prevent recursion issues)
- Each sub-agent consumes API tokens independently
- Context is not automatically shared between agents
- No built-in agent-to-agent communication (use files/results)

## Future Enhancements

Potential improvements:
- Agent-to-agent messaging
- Automatic task decomposition
- Agent workflows/pipelines
- Result aggregation tools
- Agent templates
