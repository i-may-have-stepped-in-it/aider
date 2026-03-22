"""
Aider UI components for docked prompt and enhanced status bar.

Matches kimi-cli UX flow with:
- Dual prompt modes (AGENT ✨ / SHELL $)
- Docked prompt above status bar
- Rich status bar with git, cwd, context, cost
- Mode toggle with Ctrl-X
- Live output area above prompt
- Thinking state management
- File mention completion (@filename)
- Syntax highlighting in input
"""

from .docked_prompt import DockedPromptSession, PromptMode
from .status_bar import StatusBarRenderer
from .live_output import LiveOutputManager, LiveRichConsole

from .thinking_state import ThinkingStateManager, AsyncSendMessageAdapter, ThinkingState
from .input_enhancements import (
    FileMentionCompleter,
    SlashCommandCompleter,
    InputHighlighter,
    create_enhanced_completer,
)

__all__ = [
    "DockedPromptSession",
    "PromptMode",
    "StatusBarRenderer",
    "LiveOutputManager",
    "LiveRichConsole",
    "ThinkingStateManager",
    "AsyncSendMessageAdapter",
    "ThinkingState",
    "FileMentionCompleter",
    "SlashCommandCompleter",
    "InputHighlighter",
    "create_enhanced_completer",
]
