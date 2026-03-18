---
parent: Usage
title: Multi-Agent Mode
nav_order: 90
---

# Multi-Agent Mode

Aider's multi-agent system allows you to spawn sub-agents for parallel task execution.

## Overview

Sub-agents are independent aider instances that can work on tasks in parallel:

- **Parallel execution** - Multiple agents work simultaneously
- **Fault tolerance** - Circuit breaker pattern prevents cascading failures
- **Lifecycle management** - Agents progress through PENDING → RUNNING → COMPLETED/ERROR states
- **Result aggregation** - Collect and combine results from all agents

## Commands

### Spawn an Agent

```bash
/agent spawn "Review auth.py for security issues"

# With specific model
/agent spawn "Optimize database queries" --model claude-sonnet

# With files
/agent spawn "Document the API" --files api.py models.py
```

### List Agents

```bash
/agent list
```

Shows all agents with their status:
- `PENDING` - Waiting to start
- `RUNNING` - Currently working
- `COMPLETED` - Finished successfully
- `ERROR` - Failed or cancelled

### Check Agent Status

```bash
/agent status <agent-id>
```

### Get Agent Result

```bash
/agent result <agent-id>
```

### Cancel an Agent

```bash
/agent cancel <agent-id>
```

## Agent Swarm

Coordinate multiple agents for complex tasks:

```bash
/swarm "Design the database schema" --agents "architect,developer,reviewer"
```

This spawns three agents with different roles to collaborate on the task.

## Configuration

### Environment Variables

```bash
export AIDER_ENABLE_AGENTS=true      # Enable agent system
export AIDER_MAX_AGENTS=10           # Max concurrent agents
export AIDER_AGENT_TIMEOUT=300       # Timeout in seconds
```

### Command Line

```bash
aider --enable-agents --max-agents 5
```

## How It Works

```
Parent Aider
    ↓
Spawns Sub-Agent(s)
    ↓
Each agent:
  - Gets its own coder instance
  - Works on assigned task
  - Reports progress
  - Returns result
    ↓
Results aggregated back to parent
```

## Use Cases

### Parallel Code Review

```bash
# Review multiple files simultaneously
/agent spawn "Review auth.py" --model claude
/agent spawn "Review models.py" --model claude
/agent spawn "Review api.py" --model claude

# Wait for all to complete
/agent list
```

### Multi-Model Problem Solving

```bash
# Architecture with one model
/agent spawn "Design the caching layer" --model o1-preview

# Implementation with another
/agent spawn "Implement the cache" --model claude-sonnet
```

### Background Tasks

```bash
# Start long-running analysis in background
/agent spawn "Analyze codebase for tech debt" --files "*.py"

# Continue working while agent runs
# Later, check results
/agent result <agent-id>
```

## Circuit Breaker

The agent system includes circuit breaker protection:

- **CLOSED** - Normal operation, agents can spawn
- **OPEN** - Too many failures, new agents blocked temporarily
- **HALF_OPEN** - Testing if system recovered

This prevents resource exhaustion from failing agents.

## A2A Protocol

Agents communicate via the Agent-to-Agent (A2A) protocol:

- Async message passing
- Capability advertisement
- Request/response patterns

```bash
# A2A commands
/a2a send <agent-id> "message"
/a2a broadcast "message to all agents"
/a2a capabilities  # List agent capabilities
```

## Integration with Skills

Skills automatically use agents when available:

```bash
# This uses parallel agents internally
/skill run code-review -f *.py --agents
```

## Troubleshooting

### Agents Not Available

```
❌ Agents not available
```

- Check `AIDER_ENABLE_AGENTS=true`
- Verify system resources (agents consume memory/CPU)

### Agent Timeouts

Increase timeout:
```bash
export AIDER_AGENT_TIMEOUT=600  # 10 minutes
```

### Too Many Agents

Reduce concurrent limit:
```bash
aider --max-agents 3
```

## See Also

- [Skills](skills.html) - High-level capabilities using agents
- [Tips](tips.html) - General usage tips
