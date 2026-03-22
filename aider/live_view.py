"""
Live streaming view for Aider's pretty UI.

Provides in-place streaming updates using Rich's Live display,
inspired by kimi-cli's visualize module.
"""

import threading
from collections import deque
from typing import Optional

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text


class _ContentBlock:
    """
    Streaming text content block (assistant response or thinking).
    
    Similar to kimi-cli's _ContentBlock - renders as a spinner while
    streaming, then as formatted markdown when complete.
    """
    
    def __init__(self, is_thinking: bool = False):
        self.is_thinking = is_thinking
        self.raw_text = ""
        self._spinner = Spinner(
            "dots", 
            text="Thinking..." if is_thinking else "",
            style="dim italic" if is_thinking else ""
        )
    
    def compose(self) -> RenderableType:
        """Render for live view - show spinner while streaming."""
        if not self.raw_text:
            return self._spinner
        
        # Show partial content with thinking style if applicable
        style = "dim italic" if self.is_thinking else ""
        # Truncate very long content for live view performance
        preview = self.raw_text[:2000] + "..." if len(self.raw_text) > 2000 else self.raw_text
        return Text(preview, style=style)
    
    def compose_final(self) -> RenderableType:
        """Render final content - full markdown."""
        style = "dim italic" if self.is_thinking else ""
        return Markdown(self.raw_text, style=style)
    
    def append(self, content: str) -> None:
        """Append streaming content."""
        self.raw_text += content


class _ToolCallBlock:
    """
    Tool call display block with arguments and result.
    
    Shows bullet-point style tool calls like kimi-cli:
    "Using FetchURL (example.com)" with a spinner, then checkmark/X on completion.
    """
    
    def __init__(self, tool_name: str, tool_id: str):
        self.tool_name = tool_name
        self.tool_id = tool_id
        self.argument: Optional[str] = None  # Key argument to display
        self.result: Optional[dict] = None
        self.is_error: bool = False
        self._spinner = Spinner("dots", text="")
    
    def set_argument(self, arg: str) -> None:
        """Set the key argument to display (e.g., URL, file path)."""
        self.argument = arg
    
    def finish(self, result: dict, is_error: bool = False) -> None:
        """Mark tool call as finished with result."""
        self.result = result
        self.is_error = is_error
    
    def compose(self) -> RenderableType:
        """Render tool call with bullet point style."""
        text = Text()
        
        # "Using" vs "Used" based on completion
        text.append("Used " if self.finished else "Using ")
        text.append(self.tool_name, style="blue")
        
        if self.argument:
            text.append(" (", style="dim")
            text.append(self.argument, style="dim")
            text.append(")", style="dim")
        
        if self.finished:
            # Use checkmark for success, X for error
            bullet = "✓ " if not self.is_error else "✗ "
            bullet_style = "green" if not self.is_error else "red"
            return Text(bullet, style=bullet_style) + text
        else:
            # Still running - show with spinner
            return self._spinner, text
    
    @property
    def finished(self) -> bool:
        return self.result is not None


class _NotificationBlock:
    """Temporary notification displayed in live view."""
    
    _SEVERITY_STYLES = {
        "info": "cyan",
        "success": "green", 
        "warning": "yellow",
        "error": "red",
    }
    
    def __init__(self, message: str, severity: str = "info"):
        self.message = message
        self.severity = severity
    
    def compose(self) -> RenderableType:
        style = self._SEVERITY_STYLES.get(self.severity, "cyan")
        return Text(f"• {self.message}", style=style)


class _StatusBlock:
    """Status line shown at bottom of live view."""
    
    def __init__(self, status_data: dict):
        self.status_data = status_data
        self.text = Text(justify="right")
        self._update_text()
    
    def update(self, status_data: dict) -> None:
        self.status_data = status_data
        self._update_text()
    
    def _update_text(self) -> None:
        """Format status like kimi-cli: context usage and cost."""
        tokens_pct = self.status_data.get("tokens_pct", 0.0)
        tokens_used = self.status_data.get("tokens_used", 0)
        tokens_max = self.status_data.get("tokens_max", 0)
        cost = self.status_data.get("cost", 0.0)
        
        parts = []
        
        if tokens_max > 0:
            # Color based on usage
            if tokens_pct < 70:
                color = "#00aa00"
            elif tokens_pct < 90:
                color = "#ffaa00"
            else:
                color = "#ff5555"
            
            def fmt_tok(n):
                if n >= 1_000_000:
                    return f"{n/1_000_000:.1f}m"
                elif n >= 1_000:
                    return f"{n/1_000:.1f}k"
                return str(n)
            
            parts.append(f"[{color}]context: {tokens_pct:.1f}% ({fmt_tok(tokens_used)}/{fmt_tok(tokens_max)})[/{color}]")
        
        parts.append(f"[green]${cost:.2f}[/green]")
        
        self.text = Text.from_markup(" · ".join(parts), justify="right")
    
    def render(self) -> RenderableType:
        return self.text


class LiveView:
    """
    Live streaming display for Aider using Rich's Live.
    
    Manages:
    - Streaming content blocks (assistant responses, thinking)
    - Tool call displays with spinners
    - Notifications
    - Status line at bottom
    
    Similar to kimi-cli's _LiveView class.
    """
    
    def __init__(self, io, status_data: dict, console: Optional[Console] = None):
        self.io = io
        self.status_data = status_data
        self.console = console or io.console
        
        # Content blocks
        self.current_content_block: Optional[_ContentBlock] = None
        self.tool_call_blocks: dict[str, _ToolCallBlock] = {}
        self.notification_blocks: deque[_NotificationBlock] = deque(maxlen=4)
        self.status_block = _StatusBlock(status_data)
        
        # State
        self._live: Optional[Live] = None
        self._need_recompose = False
        self._stop_event = threading.Event()
    
    def start(self) -> None:
        """Start the live display."""
        if self._live is not None:
            return
        
        self._stop_event.clear()
        self._live = Live(
            self.compose(),
            console=self.console,
            refresh_per_second=10,
            transient=True,  # Disappear when stopped (like kimi-cli)
            vertical_overflow="visible",
        )
        self._live.start()
    
    def stop(self) -> None:
        """Stop the live display."""
        if self._live is None:
            return
        
        self._stop_event.set()
        
        # With transient=False, content stays on screen
        # Just stop the live refresh
        self._live.stop()
        self._live = None
    
    def _flush_all_content(self) -> None:
        """Flush all content blocks to terminal history."""
        # Flush current content
        self.flush_content()
        
        # Flush finished tool calls
        self.flush_finished_tool_calls()
        
        # Flush notifications
        self.flush_notifications()
    
    def compose(self, include_status: bool = True) -> RenderableType:
        """Compose the live view display."""
        blocks: list[RenderableType] = []

        # Current streaming content
        if self.current_content_block is not None:
            blocks.append(self.current_content_block.compose())

        # Tool calls
        for tool_call in self.tool_call_blocks.values():
            blocks.append(tool_call.compose())

        # Notifications
        for notification in self.notification_blocks:
            blocks.append(notification.compose())

        # Status line at bottom
        if include_status:
            blocks.append(self.status_block.render())

        return Group(*blocks)
    
    def refresh(self) -> None:
        """Schedule a refresh of the live view."""
        self._need_recompose = True
        if self._live is not None:
            self._live.update(self.compose(), refresh=True)
            self._need_recompose = False
    
    # Content management
    
    def append_content(self, content: str, is_thinking: bool = False) -> None:
        """Append streaming content to current block."""
        if not content:
            return
        
        # Create new block if needed or if thinking status changed
        if (self.current_content_block is None or 
            self.current_content_block.is_thinking != is_thinking):
            self.flush_content()
            self.current_content_block = _ContentBlock(is_thinking)
        
        self.current_content_block.append(content)
        self.refresh()
    
    def flush_content(self) -> None:
        """Flush current content block to terminal history."""
        if self.current_content_block is not None:
            self.console.print(self.current_content_block.compose_final())
            self.current_content_block = None
            self.refresh()
    
    # Tool call management
    
    def append_tool_call(self, tool_id: str, tool_name: str, argument: Optional[str] = None) -> None:
        """Add a new tool call to display."""
        self.flush_content()  # Flush any content before tool call
        
        block = _ToolCallBlock(tool_name, tool_id)
        if argument:
            block.set_argument(argument)
        
        self.tool_call_blocks[tool_id] = block
        self.refresh()
    
    def update_tool_call(self, tool_id: str, argument: str) -> None:
        """Update tool call argument (for streaming args)."""
        if block := self.tool_call_blocks.get(tool_id):
            block.set_argument(argument)
            self.refresh()
    
    def finish_tool_call(self, tool_id: str, result: dict, is_error: bool = False) -> None:
        """Mark tool call as finished."""
        if block := self.tool_call_blocks.get(tool_id):
            block.finish(result, is_error)
            self.flush_finished_tool_calls()
    
    def flush_finished_tool_calls(self) -> None:
        """Flush completed tool calls to terminal history."""
        # Find all finished tool calls at the beginning
        to_remove = []
        for tool_id, block in self.tool_call_blocks.items():
            if block.finished:
                to_remove.append(tool_id)
            else:
                # Stop at first unfinished
                break
        
        for tool_id in to_remove:
            block = self.tool_call_blocks.pop(tool_id)
            self.console.print(block.compose())
        
        if to_remove:
            self.refresh()
    
    # Notification management
    
    def add_notification(self, message: str, severity: str = "info") -> None:
        """Add a temporary notification."""
        self.notification_blocks.append(_NotificationBlock(message, severity))
        self.refresh()
    
    def flush_notifications(self) -> None:
        """Flush notifications to terminal history."""
        while self.notification_blocks:
            notif = self.notification_blocks.popleft()
            self.console.print(notif.compose())
        self.refresh()
    
    # Status updates
    
    def update_status(self, status_data: dict) -> None:
        """Update status display."""
        self.status_data = status_data
        self.status_block.update(status_data)
        self.refresh()
    
    # Context manager support
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class StreamingMarkdownParser:
    """
    Parse streaming markdown to separate thinking blocks from content.
    
    Handles <thinking> tags and reasoning_content from models.
    """
    
    def __init__(self):
        self.in_thinking_block = False
        self.buffer = ""
    
    def append(self, chunk: str) -> list[tuple[str, bool]]:
        """
        Append a chunk and return list of (content, is_thinking) tuples.
        
        Handles:
        - <thinking>...</thinking> blocks
        - Streaming partial tags
        """
        self.buffer += chunk
        results = []
        
        while True:
            if self.in_thinking_block:
                # Look for closing tag
                end_idx = self.buffer.find("</thinking>")
                if end_idx == -1:
                    # Still in thinking block, return all as thinking
                    if self.buffer:
                        results.append((self.buffer, True))
                        self.buffer = ""
                    break
                else:
                    # End of thinking block
                    if end_idx > 0:
                        results.append((self.buffer[:end_idx], True))
                    self.buffer = self.buffer[end_idx + len("</thinking>"):]
                    self.in_thinking_block = False
            else:
                # Look for opening tag
                start_idx = self.buffer.find("<thinking>")
                if start_idx == -1:
                    # No thinking block, return all as content
                    if self.buffer:
                        results.append((self.buffer, False))
                        self.buffer = ""
                    break
                else:
                    # Start of thinking block
                    if start_idx > 0:
                        results.append((self.buffer[:start_idx], False))
                    self.buffer = self.buffer[start_idx + len("<thinking>"):]
                    self.in_thinking_block = True
        
        return results
    
    def flush(self) -> list[tuple[str, bool]]:
        """Flush any remaining content."""
        results = []
        if self.buffer:
            results.append((self.buffer, self.in_thinking_block))
            self.buffer = ""
        return results
