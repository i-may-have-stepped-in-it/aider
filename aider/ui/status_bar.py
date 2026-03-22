"""
Status bar renderer for docked prompt.

Renders a rich status bar showing:
- Mode indicator (agent/shell)
- Model name with thinking indicator
- Git branch with status badges
- Current working directory
- Context usage percentage
- Background task count
- Keyboard shortcuts
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Optional

from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText

from .terminal_utils import terminal_width


@dataclass
class GitStatus:
    """Git repository status."""
    branch: str = ""
    dirty: bool = False
    ahead: int = 0
    behind: int = 0
    
    @property
    def badge(self) -> str:
        """Generate git status badge."""
        if not self.branch:
            return ""
        
        parts = [self.branch]
        if self.dirty:
            parts.append("*")
        if self.ahead > 0:
            parts.append(f"↑{self.ahead}")
        if self.behind > 0:
            parts.append(f"↓{self.behind}")
        
        return "".join(parts)


class StatusBarRenderer:
    """Renders the bottom status bar for docked prompt."""
    
    # Cache for git status to avoid repeated calls
    _git_cache: dict = {}
    _git_cache_time: float = 0
    _GIT_CACHE_TTL = 1.0  # seconds
    
    def __init__(self, status_provider: Callable[[], dict]):
        self._status_provider = status_provider
        self._tip_index = 0
        self._last_tip_time = time.time()
    
    def render(self) -> AnyFormattedText:
        """Render the full status bar."""
        status = self._status_provider()
        columns = terminal_width.get_width()
        
        fragments = []
        
        # Top separator line
        fragments.append(("fg:#4d4d4d", "─" * columns))
        fragments.append(("", "\n"))
        
        # Line 1: Mode | Model | Git | CWD | Tips
        remaining = columns
        
        # Mode indicator with model
        mode = status.get("mode")
        model_name = status.get("model_name", "")
        thinking = status.get("thinking", False)
        
        mode_text = mode.value if mode else "agent"
        if model_name and mode and mode.value == "agent":
            thinking_dot = "●" if thinking else "○"
            mode_text = f"{mode_text} ({model_name} {thinking_dot})"
        
        mode_frag = f"{mode_text}  "
        fragments.append(("bold", mode_frag))
        remaining -= len(mode_frag)
        
        # Git info
        git_branch = status.get("git_branch", "")
        if git_branch:
            git_status = self._get_git_status(git_branch)
            if git_status:
                git_text = f"{git_status.badge}  "
                fragments.append(("fg:#a371f7", git_text))  # Purple for git
                remaining -= len(git_text)
        
        # CWD (shortened)
        cwd = status.get("cwd", "")
        if cwd:
            short_cwd = self._shorten_cwd(cwd)
            cwd_text = f"{short_cwd}  "
            fragments.append(("fg:#666666", cwd_text))
            remaining -= len(cwd_text)
        
        # Context percentage
        context_used = status.get("context_used", 0)
        context_total = status.get("context_total", 0)
        if context_total > 0:
            pct = (context_used / context_total) * 100
            context_text = f"context: {pct:.1f}% ({context_used/1000:.1f}k/{context_total/1000:.1f}k)"
            if remaining > len(context_text) + 2:
                # Right-align context
                padding = " " * (remaining - len(context_text) - 2)
                fragments.append(("", padding))
                color = "fg:#ff7b72" if pct > 80 else "fg:#7ee787" if pct < 50 else "fg:#ffa657"
                fragments.append((color, context_text))
        
        # Line 2: Shortcuts (left) | Cost/Agents (right)
        fragments.append(("", "\n"))
        
        shortcuts = self._get_shortcuts(status)
        right_info = self._get_right_info(status)
        
        # Calculate padding for right alignment
        shortcuts_len = len(shortcuts)
        right_len = len(right_info)
        
        fragments.append(("fg:#555555", shortcuts))
        
        if shortcuts_len + right_len < columns:
            padding = " " * (columns - shortcuts_len - right_len)
            fragments.append(("", padding))
        
        fragments.append(("fg:#79c0ff", right_info))
        
        return FormattedText(fragments)
    
    def _get_git_status(self, branch: str) -> Optional[GitStatus]:
        """Get git status with caching."""
        now = time.time()
        cwd = os.getcwd()
        cache_key = f"{cwd}:{branch}"
        
        if now - self._git_cache_time < self._GIT_CACHE_TTL:
            if cache_key in self._git_cache:
                return self._git_cache[cache_key]
        
        status = self._fetch_git_status(branch)
        self._git_cache[cache_key] = status
        self._git_cache_time = now
        return status
    
    def _fetch_git_status(self, branch: str) -> GitStatus:
        """Fetch actual git status."""
        result = GitStatus(branch=branch)
        
        try:
            # Check for dirty working tree
            result.dirty = subprocess.run(
                ["git", "diff", "--quiet"],
                capture_output=True,
                timeout=0.5,
            ).returncode != 0
            
            # Check for staged changes
            if not result.dirty:
                result.dirty = subprocess.run(
                    ["git", "diff", "--cached", "--quiet"],
                    capture_output=True,
                    timeout=0.5,
                ).returncode != 0
            
            # Check ahead/behind
            try:
                output = subprocess.run(
                    ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                )
                if output.returncode == 0:
                    ahead, behind = output.stdout.strip().split()
                    result.ahead = int(ahead)
                    result.behind = int(behind)
            except Exception:
                pass
                
        except Exception:
            pass
        
        return result
    
    def _shorten_cwd(self, cwd: str) -> str:
        """Shorten current working directory for display."""
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        
        # Limit length
        if len(cwd) > 30:
            parts = cwd.split("/")
            if len(parts) > 3:
                cwd = f".../{'/'.join(parts[-2:])}"
        
        return cwd
    
    def _get_shortcuts(self, status: dict) -> str:
        """Get keyboard shortcuts text."""
        mode = status.get("mode")
        
        if mode and mode.value == "shell":
            return "ctrl-x: agent mode | enter: run | ctrl-c: cancel"
        
        # Agent mode shortcuts
        parts = [
            "ctrl-x: shell mode",
            "tab: complete" if not status.get("running") else "tab: queue",
            "ctrl-o: editor",
            "ctrl-j: newline",
        ]
        
        if status.get("running"):
            parts.append("enter: steer")
            parts.append("esc: cancel")
        else:
            parts.append("enter: submit")
        
        return " | ".join(parts)
    
    def _get_right_info(self, status: dict) -> str:
        """Get right-aligned info (cost, agents, phase)."""
        parts = []
        
        cost = status.get("cost", 0.0)
        if cost > 0:
            parts.append(f"${cost:.3f}")
        
        agents = status.get("agents", 0)
        if agents > 0:
            parts.append(f"agents: {agents}")
        
        phase = status.get("phase", "")
        if phase and phase != "Idle":
            parts.append(f"[{phase}]")
        
        return "  ".join(parts) if parts else ""
