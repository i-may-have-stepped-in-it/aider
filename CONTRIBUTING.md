# Contributing to OpenClaw Aider

> **Notice:** This is a private, security-hardened, and high-autonomy fork of the original Aider project. These contribution guidelines supersede the upstream repository's standards, reflecting our focus on enterprise-grade reliability and autonomous agent capabilities.

We welcome contributions from internal developers that align with our architectural vision of building a semantically aware, highly observable, and secure AI agent framework.

---

## 🚀 Architectural Vision & Core Principles

OpenClaw Aider is designed to be a robust foundation for autonomous multi-agent workflows. All new contributions must adhere to the following core principles:

1. **Decoupled Architecture (Event-Driven):** Core logic must remain strictly separated from UI rendering and infrastructure concerns.
   - **NO Monkey-Patching.** 
   - All state changes (e.g., phase transitions, cost updates, tool progress) must be broadcast using the `HooksManager` (`aider/hooks_manager.py`).
   - UI components must implement the `TerminalUIObserver` interface (`aider/io_interfaces.py`) to consume these events.
2. **Autonomous Workflow:** The primary execution path is the `ArchitectCoder` lifecycle: **Librarian** (Discovery) → **Architect** (Planning) → **Security Scan** → **Reviewer** (Critique) → **Editor** (Execution). Features should integrate into this pipeline rather than circumventing it.
3. **Semantic Intelligence:** We are moving beyond regex. Leverage the `ProjectMemory` (Local RAG) and `LSPClient` where applicable for true contextual understanding.

---

## 🛠️ Enterprise Coding Standards

This fork enforces strict, modern Python development standards to ensure production stability.

### Python Compatibility
- Aider currently supports Python versions **3.10, 3.11, 3.12, 3.13, and 3.14**. 
- Leverage modern Python features (e.g., `asyncio`, `dataclasses`, structural pattern matching where appropriate).

### Code Style
- **Type Hints (PEP 484):** Type hints are **MANDATORY** for all new modules, classes, and complex function signatures. This is a deliberate reversal of the upstream policy to ensure enterprise reliability.
- **Formatter:** The project uses [Black](https://black.readthedocs.io/en/stable/) for formatting, with a maximum line length of **100 characters**.
- **Import Sorting:** [isort](https://pycqa.github.io/isort/) is used with the `black` profile.
- **Linter:** [flake8](https://flake8.pycqa.org/en/latest/).

### Pre-commit Hooks
You **must** install and use `pre-commit` to ensure your code is automatically formatted and linted before submission.
```bash
pip install pre-commit
pre-commit install
# To run manually:
pre-commit run --all-files
```

---

## 🔒 Strict Security Protocols (CRITICAL)

Security is our primary differentiator. Any PR that violates these rules will be immediately rejected.

1. **Subprocess Execution:**
   - **NEVER** use `shell=True` in `subprocess.run`, `subprocess.Popen`, or `asyncio.create_subprocess_exec`.
   - **ALWAYS** use `shlex.split(command)` to parse command strings into safe argument lists before execution.
2. **Path Handling:**
   - All file operations must validate paths against the project root to definitively prevent path traversal vulnerabilities.
3. **Automated Guardrails:**
   - If your feature introduces new AI-generated artifacts, it **must** be validated by the `PolicyEngine` (`aider/security/policy.py`) before execution.
4. **Sensitive Data:**
   - Never log, print, or expose API keys, session tokens, or other credentials in stack traces or UI outputs.

---

## 🧪 Testing, Validation & Audit

Rigorous validation is the only path to finality. Unverified changes are incomplete changes.

### Test Organization
- The primary test suite is located in the root `tests/` directory.
- Test files must follow the `test_*.py` naming convention.
- If you are adding new infrastructure or logic, you must include corresponding unit tests.

### Security Testing
- Features involving system state changes (I/O, network, process execution) must have explicit adversarial test cases added to `tests/test_security.py` or `tests/test_policy_engine.py` to prove they resist common attack vectors.

### Enterprise Audit & Traceability
- All significant autonomous actions (e.g., completing a plan, running a tool, finding a security violation) must be logged via the `AuditManager` (`aider/audit/manager.py`) to maintain a complete traceability matrix for compliance.

---

## 💻 Setting up a Development Environment

1. **Clone the Repository**
2. **Create a Virtual Environment** (Outside the repo directory is recommended):
   ```bash
   python3.14 -m venv ../aider_venv
   source ../aider_venv/bin/activate
   ```
3. **Install Editable & Dependencies:**
   ```bash
   pip install -e .
   pip install -r requirements.txt
   pip install -r requirements/requirements-dev.txt
   ```
4. **Install Pre-commit:**
   ```bash
   pre-commit install
   ```

### Managing Dependencies
Do not manually edit `requirements.txt`. Add new dependencies to `requirements/requirements.in` (or `requirements-dev.in`), then compile:
```bash
pip install pip-tools
./scripts/pip-compile.sh
```

---

By contributing to this repository, you agree to adhere to these enterprise standards and maintain the security and architectural integrity of the OpenClaw Aider framework.
