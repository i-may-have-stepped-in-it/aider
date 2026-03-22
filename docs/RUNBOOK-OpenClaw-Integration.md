# Runbook: OpenClaw Integration Management

## Overview
OpenClaw provides a gateway and skill-bridging system for Aider. This runbook covers common administrative tasks and troubleshooting steps for maintaining the integration.

## Component Map
1. **OpenClawModel**: Custom LLM provider in `aider/openclaw_model.py`.
2. **OpenClawBridge**: Skill-bridging layer in `aider/openclaw_bridge.py`.
3. **OpenClawAdapter**: Shared-skill adaptation in `aider/skills/openclaw_adapter.py`.

## Operational Tasks

### Verifying Gateway Connection
To verify that Aider can reach the OpenClaw gateway:
```bash
# Run Aider with the OpenClaw model and a simple query
aider --model openclaw/chat --message "ping"
```
Expectation: A successful response from the model indicates the `requests` library and gateway authentication are working correctly.

### Syncing New Skills
When new OpenClaw skills are added to the external `/home/openclaw/.codex/skills` directory, Aider must re-initialize its bridge:
1. Restart the Aider session.
2. Verify discovery: `/skill list` should show the new skills with a "🔧" emoji.

## Troubleshooting

### `RuntimeError` during /skill run or /web
If Aider crashes with `asyncio.run() cannot be called from a running event loop`:
- **Cause**: Blocking code (like URL scraping or confirmation prompts) is being called directly from the async UI thread.
- **Solution**: Ensure the call path uses `run_async_safely` or is properly awaited in an async task. Check `aider/io.py`'s `confirm_ask` for correct context-awareness.

### Skill Output Missing in Chat
If `/skill run <name>` succeeds but no output appears:
- **Cause**: `OpenClawBridge` might be capturing stdout/stderr but not returning it to the adapter.
- **Solution**: Check the skill's `duration_ms` in `/skill info <name>`. If it's very low, the skill may be failing silently. Verify that `OpenClawAdapter._execute_impl` is combining stdout and stderr correctly.

### LLM Response Parsing Errors
If Aider reports that it cannot parse the model's response:
- **Cause**: The OpenClaw gateway may be returning a non-standard JSON structure or a `SimpleNamespace` instead of a `dict`.
- **Solution**: Inspect `aider/openclaw_model.py`. Ensure `simple_send_with_retries` is checking for both `.choices` (object attribute) and `["choices"]` (dictionary key).

### Test Environment Fallbacks
Aider implements a safe fallback mechanism for `openclaw:` models during automated testing:
- **Detection**: Triggered if `PYTEST_CURRENT_TEST` is set or if `stdin` is not a TTY.
- **Behavior**: If `OpenClawModel` fails (e.g., due to no gateway), `aider/models.py` returns a local mock response.
- **Verification**: Check for "Test environment detected, returning mock response" in verbose output if tests fail unexpectedly.

## Maintenance
- **Dependencies**: Monitor the `requests` and `httpx` versions.
- **Cleanup**: Periodically clean up stale `/tmp/aider-openclaw-*` directories if they accumulate.
