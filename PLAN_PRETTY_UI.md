# Pretty UI Improvement Plan

## Problem Analysis

Based on your feedback, the current "pretty" UI has these issues:

1. **Scrolling Problems**: LLM responses run off the bottom of the screen with no way to scroll back and see what was missed
2. **Visual Clutter**: Every status update, spinner, and action prints inline, creating a messy stream
3. **No Visual Hierarchy**: Everything appears "in the front" with no distinction between user input, assistant responses, system messages, and status indicators
4. **Disruptive Status Indicators**: The `░█ Waiting for openai/chat` style spinners interrupt the content flow
5. **Token Info Dump**: Cost/tokens appear as plain text at the end, breaking the conversational flow

## Proposed Improvements

### Phase 1: Output Buffer Management
**Goal**: Keep content visible and scrollable

- **Approach A**: Use Rich's `Live` display with a fixed output area that maintains scrollback
  - Pros: Native Rich integration, handles terminal resizing
  - Cons: May interfere with prompt-toolkit's input handling
  
- **Approach B**: Custom screen buffer with paging
  - Pros: Full control over scrollback, can add search
  - Cons: More complex, risk of terminal compatibility issues

- **Approach C**: Simpler - ensure all output goes through the same console with proper flushing
  - Pros: Minimal changes, less risk
  - Cons: Doesn't solve the scrolling issue completely

**Recommendation**: Approach A with careful integration testing

### Phase 2: Status Area Separation  
**Goal**: Keep status indicators out of the content stream

- Create a **fixed bottom status bar** (like vim/airline) that shows:
  - Current mode (CHAT/AUTO)
  - Active model
  - Spinner/loading state
  - Token count & cost
  - Agent count
  
- This bar updates in-place without scrolling the content area

### Phase 3: Visual Message Hierarchy
**Goal**: Distinguish between different message types

| Message Type | Current | Proposed |
|--------------|---------|----------|
| User input | Plain text | Right-aligned bubble or distinct color bar |
| Assistant response | Markdown | Full-width panel with subtle border |
| System/tool output | Plain text | Collapsible panel or dimmed style |
| Errors | Red text | Red panel with icon |
| Token summary | Plain text | Compact status bar integration |

### Phase 4: Streaming Improvements
**Goal**: Better handling of partial LLM responses

- Reserve a **dedicated streaming area** at the bottom (above status bar)
- Content "promotes" to the main scrollback once a section is complete
- Prevents the "jumping" feel of streaming markdown

## Implementation Options

### Option 1: Full-Screen TUI (Most Ambitious)
Use `textual` or `prompt_toolkit` full-screen mode:
- Scrollable history pane (top 80%)
- Streaming area (middle 15%)
- Status bar (bottom 5%)
- Input line (bottom)

**Pros**: Professional feel, solves all problems
**Cons**: Major refactor, may break some terminal workflows

### Option 2: Rich Layout with Live Display (Recommended)
Use Rich's `Layout` + `Live` for structured output:
- Keep existing prompt-toolkit input
- Structured output areas via Rich
- Minimal changes to architecture

**Pros**: Uses existing dependencies, incremental improvement
**Cons**: Still some terminal compatibility edge cases

### Option 3: Minimal Improvements (Safest)
- Better use of panels/headers in current output
- Move token info to a single-line summary
- Improve spinner to be less intrusive

**Pros**: Low risk, quick to implement
**Cons**: Doesn't fully solve scrolling

## Questions for You

1. **Which approach** aligns with your vision? (Full-screen TUI / Rich Layout / Minimal)

2. **Priority order**: Which issues bother you most? 
   - (a) Scrolling/visibility
   - (b) Visual clutter/status indicators  
   - (c) Message hierarchy
   - (d) Token summary placement

3. **Terminal compatibility**: Do you need to support:
   - Basic terminals (dumb TERM, no color)
   - piped/non-interactive usage
   - Or can we assume modern terminal emulator?

4. **Scrolling behavior**: Would you prefer:
   - Auto-scroll to bottom like a chat app
   - Stay at current position unless at bottom
   - Manual scroll only

5. **Status bar**: What info is essential to always see?
   - Model name
   - Token count
   - Cost
   - Mode (chat/auto)
   - Git status
   - Other?

## My Recommendation

Implement **Option 2 (Rich Layout)** with:
1. A `Layout` with three sections: scrollback history, streaming area, status bar
2. Keep prompt-toolkit for input (proven, feature-rich)
3. Token/cost always visible in status bar
4. Different panel styles for user vs assistant vs system
5. Respect `--no-pretty` for plain output

Estimated effort: 2-3 days for core implementation, 1-2 days for testing edge cases.

---

Awaiting your feedback before proceeding.
