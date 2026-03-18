# OpenClaw Gateway Integration - Implementation Summary

> **Status**: Complete  
> **Date**: 2026-03-18  
> **Purpose**: Technical summary of what was implemented  
> **User Guide**: [OpenClaw Integration](OPENCLAW_INTEGRATION.md) | [Documentation Index](DOCUMENTATION_INDEX.md)

---

## What Was Implemented

### 1. Core Module: `aider/openclaw_model.py`

A new model class that provides direct integration with OpenClaw Gateway:

**Classes:**
- `OpenClawConfig` - Configuration dataclass with env var support
- `OpenClawModel` - Model class supporting both OpenResponses and HTTP APIs

**Key Features:**
- Automatic OpenClaw endpoint detection
- Dual API support (OpenResponses + OpenAI-compatible HTTP)
- Agent selection via headers or model name parsing
- Session continuity support
- Graceful fallback to litellm

**Configuration via Environment Variables:**
```bash
AIDER_OPENCLAW_MODE=responses|http|auto|disabled  # Default: auto
AIDER_OPENCLAW_AGENT_ID=chat                      # Default: chat
AIDER_OPENCLAW_SESSION_KEY=                       # Optional
AIDER_OPENCLAW_TIMEOUT=300                        # Default: 300s
```

### 2. Modified: `aider/models.py`

**Changes:**
- Added `_is_openclaw_endpoint()` method
- Added `_use_openclaw_model()` method
- Modified `send_completion()` to detect and use OpenClawModel
- Added OpenClaw header injection for HTTP API fallback
- Added model aliases: `openclaw`, `openclaw-chat`, `openclaw-main`

**Integration Logic:**
```python
if self._use_openclaw_model():
    try:
        from aider.openclaw_model import OpenClawModel, OpenClawConfig
        oc_model = OpenClawModel(self.name, config=config, verbose=self.verbose)
        return oc_model.send_completion(messages, functions, stream, temperature)
    except:
        # Fall back to litellm
```

### 3. Configuration: `aider/resources/openclaw-settings.yml`

Example configurations for:
- Basic OpenClaw usage
- Tier routing (@highspeed, @intelligence, @uncensored)
- Agent-specific models
- Session management

### 4. Documentation: `OPENCLAW_INTEGRATION.md`

Comprehensive guide covering:
- Quick start
- Configuration modes
- Agent selection methods
- Session continuity
- Tier routing
- Troubleshooting
- Architecture diagrams

### 5. Tests: `tests/test_openclaw_model.py`

19 test cases covering:
- Configuration management
- Endpoint detection
- Model initialization
- API request formatting
- Header generation
- Factory function behavior

---

## Usage Examples

### Basic Usage (Recommended)

```bash
# Environment
export OPENAI_API_BASE=http://127.0.0.1:18789/v1
export OPENAI_API_KEY=<token>

# Use OpenClaw with chat agent (avoids BOOTSTRAP.md)
aider --model openclaw
# OR explicitly
aider --model openclaw:chat
```

### With Tier Routing

```bash
# Option 1: Environment variable
export TIER_OVERRIDE=highspeed
aider --model openclaw:chat

# Option 2: Include in first message
aider --model openclaw:chat
# Then: "@highspeed explain this code"
```

### Session Continuity

```bash
export AIDER_OPENCLAW_SESSION_KEY="aider-$(date +%Y%m%d)"
aider --model openclaw:chat
```

### Force Specific Mode

```bash
# Use OpenResponses API explicitly
export AIDER_OPENCLAW_MODE=responses
aider --model openclaw:chat

# Use HTTP API explicitly  
export AIDER_OPENCLAW_MODE=http
aider --model openai/chat

# Disable OpenClaw integration
export AIDER_OPENCLAW_MODE=disabled
aider --model openai/gpt-4o --openai-api-base http://127.0.0.1:18789/v1
```

---

## How It Solves the Original Problem

### Original Issue
Aider using `AIDER_MODEL=openai/chat` with `OPENAI_API_BASE=http://127.0.0.1:18789/v1` was:
1. Sending requests to OpenClaw Gateway
2. Gateway defaulting to `main` agent (not `chat`)
3. `main` agent had BOOTSTRAP.md → "I just came online" message

### Solution Implemented

**Option 1: Use `openclaw:chat` model (Recommended)**
```bash
aider --model openclaw:chat
```
- Automatically parsed as agent_id = `chat`
- Uses `chat` agent which has `skipBootstrap: true`
- No BOOTSTRAP.md, no welcome message

**Option 2: Use environment variable**
```bash
export AIDER_OPENCLAW_AGENT_ID=chat
aider --model openai/chat  # or any model name
```
- Header `X-OpenClaw-Agent-Id: chat` added to all requests
- Forces Gateway to use `chat` agent

**Option 3: Use Model Settings YAML**
```yaml
- name: my-model
  extra_params:
    extra_headers:
      X-OpenClaw-Agent-Id: chat
```

---

## Architecture Flow

### Auto-Detection Flow
```
Aider starts
    ↓
Model initialized
    ↓
Is model name "openclaw:*"?
    ↓ YES → Use OpenClawModel with parsed agent_id
    ↓ NO
Is endpoint OpenClaw (127.0.0.1:18789)?
    ↓ YES
Check AIDER_OPENCLAW_MODE
    ↓ responses → OpenResponses API
    ↓ http → HTTP API + headers
    ↓ auto → Try responses, fallback to http
    ↓ disabled → Standard litellm
    ↓ NO → Standard litellm
```

### Request Flow (OpenResponses API)
```
Aider → OpenClawModel.send_completion()
    ↓
POST http://127.0.0.1:18789/responses
    Headers:
      Authorization: Bearer <token>
      X-OpenClaw-Agent-Id: chat
      X-OpenClaw-Session-Key: <optional>
    Body:
      messages: [...]
      stream: true/false
    ↓
OpenClaw Gateway
    ↓
Agent: chat (with skipBootstrap: true)
    ↓
Direct LLM call via @mariozechner/pi-ai SDK
    ↓
Response (normalized to OpenAI format)
```

### Request Flow (HTTP API Fallback)
```
Aider → OpenClawModel.send_completion() [http mode]
    ↓
POST http://127.0.0.1:18789/v1/chat/completions
    Headers:
      Authorization: Bearer <token>
      X-OpenClaw-Agent-Id: chat
      X-OpenClaw-Session-Key: <optional>
    Body:
      model: "openai/chat"
      messages: [...]
      stream: true/false
    ↓
OpenClaw Gateway (openai-http.ts)
    ↓
Agent: chat (with skipBootstrap: true)
    ↓
LLM Response (OpenAI-compatible format)
```

---

## Files Changed

| File | Changes |
|------|---------|
| `aider/openclaw_model.py` | NEW - Core OpenClaw integration module |
| `aider/models.py` | MODIFIED - Added OpenClaw detection and delegation |
| `aider/resources/openclaw-settings.yml` | NEW - Example configurations |
| `OPENCLAW_INTEGRATION.md` | NEW - Comprehensive documentation |
| `tests/test_openclaw_model.py` | NEW - 19 unit tests |

---

## Testing

Run tests:
```bash
cd /home/openclaw/openclaw/aider
python3 -m pytest tests/test_openclaw_model.py -v
```

Test results:
```
============================== 19 passed in 0.92s ==============================
```

---

## Next Steps

1. **Test with live OpenClaw Gateway**
   ```bash
   export OPENAI_API_BASE=http://127.0.0.1:18789/v1
   export OPENAI_API_KEY=<token>
   aider --model openclaw:chat
   ```

2. **Verify no "I just came online" message**

3. **Test tier routing**
   ```bash
   aider --model openclaw:chat
   # Type: "@highspeed explain this code"
   ```

4. **Optional: Clean up old BOOTSTRAP.md**
   ```bash
   rm ~/.openclaw/.openclaw/workspace-main/BOOTSTRAP.md
   ```

---

## Summary

✅ **Dual API Support**: OpenResponses + HTTP  
✅ **Auto-Detection**: Works transparently with existing configs  
✅ **Agent Selection**: Forces `chat` agent to avoid bootstrap  
✅ **Configurable**: Multiple modes and options  
✅ **Fallback**: Graceful degradation to litellm  
✅ **Tested**: 19 passing unit tests  
✅ **Documented**: Comprehensive guide  

The implementation provides a robust, configurable solution for Aider+OpenClaw integration that solves the bootstrap message problem while maintaining flexibility for different use cases.
