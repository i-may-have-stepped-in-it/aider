# Aider Documentation Index

Complete guide to all documentation files in this repository.

---

## 🚀 Getting Started

| Document | Purpose | Read If... |
|----------|---------|------------|
| [README.md](README.md) | Project overview, quick start | You're new to the project |
| [OPENCLAW_INTEGRATION.md](OPENCLAW_INTEGRATION.md) | OpenClaw Gateway setup | Using OpenClaw as your LLM backend |

---

## 🔒 Security & Architecture

| Document | Purpose | Read If... |
|----------|---------|------------|
| [AGENTS.md](AGENTS.md) | Complete architecture guide | You want to understand the codebase structure |
| [OPENCLAW_ARCHITECTURE_COMPLETE.md](OPENCLAW_ARCHITECTURE_COMPLETE.md) | OpenClaw architecture deep-dive | Integrating with OpenClaw Gateway |
| [OPENCLAW_IMPLEMENTATION_SUMMARY.md](OPENCLAW_IMPLEMENTATION_SUMMARY.md) | Implementation details | You want technical implementation details |

### Security Audit
The [AGENTS.md](AGENTS.md#security--code-quality-audit-2026-03-17) file contains a comprehensive security audit documenting:
- 12 critical vulnerabilities patched
- Thread-safety improvements
- Async safety fixes

---

## 🤖 Features

### Multi-Agent System
| Document | Purpose |
|----------|---------|
| [AGENTS.md](AGENTS.md#multi-agent-system-agents) | Agent architecture overview |
| [AGENTS_INTEGRATION.md](AGENTS_INTEGRATION.md) | Agent integration patterns |

### Skills System
| Document | Purpose |
|----------|---------|
| [SKILLS.md](SKILLS.md) | Skills usage and creation |

### Hooks System
| Document | Purpose |
|----------|---------|
| [HOOKS_README.md](HOOKS_README.md) | Hooks system overview |
| [HOOKS_QUICKSTART.md](HOOKS_QUICKSTART.md) | Quick start for hooks |
| [OPENCLAW_HOOKS_DESIGN.md](OPENCLAW_HOOKS_DESIGN.md) | OpenClaw hooks design |

### Tools System
| Document | Purpose |
|----------|---------|
| [TOOL_SYSTEM_V2_SUMMARY.md](TOOL_SYSTEM_V2_SUMMARY.md) | Tools v2 (production) architecture |
| [TOOL_SYSTEM_SUMMARY.md](TOOL_SYSTEM_SUMMARY.md) | Tools v1 overview (legacy) |

---

## 🔧 Integration

| Document | Purpose |
|----------|---------|
| [INTEGRATION_SUMMARY.md](INTEGRATION_SUMMARY.md) | General integration patterns |
| [COMPLETION_SUMMARY.md](COMPLETION_SUMMARY.md) | Completion system details |

---

## 🛠️ Development

| Document | Purpose |
|----------|---------|
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines |
| [HISTORY.md](HISTORY.md) | Changelog |

---

## 📖 Documentation by Task

### "I want to set up OpenClaw..."
1. [README.md](README.md#openclaw-gateway-recommended) - Quick setup
2. [OPENCLAW_INTEGRATION.md](OPENCLAW_INTEGRATION.md) - Detailed configuration
3. [OPENCLAW_IMPLEMENTATION_SUMMARY.md](OPENCLAW_IMPLEMENTATION_SUMMARY.md) - Advanced options

### "I want to understand the architecture..."
1. [AGENTS.md](AGENTS.md) - High-level architecture
2. [OPENCLAW_ARCHITECTURE_COMPLETE.md](OPENCLAW_ARCHITECTURE_COMPLETE.md) - OpenClaw specifics
3. [TOOL_SYSTEM_V2_SUMMARY.md](TOOL_SYSTEM_V2_SUMMARY.md) - Tools architecture

### "I want to use skills..."
1. [SKILLS.md](SKILLS.md) - Complete skills guide

### "I want to extend aider with hooks..."
1. [HOOKS_QUICKSTART.md](HOOKS_QUICKSTART.md) - Get started quickly
2. [HOOKS_README.md](HOOKS_README.md) - Full reference

### "I want to contribute..."
1. [CONTRIBUTING.md](CONTRIBUTING.md) - Guidelines
2. [AGENTS.md](AGENTS.md) - Architecture understanding

---

## 📝 Quick Reference

### Environment Variables

| Variable | Purpose | Documentation |
|----------|---------|---------------|
| `OPENAI_API_BASE` | LLM API endpoint | [OPENCLAW_INTEGRATION.md](OPENCLAW_INTEGRATION.md) |
| `OPENAI_API_KEY` | API authentication | [OPENCLAW_INTEGRATION.md](OPENCLAW_INTEGRATION.md) |
| `AIDER_OPENCLAW_MODE` | OpenClaw mode (auto/http/responses) | [OPENCLAW_INTEGRATION.md](OPENCLAW_INTEGRATION.md#configuration-modes) |
| `AIDER_OPENCLAW_AGENT_ID` | Default agent ID | [OPENCLAW_INTEGRATION.md](OPENCLAW_INTEGRATION.md#agent-selection) |
| `AIDER_ENABLE_AGENTS` | Enable sub-agents | [SKILLS.md](SKILLS.md#configuration) |

### Common Commands

```bash
# OpenClaw with chat agent
aider --model openclaw:chat

# Skills
/skill list
/skill run code-review -f file.py --agents

# Agents
/agent spawn "task description"
/agent list

# Autonomous mode
/auto "implement feature"
```

---

## 🔗 External Resources

- [Original Aider Docs](https://aider.chat/docs/)
- [OpenClaw Documentation](https://docs.openclaw.ai)
- [GitHub Repository](https://github.com/i-may-have-stepped-in-it/aider)

---

## 🆕 What's New in v2.1.0

### Bootstrap/Runtime Architecture
Clean initialization without monkeypatching:
- `bootstrap/` - Service initialization
- `session_runtime.py` - Shared services container
- `agents/service.py` - AgentService pattern
- No more Coder class monkeypatching!

### Modularized Architecture
- **Base Coder**: Split into 13 focused modules (`base_coder_*.py`)
- **Commands**: Split into 6 modules (`commands_*.py`)
- **Tool Router**: Split into 8 focused mixins (`router_*.py`)
- **Auto-Discovery**: 100+ skills discovered automatically

### New Infrastructure
- `audit/` - Audit logging
- `security/` - Security hardening
- `memory/` - Memory management
- `lsp/` - Language Server Protocol
- `openclaw_metadata.py` - OpenClaw model metadata resolution

---

*Last Updated: 2026-03-19*
