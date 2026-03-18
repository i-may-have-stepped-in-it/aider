# OpenClaw Gateway Integration for Aider

This document describes the integrated OpenClaw Gateway support in Aider, which provides direct connectivity to OpenClaw agents without requiring manual HTTP API configuration.

## Overview

Aider now has built-in support for OpenClaw Gateway, a self-hosted AI agent gateway. This integration:

- Automatically detects OpenClaw endpoints
- Supports both OpenResponses API (preferred) and OpenAI-compatible HTTP API
- Handles agent selection to avoid bootstrap/welcome messages
- Provides configurable session continuity
- Falls back gracefully to standard litellm if OpenClaw is unavailable

## Quick Start

### 1. Configure Environment Variables

```bash
# Required - point to your OpenClaw Gateway
export OPENAI_API_BASE=http://127.0.0.1:18789/v1
export OPENAI_API_KEY=<your-openclaw-token>

# Optional - control OpenClaw behavior
export AIDER_OPENCLAW_MODE=auto        # responses|http|auto|disabled
export AIDER_OPENCLAW_AGENT_ID=chat    # which agent to use
export AIDER_OPENCLAW_SESSION_KEY=     # for session continuity
```

### 2. Use OpenClaw Model

```bash
# Option 1: Use openclaw alias (uses 'chat' agent by default)
aider --model openclaw

# Option 2: Explicitly specify agent via model name
aider --model openclaw:chat

# Option 3: Use HTTP API with litellm (no special handling)
aider --model openai/gpt-4o --openai-api-base http://127.0.0.1:18789/v1
```

## Configuration Modes

### Mode: `auto` (Default)

Automatically detects OpenClaw endpoints and uses the best available method:

1. If endpoint contains `127.0.0.1:18789`, `localhost:18789`, or `openclaw` → use OpenClawModel
2. Attempt OpenResponses API first
3. Fall back to HTTP API with headers if Responses API fails

```bash
export AIDER_OPENCLAW_MODE=auto
export OPENAI_API_BASE=http://127.0.0.1:18789/v1
aider --model openclaw:chat
```

### Mode: `responses`

Force use of OpenResponses API (native OpenClaw protocol):

```bash
export AIDER_OPENCLAW_MODE=responses
aider --model openclaw:chat
```

**Pros:**
- Native OpenClaw protocol
- Better agent context handling
- Designed for agent-to-agent communication

**Cons:**
- Different response format than OpenAI
- May have different capabilities

### Mode: `http`

Force use of OpenAI-compatible HTTP API with custom headers:

```bash
export AIDER_OPENCLAW_MODE=http
export AIDER_OPENCLAW_AGENT_ID=chat
aider --model openai/chat
```

**Pros:**
- Standard OpenAI format
- Full litellm compatibility
- Streaming support

**Cons:**
- Header injection may not work with all litellm providers
- Less direct agent control

### Mode: `disabled`

Disable OpenClaw integration and use standard litellm:

```bash
export AIDER_OPENCLAW_MODE=disabled
aider --model openai/gpt-4o --openai-api-base http://127.0.0.1:18789/v1
```

## Agent Selection

### Using Model Name

The `openclaw:<agent_id>` syntax automatically selects the specified agent:

```bash
aider --model openclaw:chat      # Uses 'chat' agent (recommended)
aider --model openclaw:kimi      # Uses 'kimi' agent
aider --model openclaw:claude    # Uses 'claude' agent
```

### Using Environment Variable

```bash
export AIDER_OPENCLAW_AGENT_ID=chat
aider --model openai/chat
```

### Using Model Settings YAML

Create `.aider.model.settings.yml`:

```yaml
- name: my-openclaw-chat
  extra_params:
    api_base: http://127.0.0.1:18789/v1
    extra_headers:
      X-OpenClaw-Agent-Id: chat
  streaming: true
```

Then use:

```bash
aider --model my-openclaw-chat
```

## Session Continuity

To maintain conversation context across Aider sessions:

```bash
export AIDER_OPENCLAW_SESSION_KEY="aider-dev-session-$(date +%Y%m%d)"
aider --model openclaw:chat
```

The same session key will be used for all requests, allowing the OpenClaw agent to maintain context.

## Tier Routing with @pool/* Aliases

If you have the model-router extension configured, you can use tier aliases:

```bash
# Option 1: Include tier hint in first message
aider --model openclaw:chat
# Then in chat: "@highspeed explain this code"

# Option 2: Set tier via environment
export TIER_OVERRIDE=highspeed
aider --model openclaw:chat

# Option 3: Use model settings with prefix
```yaml
- name: openclaw-speed
  system_prompt_prefix: "@highspeed "
  extra_params:
    api_base: http://127.0.0.1:18789/v1
```

## Troubleshooting

### "I just came online" Message

If you see the OpenClaw welcome message, the wrong agent is being used:

**Problem:** Using `main` agent instead of `chat`  
**Solution:** Use `openclaw:chat` or set `AIDER_OPENCLAW_AGENT_ID=chat`

### Connection Refused

```
Error: Connection refused to 127.0.0.1:18789
```

**Problem:** OpenClaw Gateway not running  
**Solution:** Start the gateway: `openclaw gateway start`

### Authentication Failed

```
Error: 401 Unauthorized
```

**Problem:** Invalid API key  
**Solution:** Check `OPENAI_API_KEY` matches your OpenClaw token

### Model Not Found

```
Error: Unknown model 'openclaw:chat'
```

**Problem:** Model alias not recognized  
**Solution:** Use explicit model name with `--openai-api-base`

## Advanced Configuration

### Custom OpenClawModel Instance

For programmatic usage:

```python
from aider.openclaw_model import OpenClawModel, OpenClawConfig

config = OpenClawConfig(
    api_base="http://127.0.0.1:18789/v1",
    api_key="your-token",
    agent_id="chat",
    mode="responses",
    session_key="my-session",
)

model = OpenClawModel("openclaw:chat", config=config)
```

### Factory Function

```python
from aider.openclaw_model import create_model

# Auto-detects OpenClaw and creates appropriate model
model = create_model("openclaw:chat", use_openclaw=None)

# Force OpenClaw
model = create_model("openai/chat", use_openclaw=True)

# Force standard Model
model = create_model("openai/gpt-4o", use_openclaw=False)
```

## Migration Guide

### From HTTP API Only

**Before:**
```bash
export OPENAI_API_BASE=http://127.0.0.1:18789/v1
export OPENAI_API_KEY=<token>
aider --model openai/chat
```

**After:**
```bash
export OPENAI_API_BASE=http://127.0.0.1:18789/v1
export OPENAI_API_KEY=<token>
export AIDER_OPENCLAW_AGENT_ID=chat
aider --model openclaw:chat
```

### From Custom Scripts

**Before:**
```bash
curl -H "X-OpenClaw-Agent-Id: chat" ...
```

**After:**
```bash
export AIDER_OPENCLAW_AGENT_ID=chat
aider --model openclaw:chat
```

## Architecture

### Detection Flow

```
Aider startup
    ↓
Model name starts with "openclaw:"?
    ↓ YES
Use OpenClawModel with parsed agent_id
    ↓ NO
Is endpoint OpenClaw (127.0.0.1:18789)?
    ↓ YES
Check AIDER_OPENCLAW_MODE
    ↓ responses
Use OpenResponses API
    ↓ http
Use HTTP API with headers
    ↓ auto (default)
Try responses, fallback to http
    ↓ NO
Use standard litellm
```

### Request Flow (OpenResponses)

```
Aider → OpenClawModel.send_completion()
    ↓
POST /responses
    Headers: X-OpenClaw-Agent-Id: chat
    Body: {messages: [...]}
    ↓
OpenClaw Gateway
    ↓
Chat Agent (skipBootstrap: true)
    ↓
LLM Response
```

### Request Flow (HTTP API)

```
Aider → Model.send_completion()
    ↓
litellm.completion()
    Headers: X-OpenClaw-Agent-Id: chat
    Body: {model: "openai/chat", messages: [...]}
    ↓
OpenClaw Gateway
    ↓
Chat Agent (skipBootstrap: true)
    ↓
LLM Response (OpenAI format)
```

## References

- [OpenClaw Documentation](https://docs.openclaw.ai)
- [OpenClaw Gateway HTTP API](https://docs.openclaw.ai/gateway/openai-http-api)
- [OpenClaw OpenResponses API](https://docs.openclaw.ai/gateway/openresponses-http-api)
- [Aider Model Settings](https://aider.chat/docs/config/adv-model-settings.html)
