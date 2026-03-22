# QoL Improvements - Workflow Implementation Plan

## Phase 1: Context & Requirements (COMPLETED)

### Statement of Need
The Aider fork has 5 critical QoL issues that need immediate fixing:
1. Dashboard broken (missing imports)
2. Toast system non-functional
3. Missing command aliases
4. No budget CLI flag
5. No cost warnings for expensive models

### Context Mode: existing_code
We have existing code that needs modification, not new code.

---

## Phase 2a: Implementation Readiness

### Files to Modify:
| File | Change Type | Lines |
|------|-------------|-------|
| `aider/gui/dashboard.py` | Fix imports | ~5 |
| `aider/io.py` | Fix toast rendering | ~20 |
| `aider/commands.py` | Add aliases | ~10 |
| `aider/args.py` | Add --budget flag | ~5 |
| `aider/coders/base_coder_output.py` | Add cost warnings | ~15 |

---

## Phase 2: Implementation

### Task Breakdown:
1. **Fix dashboard imports** (30 min)
   - Add missing `Panel` and `Layout` imports from Rich
   
2. **Fix toast rendering** (2 hours)
   - Connect ToastManager to console output
   - Add visual toast display
   
3. **Add command aliases** (1 hour)
   - /a → add, /d → drop, /q → exit, /u → undo, /c → commit
   
4. **Add --budget flag** (2 hours)
   - Add to args.py
   - Pass to SessionRuntime cost tracker
   
5. **Add cost warnings** (1 hour)
   - Warn before using expensive models (Claude Opus, GPT-4, etc.)

---

## Phase 3: Principal Engineer Critique

### Review Checklist:
- [ ] Changes are minimal and focused
- [ ] No breaking changes
- [ ] Follows existing code patterns
- [ ] Security considerations addressed

---

## Phase 4: Corrected Rewrite

### Lint/Format:
- Run ruff/black on modified files
- Ensure type hints if required

---

## Phase 4.5: Test Execution

### Tests:
- Dashboard imports resolve
- Toast displays correctly
- Aliases work in command parser
- --budget flag accepted
- Cost warnings trigger appropriately

---

## Implementation Order

1. Fix dashboard (safest - just adding imports)
2. Add command aliases (low risk)
3. Add --budget flag (medium risk)
4. Fix toast rendering (medium risk)
5. Add cost warnings (low risk)
