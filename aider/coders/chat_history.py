from typing import Any, Dict, List, Optional

from aider.history import ChatSummary


class ChatHistory:
    """
    Manages the history of chat messages, including summarization and context management.
    """

    def __init__(
        self,
        summarizer: Optional[ChatSummary] = None,
        done_messages: Optional[List[Dict[str, Any]]] = None,
        cur_messages: Optional[List[Dict[str, Any]]] = None,
    ):
        self.summarizer = summarizer
        self.done_messages = done_messages or []
        self.cur_messages = cur_messages or []
        self.summarized_done_messages = []
        self.summarizing_messages = None

    def add_message(self, role: str, content: str):
        """Adds a message to the current message list."""
        self.cur_messages.append({"role": role, "content": content})

    def finalize_turn(self):
        """Moves current messages to done_messages and clears the current list."""
        self.done_messages.extend(self.cur_messages)
        self.cur_messages = []

    def clear(self):
        """Clears all history."""
        self.done_messages = []
        self.cur_messages = []
        self.summarized_done_messages = []

    def get_full_history(self) -> List[Dict[str, Any]]:
        """Returns the full list of messages (done + current)."""
        return self.done_messages + self.cur_messages

    def summarize_if_needed(self):
        """Checks if history needs summarization and performs it if a summarizer is available."""
        if not self.summarizer:
            return

        # Simple check for now, can be more complex based on token counts
        if self.summarizer.too_big(self.done_messages):
            self.done_messages = self.summarizer.summarize(self.done_messages)

    def __len__(self):
        return len(self.done_messages) + len(self.cur_messages)
