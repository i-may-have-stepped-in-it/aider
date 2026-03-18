---
parent: Connecting to LLMs
nav_order: 50
title: OpenClaw Gateway
---

# OpenClaw Gateway

OpenClaw Gateway is a self-hosted AI agent gateway that provides access to multiple LLMs through a single endpoint. Aider has built-in integration with OpenClaw for seamless code editing.

## Why OpenClaw?

- **No per-token costs** - Self-hosted, no API usage fees
- **Multiple LLMs** - Access various models through one gateway
- **Tier routing** - Route requests to different model tiers (@highspeed, @intelligence, @uncensored)
- **Session continuity** - Maintain context across conversations

## Quick Start

### 1. Install and Start OpenClaw Gateway

Follow the [OpenClaw documentation](https://docs.openclaw.ai) to install and start the gateway:

```bash
# Gateway will be available at http://127.0.0.1:18789
openclaw gateway start
```

### 2. Configure Aider

```bash
# Mac/Linux:
export OPENAI_API_BASE=http://127.0.0.1:18789/v1
export OPENAI_API_KEY=<your-openclaw-token>

# Windows:
setx OPENAI_API_BASE http://127.0.0.1:18789/v1
setx OPENAI_API_KEY <your-openclaw-token>
# ... restart shell after setx commands
```

### 3. Use Aider with OpenClaw

```bash
# Change directory into your codebase
cd /to/your/project

# Use the openclaw model alias (recommended)
aider --model openclaw

# Or specify a specific agent
aider --model openclaw:chat
aider --model openclaw:kimi
```

## Configuration Modes

Aider supports multiple OpenClaw connection modes:

| Mode | Environment Variable | Description |
|------|---------------------|-------------|
| `auto` | `AIDER_OPENCLAW_MODE=auto` | Auto-detect best method (default) |
| `http` | `AIDER_OPENCLAW_MODE=http` | Use OpenAI-compatible HTTP API |
| `responses` | `AIDER_OPENCLAW_MODE=responses` | Use OpenResponses API |
| `disabled` | `AIDER_OPENCLAW_MODE=disabled` | Disable OpenClaw integration |

## Agent Selection

OpenClaw uses different agents for different tasks:

- `chat` - General coding assistant (recommended, avoids bootstrap messages)
- `kimi` - Optimized for code understanding
- `main` - Default agent (may show welcome messages)

```bash
# Use specific agent
aider --model openclaw:chat

# Or via environment variable
export AIDER_OPENCLAW_AGENT_ID=chat
aider --model openai/chat
```

## Session Continuity

To maintain conversation context across aider sessions:

```bash
export AIDER_OPENCLAW_SESSION_KEY="my-project-session"
aider --model openclaw
```

## Tier Routing

If your OpenClaw has tier routing configured:

```bash
# In your first message, include tier hint:
@highspeed Explain this code

# Or set via environment:
export TIER_OVERRIDE=highspeed
```

## Troubleshooting

### "I just came online" Message

You're using the `main` agent instead of `chat`. Use:
```bash
aider --model openclaw:chat
```

### Connection Refused

OpenClaw Gateway is not running:
```bash
openclaw gateway start
```

### 401 Unauthorized

Invalid API key. Check that `OPENAI_API_KEY` matches your OpenClaw token.

### Model Not Found

Use the explicit format:
```bash
aider --model openai/chat --openai-api-base http://127.0.0.1:18789/v1
```

## Advanced Configuration

Create `.aider.model.settings.yml`:

```yaml
- name: my-openclaw
  extra_params:
    api_base: http://127.0.0.1:18789/v1
    extra_headers:
      X-OpenClaw-Agent-Id: chat
  streaming: true
```

Then use:
```bash
aider --model my-openclaw
```

## See Also

- [OpenClaw Documentation](https://docs.openclaw.ai)
- [Model Warnings](warnings.html) - Information about model warnings
- [OpenAI Compatible APIs](openai-compat.html) - Generic OpenAI-compatible configuration
