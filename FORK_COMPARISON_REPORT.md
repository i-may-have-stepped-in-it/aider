# Aider Fork Comparison Report

## Overview

| Repository | URL | Status |
|------------|-----|--------|
| **Upstream** | https://github.com/Aider-AI/aider | Original project |
| **This Fork** | https://github.com/i-may-have-stepped-in-it/aider | Local fork with extensive extensions |

## Statistics

| Metric | Value |
|--------|-------|
| Commits ahead of upstream | **44** |
| Commits behind upstream | **0** |
| New files added | **193** |
| Files modified | **51** |
| New directories | **10** |

---

## Key Differences

### 1. Architecture Transformation

**Upstream**: Single-agent pair programming tool
**This Fork**: Multi-Agent Autonomous Ecosystem ("Parity+")

```
Upstream: User ↔ Coder ↔ LLM

This Fork: User ↔ Coder ↔ AgentService ↔ Multiple Sub-Agents
                      ↓
                A2A Message Bus
                      ↓
            ┌─────────┼─────────┐
            ▼         ▼         ▼
       Librarian  Architect  Reviewer
       Agent      Agent       Agent
```

### 2. New Systems Added

#### A. Multi-Agent System (`aider/agents/`)
- **AgentService** - Session-level agent management
- **AgentRegistry** - Lifecycle management with circuit breaker
- **AgentExecutor** - Spawn and execute sub-agents
- **MissionGovernor** - Safety limits (cost, depth, turns)
- **AutonomousAgent** - Self-directed workflow agent
- **A2AEnabledAgent** - Agent-to-agent messaging

**New Commands:**
- `/agent spawn <task>` - Create sub-agent
- `/agent list` - List active agents
- `/agent status <id>` - Check agent status
- `/agent wait <id>` - Wait for completion
- `/agent results <id>` - Get results

#### B. A2A Protocol (`aider/a2a/`)
- **A2AMessageBus** - Async message passing between agents
- **A2AEnabledAgent** - Mixin for A2A capabilities
- **A2ACommands** - `/a2a` CLI commands
- Capability advertisement and discovery

#### C. Skills System (`aider/skills/`)
- **Auto-discovery** from 4 sources:
  - Python skills (aider/skills/*.py)
  - YAML skills (~/.config/aider/skills/*.yaml)
  - ACP agents (~/.acpx/config.json)
  - OpenClaw skills (via bridge)
- **SkillRegistry** - Dynamic loading
- **ParallelSkill** - Multi-agent skill execution

**New Commands:**
- `/skill list` - List available skills
- `/skill run <name>` - Execute skill
- `/skill info <name>` - Show skill details

#### D. Hooks System (`aider/hooks_manager.py`)
- **20 Hook Points** including:
  - PRE_COMMIT, POST_COMMIT
  - PRE_EDIT, POST_EDIT
  - UI_PHASE_UPDATE, UI_COST_UPDATE
  - UI_AGENT_HEARTBEAT, UI_TOOL_PROGRESS
- **HookConfig** with priority, timeout, retry, dependencies
- **Execution history** tracking

#### E. Tool System v2 (`aider/tools_v2/`)
- **ToolRouterV2** with modular mixins
- **AsyncExecutor** - Safe async/sync bridging
- **AccurateCostTracker** - True cost with overhead (40-60% more accurate)
- **ResilientExecutor** - Circuit breaker + retry logic
- **Sandbox** - Multi-layer security (firejail/unshare/minimal)
- **SmartCompressor** - Semantic output compression

#### F. Bootstrap Architecture (`aider/bootstrap/`)
- **launch.py** - Argument parsing, git setup
- **session.py** - Coder/command creation
- **runtime.py** - Runtime service attachment
- **session_runtime.py** - Shared services container
- Clean separation, no monkeypatching

#### G. GUI Components (`aider/gui/`)
- **LiveDashboard** - Real-time status display
- **DiffViewer** - Side-by-side diff visualization
- **Hints** - Contextual hint system

### 3. New Commands

| Command | Description |
|---------|-------------|
| `/auto "task"` | Autonomous 4-phase workflow (Librarian→Architect→Reviewer→Editor) |
| `/swarm "task"` | Collaborative multi-agent execution |
| `/skill <action>` | Skill management and execution |
| `/agent <action>` | Agent management |
| `/a2a <action>` | Agent-to-agent communication |
| `/cache` | Show token caching statistics |
| `/watch <action>` | Monitor background processes |
| `/mcp <action>` | MCP server management |
| `/index <action>` | Semantic index management |
| `/auto-mode [on/off]` | Toggle tool auto-confirmation |
| `/think-tokens [value]` | Set thinking budget |
| `/reasoning-effort [level]` | Set reasoning effort |

### 4. Modified Core Components

#### Coder System
- **Modularized base_coder.py** into 13 focused mixins
- Added `ToolEnabledCoderV2` for tool use
- Added `ArchitectCoder` for autonomous workflow
- Token caching statistics tracking

#### Commands System
- Split `commands.py` into 6 modules:
  - `commands_files.py`
  - `commands_modes.py`
  - `commands_tools.py`
  - `commands_workflow.py`
  - `commands_collaboration.py`
  - `commands_misc.py`

#### Model Support
- **OpenClaw integration** - Gateway for external models
- **Model routing** with tier aliases (@speed, @intel, @uncen)
- **OpenRouter** integration

### 5. Documentation

| Document | Purpose |
|----------|---------|
| `AGENTS.md` | Comprehensive architecture documentation (1000+ lines) |
| `OPENCLAW_INTEGRATION.md` | OpenClaw gateway docs |
| `TOOL_SYSTEM_V2_SUMMARY.md` | Tool system architecture |
| `HOOKS_README.md` | Hooks system usage |
| `SKILLS.md` | Skills system docs |
| `EXTENSIONS_SUMMARY.md` | All extensions overview |
| `OPENCLAW_ARCHITECTURE_COMPLETE.md` | Full architecture diagram |

---

## Feature Comparison Matrix

| Feature | Upstream | This Fork |
|---------|----------|-----------|
| **Core Editing** | ✅ | ✅ |
| **Multiple Edit Formats** | ✅ | ✅ |
| **Git Integration** | ✅ | ✅ |
| **Repo Map** | ✅ | ✅ |
| **Sub-Agents** | ❌ | ✅ |
| **A2A Protocol** | ❌ | ✅ |
| **Skills System** | ❌ | ✅ |
| **Hooks System** | ❌ | ✅ (20 hook points) |
| **Tool System v2** | ❌ | ✅ (Production-ready) |
| **Autonomous Workflow** | ❌ | ✅ (`/auto`) |
| **Swarm Execution** | ❌ | ✅ (`/swarm`) |
| **Circuit Breaker** | ❌ | ✅ |
| **Multi-Layer Sandbox** | ❌ | ✅ (firejail/unshare) |
| **Accurate Cost Tracking** | ❌ | ✅ (40-60% overhead) |
| **Live Dashboard** | ❌ | ✅ (`--dashboard`) |
| **MCP Server** | ❌ | ✅ |
| **ACP Mode** | ❌ | ✅ (`--acp`) |
| **OpenClaw Gateway** | ❌ | ✅ |
| **Token Caching Stats** | ❌ | ✅ (`/cache`) |
| **Security Policy Engine** | ❌ | ✅ |
| **Audit Logging** | ❌ | ✅ |

---

## Version Information

| | Upstream | This Fork |
|--|----------|-----------|
| **Version** | ~0.70.x | 2.1.0 (Parity+) |
| **Codename** | aider-chat | Modularized Architecture |
| **Architecture** | Monolithic | Bootstrap + Modularized |

---

## Summary

This fork has transformed Aider from a **single-agent pair programming tool** into a **Multi-Agent Autonomous Ecosystem** with:

1. **44 additional commits** with 193 new files
2. **Complete architecture overhaul** (bootstrap + modularized)
3. **10 new subsystems** (agents, skills, hooks, A2A, tools v2, etc.)
4. **Production-ready tooling** (circuit breaker, sandbox, cost tracking)
5. **Advanced autonomous capabilities** (`/auto`, `/swarm`)

**Essentially**: This fork implements the full OpenClaw workflow specification while maintaining compatibility with upstream's core editing functionality.

---

*Report generated: 2026-03-20*
