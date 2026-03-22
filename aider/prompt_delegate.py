"""
Running Prompt Delegate protocol for Aider.

Allows the input prompt to remain active during LLM generation,
enabling users to type ahead or "steer" the current generation.

Pattern inspired by kimi-cli's RunningPromptDelegate.
"""

import threading
from typing import Callable, Optional, Protocol

from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText


class RunningPromptDelegate(Protocol):
    """
    Protocol for handling input while LLM is generating.

    When attached to a CustomPromptSession, the delegate can:
    - Render content in the prompt area during streaming
    - Handle specific keyboard events
    - Receive user input submitted during generation
    """

    def render_running_prompt_body(self, columns: int) -> AnyFormattedText:
        """
        Render content shown in the prompt area during streaming.

        This replaces the normal prompt content while the LLM is working.
        """
        ...

    def running_prompt_placeholder(self) -> Optional[AnyFormattedText]:
        """
        Placeholder text shown when input is empty during streaming.

        Return None for no placeholder.
        """
        ...

    def should_handle_running_prompt_key(self, key: str) -> bool:
        """
        Return True if this delegate handles the given key.

        Keys like "escape" for cancel, "up"/"down" for navigation.
        """
        ...

    def handle_running_prompt_key(self, key: str, event) -> None:
        """
        Handle a keypress during streaming.

        Only called if should_handle_running_prompt_key returned True.
        """
        ...

    def handle_local_input(self, user_input: str, queue: bool = False) -> None:
        """
        Called when user submits input while LLM is streaming.

        Args:
            user_input: The text submitted
            queue: True if Tab key (queue for next turn),
                   False if Enter key (steer current generation)
        """
        ...


class PromptLiveViewDelegate:
    """
    Combined Live View + Running Prompt Delegate.

    Manages both the live display above the prompt and the
    running prompt area below it during LLM generation.
    """

    def __init__(
        self,
        io,
        status_data: dict,
        steer_callback: Optional[Callable[[str], None]] = None,
        cancel_callback: Optional[Callable[[], None]] = None,
    ):
        from aider.live_view import LiveView

        self.io = io
        self.steer_callback = steer_callback
        self.cancel_callback = cancel_callback
        self.pending_steers: list[str] = []
        self.cancelled = False

        # Create underlying LiveView for content display
        self.live_view = LiveView(io, status_data)

    def _invalidate(self) -> None:
        """Force a UI refresh if a prompt session is active."""
        if self.io.prompt_session:
            self.io.prompt_session.app.invalidate()

    # RunningPromptDelegate implementation

    def render_running_prompt_body(self, columns: int) -> AnyFormattedText:
        """Render the live view content in the prompt area."""
        # Get the current live view composition (without status line)
        renderable = self.live_view.compose(include_status=False)

        # Convert Rich renderable to prompt_toolkit formatted text
        # This is a simplified version - full implementation would
        # render to ANSI and convert
        from rich.console import Console
        from io import StringIO

        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=columns)
        console.print(renderable)

        # Convert ANSI to formatted text (simplified)
        text = buf.getvalue()
        return FormattedText([("", text)])

    def running_prompt_placeholder(self) -> Optional[AnyFormattedText]:
        """Placeholder for empty input during streaming."""
        return FormattedText([("fg:#666666", "Tab: queue · Enter: steer · Esc: cancel")])

    def should_handle_running_prompt_key(self, key: str) -> bool:
        """Handle ESC for cancel and arrow keys."""
        return key in ("escape", "ctrl-c")

    def handle_running_prompt_key(self, key: str, event) -> None:
        """Handle cancel keys."""
        if key == "escape" and self.cancel_callback:
            self.cancelled = True
            self.cancel_callback()

    def handle_local_input(self, user_input: str, queue: bool = False) -> None:
        """
        Handle user input submitted while LLM is streaming.

        Args:
            user_input: The text submitted
            queue: If True, queue for next turn (Tab key).
                   If False, steer current generation (Enter key).

        Codex-style UX:
        - Tab = queue message (runs after current generation)
        - Enter = steer/interrupt (affects current generation)
        """
        if queue:
            # Queue for next turn (Tab key)
            self.io.console.print(f"[bold cyan]Queued:[/bold cyan] {user_input}")
            self.pending_steers.append(user_input)
            # Also notify via callback for tracking
            if self.steer_callback:
                self.steer_callback(user_input, is_steer=False)
        else:
            # Steer current generation (Enter key)
            self.io.console.print(f"[bold yellow]Steer:[/bold yellow] {user_input}")
            if self.steer_callback:
                self.steer_callback(user_input, is_steer=True)

    # LiveView delegation

    def start(self) -> None:
        """Start the live view."""
        self.live_view.start()

    def stop(self) -> None:
        """Stop the live view."""
        self.live_view.stop()

    def append_content(self, content: str, is_thinking: bool = False) -> None:
        """Append streaming content."""
        self.live_view.append_content(content, is_thinking)
        self._invalidate()

    def append_tool_call(
        self, tool_id: str, tool_name: str, argument: Optional[str] = None
    ) -> None:
        """Add a tool call."""
        self.live_view.append_tool_call(tool_id, tool_name, argument)
        self._invalidate()

    def finish_tool_call(
        self, tool_id: str, result: dict, is_error: bool = False
    ) -> None:
        """Finish a tool call."""
        self.live_view.finish_tool_call(tool_id, result, is_error)
        self._invalidate()

    def add_notification(self, message: str, severity: str = "info") -> None:
        """Add a notification."""
        self.live_view.add_notification(message, severity)
        self._invalidate()

    def update_status(self, status_data: dict) -> None:
        """Update status display."""
        self.live_view.update_status(status_data)
        self._invalidate()

    def get_pending_steers(self) -> list[str]:
        """Get and clear pending steer messages."""
        steers = self.pending_steers.copy()
        self.pending_steers.clear()
        return steers


class QueuedInputManager:
    """
    Manages input queued while LLM is generating.

    Follows kimi-cli's pattern of allowing users to type ahead
    while the agent is working.
    """

    def __init__(self):
        self.queue: list[str] = []
        self._lock = None

    def add(self, message: str) -> None:
        """Add a message to the queue."""
        if self._lock is None:
            self._lock = threading.Lock()

        with self._lock:
            self.queue.append(message)

    def get_next(self) -> Optional[str]:
        """Get the next queued message, or None if empty."""
        if self._lock is None:
            return None

        with self._lock:
            if self.queue:
                return self.queue.pop(0)
            return None

    def has_pending(self) -> bool:
        """Check if there are queued messages."""
        return len(self.queue) > 0

    def clear(self) -> None:
        """Clear all queued messages."""
        if self._lock:
            with self._lock:
                self.queue.clear()

    def peek_all(self) -> list[str]:
        """Get all queued messages without removing them."""
        return self.queue.copy()


SteerCallback = Callable[[str], None]
CancelCallback = Callable[[], None]


def create_running_prompt_delegate(
    io,
    status_data: dict,
    steer_callback: Optional[SteerCallback] = None,
    cancel_callback: Optional[CancelCallback] = None,
) -> PromptLiveViewDelegate:
    """
    Factory function to create a running prompt delegate.

    Usage:
        delegate = create_running_prompt_delegate(
            io=self.io,
            status_data=self.io.status_data,
            steer_callback=self._handle_steer,
            cancel_callback=self._handle_cancel,
        )
        self.io.prompt_session.attach_running_prompt(delegate)
    """
    return PromptLiveViewDelegate(
        io=io,
        status_data=status_data,
        steer_callback=steer_callback,
        cancel_callback=cancel_callback,
    )
