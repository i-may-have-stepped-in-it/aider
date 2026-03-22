<p align="center">
    <a href="https://github.com/i-may-have-stepped-in-it/aider"><img src="https://aider.chat/assets/logo.svg" alt="Aider Logo" width="300"></a>
</p>

<h1 align="center">
Aider (Security Hardened + Autonomous Agent Parity) v2.1.0
</h1>

> **Note**: This is a security-hardened fork of the original [Aider](https://github.com/Aider-AI/aider) project by [Paul Gauthier](https://github.com/paul-gauthier). This fork includes:
> - **Security fixes**: 12 critical vulnerabilities patched
> - **Autonomous Agent Mode**: Full parity with Claude Code/Codex via `/auto` command
> - **Multi-Agent Infrastructure**: Sub-agents, A2A protocol, skills system
> - **Modularized Architecture**: Clean bootstrap/runtime, no monkeypatching (v2.1.0)

<p align="center">
AI Pair Programming in Your Terminal — Now with Enterprise-Grade Security
</p>

<p align="center">
  <a href="https://github.com/i-may-have-stepped-in-it/aider/stargazers"><img alt="GitHub Stars" 
src="https://img.shields.io/github/stars/i-may-have-stepped-in-it/aider?style=flat-square&logo=github&color=f1c40f&labelColor=555555"/></a>
  <img alt="Security Status" src="https://img.shields.io/badge/Security-12%20CVEs%20Fixed-brightgreen?style=flat-square&labelColor=555555"/>
  <img alt="Tests" src="https://img.shields.io/badge/Tests-705%20passing-blue?style=flat-square&labelColor=555555"/>
</p>

## 🔒 Security Hardening

This fork addresses critical security vulnerabilities found in the original codebase:

| CVE Risk | Issue | Fix |
|----------|-------|-----|
| **Critical** | Shell injection in sandbox | `shlex.parse()` + `exec()` instead of `shell=True` |
| **Critical** | Code injection via `eval()` | AST-based parsing with whitelist |
| **Critical** | Path traversal in skill loading | Input validation + path resolution |
| **High** | Nested `asyncio.run()` crashes | Thread pool isolation pattern |
| **High** | Race conditions in CircuitBreaker | `threading.Lock()` added |

**Full security audit details**: See [AGENTS.md](AGENTS.md#security--code-quality-audit-2026-03-17)

## 🤖 Autonomous Agent Mode (`/auto`)

Full parity with Claude Code, Codex, and Gemini autonomous modes:

```bash
# Basic autonomous task
/auto "Add error handling to the auth module"

# With test verification (self-correcting)
/auto "Fix the login bug" --test "pytest tests/test_auth.py"

# Uses full Architect workflow:
# 1. Librarian phase - Auto-discovers relevant files
# 2. Architect phase - Plans with tool access
# 3. Security Scan phase - Checks for vulnerabilities
# 4. Reviewer phase - Self-critiques the plan
# 5. Editor phase - Executes with proper formatting
# 6. Self-correction - Retries on test failures
```

## 🏗️ Multi-Agent Architecture

This fork includes a complete multi-agent ecosystem:

### Sub-Agents (`/agent` commands)
```bash
/agent spawn "Review auth.py for security issues" --model claude-sonnet
/agent list                    # View all agents
/agent status <id>             # Check agent progress  
/agent result <id>             # Get final result
/agent cancel <id>             # Cancel running agent
```

### Agent Swarm (`/swarm`)
```bash
/swarm "Design the database schema" --agents "architect,developer,reviewer"
```

### A2A Protocol (Agent-to-Agent)
- Async message passing between agents
- Capability advertisement and discovery
- Request/response patterns

## ✨ All Original Aider Features

### [Cloud and local LLMs](https://aider.chat/docs/llms.html)
Aider works best with Claude 3.7 Sonnet, DeepSeek R1 & Chat V3, OpenAI o1, o3-mini & GPT-4o, but can connect to almost any LLM, including local models.

### [Maps your codebase](https://aider.chat/docs/repomap.html)
Aider makes a map of your entire codebase, which helps it work well in larger projects.

### [100+ code languages](https://aider.chat/docs/languages.html)
Aider works with most popular programming languages: python, javascript, rust, ruby, go, cpp, php, html, css, and dozens more.

### [Git integration](https://aider.chat/docs/git.html)
Aider automatically commits changes with sensible commit messages. Use familiar git tools to easily diff, manage and undo AI changes.

### [Use in your IDE](https://aider.chat/docs/usage/watch.html)
Use aider from within your favorite IDE or editor. Ask for changes by adding comments to your code and aider will get to work.

### [Images & web pages](https://aider.chat/docs/usage/images-urls.html)
Add images and web pages to the chat to provide visual context, screenshots, reference docs, etc.

### [Voice-to-code](https://aider.chat/docs/usage/voice.html)
Speak with aider about your code! Request new features, test cases or bug fixes using your voice and let aider implement the changes.

### [Linting & testing](https://aider.chat/docs/usage/lint-test.html)
Automatically lint and test your code every time aider makes changes. Aider can fix problems detected by your linters and test suites.

---

## 🎯 Quality of Life Improvements (v2.1.0)

This fork includes **67 QoL improvements** for a smoother developer experience:

### Quick Aliases
```bash
/a <file>        # Same as /add
/d <file>        # Same as /drop  
/c               # Same as /commit
/q or /x         # Same as /exit
/u               # Same as /undo
/gs              # Git status shorthand
/gd              # Git diff shorthand
/ctx             # Show context (files in chat)
```

### File Management
```bash
/save [file]     # Save session to JSON
/load <file>     # Restore session from JSON
/find <pattern>  # Search within chat files
/exclude <pat>   # Add pattern to .aiderignore
/rename <o> <n>  # Rename file with git mv
/pin <file>      # Pin file to top of context
/tail <f> [n]    # Show last n lines of file
/head <f> [n]    # Show first n lines of file
```

### Git Workflow
```bash
/undo            # Undo last commit with confirmation
/checkpoint      # Create git stash point
/recent [n]      # Show recently modified files
/untracked       # Show untracked files
/blame <file>    # Git blame with binary detection
/install-hook    # Install pre-commit hook for AI! comments
```

### Information & Insights
```bash
/cost            # Show session spending & budget
/stats           # Session statistics
/context         # Show current files (with pins marked)
/suggest         # Get command suggestions based on context
/map             # Show repo-map status
```

See [QOL_IMPROVEMENTS_REPORT.md](QOL_IMPROVEMENTS_REPORT.md) for the complete list of 67 improvements.

## 🚀 Getting Started

### Quick Install

```bash
# Install this fork
python -m pip install -e git+https://github.com/i-may-have-stepped-in-it/aider.git#egg=aider-chat

# Or clone and install locally
git clone https://github.com/i-may-have-stepped-in-it/aider.git
cd aider
python -m pip install -e .
```

### OpenClaw Gateway (Recommended)

Connect to your self-hosted OpenClaw Gateway:

```bash
# 1. Configure environment
export OPENAI_API_BASE=http://127.0.0.1:18789/v1
export OPENAI_API_KEY=<your-openclaw-token>

# 2. Use with OpenClaw (avoids bootstrap messages)
cd /to/your/project
aider --model openclaw

# Or specify agent explicitly
aider --model openclaw:chat
```

**Why OpenClaw?**
- No per-token API costs (self-hosted)
- Access to multiple LLMs through one endpoint
- Tier routing (@highspeed, @intelligence, @uncensored)
- Session continuity across conversations

[→ Full OpenClaw Setup Guide](OPENCLAW_INTEGRATION.md)

### Cloud LLMs

```bash
# Change directory into your codebase
cd /to/your/project

# DeepSeek
aider --model deepseek --api-key deepseek=<key>

# Claude 3.7 Sonnet
aider --model sonnet --api-key anthropic=<key>

# o3-mini
aider --model o3-mini --api-key openai=<key>
```

## 📚 Documentation

**Start Here**: [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) - Complete navigation guide

### Quick Reference
- [EXTENSIONS_SUMMARY.md](EXTENSIONS_SUMMARY.md) - All extensions vs original Aider
- [OPENCLAW_INTEGRATION.md](OPENCLAW_INTEGRATION.md) - OpenClaw Gateway setup
- [AGENTS.md](AGENTS.md) - Architecture & security audit
- [SKILLS.md](SKILLS.md) - Skills system
- [HOOKS_README.md](HOOKS_README.md) - Hooks system

### Original Aider Docs
- [Installation Guide](https://aider.chat/docs/install.html)
- [Usage Guide](https://aider.chat/docs/usage.html)
- [Tutorial Videos](https://aider.chat/docs/usage/tutorials.html)
- [Connecting to LLMs](https://aider.chat/docs/llms.html)
- [Configuration Options](https://aider.chat/docs/config.html)

## 🔄 Changes from Original Aider

### Security Fixes (20 files modified)
- **12 critical vulnerabilities** patched (shell injection, eval injection, path traversal)
- **Thread-safety** added to CircuitBreaker and MissionGovernor
- **Async safety** - All nested asyncio.run() calls fixed

### Architecture Improvements (v2.1.0)
- **Bootstrap/Runtime** - Clean initialization without monkeypatching
- **Modularized Base Coder** - Split into 13 focused modules
- **Modularized Commands** - Split into 6 focused modules  
- **Auto-Discovery** - 100+ skills discovered automatically
- **`/auto` command** - Full Architect workflow (Librarian → Architect → Security Scan → Reviewer → Editor)
- **New Infrastructure** - Audit, security, memory, LSP modules
- **Test fixes** - All tests passing
- **Documentation** - Comprehensive architecture docs in AGENTS.md

### Code Quality
- ~53,000 lines of Python across 206+ files
- 700+ tests across 55+ test files
- Modular architecture with clean separation
- 24 comprehensive documentation files
- All modules import successfully

## 🤝 Contributing

This fork maintains compatibility with the original Aider project. Security fixes are backported where applicable.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 📜 License

Apache Software License - same as original Aider project.

## 🙏 Credits

- Original [Aider](https://github.com/Aider-AI/aider) by [Paul Gauthier](https://github.com/paul-gauthier)
- "Parity+" agentic infrastructure inspired by Claude and Kimi
- Security audit and hardening by [i-may-have-stepped-in-it](https://github.com/i-may-have-stepped-in-it)

---

<p align="center">
  <sub>Built with ❤️ by the Aider community. Hardened for production.</sub>
</p>
