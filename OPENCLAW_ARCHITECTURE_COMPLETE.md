# OpenClaw Architecture - Complete Understanding

## Date: 2026-03-17
## Status: COMPREHENSIVE ANALYSIS

---

## 1. System Overview

OpenClaw is a **self-hosted AI agent gateway** that connects LLMs to messaging platforms. The key architectural principle is **"single process, multi-channel"** - one Gateway process manages all connections.

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENTS                                  │
│  (CLI, HTTP API, Web UI)                                       │
└─────────────────────────┬───────────────────────────────────────┘
                          │ WebSocket/HTTP
┌─────────────────────────▼───────────────────────────────────────┐
│                      GATEWAY                                    │
│  (Port 127.0.0.1:18789)                                        │
│  • Routing • Auth • Sessions • State Management                │
└─────────────────────────┬───────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│   CHANNELS    │ │    AGENT      │ │    MEMORY     │
│ (WhatsApp,    │ │   RUNTIME     │ │   SYSTEM      │
│  Telegram,    │ │               │ │               │
│  Discord...)  │ │ • ACP Mode    │ │ • File-based  │
└───────────────┘ │ • Standard    │ │ • Vector DB   │
                  └───────────────┘ └───────────────┘
```

---

## 2. The Bootstrap Message - Root Cause IDENTIFIED

### Where It Comes From

**Source**: `docs/reference/templates/BOOTSTRAP.md`

```markdown
> "Hey. I just came online. Who am I? Who are you?"
```

**Flow**:
1. Template loaded in `src/agents/workspace.ts:431-432`
2. Written to workspace as `BOOTSTRAP.md`
3. Added to bootstrap entries list (`workspace.ts:513-515`)
4. Injected into system prompt under "Project Context" (`system-prompt.ts:616-648`)
5. **LLM generates the welcome message** based on this instruction

### When It's Triggered

**Condition**: `ensureBootstrapFiles: !agentCfg?.skipBootstrap` (default: TRUE)

In `src/commands/agent.ts:638-639`:
```typescript
const workspace = await ensureAgentWorkspace({
  dir: workspaceDirRaw,
  ensureBootstrapFiles: !agentCfg?.skipBootstrap,  // DEFAULT: true → bootstrap enabled
});
```

**New Session Detection** (`src/commands/agent/session.ts:146`):
```typescript
const isNewSession = !fresh && !opts.sessionId;
// isNewSession = true when:
// - No session key provided (new HTTP call), OR
// - Session is stale per reset policy
```

---

## 3. HTTP API Flow (What Aider Uses)

### Complete Request Path

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. HTTP REQUEST                                                  │
│    POST /v1/chat/completions                                     │
│    Headers: Authorization, Content-Type: application/json        │
│    Body: { model: "@pool/speed", messages: [...] }              │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. GATEWAY HANDLER                                               │
│    src/gateway/openai-http.ts:408                                │
│    • Authenticates request                                       │
│    • Parses OpenAI format                                        │
│    • Resolves session key (generated UUID if not provided)       │
│    • Builds command input (deliver=false for API)               │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. AGENT COMMAND                                                 │
│    src/commands/agent.ts:1239 (agentCommandFromIngress)          │
│    • Security check: senderIsOwner must be explicit             │
│    • Calls agentCommandInternal                                 │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. SESSION PREPARATION                                           │
│    src/commands/agent.ts:504 (prepareAgentCommandExecution)      │
│    • Load config                                                 │
│    • Resolve/Create session ←── NEW SESSION TRIGGER             │
│    • Create workspace ←── BOOTSTRAP TRIGGER                     │
│    • Resolve model                                               │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. EXECUTION MODE CHECK                                          │
│    src/commands/agent.ts:728                                     │
│    IF acpResolution.kind === "ready":                            │
│       → acpManager.runTurn() (ACP mode)                         │
│    ELSE:                                                         │
│       → runEmbeddedPiAgent() (Standard mode)                    │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. AGENT EXECUTION                                               │
│    • Build system prompt (includes BOOTSTRAP.md content)        │
│    • Load skills                                                 │
│    • Execute LLM call via @mariozechner/pi-ai SDK               │
└────────────────────┬───────────────────────────────────────┬────┘
                     │                                       │
        ┌────────────┘                                       └────────────┐
        ▼                                                                 ▼
┌──────────────────────┐                                    ┌──────────────────────┐
│ 7a. NON-STREAMING    │                                    │ 7b. STREAMING        │
│    Await result      │                                    │    Subscribe to      │
│    Return JSON       │                                    │    agent events      │
└──────────────────────┘                                    │    Emit SSE chunks   │
                                                            └──────────────────────┘
```

### Critical Point: NEW vs EXISTING SESSION

**Session Key Resolution** (`src/gateway/http-utils.ts:82`):
```typescript
// HTTP API does NOT provide session key by default
// → Generates new UUID for each request
// → Creates NEW session every time
// → Triggers bootstrap EVERY time
```

---

## 4. ACP vs Standard Mode

### ACP (Agent Control Plane) Mode

**Trigger**: Session key contains `:acp:` pattern

**Characteristics**:
- Uses `acpManager.runTurn()`
- Pluggable backend architecture
- Modes: `oneshot` (auto-close) or `persistent`
- Limited tool access (backend-dependent)
- Async identity resolution

**When Used**:
- Explicit ACP sessions
- ACP backend configured

### Standard Mode

**Trigger**: Regular session key (no `:acp:`)

**Characteristics**:
- Uses `runEmbeddedPiAgent()`
- Direct `pi-coding-agent` SDK integration
- Full OpenClaw tool suite
- File-based session persistence
- Bootstrap files loaded

**When Used**:
- HTTP API calls
- Channel messages (WhatsApp, etc.)
- CLI interactions

---

## 5. Solution Options - REVISED

### Option 1: Use Existing `skipBootstrap` Config

**Already implemented in OpenClaw!**

**Config location** (`src/config/types.agent-defaults.ts:137-138`):
```typescript
/** Skip bootstrap (BOOTSTRAP.md creation, etc.) for pre-configured deployments. */
skipBootstrap?: boolean;
```

**Used in**:
- `src/commands/agent.ts:639`
- `src/auto-reply/reply/get-reply.ts:108`
- `src/cron/isolated-agent/run.ts:255`

**Implementation**:
```typescript
// In gateway, when calling agent:
const commandInput = buildAgentCommandInput({
  prompt: { message },
  sessionKey,
  runId,
  messageChannel,
  // Pass through agent config
  agentConfig: {
    skipBootstrap: true,  // NEW: Skip bootstrap for API calls
  },
});
```

**Pros**:
- Already exists in codebase
- Minimal change
- No bootstrap files created

**Cons**:
- Need to pass config through ingress
- May lose useful context files (AGENTS.md, etc.)

---

### Option 2: Lightweight Context Mode

**Already implemented!** (`src/agents/bootstrap-files.ts:47-62`)

```typescript
function applyContextModeFilter(params: {
  files: WorkspaceBootstrapFile[];
  contextMode?: BootstrapContextMode;  // "full" | "lightweight"
  runKind?: BootstrapContextRunKind;   // "default" | "heartbeat" | "cron"
}): WorkspaceBootstrapFile[] {
  if (contextMode !== "lightweight") {
    return params.files;
  }
  if (runKind === "heartbeat") {
    return params.files.filter((file) => file.name === "HEARTBEAT.md");
  }
  // cron/default lightweight mode keeps bootstrap context empty
  return [];  // ← No bootstrap files!
}
```

**Implementation**:
```typescript
// In gateway handler:
const commandInput = buildAgentCommandInput({
  prompt: { message },
  contextMode: "lightweight",  // Skip bootstrap files
  runKind: "default",
});
```

**Pros**:
- Already exists
- Keeps essential files, skips BOOTSTRAP.md
- Clean separation

**Cons**:
- Need to verify it's actually used
- May need plumbing through command chain

---

### Option 3: Filter BOOTSTRAP.md Specifically

**Location**: `src/agents/workspace.ts:551-559`

Already have `MINIMAL_BOOTSTRAP_ALLOWLIST`:
```typescript
const MINIMAL_BOOTSTRAP_ALLOWLIST = new Set([
  DEFAULT_AGENTS_FILENAME,      // AGENTS.md
  DEFAULT_TOOLS_FILENAME,       // TOOLS.md
  DEFAULT_SOUL_FILENAME,        // SOUL.md
  DEFAULT_IDENTITY_FILENAME,    // IDENTITY.md
  DEFAULT_USER_FILENAME,        // USER.md
  // NOTE: BOOTSTRAP.md is NOT in this list
]);
```

**Implementation**:
```typescript
// Add new filter mode for API calls
const API_BOOTSTRAP_ALLOWLIST = new Set([
  // Essential files only, exclude BOOTSTRAP.md
  DEFAULT_AGENTS_FILENAME,
  DEFAULT_TOOLS_FILENAME,
  // etc.
]);

// In workspace.ts filterBootstrapFilesForSession()
if (params.isApiCall) {
  return filterToAllowlist(files, API_BOOTSTRAP_ALLOWLIST);
}
```

**Pros**:
- Surgical - only removes BOOTSTRAP.md
- Keeps other useful context
- Clear intent

**Cons**:
- Need to add `isApiCall` parameter through chain
- More invasive change

---

### Option 4: X-OpenClaw-Session-Key Header

**Current behavior**: No session key = new session = bootstrap

**Better behavior**: Client provides session key for continuity

```typescript
// Aider could send:
headers: {
  "X-OpenClaw-Session-Key": "aider-session-123",
}

// Gateway reuses session
// No new session = no bootstrap trigger
```

**Pros**:
- Existing mechanism
- Session continuity
- No code changes needed

**Cons**:
- Aider needs modification
- Session may still get stale
- Not a complete solution

---

## 6. Recommended Solution

### Primary: Option 2 - Lightweight Context Mode

**Why**:
1. Already implemented in OpenClaw
2. Proven usage (cron, heartbeat modes)
3. Minimal code changes
4. Clear semantic meaning

**Implementation Plan**:

1. **Gateway** (`openai-http.ts`):
   ```typescript
   const commandInput = buildAgentCommandInput({
     prompt: { message, extraSystemPrompt, images },
     sessionKey,
     runId,
     messageChannel,
     // NEW: Signal this is API passthrough
     contextMode: "lightweight",
     runKind: "default",
   });
   ```

2. **Command Input Builder** (`agent.ts`):
   - Pass `contextMode` and `runKind` through to workspace preparation

3. **Workspace** (`workspace.ts`):
   - Already uses `applyContextModeFilter()`
   - Verify it receives parameters correctly

4. **Bootstrap Files** (`bootstrap-files.ts`):
   - Already filters based on mode
   - `lightweight` mode returns `[]` (empty)

---

### Alternative: Option 1 - skipBootstrap

If lightweight mode doesn't work, use existing `skipBootstrap` config:

```typescript
// Gateway
const commandInput = buildAgentCommandInput({
  prompt: { message },
  agentConfig: {
    skipBootstrap: true,
  },
});

// agentCommandInternal (agent.ts)
const workspace = await ensureAgentWorkspace({
  dir: workspaceDirRaw,
  ensureBootstrapFiles: !(agentCfg?.skipBootstrap ?? false),
});
```

---

## 7. Model Resolution Integration

### Current Model Router Hook

**Extension**: `~/.openclaw/extensions/model-router/index.ts`

**Hook**: `before_model_resolve`

```typescript
api.on("before_model_resolve", (event, ctx) => {
  const decision = routePrompt(prompt, ctx.sessionKey);
  if (decision?.model) {
    const [provider, ...modelParts] = decision.model.split("/");
    return {
      providerOverride: provider,
      modelOverride: modelParts.join("/"),
    };
  }
});
```

### Integration with @pool/* Aliases

**No changes needed to model-router!**

The hook already:
1. Receives prompt
2. Calls `routePrompt()` → runs `message-hook-v2.sh`
3. If prompt contains `@pool/speed`, router handles it
4. Returns resolved model

**What we need**:
- Ensure `@pool/speed` in prompt triggers correct routing
- OR pass model override directly from gateway

**Gateway approach**:
```typescript
// Gateway resolves @pool/* before calling agent
if (model.startsWith("@pool/")) {
  const tier = model.replace("@pool/", "");
  const tierMap = { speed: "highspeed", intel: "intelligence", uncen: "uncensored" };
  
  // Add tier hint to prompt for router
  const enrichedPrompt = `@${tierMap[tier]} ${prompt.message}`;
  
  // OR: Pass model override directly
  commandInput.modelOverride = resolveTierModel(tier);
}
```

---

## 8. Files to Modify

### Minimal Change Set

1. **`src/gateway/openai-http.ts`**
   - Detect `@pool/*` models
   - Add `contextMode: "lightweight"` to command input
   - OR add `agentConfig.skipBootstrap: true`

2. **`src/commands/agent.ts`**
   - Pass `contextMode` through to workspace preparation
   - OR handle `agentConfig.skipBootstrap`

3. **Verify**: `src/agents/workspace.ts` and `src/agents/bootstrap-files.ts`
   - Already support lightweight mode
   - May need parameter plumbing

### Alternative: Config-Only Solution

If code changes are difficult, document:

```yaml
# ~/.openclaw/config.yaml
agents:
  defaults:
    skipBootstrap: true  # Disables bootstrap for all agents
```

**But this affects ALL agents (WhatsApp, Slack, etc.)** - not ideal.

---

## 9. Testing Plan

1. **Test lightweight mode**:
   ```bash
   curl -X POST http://127.0.0.1:18789/v1/chat/completions \
     -H "Authorization: Bearer $TOKEN" \
     -d '{
       "model": "@pool/speed",
       "messages": [{"role": "user", "content": "Hello"}],
       "stream": false
     }'
   ```
   - Should NOT see "I just came online"
   - Should see direct LLM response

2. **Verify context files**:
   - Check if AGENTS.md, TOOLS.md still loaded (if needed)
   - Verify BOOTSTRAP.md excluded

3. **Test model resolution**:
   - `@pool/speed` → should route to highspeed tier model
   - Verify via router logs

---

## 10. Summary

**Root Cause**: HTTP API creates new session → triggers bootstrap → BOOTSTRAP.md injected → LLM generates welcome message.

**Solution**: Use existing `contextMode: "lightweight"` or `skipBootstrap: true` to suppress bootstrap files.

**Integration**: Gateway detects `@pool/*` → passes lightweight mode → agent runs without bootstrap → direct LLM response.

**Key Insight**: OpenClaw already has the mechanisms we need. We just need to wire them up correctly.
