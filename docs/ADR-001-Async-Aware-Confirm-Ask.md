# ADR-001: Async-Aware Confirmation Dialogs

## Status
Accepted

## Context
Aider is transitioning to an async-first architecture (Option B with persistent prompt) to support non-blocking background generation. The core `InputOutput` class handles user interaction, including confirmation dialogs via `confirm_ask`.

In the original synchronous implementation, `confirm_ask` uses `prompt_toolkit`'s synchronous `prompt()` or the built-in `input()`. However, when Aider runs within an active `asyncio` event loop (e.g., during background generation or when using the new `main_async.py` entrypoint), calling these synchronous blocking functions results in a `RuntimeError: asyncio.run() cannot be called from a running event loop` or blocks the loop entirely, preventing concurrent tasks (like UI heartbeats or background streaming) from executing.

## Decision
Modify `InputOutput.confirm_ask` to be context-aware:
1. Detect if an `asyncio` event loop is already running in the current thread.
2. If a loop is running, delegate the confirmation prompt to an `AsyncExecutor` using `run_async_safely`.
3. The executor runs the async-aware `AsyncAiderPromptSession.prompt_async` in a worker thread, bridging the sync-to-async boundary safely without nesting event loops.
4. If no loop is running, fall back to the legacy synchronous `prompt()` or `input()`.

### Terminal Synchronization
To prevent cursor position report leaks (`^[[54;8R`) during high-frequency UI re-renders, `DockedPromptSession` now caches terminal width for 0.5s. This reduces the number of Device Status Report (DSR) escape sequences sent to the terminal driver.

## Consequences
### Positive
- Prevents `RuntimeError` when confirmation is requested during async sessions.
- Allows background tasks to continue processing while waiting for user confirmation.
- Eliminates terminal noise/artifacts (`^[[54;8R`) in modern terminal emulators.
- Maintains backward compatibility for synchronous call sites.

### Negative
- Introduces a dependency on `AsyncExecutor` within the `io.py` module.
- Slight overhead for thread-bridging during confirmation.
- Increased complexity in the `confirm_ask` call path.

## Alternatives Considered
- **Making all call sites async**: Rejected due to the sheer number of call sites (27+) and the desire to maintain a clean synchronous API for existing plugins and extensions.
- **Using `aioconsole`**: Rejected to avoid adding a new heavy dependency and because `prompt_toolkit` is already integrated.
