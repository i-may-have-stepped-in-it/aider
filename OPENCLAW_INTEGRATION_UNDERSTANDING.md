# OpenClaw Integration - Historical Design Notes

> **Status**: Historical/Archive - Design notes from initial integration  
> **Date**: 2026-03-17  
> **See Also**: [Integration Guide](OPENCLAW_INTEGRATION.md) | [Architecture Complete](OPENCLAW_ARCHITECTURE_COMPLETE.md)

## Purpose

This document contains historical design notes from the initial OpenClaw integration. It documents the investigation into bootstrap messages, routing architecture, and solution options that were considered.

For current usage, see [OPENCLAW_INTEGRATION.md](OPENCLAW_INTEGRATION.md).

---

## 1. Model Router Architecture

### Components
| Component | Location | Purpose |
|-----------|----------|---------|
| Python Core | `~/.openclaw/skills/model-router/scripts/router_core.py` | 4-layer routing logic |
| Message Hook | `~/.openclaw/skills/model-router/scripts/message-hook-v2.sh` | Bash wrapper, stdin input |
| VS Code Extension | `~/.openclaw/extensions/model-router/index.ts` | TypeScript plugin with hooks |

### Routing Flow (4 Layers)
1. **System Filter**: Detects heartbeat/cron/slash commands
2. **Prefix Routing**: `@kimi`, `@codex`, `@flash` etc. bypass complexity
3. **Continuation**: "continue"/"also" + session → same model
4. **Complexity Analysis**: Score 0.0-1.0 based on message length, code blocks, keywords

### Failover Chains
- **Intelligence**: codex → kimi → zai/glm-5 → zai/glm-4.7 → openrouter/minimax
- **Highspeed**: zai/glm-4.5-air → zai-public/glm-4.7-flash → zai/glm-4.5

### Health Checks
- Model cooldowns (`.router_cooldowns`)
- Circuit breakers (`.router_circuit_breakers`)
- Provider health (quota, balance)
- Rate limiting protection

---

## 2. OpenClaw LLM Request Flow

```
Gateway HTTP Handler (openai-http.ts)
    ↓
agentCommandFromIngress()
    ↓
agentCommandInternal()
    ↓
runWithModelFallback() → runEmbeddedPiAgent()
    ↓
@mariozechner/pi-ai SDK (external package)
    ↓
Auth Profiles (from ~/.openclaw/agents/default/auth-profiles.json)
    ↓
HTTP Request to Provider
```

### Key Insight: Credentials Are NOT in Gateway
- API keys stored in `auth-profiles.json`
- Resolved via `model-auth.ts:resolveApiKeyForProvider()`
- Gateway should NOT make direct HTTP calls
- Must use agent infrastructure for auth

---

## 3. The Real Problem

### Current Behavior (Broken)
1. Aider sends: `"implement this in your configuration"` with `model: "@speed"`
2. Gateway calls `agentCommandFromIngress()`
3. Agent starts and sends **bootstrap message**: "I just came online..."
4. Agent interprets request as about **its own** BOOTSTRAP.md
5. Response is wrong context

### Root Cause
The agent **always** initializes with a welcome/bootstrap persona when starting a session via HTTP API, regardless of the model requested.

---

## 4. Solution Options Analysis

### Option A: Silent Agent Mode
Add flag to suppress bootstrap while keeping agent infrastructure:
```typescript
const commandInput = buildAgentCommandInput({
  prompt: { message },
  silentMode: true,  // NEW: Skip bootstrap
});
```
**Pros**: Uses existing auth, circuit breakers, health checks  
**Cons**: Need to find/modify bootstrap source

### Option B: Gateway Model Resolution (Revised)
1. Gateway resolves `@pool/speed` → `zai/glm-4.5-air` via model-router
2. Gateway passes **explicit model** to agent
3. Agent runs with pre-resolved model, skip its own resolution
4. Bootstrap may still happen

**Pros**: Clean separation  
**Cons**: Bootstrap still needs addressing

### Option C: Extend Model-Router Hook
Use existing `before_model_resolve` hook to:
1. Detect `@pool/*` aliases
2. Return `modelOverride` immediately
3. Suppress bootstrap when override present

**Pros**: Uses existing extension infrastructure  
**Cons**: Bootstrap suppression mechanism unclear

---

## 5. Key Files for Investigation

### Gateway Layer
- `~/openclaw/src/gateway/openai-http.ts` - HTTP handler (line ~560)
- `~/openclaw/src/gateway/call.ts` - Gateway client

### Agent Layer
- `~/openclaw/src/commands/agent.ts` - `agentCommandFromIngress()` (line ~1239)
- `~/openclaw/src/agents/pi-embedded-runner/run.ts` - Main agent execution
- `~/openclaw/src/agents/pi-embedded-runner/run/attempt.ts` - Attempt logic (~2700 lines)

### Model Resolution
- `~/openclaw/src/agents/model.ts` - Model resolution
- `~/openclaw/src/agents/model-selection.ts` - Selection logic
- `~/openclaw/src/agents/model-auth.ts` - API key resolution (~441 lines)

### Model Router
- `~/.openclaw/skills/model-router/scripts/router_core.py` - Core logic
- `~/.openclaw/extensions/model-router/index.ts` - TS plugin with hooks

---

## 6. Bootstrap Message Source

**Unknown**: Need to investigate where bootstrap message comes from:
- System prompt in agent initialization?
- First response from model?
- Hardcoded agent behavior?
- ACP (Agent Control Plane) initialization?

**Files to check**:
- `~/openclaw/src/agents/pi-embedded-runner/run.ts` for session initialization
- `~/openclaw/src/agents/agent-prompt.ts` for prompt building
- ACP-related files for control plane messages

---

## 7. TIER_OVERRIDE Already Exists

The model-router already supports `TIER_OVERRIDE` environment variable:
```python
# In router_core.py
tier_override = os.environ.get("TIER_OVERRIDE")
if tier_override:
    model = find_healthy_model_in_tier("", tier_override)
    return f"{tier_override}:{model}:tier_passthrough_override:{decision_id}"
```

This was added in my changes but exists in the actual implementation path.

---

## 8. What NOT To Do

1. **Don't make direct HTTP calls in gateway** - Bypasses auth profiles, circuit breakers
2. **Don't bypass the agent entirely** - Loses health checks, failover, auth
3. **Don't hardcode provider URLs in gateway** - Should use model-router resolution
4. **Don't add complex config requirements** - Should work with existing infrastructure

---

## Next Steps

1. **Investigate bootstrap source** - Find where "I just came online" message originates
2. **Design minimal intervention** - Smallest change that fixes the issue
3. **Consider using existing hooks** - `before_model_resolve` may be the right place
4. **Test with actual gateway** - Verify behavior end-to-end
