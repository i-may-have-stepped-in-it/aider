# Async Refactor Plan: Option B Persistent Prompt

## Goal
Transform Aider's UI layer from threading-based to async/await, achieving true kimi-cli style persistent prompt where input is never blocked during generation.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Async Event Loop (asyncio)                    │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ PromptSession│  │ LiveView     │  │ Generation Task      │  │
│  │ (always on)  │  │ (streaming)  │  │ (background)         │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                     │              │
│         └─────────────────┼─────────────────────┘              │
│                           │                                    │
│                    ┌──────┴──────┐                            │
│                    │ Message Bus │                            │
│                    │ (asyncio.Queue)                          │
│                    └──────┬──────┘                            │
│                           │                                    │
│         ┌─────────────────┼─────────────────┐                 │
│         ▼                 ▼                 ▼                 │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐            │
│  │ User Input │   │  Steer     │   │  Cancel    │            │
│  │ (queue)    │   │ (interrupt)│   │ (abort)    │            │
│  └────────────┘   └────────────┘   └────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

## Phase 1: Core Async Infrastructure ✓ (partial)

### Already Done
- [x] Basic async methods in base_coder_control.py
- [x] Async IO methods (get_input_async, display_user_input_async)
- [x] run_interactive_session_async
- [x] main_async.py entry point

### Still Needed
- [ ] Async-compatible PromptSession
- [ ] Async RunningPromptManager
- [ ] Async LiveView
- [ ] Message queue system

## Phase 2: Async Prompt Session

**Problem**: prompt_toolkit's PromptSession.prompt() is blocking
**Solution**: Use prompt_toolkit's async support + patch_stdout

```python
class AsyncAiderPromptSession:
    async def prompt_async(self, ...):
        with patch_stdout(raw=True):
            return await self.session.prompt_async(...)
```

## Phase 3: Async Running Prompt Manager

**Current**: Thread-based with locks
**New**: Async task management with asyncio

```python
class AsyncRunningPromptManager:
    def __init__(self):
        self._generation_task: Optional[asyncio.Task] = None
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._cancel_event: asyncio.Event = asyncio.Event()
    
    async def start_generation(self, func, *args):
        self._generation_task = asyncio.create_task(
            self._generation_worker(func, args)
        )
    
    async def queue_message(self, message: str):
        await self._message_queue.put(message)
    
    async def steer(self, message: str):
        self._cancel_event.set()
        await self._generation_task  # Wait for cancellation
        return message  # Return steer message for immediate processing
```

## Phase 4: Async Coder Integration

**Key Change**: run_async() must handle concurrent input + generation

```python
async def run_async(self, ...):
    while True:
        # Get input (non-blocking if generation is running)
        user_message = await self.get_input_async()
        
        if self.is_generating:
            # Queue or steer
            if is_tab_pressed:
                await self.queue_message(user_message)
            else:  # Enter = steer
                await self.steer_generation(user_message)
        else:
            # Start new generation
            await self.run_one_async(user_message)
```

## Phase 5: Git Async Wrappers

GitPython is synchronous - wrap with asyncio.to_thread():

```python
class AsyncRepo:
    def __init__(self, sync_repo):
        self._repo = sync_repo
    
    async def commit(self, message):
        return await asyncio.to_thread(self._repo.commit, message)
    
    async def get_branch_name(self):
        return await asyncio.to_thread(self._repo.get_branch_name)
```

## Phase 6: Message Queue & Steering Protocol

### Message Types
- `QUEUE`: Add to queue for next turn
- `STEER`: Cancel current, start new with this message
- `CANCEL`: Just cancel current

### Flow
1. User presses Tab during generation → QUEUE
2. User presses Enter during generation → STEER
3. User presses Escape → CANCEL

## Implementation Checklist

### Infrastructure
- [ ] Create `aider/async_compat.py` with shared utilities
- [ ] AsyncPromptSession class
- [ ] AsyncRunningPromptManager class
- [ ] Message queue system

### Core Integration
- [ ] Update base_coder_control.py with proper async flow
- [ ] Update io.py with async prompt session
- [ ] Update live_view.py with async support
- [ ] Update prompt_delegate.py with async handlers

### Git Integration
- [ ] Wrap GitPython calls in asyncio.to_thread()
- [ ] Async repo methods

### Entry Point
- [ ] Complete main_async.py integration
- [ ] Environment variable toggle (AIDER_ASYNC=1)

### Testing
- [ ] Async unit tests
- [ ] Integration tests for message queue
- [ ] Steering behavior tests

## Files to Modify

1. `aider/async_compat.py` - New async utilities
2. `aider/io.py` - Async prompt session
3. `aider/running_prompt.py` - Async manager (or new async_running_prompt.py)
4. `aider/live_view.py` - Async live view
5. `aider/prompt_delegate.py` - Async delegates
6. `aider/coders/base_coder_control.py` - Async integration
7. `aider/repo.py` - Async wrappers
8. `aider/bootstrap/runtime.py` - Async session runner
9. `aider/main_async.py` - Entry point

## Key Design Decisions

1. **Backward Compatibility**: Keep sync methods, add async variants
2. **Default Mode**: Sync by default (AIDER_ASYNC=0), opt-in to async
3. **Thread Safety**: All shared state via asyncio primitives
4. **Cancellation**: Cooperative cancellation with asyncio.Event
5. **Error Handling**: Exceptions propagate through tasks, caught at top level
