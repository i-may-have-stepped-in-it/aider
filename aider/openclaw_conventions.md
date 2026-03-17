# OpenClaw Conventions for Aider

This document describes how OpenClaw skills integrate with Aider and provides
usage examples for the `/skill` command.

## Overview

[OpenClaw](https://github.com/openclaw-org/openclaw) is a skill ecosystem that
provides composable capabilities for AI agents. Aider integrates with OpenClaw
through the `/skill` command, allowing you to:

- **Discover** available skills for your workflow
- **Execute** skill scripts directly from Aider
- **Validate** skill configurations
- **Search** for skills by capability

## Quick Start

### Listing Available Skills

```
/skill list
```

Shows all discovered OpenClaw skills with their descriptions.

```
/skill list --verbose
```

Shows detailed information including requirements and install options.

### Running a Skill

```
/skill run <skill-name> [action] [args...]
```

Examples:

```
# Run the default action of a skill
/skill run github

# Run a specific action
/skill run github pr-list

# Pass arguments to the skill
/skill run gh-issues list --state open --limit 10
```

### Getting Skill Information

```
/skill info <skill-name>
```

Shows detailed metadata about a skill:
- Description and purpose
- Required binaries
- Installation options
- Available scripts

Example:

```
/skill info kimi
```

Output:
```
🌙 kimi
==================================================

Description:
  Kimi Code CLI for interactive coding help, shell-assisted repo work, 
  and ACP editor integration.

Homepage:
  https://github.com/MoonshotAI/kimi-cli

Requirements:
  [✓] kimi

Installation Options:
  • Install Kimi CLI (uv tool install kimi-cli) (pipx)
```

### Searching for Skills

```
/skill search <query>
```

Finds skills matching your search terms in their name or description.

Example:

```
/skill search git
```

### Validating Skills

```
/skill validate          # Validate all skills
/skill validate <name>   # Validate specific skill
```

Checks that a skill's configuration is valid and requirements are met.

## Skill Structure

OpenClaw skills follow a standard structure:

```
skill-name/
├── SKILL.md              # Skill metadata and documentation
├── scripts/              # Executable scripts (optional)
│   ├── skill-name.py
│   ├── action.sh
│   └── ...
└── references/           # Reference documentation (optional)
    └── ...
```

### SKILL.md Format

Skills define their metadata in YAML frontmatter:

```yaml
---
name: skill-name
description: What this skill does
homepage: https://github.com/org/repo
metadata:
  openclaw:
    emoji: 🛠️
    requires:
      bins: [binary1, binary2]
    install:
      - id: method1
        kind: brew
        package: package-name
        label: Install via Homebrew
---

# Skill Documentation

## When to use
...

## Quick start
...
```

## Common Skills

### Development Tools

| Skill | Description | Usage Example |
|-------|-------------|---------------|
| `github` | GitHub CLI operations | `/skill run github pr-list` |
| `kimi` | Kimi Code CLI | `/skill run kimi` |
| `codex` | OpenAI Codex CLI | `/skill run codex` |
| `claude` | Claude Code CLI | `/skill run claude` |
| `tmux` | Tmux session management | `/skill run tmux find-sessions` |

### AI/Image Generation

| Skill | Description | Usage Example |
|-------|-------------|---------------|
| `openai-image-gen` | Generate images with DALL-E | `/skill run openai-image-gen` |
| `nano-banana-pro` | Generate images with Gemini | `/skill run nano-banana-pro` |
| `comfyui` | ComfyUI workflow execution | `/skill run comfyui status` |

### Productivity

| Skill | Description | Usage Example |
|-------|-------------|---------------|
| `obsidian` | Obsidian vault operations | `/skill info obsidian` |
| `notion` | Notion API integration | `/skill info notion` |
| `things-mac` | Things 3 task management | `/skill info things-mac` |

### Communication

| Skill | Description | Usage Example |
|-------|-------------|---------------|
| `slack` | Slack messaging | `/skill info slack` |
| `discord` | Discord operations | `/skill info discord` |
| `imsg` | iMessage sending | `/skill info imsg` |

## Integration with Aider Workflows

### Pre-commit Hooks

Skills can be configured to run before Aider commits changes:

```python
# In .aider.conf.yml or similar
openclaw:
  hooks:
    pre-commit:
      - skill: skill-validator
        action: check
```

### Model-Specific Skills

Some skills work better with specific models:

- **Image generation**: Use with GPT-4 Vision or Claude 3 for better results
- **Code analysis**: Pair with architect mode for complex tasks
- **Git operations**: Compatible with all models

### Combining Skills

Chain multiple skills together in your workflow:

```
# 1. Generate an image
/skill run nano-banana-pro generate "A robot coding"

# 2. Upload to Discord
/skill run discord-upload ./generated/robot-coding.png

# 3. Create GitHub issue with the image
/skill run github issue-create --title "New mascot" --body "See attached"
```

## Configuration

### Custom Skills Path

Set the `OPENCLAW_SKILLS_PATH` environment variable to add custom skill directories:

```bash
export OPENCLAW_SKILLS_PATH="/path/to/custom/skills:/another/path"
aider
```

### Skill Discovery

Aider searches for skills in these locations (in order):

1. Paths in `OPENCLAW_SKILLS_PATH` environment variable
2. `/home/openclaw/openclaw/skills`
3. `~/.openclaw/skills`

### Disabling Skills

To temporarily disable OpenClaw integration:

```
# Set environment variable before starting Aider
export AIDER_OPENCLAW_ENABLED=false
```

## Troubleshooting

### Skill Not Found

If a skill isn't discovered:

1. Check the skill path exists: `/skill validate <name>`
2. Verify SKILL.md is present in the skill directory
3. Check that scripts are executable: `chmod +x scripts/*`

### Execution Failures

If a skill fails to execute:

1. Check requirements: `/skill info <name>`
2. Run with verbose output: `/skill run <name> --verbose`
3. Check that required binaries are installed
4. Review skill documentation: `/skill info <name>`

### Permission Errors

Skills must have executable scripts:

```bash
# In the skill directory
chmod +x scripts/*.py scripts/*.sh
```

## Best Practices

1. **Validate before use**: Run `/skill validate <name>` on new skills
2. **Check info first**: Use `/skill info` to understand requirements
3. **Use specific actions**: Prefer explicit actions over defaults
4. **Review output**: Skills may produce structured output - check stdout
5. **Combine thoughtfully**: Chain skills for complex workflows

## Contributing Skills

To create a new OpenClaw skill:

1. Create a new directory in your skills path
2. Add a `SKILL.md` with proper frontmatter
3. Add executable scripts to `scripts/`
4. Test with `/skill validate <name>`
5. Use `/skill run <name>` to verify functionality

See the [OpenClaw skill documentation](https://github.com/openclaw-org/openclaw) for
full skill development guidelines.

## See Also

- `/skill list` - Discover available skills
- `/skill info <name>` - Learn about a specific skill
- [OpenClaw Repository](https://github.com/openclaw-org/openclaw)
- [Aider Documentation](https://aider.chat/docs/)
