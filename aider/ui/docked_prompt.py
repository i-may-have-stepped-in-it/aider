"""
Docked prompt implementation matching kimi-cli UX.

Features:
- Prompt docked at bottom with separator line
- Status/MCP info rendered above prompt
- No continuation prompt (clean multiline)
- Dual AGENT (✨) / SHELL ($) modes with Ctrl-X toggle
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.completion import Completer
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from .terminal_utils import terminal_width


class PromptMode(Enum):
    """Dual prompt modes matching kimi-cli."""
    AGENT = "agent"
    SHELL = "shell"
    
    def toggle(self) -> PromptMode:
        return PromptMode.SHELL if self == PromptMode.AGENT else PromptMode.AGENT
    
    @property
    def symbol(self) -> str:
        return PROMPT_SYMBOL if self == PromptMode.AGENT else PROMPT_SYMBOL_SHELL
    
    @property
    def thinking_symbol(self) -> str:
        return PROMPT_SYMBOL_THINKING if self == PromptMode.AGENT else "⚡"


@dataclass
class PromptStatus:
    """Status data for the prompt session."""
    mode: PromptMode = PromptMode.AGENT
    model_name: str = ""
    thinking: bool = False
    git_branch: str = ""
    git_dirty: bool = False
    cwd: str = ""
    context_used: int = 0
    context_total: int = 0
    cost: float = 0.0
    agents: int = 0
    phase: str = "Idle"


# Prompt symbols
PROMPT_SYMBOL = "✨"
PROMPT_SYMBOL_SHELL = "$"
PROMPT_SYMBOL_THINKING = "💫"


class DockedPromptSession:
    """
    Docked prompt session matching kimi-cli layout.
    
    Layout:
    [status line with model, git, cwd, context]
    ──────────────────────────────────────────
    ✨ (user types here)
    """
    
    def __init__(
        self,
        model_name: str = "",
        input_history_file: Optional[str] = None,
        editing_mode: Any = None,
        agent_completer: Optional[Completer] = None,
        shell_completer: Optional[Completer] = None,
        on_mode_toggle: Optional[Callable[[PromptMode], None]] = None,
    ):
        self._status = PromptStatus(model_name=model_name)
        self._on_mode_toggle = on_mode_toggle
        self._input_history_file = input_history_file
        self._editing_mode = editing_mode
        self._agent_completer = agent_completer
        self._shell_completer = shell_completer
        
        # Running state
        self._running = False
        self._queued_input: Optional[str] = None
        
        # History
        self._history = self._load_history()
        
        # Key bindings
        self._kb = self._build_key_bindings()
        
        # Build session
        self._session = self._build_session()

    def _load_history(self) -> Any:
        """Load command history."""
        if self._input_history_file:
            try:
                return FileHistory(self._input_history_file)
            except Exception:
                pass
        return InMemoryHistory()
    
    def _build_key_bindings(self) -> KeyBindings:
        """Build key bindings matching kimi-cli behavior."""
        from prompt_toolkit.filters import has_completions, is_searching
        
        kb = KeyBindings()
        
        @kb.add("c-x", eager=True)
        def toggle_mode(event):
            """Ctrl-X toggles between AGENT and SHELL modes."""
            if not self._running:
                self._status.mode = self._status.mode.toggle()
                if self._on_mode_toggle:
                    self._on_mode_toggle(self._status.mode)
                self._apply_mode()
                event.app.invalidate()
        
        @kb.add("enter", filter=has_completions)
        def accept_completion(event):
            """Accept first completion when Enter is pressed and completions shown."""
            buff = event.current_buffer
            if buff.complete_state and buff.complete_state.completions:
                completion = buff.complete_state.current_completion
                if not completion:
                    completion = buff.complete_state.completions[0]
                buff.apply_completion(completion)
        
        @kb.add("enter", eager=True, filter=~is_searching & ~has_completions)
        def submit_input(event):
            """Enter submits the input."""
            event.current_buffer.validate_and_handle()
        
        @kb.add("c-j", eager=True)
        @kb.add("escape", "enter", eager=True)  # Alt+Enter
        def insert_newline(event):
            """Ctrl-J or Alt-Enter inserts a newline."""
            event.current_buffer.insert_text("\n")
        
        return kb
    
    def _build_session(self) -> PromptSession:
        """Build the prompt_toolkit session."""
        # Determine completer based on mode
        completer = self._shell_completer if self._status.mode == PromptMode.SHELL else self._agent_completer
        
        session_kwargs = {
            "message": self._render_message,
            "completer": completer,
            "complete_while_typing": True,
            "multiline": True,
            "key_bindings": self._kb,
            "history": self._history,
            "bottom_toolbar": self._render_bottom_toolbar,
            "style": Style.from_dict({
                "bottom-toolbar": "noreverse",
            }),
        }
        
        if self._editing_mode:
            session_kwargs["editing_mode"] = self._editing_mode
        
        return PromptSession[str](**session_kwargs)
    
    def _apply_mode(self) -> None:
        """Apply current mode to session."""
        # Update completer
        if self._status.mode == PromptMode.SHELL:
            self._session.default_buffer.completer = self._shell_completer
        else:
            self._session.default_buffer.completer = self._agent_completer
    
    def _render_message(self) -> FormattedText:
        """Render the full prompt message including status and separator."""
        columns = terminal_width.get_width()
        
        fragments = FormattedText()
        
        # Add status line above prompt
        status_line = self._render_status_line()
        if status_line:
            fragments.extend(status_line)
            fragments.append(("", "\n"))
        
        # Add separator line
        fragments.append(("fg:#4d4d4d", "─" * columns))
        fragments.append(("", "\n"))
        
        # Add prompt symbol
        symbol = self._get_prompt_symbol()
        fragments.append(("", f"{symbol} "))
        
        return fragments
    
    def _render_status_line(self) -> FormattedText:
        """Render single-line status (model, git, cwd, context)."""
        fragments = FormattedText()
        
        # Mode and model
        mode_text = self._status.mode.value
        if self._status.model_name and self._status.mode == PromptMode.AGENT:
            thinking_dot = "●" if self._status.thinking else "○"
            mode_text = f"{mode_text} ({self._status.model_name} {thinking_dot})"
        fragments.append(("bold", mode_text))
        fragments.append(("", "  "))
        
        # Git branch
        if self._status.git_branch:
            badge = self._status.git_branch
            if self._status.git_dirty:
                badge += "*"
            fragments.append(("fg:#a371f7", badge))  # Purple for git
            fragments.append(("", "  "))
        
        # CWD
        if self._status.cwd:
            short_cwd = self._shorten_cwd(self._status.cwd)
            fragments.append(("fg:#666666", short_cwd))
            fragments.append(("", "  "))
        
        return fragments
    
    def _render_bottom_toolbar(self) -> FormattedText:
        """Render bottom toolbar with shortcuts, context bar, and cost."""
        columns = terminal_width.get_width()
        
        fragments = FormattedText()
        
        # Build right-side info (context bar + cost)
        right_parts = []
        
        # Context visualization (mini progress bar)
        if self._status.context_total > 0:
            pct = (self._status.context_used / self._status.context_total) * 100
            used_k = self._status.context_used / 1000
            total_k = self._status.context_total / 1000
            
            # Color based on usage
            if pct > 80:
                bar_color = "#ff7b72"  # Red
            elif pct < 50:
                bar_color = "#7ee787"  # Green
            else:
                bar_color = "#ffa657"  # Orange
            
            # Mini bar: [████    ] 45%
            bar_width = 8
            filled = int((pct / 100) * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            
            context_str = f"[{bar}] {pct:.0f}% ({used_k:.1f}k/{total_k:.0f}k)"
            right_parts.append((f"fg:{bar_color}", context_str))
        
        # Cost display
        if self._status.cost > 0:
            cost_str = f"${self._status.cost:.3f}"
            right_parts.append(("fg:#79c0ff", cost_str))
        
        # Build right side string
        right_text = "  ".join(text for _, text in right_parts)
        
        # Left side: shortcuts
        shortcuts = self._get_shortcuts()
        
        # Calculate layout
        shortcuts_len = len(shortcuts)
        right_len = len(right_text)
        
        # Add shortcuts
        fragments.append(("fg:#555555", shortcuts))
        
        # Add right-aligned info with padding
        if right_text and shortcuts_len + right_len < columns:
            padding = " " * (columns - shortcuts_len - right_len)
            fragments.append(("", padding))
            
            # Add styled parts
            for style, text in right_parts:
                fragments.append((style, text))
                fragments.append(("", "  "))
            # Remove trailing space
            if fragments and fragments[-1] == ("", "  "):
                fragments.pop()
        
        return fragments
    
    def _get_prompt_symbol(self) -> str:
        """Get the appropriate prompt symbol."""
        if self._status.mode == PromptMode.SHELL:
            return PROMPT_SYMBOL_SHELL
        if self._running:
            return PROMPT_SYMBOL_THINKING
        return PROMPT_SYMBOL
    
    def _get_shortcuts(self) -> str:
        """Get keyboard shortcuts text."""
        if self._status.mode == PromptMode.SHELL:
            return "ctrl-x: agent mode | enter: run | ctrl-c: cancel"
        
        parts = [
            "ctrl-x: shell mode",
            "tab: complete" if not self._running else "tab: queue",
            "ctrl-o: editor",
            "ctrl-j: newline",
        ]
        
        if self._running:
            parts.extend(["enter: steer", "esc: cancel"])
        else:
            parts.append("enter: submit")
        
        return " | ".join(parts)
    
    def _shorten_cwd(self, cwd: str) -> str:
        """Shorten current working directory."""
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        
        if len(cwd) > 25:
            parts = cwd.split("/")
            if len(parts) > 2:
                cwd = f".../{'/'.join(parts[-2:])}"
        
        return cwd
    
    async def prompt_async(self, message: str = "", **kwargs) -> Optional[str]:
        """Get input asynchronously (compatibility with AsyncAiderPromptSession)."""
        try:
            # Use patch_stdout so output appears above the prompt
            with patch_stdout(raw=True):
                text = await self._session.prompt_async()
            if text:
                self._last_history_content = text
            return text
        except (EOFError, KeyboardInterrupt):
            return None
    
    def set_running(self, running: bool):
        """Set running state."""
        self._running = running
        if not running:
            self._queued_input = None
        self.invalidate()
    
    def has_queued_input(self) -> bool:
        return self._queued_input is not None
    
    def get_queued_input(self) -> Optional[str]:
        text = self._queued_input
        self._queued_input = None
        return text
    
    def queue_input(self, text: str) -> None:
        """Queue input for later processing."""
        self._queued_input = text
    
    def update_status(self, **kwargs):
        """Update status data."""
        for key, value in kwargs.items():
            if hasattr(self._status, key):
                setattr(self._status, key, value)
        self.invalidate()
    
    def invalidate(self):
        """Invalidate UI."""
        app = get_app_or_none()
        if app:
            app.invalidate()
    
    # Compatibility methods for AsyncPromptSession interface
    def attach_running_prompt(self, delegate):
        """Attach a running prompt delegate (compatibility with AsyncAiderPromptSession)."""
        self._running = True
        self.invalidate()
    
    def detach_running_prompt(self):
        """Detach the running prompt delegate."""
        self._running = False
        self.invalidate()
    
    @property
    def session(self) -> PromptSession:
        return self._session
    
    @property
    def mode(self) -> PromptMode:
        return self._status.mode
    
    @mode.setter
    def mode(self, value: PromptMode):
        self._status.mode = value
        self._apply_mode()
        self.invalidate()
