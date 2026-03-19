# GEMINI.md - Aider (Security Hardened + Autonomous Agent Parity)

This document provides essential context and instructions for AI agents working in this repository. **Always prioritize these guidelines during research, implementation, and validation.**

## 🚀 Project Overview
**OpenClaw Aider (v2.0.10)** is a security-hardened, high-autonomy fork of the original Aider AI pair programming tool. It has been re-engineered for production stability and complex agentic workflows.

### Key Architectural Pillars:
- **Autonomous Architect Workflow:** A four-phase cycle: **Librarian** (Discovery) → **Architect** (Planning) → **Reviewer** (Critique) → **Editor** (Execution).
- **Multi-Agent Infrastructure:** Support for sub-agents (`/agent`), swarms (`/swarm`), and the **A2A (Agent-to-Agent) Protocol** for asynchronous collaboration.
- **Security Hardening:** Mandatory use of `shlex.split()` for command parsing (no `shell=True`) and isolated execution via the `tools_v2/sandbox.py` (supporting `firejail` and `unshare`).
- **OpenClaw Integration:** Direct integration with OpenClaw Gateway for model routing, session continuity, and tier-based performance selection (`@intelligence`, `@highspeed`).

---

## 🛠️ Development Operations

### Environment Setup
- **Python Version:** `>=3.10, <3.15`
- **Installation:** `pip install -e .` (installs `aider` and `openclaw-aider` commands).
- **Dev Dependencies:** `pip install -e .[dev]`

### Building and Running
- **Entry Point:** `aider.main:main` (CLI) or `aider/__main__.py`.
- **Primary Command:** `aider --model <model_name>`
- **OpenClaw Specific:** `aider --model openclaw:chat`

### Testing & Validation
- **Test Runner:** `pytest`
- **Config:** `pytest.ini`
- **Key Test Suites:**
  - `tests/basic/`: Core functional tests.
  - `tests/help/`: Help system verification.
  - `tests/test_openclaw_model.py`: OpenClaw integration tests.
  - `test_integration.py`, `test_skills.py`, `test_agents.py`: New agentic infrastructure tests.

---

## 📜 Development Conventions

### Coding Style & Linting
- **Formatter:** `black` (Line length: 100).
- **Import Sorting:** `isort` (Black profile).
- **Linter:** `flake8`.
- **Pre-commit:** Enforced via `.pre-commit-config.yaml`. Run `pre-commit run --all-files` before pushing.

### Security Standards (CRITICAL)
- **Shell Commands:** NEVER use `shell=True` in `subprocess` or `asyncio`. Use `shlex.split(command)` and pass arguments as a list.
- **Sandboxing:** Destructive or untrusted tools MUST run through `ToolEnabledCoderV2` with sandboxing enabled.
- **Path Validation:** All file operations must be validated against the project root to prevent path traversal.

### Agentic Patterns
- **Sub-Agents:** Use the `/agent spawn` command for parallelizable tasks (e.g., reviewing multiple files).
- **Skills System:** New features should be implemented as "Skills" in `aider/skills/` to maintain modularity.
- **Circuit Breakers:** Long-running or recursive processes must implement the `CircuitBreakers` from `aider/tools_v2/circuit_breaker.py` to prevent runaway API costs.

---

## 📂 Key Directory Map
- `aider/`: Core application logic.
- `aider/agents/`: Multi-agent coordination and execution.
- `aider/skills/`: Domain-specific task implementations (Review, Tests, Refactor).
- `aider/tools_v2/`: Production-grade tool implementations (Sandbox, Router, Cost Tracking).
- `aider/openclaw_model.py`: Custom model adapter for OpenClaw Gateway.
- `tests/`: Comprehensive test suite divided by subsystem.

---

## 📍 TODOs & Future Roadmap
- [ ] Expand MCP (Model Context Protocol) integration in `aider/tools_v2/mcp_manager.py`.
- [ ] Implement advanced result aggregation in `aider/skills/acp_delegation.py`.
- [ ] Optimize semantic compression in `aider/tools_v2/compression.py` for long-context models.
