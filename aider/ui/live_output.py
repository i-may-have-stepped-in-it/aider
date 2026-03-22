"""
Live output manager for docked prompt UI.

Uses Rich.Live to create a fixed output area above the prompt,
allowing LLM responses to stream while the prompt stays docked.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


class LiveOutputManager:
    """
    Manages a live output area above a fixed prompt.
    
    Creates a Rich.Live display that captures all output and renders
    it in a fixed area, while keeping the prompt at the bottom.
    """
    
    def __init__(self, console: Optional[Console] = None):
        self._base_console = console or Console()
        self._live: Optional[Live] = None
        self._output_buffer: List[RenderableType] = []
        self._max_lines = 2000  # Keep last 2000 items
        self._is_active = False
        self._lock = threading.Lock()
        self._last_refresh = 0
        self._refresh_delay = 0.05  # Max 20Hz refresh
    
    def start(self) -> None:
        """Start the live output display."""
        with self._lock:
            if self._is_active:
                return
            
            # Create a Live display with the output buffer
            # auto_refresh=False is key to avoiding flicker
            self._live = Live(
                self._render_output(),
                console=self._base_console,
                auto_refresh=False,
                screen=False,
                transient=False,
                vertical_overflow="visible",
            )
            self._live.start()
            self._is_active = True
    
    def stop(self) -> None:
        """Stop the live output display."""
        with self._lock:
            if not self._is_active or not self._live:
                return
            
            # Final refresh to ensure all content is visible
            self.refresh(force=True)
            self._live.stop()
            self._is_active = False
            self._live = None
            
            # Clear buffer to free memory
            self._output_buffer.clear()
    
    def add_renderable(self, renderable: RenderableType, append: bool = False) -> None:
        """Add a rich renderable directly to the output area."""
        with self._lock:
            if append and self._output_buffer and isinstance(self._output_buffer[-1], Text) and isinstance(renderable, Text):
                # Append to last Text object
                self._output_buffer[-1].append(renderable)
            else:
                self._output_buffer.append(renderable)
            
            # Trim buffer
            if len(self._output_buffer) > self._max_lines:
                self._output_buffer = self._output_buffer[-self._max_lines:]
            
            # Request refresh
            if self._is_active and self._live:
                self.refresh()
    
    def refresh(self, force: bool = False) -> None:
        """Refresh the live display if throttled delay has passed."""
        now = time.time()
        if not force and now - self._last_refresh < self._refresh_delay:
            return
            
        if self._is_active and self._live:
            self._live.update(self._render_output(), refresh=True)
            self._last_refresh = now
    
    def _render_output(self) -> Group:
        """Render the current output buffer as a Group."""
        if not self._output_buffer:
            return Group(Text(""))
        
        return Group(*self._output_buffer)
    
    def clear(self) -> None:
        """Clear the output buffer."""
        with self._lock:
            self._output_buffer.clear()
            if self._is_active and self._live:
                self._live.update(self._render_output(), refresh=True)
    
    @property
    def is_active(self) -> bool:
        return self._is_active


class LiveRichConsole:
    """
    A robust console wrapper that routes output to LiveOutputManager.
    
    Implements a subset of the Rich Console interface for routing 
    output to the live area during background generation.
    """
    
    def __init__(self, live_manager: LiveOutputManager, base_console: Console):
        self._live = live_manager
        self._base = base_console
        self._capturing = True
        # Cache a capture console to avoid repeated instantiation
        self._capture_console = Console(
            width=self._base.width, 
            force_terminal=True, 
            color_system=self._base.color_system
        )
    
    def print(self, *objects: Any, **kwargs: Any) -> None:
        """Print to the live output area or base console."""
        if not self._capturing or not self._live.is_active:
            self._base.print(*objects, **kwargs)
            return
            
        try:
            # Check if we should append (no newline)
            append = kwargs.get("end") == ""

            # If it's a single rich renderable, add it directly
            if len(objects) == 1 and hasattr(objects[0], "__rich_console__"):
                if isinstance(objects[0], Text):
                    self._live.add_renderable(objects[0], append=append)
                else:
                    self._live.add_renderable(objects[0])
                return

            # Otherwise, render to a string and add as Text
            with self._capture_console.capture() as capture:
                self._capture_console.print(*objects, **kwargs)
            
            self._live.add_renderable(Text.from_ansi(capture.get()), append=append)
        except Exception:
            # Fallback to base console if anything goes wrong in the live bridge
            self._base.print(*objects, **kwargs)

    def rule(self, title: str = "", **kwargs: Any) -> None:
        """Draw a horizontal rule in the live area."""
        from rich.rule import Rule
        self.print(Rule(title, **kwargs))

    def status(self, status: str, **kwargs: Any):
        """Pass through status to base console (usually shows in fixed area)."""
        return self._base.status(status, **kwargs)

    def log(self, *objects: Any, **kwargs: Any) -> None:
        """Log to the live area."""
        # Logs usually include timestamps, we'll let Rich handle it in a capture
        from rich.console import Console
        capture_console = Console(width=self._base.width, force_terminal=True)
        with capture_console.capture() as capture:
            capture_console.log(*objects, **kwargs)
        
        self._live.add_renderable(Text.from_ansi(capture.get()))

    def clear(self) -> None:
        """Clear the live output area."""
        self._live.clear()

    @property
    def width(self) -> int:
        return self._base.width

    @property
    def height(self) -> int:
        return self._base.height

    def __getattr__(self, name: str):
        """Pass through other attributes/methods to base console."""
        return getattr(self._base, name)
