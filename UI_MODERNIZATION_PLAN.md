# Aider UI Modernization Plan

## Overview

Modernize Aider's "pretty" UI by adopting proven patterns from kimi-cli, Codex CLI, and Gemini CLI. The goal is a more informative, responsive, and polished terminal experience.

**Inspiration Sources:**
- **kimi-cli** (Python/prompt_toolkit): Status bar layout, running prompt delegate, live streaming
- **Codex CLI** (Rust/ratatui): Footer modes, configurable status line, context-aware hints
- **Gemini CLI** (Node.js/Ink): Persistent input, streaming architecture

---

## Current State Analysis

### Architecture
```
┌─────────────────────────────────────┐
│  Output Area (append-only)          │
│  - tool_output()                    │
│  - assistant_output()               │
│  - streaming uses MarkdownStream    │
├─────────────────────────────────────┤
│  WaitingSpinner (temporary)         │
├─────────────────────────────────────┤
│  Input (blocked during LLM)         │
│  prompt_session.prompt()            │
└─────────────────────────────────────┘
```

### Problems
1. **Status bar is single-line and basic** - No context usage display, no shortcuts
2. **No persistent prompt separator** - Visual separation between output and input is weak
3. **Spinner is separate from UI** - Jarring transition between states
4. **Input blocked during LLM** - Can't type ahead or steer
5. **No live streaming view** - Content appends instead of updating in-place
6. **Footer hints are static** - Don't adapt to context (empty vs draft vs running)

---

## Target State

### Architecture
```
┌─────────────────────────────────────────────────────────────┐
│  Live View Area (Rich Live, updates in-place)               │
│  - Streaming content with syntax highlighting               │
│  - Tool calls with bullet points and spinners               │
│  - Notifications with severity styling                      │
├─────────────────────────────────────────────────────────────┤
│  Status Bar Line 1:                                         │
│  chat (openai/gpt-4, architect) · ctrl-x: toggle · @: file  │
├─────────────────────────────────────────────────────────────┤
│  Status Bar Line 2:                                         │
│  [toast messages here]               context: 45.2% (118k)  │
├─────────────────────────────────────────────────────────────┤
│  ─────────────────────────────────────────────────────────  │ ← separator
│  > [input area - always active, even during streaming]      │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Enhanced Status Bar
**Status:** ✅ **Completed**
- Implemented in `aider/io.py`.
- Features two-line status bar with model, git branch, and context usage.
- Includes `ToastManager` for expiring notifications.

### Phase 2: Prompt Separator
**Status:** ✅ **Completed**
- Implemented in `aider/io.py`.
- Adds a full-width `─` line above the prompt and in the status bar.

### Phase 3: Live Streaming View
**Status:** ✅ **Completed**
- Implemented in `aider/live_view.py`.
- Uses `rich.live` for in-place streaming with thinking/content blocks.
- Integrated into `BaseCoderLifecycleMixin` and `BaseCoderLLMOutputMixin`.

### Phase 4: Running Prompt Delegate
**Status:** ✅ **Completed**
- Implemented in `aider/prompt_delegate.py` and `aider/running_prompt.py`.
- Supports Codex-style non-blocking input with queuing (Tab) and steering (Enter).
- Integrated into `AiderPromptSession` in `aider/io.py`.

### Phase 5: Context-Aware Footer Modes
**Status:** ✅ **Completed**
- Implemented in `aider/io.py`.
- Features dynamic modes: `composer_empty`, `composer_has_draft`, `task_running`, etc.
- Shortcuts in the status bar update dynamically based on application state.

#### 5.2 Footer Layout Engine

```python
class FooterLayout:
    """Responsive footer layout with width-based fallbacks."""
    
    def __init__(self, width: int, status_data: dict):
        self.width = width
        self.status = status_data
    
    def render(self) -> list[Line]:
        """Render footer lines based on current mode and width."""
        mode = self.status.get("footer_mode", FooterMode.COMPOSER_EMPTY)
        
        if mode == FooterMode.SHORTCUT_OVERLAY:
            return self._render_shortcut_overlay()
        elif mode == FooterMode.QUIT_SHORTCUT_REMINDER:
            return self._render_quit_reminder()
        
        # Standard single or double line footer
        lines = []
        
        # Status line (model, context, etc.)
        status_line = self._render_status_line()
        if status_line:
            lines.append(status_line)
        
        # Context hints
        hint_line = self._render_context_hint()
        if hint_line:
            lines.append(hint_line)
        
        return lines
    
    def _render_status_line(self) -> Line | None:
        """Render configurable status line."""
        items = []
        
        # Model name
        if model := self.status.get("model_name"):
            items.append(model.split("/")[-1])
        
        # Git branch
        if branch := self.status.get("git_branch"):
            items.append(f"⎇ {branch}")
        
        # Context usage
        if pct := self.status.get("tokens_pct"):
            color = "green" if pct < 70 else "yellow" if pct < 90 else "red"
            items.append(f"[{color}]context: {pct:.1f}%[/{color}]")
        
        if not items:
            return None
        
        return Line(" · ".join(items))
    
    def _render_context_hint(self) -> Line | None:
        """Render contextual shortcuts based on footer mode."""
        mode = self.status.get("footer_mode")
        has_draft = self.status.get("has_draft", False)
        is_running = self.status.get("is_task_running", False)
        
        if is_running:
            # Task running hints
            hints = ["esc: cancel", "tab: queue message"]
        elif has_draft:
            # Has draft hints
            hints = ["enter: send", "ctrl+c: clear"]
        else:
            # Empty composer hints
            hints = ["?: shortcuts", "ctrl+x: toggle mode", "@: mention file"]
        
        # Width-aware truncation
        hint_text = " · ".join(hints)
        if len(hint_text) > self.width - 20:
            hint_text = " · ".join(hints[:2])  # Drop less important hints
        
        return Line(hint_text, style="dim")
```

#### 5.3 Dynamic Mode Transitions

```python
def set_footer_mode(self, mode: FooterMode):
    """Update footer mode and refresh display."""
    old_mode = self.status_data.get("footer_mode")
    if old_mode == mode:
        return
    
    self.status_data["footer_mode"] = mode
    
    # Schedule refresh
    if self.prompt_session:
        self.prompt_session.invalidate()
    
    # Auto-reset certain modes after timeout
    if mode in (FooterMode.QUIT_SHORTCUT_REMINDER, FooterMode.ESC_HINT):
        self._schedule_mode_reset(mode, delay=2.0)

def _schedule_mode_reset(self, expected_mode: FooterMode, delay: float):
    """Reset mode after delay if it hasn't changed."""
    import threading
    
    def reset():
        if self.status_data.get("footer_mode") == expected_mode:
            # Reset to appropriate base mode
            if self.status_data.get("is_task_running"):
                self.set_footer_mode(FooterMode.TASK_RUNNING)
            elif self.status_data.get("has_draft"):
                self.set_footer_mode(FooterMode.COMPOSER_HAS_DRAFT)
            else:
                self.set_footer_mode(FooterMode.COMPOSER_EMPTY)
    
    threading.Timer(delay, reset).start()
```

---

## File Modifications Summary

### New Files
1. `aider/live_view.py` - Live streaming display with Rich
2. `aider/prompt_delegate.py` - Running prompt delegate protocol
3. `aider/footer_modes.py` - Footer mode definitions and rendering

### Modified Files
1. `aider/io.py`
   - `_get_bottom_toolbar()` → `_get_status_bar()` (two-line)
   - Add `ToastManager`
   - Add `rule()` separator method
   - Update `CustomPromptSession` for running prompt delegate
   - Add footer mode management

2. `aider/coders/base_coder_lifecycle.py`
   - Integrate `_LiveView` in `send_message()`
   - Add `_handle_steer()` for queued input
   - Stream callbacks for live view

3. `aider/coders/base_coder.py`
   - Add `queued_messages` list
   - Handle queued messages in main loop
   - Steer callback support

4. `aider/mdstream.py`
   - Optional integration with `_LiveView`
   - Fallback for non-pretty mode

---

## Testing Strategy

### Unit Tests
```python
# test_status_bar.py
def test_status_bar_formatting():
    io = InputOutput(pretty=True)
    io.status_data.update({
        "mode": "CHAT",
        "model_name": "openai/gpt-4",
        "tokens_pct": 45.2,
        "tokens_used": 118300,
        "tokens_max": 262144,
    })
    status = io._get_status_bar()
    assert "chat (gpt-4)" in status[0].lower()
    assert "45.2%" in status[1]
    assert "118.3k" in status[1]

# test_live_view.py
def test_content_block_accumulation():
    block = _ContentBlock(is_thinking=False)
    block.append("Hello")
    block.append(" world")
    assert block.raw_text == "Hello world"
```

### Integration Tests
```python
# Test full streaming flow
def test_streaming_with_live_view():
    coder = Coder.create(...)
    coder.run("say hello")
    # Verify live view was created and stopped
    # Verify output appears correctly
```

### Manual Testing Checklist
- [ ] Status bar shows correct model name
- [ ] Context usage updates in real-time
- [ ] Color changes at 70% and 90% thresholds
- [ ] Separator line appears above prompt
- [ ] Live view renders streaming content
- [ ] Tool calls show with spinners
- [ ] Footer hints change based on state
- [ ] Can type while LLM is generating (Phase 4)
- [ ] Queued messages process after current turn
- [ ] Non-pretty mode still works (fallback)

---

## Rollout Plan

### Week 1: Phase 1 + 2
- Implement enhanced status bar
- Add prompt separator
- Release as minor version bump

### Week 2-3: Phase 3
- Implement live streaming view
- Keep as opt-in via `--live-view` flag
- Gather feedback

### Week 4-5: Phase 4
- Implement running prompt delegate
- Most complex change, needs thorough testing
- May need feature flag

### Week 6: Phase 5 + Polish
- Footer modes
- Integration testing
- Documentation updates

---

## Configuration Options

```yaml
# .aider.conf.yml

# UI Modernization options
show_status_bar: true
status_bar_items:  # Configurable like Codex CLI
  - model
  - git_branch
  - context_usage
  - cost

show_prompt_separator: true
separator_char: "─"

enable_live_view: true  # Phase 3
enable_running_prompt: true  # Phase 4

# Footer hints
footer_hints: true
hint_timeout: 2.0  # seconds
```

---

## Open Questions

1. **Live View vs Terminal Scrollback**
   - Rich Live is "transient" by default - content disappears on exit
   - kimi-cli uses `transient=True` and manually flushes to history
   - Need to ensure final content is preserved

2. **Input During Streaming**
   - Should queued messages process automatically or require confirmation?
   - How to handle /commands typed during streaming?

3. **Performance**
   - Live view refresh at 10fps - impact on slow terminals?
   - Consider rate limiting for very fast streams

4. **Accessibility**
   - Screen reader compatibility with live updates
   - Option to disable animations/live view for accessibility

---

## References

- **kimi-cli**: `src/kimi_cli/ui/shell/prompt.py`, `visualize.py`
- **Codex CLI**: `codex-rs/tui/src/bottom_pane/footer.rs`, `status_line_setup.rs`
- **Gemini CLI**: `packages/cli/src/ui/components/InputPrompt.tsx`
- **Rich Live**: https://rich.readthedocs.io/en/latest/live.html
- **prompt_toolkit**: https://python-prompt-toolkit.readthedocs.io/
