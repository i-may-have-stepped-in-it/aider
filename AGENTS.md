# Aider - AI Pair Programming in Your Terminal

> **Last Updated**: 2026-03-17  
> **Version**: 1.0.0-parity-plus
  
> **Python Support**: 3.10, 3.11, 3.12, 3.13, 3.14

## Project Overview

**Aider** is an open-source AI pair programming tool that runs in your terminal. It allows developers to collaborate with Large Language Models (LLMs) to write, edit, and maintain code. Aider integrates with Git, supports multiple LLM providers, and can work with 100+ programming languages.

- **Repository**: https://github.com/Aider-AI/aider
- **Package Name**: `aider-chat` (PyPI)
- **License**: Apache Software License
- **Python Support**: 3.10, 3.11, 3.12, 3.13, 3.14

## Architecture

### Core Components

```
aider/
├── main.py              # Application entry point and initialization
├── args.py              # Command-line argument parsing (configargparse)
├── commands.py          # Interactive command handling (/add, /drop, etc.)
├── coders/              # LLM interaction and code editing strategies
├── agents/              # Multi-agent system for parallel task execution
├── skills/              # Reusable capabilities (code review, test generation, etc.)
├── hooks/               # Extension hooks implementations
├── hooks.py             # Basic hooks system (legacy)
├── hooks_manager.py     # Advanced hooks with OpenClaw integration
├── tools/               # Tool execution system (v1)
├── tools_v2/            # Enhanced tool execution system (v2)
├── a2a/                 # Agent-to-Agent (A2A) protocol
├── mcp/                 # Model Context Protocol server
├── editor_protocol/     # Editor/IDE integration protocol
├── indexers/            # Code indexing and retrieval (semantic)
├── resources/           # Resource management
├── repo.py              # Git repository integration
├── repomap.py           # Repository mapping for context
├── io.py                # Input/Output handling
├── models.py            # LLM model configuration and settings
├── linter.py            # Code linting integration
├── analytics.py         # Usage analytics
├── onboarding.py        # First-run onboarding flow
└── website/             # Documentation website (Jekyll)
```

### Coder Classes (Edit Formats)

Aider supports multiple edit formats through the `coders/` module:

- **EditBlockCoder** - Default format using search/replace blocks
- **WholeFileCoder** - Replace entire file contents
- **UnifiedDiffCoder** - Unified diff format
- **PatchCoder** - Patch file format
- **ArchitectCoder** - Architect mode for planning
- **ToolEnabledCoder/ToolEnabledCoderV2** - Tool use via function calling
- **AskCoder** - Read-only Q&A mode
- **HelpCoder** - Built-in help system

Each coder has an associated prompts file (e.g., `editblock_prompts.py`).

### Multi-Agent System (`agents/`)

The agents module enables parallel task execution with sub-agents:

- **agent.py** - Base agent definitions (`SubAgent`, `AgentStatus`, `AgentResult`)
- **cli_agent.py** - CLI-based agent runner
- **executor.py** - Agent execution engine
- **registry.py** - Agent registration with circuit breaker and A2A bus integration
- **loop.py** - Agent coordination loop (`AutonomousAgent`)
- **gateway.py** - Gateway for agent communication
- **commands.py** - `/agent` CLI commands
- **integration.py** - Integration with main coder

Key features:
- Async agent spawning and management
- Circuit breaker pattern for fault tolerance
- A2A (Agent-to-Agent) message bus integration
- Concurrent execution with semaphore control
- Agent lifecycle management (PENDING → RUNNING → COMPLETED/ERROR)

### Skills System (`skills/`)

Skills are reusable, composable capabilities:

- **base.py** - Skill base classes (Skill, SkillContext, SkillResult)
- **agent_skill.py** - Agent-enabled skills with parallel execution
- **registry.py** - Skill discovery and registration
- **command.py** - `/skill` CLI command integration
- **code_review.py** - Code review skill
- **test_generation.py** - Test generation skill
- **refactoring.py** - Refactoring skill
- **documentation.py** - Documentation generation skill

### Hooks System

Aider has two layers of hooks for extending functionality:

#### Basic Hooks (`aider/hooks.py`)

Simple callback-based hook system:

- **pre_command/post_command** - Command execution hooks
- **pre_send/post_send** - LLM message hooks
- **pre_edit/post_edit** - File edit hooks
- **pre_summarize/post_summarize** - Chat summarization hooks
- **on_init/on_exit** - Lifecycle hooks

Usage:
```python
from aider.hooks import create_hooks_manager

hooks = create_hooks_manager(io=io, verbose=True)
hooks.register("pre_command", my_callback)
```

#### Advanced Hooks (`aider/hooks_manager.py`)

OpenClaw-integrated hooks with type safety and configuration:

- **HookPoint** enum for type-safe hook registration
- **HookConfig** for priority, timeout, retry logic
- **Skill integration** - Auto-register hooks from skills
- **Execution history** tracking

Key components:
- `HookPoint` - Enum of lifecycle points (PRE_COMMIT, POST_EDIT, etc.)
- `HookConfig` - Configuration (priority, async, timeout, retries)
- `HooksManager` - Registration, execution, and history

Usage:
```python
from aider.hooks_manager import HooksManager, HookPoint, HookConfig

manager = HooksManager()
manager.register_hook(
    name="my-hook",
    hook_point=HookPoint.PRE_EDIT,
    callback=my_function,
    config=HookConfig(priority=100)
)
```

#### Hook Implementations (`aider/hooks/`)

- **cli_agent_hook.py** - CLI agent lifecycle hooks
- **gateway_tier_hook.py** - Gateway tier management hooks

See `HOOKS_README.md` and `HOOKS_QUICKSTART.md` for detailed usage.

### A2A (Agent-to-Agent) Protocol (`a2a/`)

The A2A protocol enables agent-to-agent communication for collaborative task execution:

- **types.py** - Message types (`A2AMessage`, `A2AMessageType`, `A2AContentType`, `A2ACapability`)
- **bus.py** - Message bus for agent communication (`A2AMessageBus`)
- **agent.py** - A2A-enabled agent mixin (`A2AEnabledAgent`)
- **commands.py** - `/a2a` CLI commands (`A2ACommands`)

Features:
- Async message passing between agents
- Capability advertisement and discovery
- Request/response patterns
- Content type negotiation

### MCP (Model Context Protocol) Server (`mcp/`)

Exposes Aider as an MCP server for integration with external tools and IDEs:

- **server.py** - `AiderMCPServer` class

Features:
- JSON-RPC interface over stdio
- Tool exposure to external clients
- Resource management
- Compatible with MCP clients (Claude Desktop, etc.)

### Tools System (v1 and v2)

#### Tools v1 (`tools/`)

Original tool execution system:

- **router.py** - Tool routing and execution
- **sandbox.py** - Basic sandboxed execution
- **schema.py** - Tool schema definitions
- **cost.py** - Cost tracking
- **risk.py** - Risk assessment for operations
- **truncate.py** - Output truncation

#### Tools v2 (`tools_v2/`) - Production Architecture

Complete architectural rewrite addressing resilience, security, and observability:

| Component | File | Purpose |
|-----------|------|---------|
| **AsyncExecutor** | `async_executor.py` | Fixed async/sync boundary (no nested event loops) |
| **Sandbox** | `sandbox.py` | Secure execution with firejail/unshare profiles |
| **CircuitBreaker** | `circuit_breaker.py` | Failure isolation (CLOSED/OPEN/HALF_OPEN states) |
| **AccurateCostTracker** | `cost_tracker.py` | Cost tracking with overhead accounting |
| **SmartCompressor** | `compression.py` | Semantic output compression |
| **ToolRouterV2** | `router.py` | Resilient tool routing with retries |
| **MCPManager** | `mcp_manager.py` | MCP client integration |
| **TerminalWatcher** | `terminal_watcher.py` | Terminal output monitoring |
| **WebSearch** | `search_web.py` | Web search capabilities |

Key improvements over v1:
- No nested `asyncio.run()` calls (singleton thread pool)
- Static sandbox profiles (no injection vulnerabilities)
- Accurate cost tracking (40-60% more accurate)
- Circuit breaker pattern for failing tools
- Semantic compression (not just truncation)
- Structured logging and metrics

See `TOOL_SYSTEM_V2_SUMMARY.md` for complete architecture details.

### Editor Protocol (`editor_protocol/`)

Protocol for editor/IDE integration:

- **agent.py** - Editor agent with session management

Features:
- Session state management
- Editor-agnostic communication
- Bidirectional message handling

### Semantic Indexing (`indexers/`)

Code indexing for semantic search and retrieval:

- **semantic.py** - Semantic code indexer

Features:
- Vector-based code embeddings
- Semantic similarity search
- Integration with repomap for context retrieval

## Technology Stack

### Core Dependencies

| Category | Key Libraries |
|----------|--------------|
| LLM API | `litellm`, `openai`, `tiktoken` |
| Git | `gitpython` |
| Web/HTTP | `aiohttp`, `httpx`, `requests`, `fastapi` |
| CLI | `prompt-toolkit`, `typer`, `rich` |
| Code Parsing | `tree-sitter`, `grep-ast` |
| Audio | `sounddevice`, `soundfile`, `pydub` |
| Data | `pydantic`, `pyyaml`, `jsonschema`, `orjson` |
| Testing | `pytest` |

### Build System

- **Build Backend**: `setuptools` with `setuptools_scm`
- **Version Management**: `setuptools_scm` (auto-generated in `aider/_version.py`)
- **Dependency Management**: `pip-tools` (via `scripts/pip-compile.sh`)

## Development Setup

### Installation

#### Using pip (Traditional)

```bash
# Clone repository
git clone https://github.com/Aider-AI/aider.git
cd aider

# Create virtual environment (outside repo recommended)
python3 -m venv ../aider_venv
source ../aider_venv/bin/activate  # Linux/Mac
# or: ../aider_venv\Scripts\activate  # Windows

# Install in editable mode
pip install -e .
pip install -r requirements.txt
pip install -r requirements/requirements-dev.txt

# Optional: Install pre-commit hooks
pre-commit install
```

#### Using uv (Modern Python Packaging) - Recommended

[uv](https://github.com/astral-sh/uv) is a fast Python package manager and resolver:

```bash
# Clone repository
git clone https://github.com/Aider-AI/aider.git
cd aider

# Create virtual environment
uv venv

# Install in editable mode
uv pip install -e .

# Or install with all dev dependencies
uv pip install -e ".[dev]"

# Run tests with uv
uv run pytest

# Run aider with uv
uv run aider --version
```

### Dependency Management

Dependencies are managed in `requirements.in` files and compiled to `.txt` files:

```bash
# Edit requirements/requirements.in for main dependencies
# Edit requirements/requirements-dev.in for dev dependencies

# Compile all requirements
./scripts/pip-compile.sh

# Upgrade specific package
./scripts/pip-compile.sh --upgrade-package <package-name>
```

Available requirement files:
- `requirements.txt` - Main dependencies (auto-generated)
- `requirements/requirements.in` - Main dependency definitions
- `requirements/requirements-dev.txt` - Development dependencies
- `requirements/requirements-help.txt` - Help system dependencies
- `requirements/requirements-browser.txt` - Browser automation dependencies
- `requirements/requirements-playwright.txt` - Playwright dependencies

## Build and Test Commands

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/basic/test_coder.py

# Run specific test case
pytest tests/basic/test_coder.py::TestCoder::test_specific_case

# Run with verbose output
pytest -v
```

Test directories:
- `tests/basic/` - Core functionality tests
- `tests/help/` - Help system tests
- `tests/browser/` - Browser automation tests
- `tests/scrape/` - Web scraping tests
- `tests/tools/` - Tool system integration tests
- `aider/tests/tools/` - Tool v1 unit tests
- `aider/tests/tools_v2/` - Tool v2 integration tests

Note: Tools v2 tests are comprehensive (~90 tests) and may take longer to run.

### Building Documentation

Documentation is built with Jekyll and hosted on GitHub Pages:

```bash
cd aider/website
bundle install
bundle exec jekyll build    # Build to _site/
bundle exec jekyll serve     # Preview locally
```

### Building Docker Image

```bash
# Build Docker image
docker build -t aider -f docker/Dockerfile .

# Available targets:
# - aider-full: Full image with all extras
# - aider: Standard image with playwright support
```

### Manual Pre-commit Checks

```bash
pre-commit run --all-files
```

## Code Style Guidelines

### Python Style

- **Style Guide**: PEP 8 with modifications
- **Line Length**: 100 characters maximum
- **Type Hints**: **NOT used** in this project
- **Import Sorting**: `isort` with black profile
- **Formatter**: `black` with `--line-length 100 --preview`

### Linting Rules

- **Flake8**: Configured in `.flake8`
  - Ignored: `E203` (whitespace before colon), `W503` (line break before binary operator)
  - Max line length: 100

### Pre-commit Hooks

Configured in `.pre-commit-config.yaml`:
1. `isort` - Import sorting
2. `black` - Code formatting
3. `flake8` - Linting
4. `codespell` - Spell checking

### Code Patterns

1. **No Type Hints** - Do not add type annotations
2. **Import Style** - Use absolute imports
3. **Error Handling** - Use try-except with specific exceptions
4. **Documentation** - Docstrings for public functions
5. **Naming** - snake_case for functions/variables, CamelCase for classes

## Testing Strategy

### Test Organization

```
tests/
├── basic/          # Core functionality
│   ├── test_coder.py
│   ├── test_repo.py
│   └── ...
├── help/           # Help system tests
├── browser/        # Browser automation tests
├── scrape/         # Web scraping tests
└── fixtures/       # Test data and fixtures
```

### Testing Configuration

Pytest configuration in `pytest.ini`:
- Ignored directories: `tmp.*`, `build`, `benchmark`, `_site`, `OLD`
- Warnings suppressed: `-p no:warnings`
- Environment: `AIDER_ANALYTICS=false`

### Writing Tests

- Test files follow `test_*.py` naming
- Use pytest fixtures for setup/teardown
- Mock external API calls
- Test both success and error cases

## CI/CD and Automation

### GitHub Actions Workflows

| Workflow | Description |
|----------|-------------|
| `ubuntu-tests.yml` | Run tests on Ubuntu (Python 3.10-3.14) |
| `windows-tests.yml` | Run tests on Windows |
| `docker-build-test.yml` | Build and test Docker image |
| `docker-release.yml` | Release Docker image to registry |
| `pre-commit.yml` | Run pre-commit checks |
| `pages.yml` | Build and deploy documentation |
| `check_pypi_version.yml` | Check PyPI version consistency |

### Release Process

1. Version bumping handled by `setuptools_scm`
2. Docker images published to DockerHub
3. PyPI package published via `release.yml`

## Security Considerations

### API Key Handling

- API keys passed via environment variables or `.env` files
- Keys are scrubbed from logs and analytics
- Support for `--set-env` to set environment variables securely

### Code Execution

- Sandboxed execution for user code (configurable)
- Linting and testing hooks to validate changes
- Git integration allows easy rollback of changes

### Hook Safety

- Hooks run in isolated try-except blocks
- Hook failures don't crash Aider
- Verbose mode available for debugging

## Project-Specific Conventions

### Version Management

```python
# In aider/__init__.py
__version__ = "1.0.0-parity-plus"
  # Base version
# Actual version auto-generated by setuptools_scm in aider/_version.py
```

### Configuration Files

Aider supports multiple configuration methods (in order of precedence):
1. Command-line arguments
2. Environment variables (`AIDER_*` prefix)
3. `.aider.conf.yml` (YAML config file)
4. `.env` file

### Model Settings

Model configurations are defined in `aider/models.py` using `ModelSettings` dataclass:
- Token limits
- Context window sizes
- Editor model specifications
- API provider settings

### Edit Formats

Edit formats define how code changes are represented:

```python
# Example from coders/editblock_coder.py
class EditBlockCoder(Coder):
    edit_format = "diff"
    gpt_prompts = editblock_prompts
```

To add a new edit format:
1. Create a new coder class inheriting from `Coder`
2. Define `edit_format` and `gpt_prompts`
3. Implement required methods
4. Add to `coders/__init__.py` `__all__` list

### Repository Map

Aider builds a repository map for context using:
- Tree-sitter for AST parsing
- Tag-based symbol identification
- Ranking algorithms for relevant context

Defined in `aider/repomap.py`.

## Common Development Tasks

### Adding a New Command

1. Add command method in `aider/commands.py`
2. Method name should start with `cmd_`
3. Use `self.io.tool_output()` for output
4. Add docstring for help text

Example:
```python
def cmd_mycommand(self, args):
    """Description shown in /help"""
    self.io.tool_output(f"Executing with args: {args}")
```

### Adding a New Skill

1. Create skill class in `aider/skills/`
2. Inherit from `Skill` or `AgentSkillMixin`
3. Register in `aider/skills/registry.py`
4. Add to `SKILLS.md` documentation

### Adding a New Hook Point

1. Define hook name in `aider/hooks.py`
2. Call `hooks_manager.execute()` at appropriate location
3. Document in `HOOKS_README.md`
4. Update `.aider-hooks.yml.example`

### Adding Model Support

1. Add model settings to `aider/models.py`
2. Define token limits and context window
3. Test with sample prompts
4. Document in website docs

## External Integrations

### OpenClaw Integration

Aider integrates with OpenClaw for skill discovery:
- Skills discovered from `OPENCLAW_SKILLS_PATH` env var
- Default paths: `/home/openclaw/openclaw/skills`, `~/.openclaw/skills`
- Commands: `/skill list`, `/skill run`, `/skill info`

### LiteLLM Integration

- All LLM calls go through LiteLLM
- Supports 100+ LLM providers
- Configurable via environment variables

### Git Integration

- Uses `gitpython` for repository operations
- Auto-commits with sensible messages (configurable)
- Diff viewing and undo support

## Resources

- **Documentation**: https://aider.chat/docs/
- **Issue Tracker**: https://github.com/Aider-AI/aider/issues
- **Discord Community**: https://discord.gg/Y7X7bhMQFV
- **Benchmark Results**: https://aider.chat/docs/leaderboards/

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface                            │
│  CLI (prompt-toolkit) / GUI (streamlit) / MCP / Editor Protocol │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Command Processing                           │
│                    (aider/commands.py)                           │
│         /add, /drop, /commit, /test, /skill, /agent, etc.       │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
    │   Coder     │  │   Hooks     │  │   Agents    │
    │  (coders/)  │  │  (hooks/)   │  │  (agents/)  │
    └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
           │                │                │
           ▼                ▼                ▼
    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
    │     LLM     │  │   Skills    │  │    A2A      │
    │  (litellm)  │  │  (skills/)  │  │   (a2a/)    │
    └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
           │                │                │
           └────────┬───────┴────────┬───────┘
                    ▼                ▼
           ┌─────────────┐  ┌─────────────┐
           │ Tools v1/v2 │  │   Sandbox   │
           │ (tools/)    │  │ (sandbox)   │
           └─────────────┘  └─────────────┘
                    │
                    ▼
           ┌─────────────┐
           │ Git Repo    │
           │ (repo.py)   │
           └─────────────┘
```

## Related Documentation

| File | Purpose | Audience |
|------|---------|----------|
| `CONTRIBUTING.md` | Contribution guidelines | Contributors |
| `HOOKS_README.md` | Hooks system usage guide | Users, Developers |
| `HOOKS_QUICKSTART.md` | Quick start for hooks | Users |
| `SKILLS.md` | Skills system documentation | Users, Developers |
| `OPENCLAW_HOOKS_DESIGN.md` | OpenClaw integration design | Developers |
| `TOOL_SYSTEM_V2_SUMMARY.md` | Tools v2 architecture | Developers |
| `TOOL_SYSTEM_SUMMARY.md` | Tools v1 overview | Developers |
| `AGENTS_INTEGRATION.md` | Agent integration patterns | Developers |
| `INTEGRATION_SUMMARY.md` | General integration patterns | Developers |
| `COMPLETION_SUMMARY.md` | Completion system details | Developers |
| `.aider-hooks.yml.example` | Example hooks configuration | Users |
| `workflow.txt` | Development workflow phases | Core Developers |

## Important Files for Contributors

| File | Purpose |
|------|---------|
| `CONTRIBUTING.md` | Contribution guidelines |
| `HOOKS_README.md` | Hooks system documentation |
| `SKILLS.md` | Skills system documentation |
| `OPENCLAW_HOOKS_DESIGN.md` | OpenClaw integration design |
| `TOOL_SYSTEM_V2_SUMMARY.md` | Tool system v2 documentation |
| `INTEGRATION_SUMMARY.md` | Integration patterns |
| `.aider-hooks.yml.example` | Example hooks configuration |
| `workflow.txt` | Development workflow phases |
