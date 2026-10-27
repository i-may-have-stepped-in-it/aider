import base64
import functools
import logging
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import sys
import threading

import threading
import time
import webbrowser
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Union

from prompt_toolkit.completion import Completer, Completion, ThreadedCompleter
from prompt_toolkit.cursor_shapes import ModalCursorShapeConfig
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.filters import Condition, is_searching
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.keys import Keys
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.shortcuts import CompleteStyle, PromptSession
from prompt_toolkit.styles import Style
from pygments.lexers import MarkdownLexer, guess_lexer_for_filename
from pygments.token import Token
from rich.color import ColorParseError
from rich.columns import Columns
from rich.console import Console
from rich.markdown import Markdown
from rich.style import Style as RichStyle
from rich.text import Text

from aider.mdstream import MarkdownStream
from aider.ui import DockedPromptSession, PromptMode
from aider.ui.live_output import LiveOutputManager, LiveRichConsole
from aider.async_compat import AsyncLock, get_running_loop
from aider.async_running_prompt import AsyncRunningPromptManager

from .dump import dump  # noqa: F401
from .editor import pipe_editor
from .utils import is_audio_file, is_image_file, is_video_file

# Configure logging
logger = logging.getLogger(__name__)

# Constants
NOTIFICATION_MESSAGE = "Aider is waiting for your input"


class AsyncAiderPromptSession:
    """
    Async-aware wrapper for prompt_toolkit's PromptSession.
    
    Provides async prompt support with proper integration for background
    generation scenarios.
    """
    
    def __init__(self, session: PromptSession = None):
        self._session = session
        self._running_prompt_delegate = None
        self._input_queue = []
        self._queue_lock = threading.Lock()
        # Backward compatibility: track last submission state
        self.last_submission_was_running = False
    
    @property
    def session(self) -> PromptSession:
        return self._session
    
    @property
    def app(self):
        if self._session is None:
            return None
        return self._session.app
    
    def attach_running_prompt(self, delegate):
        """Attach a running prompt delegate for background generation."""
        self._running_prompt_delegate = delegate
        if self._session is not None and self._session.app:
            self._session.app.invalidate()
    
    def detach_running_prompt(self, delegate=None):
        """Detach the running prompt delegate."""
        self._running_prompt_delegate = None
        if self._session is not None and self._session.app:
            self._session.app.invalidate()
    
    @property
    def running_prompt_delegate(self):
        return self._running_prompt_delegate
    
    def queue_input(self, text: str):
        """Queue input for later processing."""
        with self._queue_lock:
            self._input_queue.append(text)
    
    def get_queued_input(self) -> Optional[str]:
        """Get queued input if any."""
        with self._queue_lock:
            return self._input_queue.pop(0) if self._input_queue else None
    
    def has_queued_input(self) -> bool:
        """Check if there's queued input."""
        with self._queue_lock:
            return bool(self._input_queue)
    
    async def prompt_async(self, message: str = "", **kwargs) -> str:
        """
        Async prompt using prompt_toolkit's prompt_async.
        
        Uses patch_stdout to allow background output during prompt.
        """
        
        with safe_patch_stdout():
            return await self._session.prompt_async(message, **kwargs)
    
    def prompt_sync(self, message: str = "", **kwargs) -> str:
        """Synchronous prompt (original behavior)."""
        return self._session.prompt(message, **kwargs)


@contextmanager
def safe_patch_stdout():
    """
    prompt_toolkit's patch_stdout, falling back to plain output when there's no
    real console (Windows under Git Bash/mintty, piped output, CI).
    """
    from contextlib import ExitStack

    from prompt_toolkit.patch_stdout import patch_stdout

    stack = ExitStack()
    try:
        stack.enter_context(patch_stdout(raw=True))
    except Exception:
        pass
    with stack:
        yield


def ensure_hash_prefix(color):
    """Ensure hex color values have a # prefix."""
    if not color:
        return color
    if isinstance(color, str) and color.strip() and not color.startswith("#"):
        # Check if it's a valid hex color (3 or 6 hex digits)
        if all(c in "0123456789ABCDEFabcdef" for c in color) and len(color) in (3, 6):
            return f"#{color}"
    return color


def restore_multiline(func):
    """Decorator to restore multiline mode after function execution"""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        orig_multiline = self.multiline_mode
        self.multiline_mode = False
        try:
            return func(self, *args, **kwargs)
        except Exception:
            raise
        finally:
            self.multiline_mode = orig_multiline

    return wrapper


class CommandCompletionException(Exception):
    """Raised when a command should use the normal autocompleter instead of
    command-specific completion."""

    pass


@dataclass
class ConfirmGroup:
    preference: str = None
    show_group: bool = True

    def __init__(self, items=None):
        if items is not None:
            self.show_group = len(items) > 1


class AutoCompleter(Completer):
    def __init__(
        self, root, rel_fnames, addable_rel_fnames, commands, encoding, abs_read_only_fnames=None
    ):
        self.addable_rel_fnames = addable_rel_fnames
        self.rel_fnames = rel_fnames
        self.encoding = encoding
        self.abs_read_only_fnames = abs_read_only_fnames or []

        fname_to_rel_fnames = defaultdict(list)
        for rel_fname in addable_rel_fnames:
            fname = os.path.basename(rel_fname)
            if fname != rel_fname:
                fname_to_rel_fnames[fname].append(rel_fname)
        self.fname_to_rel_fnames = fname_to_rel_fnames

        self.words = set()

        self.commands = commands
        self.command_completions = dict()
        if commands:
            self.command_names = self.commands.get_commands()

        for rel_fname in addable_rel_fnames:
            self.words.add(rel_fname)

        for rel_fname in rel_fnames:
            self.words.add(rel_fname)

        all_fnames = [Path(root) / rel_fname for rel_fname in rel_fnames]
        if abs_read_only_fnames:
            all_fnames.extend(abs_read_only_fnames)

        self.all_fnames = all_fnames
        self.tokenized = False

    def tokenize(self):
        if self.tokenized:
            return
        self.tokenized = True

        for fname in self.all_fnames:
            try:
                with open(fname, "r", encoding=self.encoding) as f:
                    content = f.read()
            except (FileNotFoundError, UnicodeDecodeError, IsADirectoryError):
                continue
            try:
                lexer = guess_lexer_for_filename(fname, content)
            except Exception:  # On Windows, bad ref to time.clock which is deprecated
                continue

            tokens = list(lexer.get_tokens(content))
            self.words.update(
                (token[1], f"`{token[1]}`") for token in tokens if token[0] in Token.Name
            )

    def get_command_completions(self, document, complete_event, text, words):
        if len(words) == 1 and not text[-1].isspace():
            partial = words[0].lower()
            candidates = [cmd for cmd in self.command_names if cmd.startswith(partial)]
            for candidate in sorted(candidates):
                yield Completion(candidate, start_position=-len(words[-1]))
            return

        if len(words) <= 1 or text[-1].isspace():
            return

        cmd = words[0]
        partial = words[-1].lower()

        match_result = self.commands.matching_commands(cmd)
        if match_result is None:
            return

        matches, _, _, _ = match_result
        if len(matches) == 1:
            cmd = matches[0]
        elif cmd not in matches:
            return

        raw_completer = self.commands.get_raw_completions(cmd)
        if raw_completer:
            yield from raw_completer(document, complete_event)
            return

        if cmd not in self.command_completions:
            candidates = self.commands.get_completions(cmd)
            self.command_completions[cmd] = candidates
        else:
            candidates = self.command_completions[cmd]

        if candidates is None:
            return

        candidates = [word for word in candidates if partial in word.lower()]
        for candidate in sorted(candidates):
            yield Completion(candidate, start_position=-len(words[-1]))

    def get_completions(self, document, complete_event):
        self.tokenize()

        text = document.text_before_cursor
        words = text.split()
        if not words:
            return

        if text and text[-1].isspace():
            # don't keep completing after a space
            return

        if text[0] == "/":
            try:
                yield from self.get_command_completions(document, complete_event, text, words)
                return
            except CommandCompletionException:
                # Fall through to normal completion
                pass

        candidates = self.words
        candidates.update(set(self.fname_to_rel_fnames))
        candidates = [word if type(word) is tuple else (word, word) for word in candidates]

        last_word = words[-1]

        # Only provide completions if the user has typed at least 3 characters
        if len(last_word) < 3:
            return

        completions = []
        for word_match, word_insert in candidates:
            if word_match.lower().startswith(last_word.lower()):
                completions.append((word_insert, -len(last_word), word_match))

                rel_fnames = self.fname_to_rel_fnames.get(word_match, [])
                if rel_fnames:
                    for rel_fname in rel_fnames:
                        completions.append((rel_fname, -len(last_word), rel_fname))

        for ins, pos, match in sorted(completions):
            yield Completion(ins, start_position=pos, display=match)


class InputOutput:
    num_error_outputs = 0
    num_user_asks = 0
    clipboard_watcher = None
    bell_on_next_input = False
    notifications_command = None

    def __init__(
        self,
        pretty=None,
        yes=None,
        input_history_file=None,
        chat_history_file=None,
        input=None,
        output=None,
        user_input_color="blue",
        tool_output_color=None,
        tool_error_color="red",
        tool_warning_color="#FFA500",
        assistant_output_color="blue",
        completion_menu_color=None,
        completion_menu_bg_color=None,
        completion_menu_current_color=None,
        completion_menu_current_bg_color=None,
        code_theme="default",
        encoding="utf-8",
        line_endings="platform",
        dry_run=False,
        llm_history_file=None,
        editingmode=EditingMode.EMACS,
        fancy_input=True,
        file_watcher=None,
        multiline_mode=False,
        root=".",
        notifications=False,
        notifications_command=None,
        enable_dashboard=False,
        theme=None,
    ):
        from aider import themes

        explicit_pretty = pretty is not None
        self.theme = themes.get(theme) if theme else themes.THEMES["classic"]
        self.placeholder = None
        self.interrupted = False
        self.never_prompts = set()
        self.editingmode = editingmode
        self.multiline_mode = multiline_mode
        self.bell_on_next_input = False
        self.notifications = notifications
        self.enable_dashboard = enable_dashboard
        if notifications and notifications_command is None:
            self.notifications_command = self.get_default_notification_command()
        else:
            self.notifications_command = notifications_command

        if pretty is None:
            no_color = os.environ.get("NO_COLOR")
            pretty = not (no_color is not None and no_color != "")

        self.code_theme = code_theme

        self.input = input
        self.output = output

        self.pretty = pretty
        if self.output:
            self.pretty = False

        self.yes = yes

        self.input_history_file = input_history_file
        if self.input_history_file:
            try:
                Path(self.input_history_file).parent.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError) as e:
                self.tool_warning(f"Could not create directory for input history: {e}")
                self.input_history_file = None
        self.llm_history_file = llm_history_file
        if chat_history_file is not None:
            self.chat_history_file = Path(chat_history_file)
        else:
            self.chat_history_file = None

        self.encoding = encoding
        valid_line_endings = {"platform", "lf", "crlf"}
        if line_endings not in valid_line_endings:
            raise ValueError(
                f"Invalid line_endings value: {line_endings}. "
                f"Must be one of: {', '.join(valid_line_endings)}"
            )
        self.newline = (
            None if line_endings == "platform" else "\n" if line_endings == "lf" else "\r\n"
        )
        self.dry_run = dry_run

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.append_chat_history(f"\n# aider chat started at {current_time}\n\n")

        self.prompt_session = None
        self.is_dumb_terminal = os.environ.get("TERM") == "dumb"

        if self.is_dumb_terminal and not explicit_pretty:
            self.pretty = False
            fancy_input = False

        self.fancy_input = fancy_input
        self.user_input_color = ensure_hash_prefix(user_input_color) if self.pretty else None
        self.tool_output_color = ensure_hash_prefix(tool_output_color) if self.pretty else None
        self.tool_error_color = ensure_hash_prefix(tool_error_color) if self.pretty else None
        self.tool_warning_color = ensure_hash_prefix(tool_warning_color) if self.pretty else None
        self.assistant_output_color = ensure_hash_prefix(assistant_output_color)
        self.completion_menu_color = ensure_hash_prefix(completion_menu_color) if self.pretty else None
        self.completion_menu_bg_color = (
            ensure_hash_prefix(completion_menu_bg_color) if self.pretty else None
        )
        self.completion_menu_current_color = (
            ensure_hash_prefix(completion_menu_current_color) if self.pretty else None
        )
        self.completion_menu_current_bg_color = (
            ensure_hash_prefix(completion_menu_current_bg_color) if self.pretty else None
        )

        self.status_data = {
            "mode": "CHAT",
            "phase": "Idle",
            "cost": 0.0,
            "percentage": 0.0,
            "agents": 0,
            "model_name": "",
            "git_branch": "",
            "has_draft": False,
            "is_task_running": False,
            "hint": "",
            "tokens_used": 0,
            "tokens_max": 0,
            "tokens_pct": 0.0,
            "footer_mode": "composer_empty",
        }
        self.dashboard = None
        
        # Async and Generation state
        self._async_running_prompt_manager = None
        self._async_prompt_session = None
        self._input_lock = AsyncLock()
        self._queued_inputs = []
        self._generation_task = None

        try:
            from aider.gui.hints import HintManager

            self.hint_manager = HintManager(self)
        except Exception:
            self.hint_manager = SimpleNamespace(
                get_contextual_hint=lambda event_type, data=None: None
            )
        
        # Toast manager for notifications
        self.toast_manager = ToastManager()

        if fancy_input:
            # Initialize PromptSession only if we have a capable terminal
            session_kwargs = {
                "input": self.input,
                "output": self.output,
                "lexer": PygmentsLexer(MarkdownLexer),
                "editing_mode": self.editingmode,
                "bottom_toolbar": self._get_bottom_toolbar,
            }
            if self.editingmode == EditingMode.VI:
                session_kwargs["cursor"] = ModalCursorShapeConfig()
            if self.input_history_file is not None:
                session_kwargs["history"] = FileHistory(self.input_history_file)
            try:
                self.prompt_session = PromptSession(**session_kwargs)
                self.console = Console()  # pretty console
            except Exception as err:
                self.console = Console(force_terminal=False, no_color=True)
                self.tool_error(f"Can't initialize prompt toolkit: {err}")  # non-pretty
        else:
            self.console = Console(force_terminal=False, no_color=True)  # non-pretty
            if self.is_dumb_terminal:
                self.tool_output("Detected dumb terminal, disabling fancy input and pretty output.")

        self.file_watcher = file_watcher
        self.root = root

        # Docked prompt session (new UI)
        self._docked_prompt = None
        self._live_output = None
        self._base_console = self.console  # Keep reference to original console
        
        # Only use docked prompt if we have fancy input and are in a real TTY
        is_interactive = hasattr(self.input, "isatty") and self.input.isatty()
        if not is_interactive and self.input is None:
            # If input is None, it defaults to stdin
            is_interactive = sys.stdin.isatty()

        if fancy_input and is_interactive and os.environ.get("AIDER_DOCKED_PROMPT", "1") != "0":
            try:
                self._docked_prompt = DockedPromptSession(
                    model_name="",
                    input_history_file=self.input_history_file,
                    editing_mode=self.editingmode,
                    on_mode_toggle=self._on_mode_toggle,
                )
                # Replace prompt_session with docked session's underlying session
                if self._docked_prompt:
                    self.prompt_session = self._docked_prompt.session
                    # Create live output manager for docked prompt
                    self._live_output = LiveOutputManager(self.console)
                    # Wrap console to route output to live area
                    self.console = LiveRichConsole(self._live_output, self.console)
            except Exception as err:
                logger.debug(f"Could not initialize docked prompt: {err}")
        
        if self.prompt_session and not self._docked_prompt:
            self._async_prompt_session = AsyncAiderPromptSession(self.prompt_session)

        # Initialize background manager if in async context
        if get_running_loop():
            self._async_running_prompt_manager = AsyncRunningPromptManager(self)

        # Validate color settings after console is initialized
        self._validate_color_settings()

    @property
    def async_running_prompt_manager(self):
        """Property accessor for async running prompt manager."""
        if self._async_running_prompt_manager is None and get_running_loop():
            self._async_running_prompt_manager = AsyncRunningPromptManager(self)
        return self._async_running_prompt_manager

    @property
    def async_prompt_session(self):
        """Get the async prompt session wrapper."""
        # When using docked prompt, return a wrapper for compatibility
        if self._docked_prompt is not None:
            return self._docked_prompt
        return self._async_prompt_session

    def set_model(self, model_name):
        """Update model name in status bar."""
        self.status_data["model_name"] = model_name
        if self._docked_prompt:
            self._docked_prompt.update_status(model_name=model_name)

    def set_git_branch(self, branch_name):
        """Update git branch in status bar."""
        self.status_data["git_branch"] = branch_name
        if self._docked_prompt:
            self._docked_prompt.update_status(git_branch=branch_name)

    def set_mode(self, mode):
        """Update mode in status bar (CHAT, AUTO, ARCHITECT, ASK)."""
        self.status_data["mode"] = mode.upper()
    
    def _on_mode_toggle(self, mode: PromptMode):
        """Handle prompt mode toggle."""
        if mode == PromptMode.SHELL:
            self.tool_output("Switched to shell mode ($). Type shell commands directly.")
        else:
            self.tool_output("Switched to agent mode (✨). Type /commands or messages.")

    def clear(self):
        """Clear the terminal screen."""
        if self.console:
            self.console.clear()
    
    def start_live_output(self):
        """Start the live output display for docked prompt."""
        if self._live_output and not self._live_output.is_active:
            self._live_output.start()
    
    def stop_live_output(self):
        """Stop the live output display."""
        if self._live_output and self._live_output.is_active:
            self._live_output.stop()

    async def get_input_async(
        self,
        root,
        rel_fnames,
        addable_rel_fnames,
        commands,
        abs_read_only_fnames=None,
        edit_format=None,
    ) -> Optional[str]:
        """Async version of get_input."""
        if self.yes:
            return ""

        # Update autocompleter
        if self.prompt_session and self.fancy_input:
            self.prompt_session.completer = AutoCompleter(
                root, rel_fnames, addable_rel_fnames, commands, self.encoding, abs_read_only_fnames
            )

        # Use docked prompt or async prompt session
        if self._docked_prompt:
            # Update status for docked prompt
            self._docked_prompt.update_status(
                model_name=self.status_data.get("model_name", ""),
                git_branch=self.status_data.get("git_branch", ""),
                cwd=self.root,
            )
            
            # Start live output area if not already started
            self.start_live_output()
            
            # Check for queued input first
            if self._docked_prompt.has_queued_input():
                return self._docked_prompt.get_queued_input()
                
            return await self._docked_prompt.prompt_async()
        
        if self._async_prompt_session:
            # Check for queued input first
            queued = self._async_prompt_session.get_queued_input()
            if queued is not None:
                return queued
                
            return await self._async_prompt_session.prompt_async()

        # Fallback to sync prompt in executor if no async session
        from aider.async_compat import run_in_thread
        return await run_in_thread(
            self.get_input,
            root,
            rel_fnames,
            addable_rel_fnames,
            commands,
            abs_read_only_fnames,
        )

    def _get_bottom_toolbar(self):
        """Generate the bottom toolbar content based on current status."""
        from prompt_toolkit.formatted_text import HTML

        mode = self.status_data.get("mode", "CHAT").upper()
        model = self.status_data.get("model_name", "unknown")
        phase = self.status_data.get("phase", "Idle")
        cost = self.status_data.get("cost", 0.0)
        percentage = self.status_data.get("percentage", 0.0)
        agents = self.status_data.get("agents", 0)
        hint = self.status_data.get("hint", "")

        from html import escape

        from aider.themes import context_meter

        theme = self.theme
        accent = f'fg="{theme.accent}"'
        muted = f'fg="{theme.muted}"'
        mode_style = 'fg="#22C55E"' if mode == "AUTO" else accent
        phase_style = f'fg="{theme.tool_warning_color}"' if phase != "Idle" else muted

        # Shorten model name if too long
        if len(model) > 28:
            model = model[:25] + "..."

        sep = f"<style {muted}> · </style>"
        parts = [
            f"<style {mode_style}><b>{escape(mode)}</b></style>",
            f"<style {accent}>{escape(model)}</style>",
            f"<style {phase_style}>{escape(phase)}</style>",
        ]
        tokens = self.status_data.get("tokens") or 0
        max_tokens = self.status_data.get("max_tokens") or 0
        if max_tokens:
            meter = context_meter(tokens, max_tokens)
            parts.append(f"<style {muted}>ctx</style> {escape(meter)}")
        if percentage:
            parts.append(f"<style {muted}>budget</style> {percentage:.0f}%")
        parts.append(f"<style {muted}>${cost:.3f}</style>")
        if agents:
            parts.append(f"<style {muted}>agents</style> {agents}")
        if hint:
            parts.append(f"<style {muted}>{escape(hint)}</style>")

        return HTML(sep.join(parts))

    def show_hint(self, event_type: str, data: dict = None):
        """Show a hint in the terminal status bar."""
        hint = self.hint_manager.get_contextual_hint(event_type, data)
        if hint:
            self.status_data["hint"] = hint
            if self.prompt_session:
                self.prompt_session.app.invalidate()

    def review_diff(self, filename, old_content, new_content):
        """Review code diff with human in the loop."""
        from .gui.diff_viewer import InteractiveDiffViewer

        viewer = InteractiveDiffViewer(self)
        return viewer.review_file(filename, old_content, new_content)

    def on_phase_change(self, phase: str, status: str = "running"):
        """Called when an autonomous workflow phase changes."""
        phase_str = phase if status == "running" else "Idle"
        self.status_data["phase"] = phase_str
        if self._docked_prompt:
            self._docked_prompt.update_status(phase=phase_str)
        if self.dashboard:
            self.dashboard.on_phase_change(phase, status)
        if self.prompt_session:
            # Force a refresh of the UI
            self.prompt_session.app.invalidate()

    def on_cost_update(self, total: float, percentage: float):
        """Called when the session cost is updated."""
        self.status_data["cost"] = total
        self.status_data["percentage"] = percentage
        if self._docked_prompt:
            self._docked_prompt.update_status(cost=total)
        if self.dashboard:
            self.dashboard.on_cost_update(total, percentage)
        if self.prompt_session:
            self.prompt_session.app.invalidate()

    def on_agent_status(self, agent_id: str, status: str, task: str = None):
        """Called when a sub-agent's status changes."""
        if self._docked_prompt:
            # Count active agents
            agent_count = self.status_data.get("agents", 0)
            self._docked_prompt.update_status(agents=agent_count)
        if self.dashboard:
            self.dashboard.on_agent_status(agent_id, status, task)
        if self.prompt_session:
            self.prompt_session.app.invalidate()

    def on_context_update(self, used: int, total: int):
        """Called when context window usage changes."""
        if self._docked_prompt:
            self._docked_prompt.update_status(context_used=used, context_total=total)

    def on_policy_check(self, result: Any):
        """Called when a security policy scan result is available."""
        if self.dashboard:
            self.dashboard.on_policy_check(result)

        # Also print to terminal if there are violations
        if hasattr(result, "violations") and result.violations:
            from rich.panel import Panel
            from rich.table import Table

            table = Table(title="Security Policy Violations", border_style="red")
            table.add_column("Rule", style="cyan")
            table.add_column("Severity", style="bold red")
            table.add_column("Message")

            for v in result.violations:
                table.add_row(v.rule_name, v.severity, v.message)

            self.console.print(
                Panel(table, border_style="red", title="[bold red]SECURITY ALERT[/bold red]")
            )

    def show_dashboard(self):
        """Enable the live dashboard."""
        if not self.enable_dashboard or not self.pretty or self.is_dumb_terminal:
            return

        from .gui.dashboard import LiveDashboard

        if not self.dashboard:
            self.dashboard = LiveDashboard(console=self.console)
            # Synchronize initial state
            self.dashboard.on_cost_update(self.status_data["cost"], self.status_data["percentage"])
            self.dashboard.on_phase_change(self.status_data["phase"])

        self.dashboard.start()

    def hide_dashboard(self):
        """Disable the live dashboard."""
        if self.dashboard:
            self.dashboard.stop()

    def update_agent_count(self, count: int):
        """Update the number of active agents."""
        self.status_data["agents"] = count
        if self.prompt_session:
            self.prompt_session.app.invalidate()

    def set_mode(self, mode: str):
        """Set the current mode (CHAT, AUTO, ASK, etc)."""
        self.status_data["mode"] = mode
        if self._docked_prompt:
            # Map aider modes to docked prompt display
            if mode.upper() == "AUTO":
                self._docked_prompt.update_status(phase="Auto")
            else:
                self._docked_prompt.update_status(phase=mode)
        if self.prompt_session:
            self.prompt_session.app.invalidate()

    def set_model(self, model_name: str):
        """Set the current model name for status bar display."""
        self.status_data["model_name"] = model_name
        if self._docked_prompt:
            self._docked_prompt.update_status(model_name=model_name)
        if self.prompt_session:
            self.prompt_session.app.invalidate()

    def set_git_branch(self, branch: str):
        """Set the current git branch for status bar display."""
        self.status_data["git_branch"] = branch
        if self._docked_prompt:
            self._docked_prompt.update_status(git_branch=branch, cwd=os.getcwd())
        if self.prompt_session:
            self.prompt_session.app.invalidate()

    def _validate_color_settings(self):
        """Validate configured color strings and reset invalid ones."""
        color_attributes = [
            "user_input_color",
            "tool_output_color",
            "tool_error_color",
            "tool_warning_color",
            "assistant_output_color",
            "completion_menu_color",
            "completion_menu_bg_color",
            "completion_menu_current_color",
            "completion_menu_current_bg_color",
        ]
        for attr_name in color_attributes:
            color_value = getattr(self, attr_name, None)
            if color_value:
                try:
                    # Try creating a style to validate the color
                    RichStyle(color=color_value)
                except ColorParseError as e:
                    self.console.print(
                        "[bold red]Warning:[/bold red] Invalid configuration for"
                        f" {attr_name}: '{color_value}'. {e}. Disabling this color."
                    )
                    setattr(self, attr_name, None)  # Reset invalid color to None

    def _prepare_terminal_output(self):
        """Clear any active prompt-toolkit render area before printing with Rich."""
        prompt_session = getattr(self, "prompt_session", None)
        if not prompt_session:
            return

        app = getattr(prompt_session, "app", None)
        if not app or not getattr(app, "is_running", False):
            return

        renderer = getattr(app, "renderer", None)
        if not renderer:
            return

        try:
            renderer.erase(leave_alternate_screen=True)
        except Exception:
            pass

    def _get_input_toolbar(self):
        if self.multiline_mode:
            return " multiline: Enter newline | Alt-Enter submit | Ctrl-X Ctrl-E external editor "
        return " Enter submit | Alt-Enter newline | Ctrl-X Ctrl-E external editor "

    def _get_prompt_toolbar(self):
        from prompt_toolkit.formatted_text import to_formatted_text

        status_bar = self._get_bottom_toolbar()
        input_toolbar = self._get_input_toolbar().strip()

        fragments = list(to_formatted_text(status_bar)) if status_bar else []
        if input_toolbar:
            if fragments:
                fragments.append((f"fg:{self.theme.muted}", "  ·  "))
            fragments.append((f"fg:{self.theme.muted}", input_toolbar))
        return fragments

    def _get_style(self):
        style_dict = {}
        if not self.pretty:
            return Style.from_dict(style_dict)

        if self.user_input_color:
            style_dict.setdefault("", self.user_input_color)
            style_dict.update(
                {
                    "pygments.literal.string": f"bold italic {self.user_input_color}",
                }
            )

        # Conditionally add 'completion-menu' style
        completion_menu_style = []
        if self.completion_menu_bg_color:
            completion_menu_style.append(f"bg:{self.completion_menu_bg_color}")
        if self.completion_menu_color:
            completion_menu_style.append(self.completion_menu_color)
        if completion_menu_style:
            style_dict["completion-menu"] = " ".join(completion_menu_style)

        # Conditionally add 'completion-menu.completion.current' style
        completion_menu_current_style = []
        if self.completion_menu_current_bg_color:
            completion_menu_current_style.append(f"bg:{self.completion_menu_current_bg_color}")
        if self.completion_menu_current_color:
            completion_menu_current_style.append(self.completion_menu_current_color)
        if completion_menu_current_style:
            style_dict["completion-menu.completion.current"] = " ".join(
                completion_menu_current_style
            )

        if self.theme.name != "classic":
            # Flat status bar instead of prompt_toolkit's reverse-video block
            style_dict["bottom-toolbar"] = "noreverse"

        return Style.from_dict(style_dict)

    def read_image(self, filename):
        try:
            with open(str(filename), "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read())
                return encoded_string.decode("utf-8")
        except OSError as err:
            self.tool_error(f"{filename}: unable to read: {err}")
            return
        except FileNotFoundError:
            self.tool_error(f"{filename}: file not found error")
            return
        except IsADirectoryError:
            self.tool_error(f"{filename}: is a directory")
            return
        except Exception as e:
            self.tool_error(f"{filename}: {e}")
            return

    def read_video(self, filename):
        """Extract frames from video for multimodal context (Gemini parity)."""
        if not shutil.which("ffmpeg"):
            self.tool_error("ffmpeg not found. Please install ffmpeg to process video files.")
            return []

        temp_dir = tempfile.mkdtemp()
        try:
            # Extract 1 frame per second, max 10 frames
            cmd = [
                "ffmpeg",
                "-i",
                str(filename),
                "-vf",
                "fps=1,scale=512:-1",
                "-vframes",
                "10",
                os.path.join(temp_dir, "frame_%03d.jpg"),
            ]
            subprocess.run(cmd, capture_output=True, check=True)

            frames = []
            for frame_file in sorted(os.listdir(temp_dir)):
                frames.append(self.read_image(os.path.join(temp_dir, frame_file)))
            return frames
        except Exception as e:
            self.tool_error(f"Video processing failed for {filename}: {e}")
            return []
        finally:
            shutil.rmtree(temp_dir)

    def read_audio(self, filename):
        """Read audio file as base64."""
        try:
            with open(str(filename), "rb") as audio_file:
                encoded_string = base64.b64encode(audio_file.read())
                return encoded_string.decode("utf-8")
        except Exception as e:
            self.tool_error(f"Audio processing failed for {filename}: {e}")
            return None

    def read_text(self, filename, silent=False):
        if is_image_file(filename):
            return self.read_image(filename)
        if is_video_file(filename):
            return self.read_video(filename)
        if is_audio_file(filename):
            return self.read_audio(filename)

        try:
            with open(str(filename), "r", encoding=self.encoding) as f:
                return f.read()
        except FileNotFoundError:
            if not silent:
                self.tool_error(f"{filename}: file not found error")
            return
        except IsADirectoryError:
            if not silent:
                self.tool_error(f"{filename}: is a directory")
            return
        except OSError as err:
            if not silent:
                self.tool_error(f"{filename}: unable to read: {err}")
            return
        except UnicodeError as e:
            if not silent:
                self.tool_error(f"{filename}: {e}")
                self.tool_error("Use --encoding to set the unicode encoding.")
            return

    def write_text(self, filename, content, max_retries=5, initial_delay=0.1):
        """
        Writes content to a file, retrying with progressive backoff if the file is locked.

        :param filename: Path to the file to write.
        :param content: Content to write to the file.
        :param max_retries: Maximum number of retries if a file lock is encountered.
        :param initial_delay: Initial delay (in seconds) before the first retry.
        """
        if self.dry_run:
            return

        delay = initial_delay
        for attempt in range(max_retries):
            try:
                with open(str(filename), "w", encoding=self.encoding, newline=self.newline) as f:
                    f.write(content)
                return  # Successfully wrote the file
            except PermissionError as err:
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    self.tool_error(
                        f"Unable to write file {filename} after {max_retries} attempts: {err}"
                    )
                    raise
            except OSError as err:
                self.tool_error(f"Unable to write file {filename}: {err}")
                raise

    def rule(self):
        self._prepare_terminal_output()
        if self.pretty:
            color = self.theme.muted if self.theme.name != "classic" else self.user_input_color
            style = dict(style=color) if color else dict()
            self.console.rule(**style)
        else:
            print()

    def interrupt_input(self):
        if self.prompt_session and self.prompt_session.app:
            # Store any partial input before interrupting
            self.placeholder = self.prompt_session.app.current_buffer.text
            self.interrupted = True
            self.prompt_session.app.exit()

    def get_input(
        self,
        root,
        rel_fnames,
        addable_rel_fnames,
        commands,
        abs_read_only_fnames=None,
        edit_format=None,
    ):
        self.rule()

        # Ring the bell if needed
        self.ring_bell()

        rel_fnames = list(rel_fnames)
        show = ""
        if rel_fnames:
            rel_read_only_fnames = [
                get_rel_fname(fname, root) for fname in (abs_read_only_fnames or [])
            ]
            show = self.format_files_for_input(rel_fnames, rel_read_only_fnames)

        prompt_prefix = ""
        if edit_format:
            prompt_prefix += edit_format
        if self.multiline_mode:
            prompt_prefix += (" " if edit_format else "") + "multi"
        prompt_prefix += "> "

        show += prompt_prefix
        self.prompt_prefix = prompt_prefix

        inp = ""
        multiline_input = False

        style = self._get_style()

        completer_instance = ThreadedCompleter(
            AutoCompleter(
                root,
                rel_fnames,
                addable_rel_fnames,
                commands,
                self.encoding,
                abs_read_only_fnames=abs_read_only_fnames,
            )
        )

        def suspend_to_bg(event):
            """Suspend currently running application."""
            event.app.suspend_to_background()

        kb = KeyBindings()

        @kb.add(Keys.ControlZ, filter=Condition(lambda: hasattr(signal, "SIGTSTP")))
        def _(event):
            "Suspend to background with ctrl-z"
            suspend_to_bg(event)

        @kb.add("c-space")
        def _(event):
            "Ignore Ctrl when pressing space bar"
            event.current_buffer.insert_text(" ")

        @kb.add("c-up")
        def _(event):
            "Navigate backward through history"
            event.current_buffer.history_backward()

        @kb.add("c-down")
        def _(event):
            "Navigate forward through history"
            event.current_buffer.history_forward()

        @kb.add("c-x", "c-e")
        def _(event):
            "Edit current input in external editor (like Bash)"
            buffer = event.current_buffer
            current_text = buffer.text

            # Open the editor with the current text
            edited_text = pipe_editor(input_data=current_text, suffix="md")

            # Replace the buffer with the edited text, strip any trailing newlines
            buffer.text = edited_text.rstrip("\n")

            # Move cursor to the end of the text
            buffer.cursor_position = len(buffer.text)

        @kb.add("enter", eager=True, filter=~is_searching)
        def _(event):
            "Handle Enter key press"
            if self.multiline_mode and not (
                self.editingmode == EditingMode.VI
                and event.app.vi_state.input_mode == InputMode.NAVIGATION
            ):
                # In multiline mode and if not in vi-mode or vi navigation/normal mode,
                # Enter adds a newline
                event.current_buffer.insert_text("\n")
            else:
                # In normal mode, Enter submits
                event.current_buffer.validate_and_handle()

        @kb.add("escape", "enter", eager=True, filter=~is_searching)  # This is Alt+Enter
        def _(event):
            "Handle Alt+Enter key press"
            if self.multiline_mode:
                # In multiline mode, Alt+Enter submits
                event.current_buffer.validate_and_handle()
            else:
                # In normal mode, Alt+Enter adds a newline
                event.current_buffer.insert_text("\n")

        while True:
            if multiline_input:
                show = self.prompt_prefix

            try:
                if self.prompt_session:
                    # Use placeholder if set, then clear it
                    default = self.placeholder or ""
                    self.placeholder = None

                    self.interrupted = False
                    if not multiline_input:
                        if self.file_watcher:
                            self.file_watcher.start()
                        if self.clipboard_watcher:
                            self.clipboard_watcher.start()

                    def get_continuation(width, line_number, is_soft_wrap):
                        return self.prompt_prefix

                    line = self.prompt_session.prompt(
                        show,
                        default=default,
                        completer=completer_instance,
                        reserve_space_for_menu=4,
                        complete_style=CompleteStyle.MULTI_COLUMN,
                        style=style,
                        key_bindings=kb,
                        complete_while_typing=True,
                        prompt_continuation=get_continuation,
                        bottom_toolbar=self._get_prompt_toolbar,
                    )
                else:
                    line = input(show)

                # Check if we were interrupted by a file change
                if self.interrupted:
                    line = line or ""
                    if self.file_watcher:
                        cmd = self.file_watcher.process_changes()
                        return cmd

            except EOFError:
                raise
            except Exception as err:
                import traceback

                self.tool_error(str(err))
                self.tool_error(traceback.format_exc())
                return ""
            except UnicodeEncodeError as err:
                self.tool_error(str(err))
                return ""
            finally:
                if self.file_watcher:
                    self.file_watcher.stop()
                if self.clipboard_watcher:
                    self.clipboard_watcher.stop()

            if line.strip("\r\n") and not multiline_input:
                stripped = line.strip("\r\n")
                if stripped == "{":
                    multiline_input = True
                    multiline_tag = None
                    inp += ""
                elif stripped[0] == "{":
                    # Extract tag if it exists (only alphanumeric chars)
                    tag = "".join(c for c in stripped[1:] if c.isalnum())
                    if stripped == "{" + tag:
                        multiline_input = True
                        multiline_tag = tag
                        inp += ""
                    else:
                        inp = line
                        break
                else:
                    inp = line
                    break
                continue
            elif multiline_input and line.strip():
                if multiline_tag:
                    # Check if line is exactly "tag}"
                    if line.strip("\r\n") == f"{multiline_tag}}}":
                        break
                    else:
                        inp += line + "\n"
                # Check if line is exactly "}"
                elif line.strip("\r\n") == "}":
                    break
                else:
                    inp += line + "\n"
            elif multiline_input:
                inp += line + "\n"
            else:
                inp = line
                break

        print()
        self.user_input(inp)
        return inp

    def add_to_input_history(self, inp):
        if not self.input_history_file:
            return
        try:
            FileHistory(self.input_history_file).append_string(inp)
            # Also add to the in-memory history if it exists
            if self.prompt_session and self.prompt_session.history:
                self.prompt_session.history.append_string(inp)
        except OSError as err:
            self.tool_warning(f"Unable to write to input history file: {err}")

    def get_input_history(self):
        if not self.input_history_file:
            return []

        fh = FileHistory(self.input_history_file)
        return fh.load_history_strings()

    def log_llm_history(self, role, content):
        if not self.llm_history_file:
            return
        timestamp = datetime.now().isoformat(timespec="seconds")
        try:
            Path(self.llm_history_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self.llm_history_file, "a", encoding="utf-8") as log_file:
                log_file.write(f"{role.upper()} {timestamp}\n")
                log_file.write(content + "\n")
        except (PermissionError, OSError) as err:
            self.tool_warning(f"Unable to write to llm history file {self.llm_history_file}: {err}")
            self.llm_history_file = None

    def display_user_input(self, inp):
        self._prepare_terminal_output()
        if self.pretty and self.user_input_color:
            style = dict(style=self.user_input_color)
        else:
            style = dict()

        self.console.print(Text(inp), **style)

    async def display_user_input_async(self, inp):
        """Async version of display_user_input."""
        from rich.text import Text

        style = dict(style=self.user_input_color) if self.user_input_color else dict()
        text = Text(inp, **style)

        with safe_patch_stdout():
            self.console.print(text)

    def user_input(self, inp, log_only=True):
        if not log_only:
            self.display_user_input(inp)

        prefix = "####"
        if inp:
            hist = inp.splitlines()
        else:
            hist = ["<blank>"]

        hist = f"  \n{prefix} ".join(hist)

        hist = f"""
{prefix} {hist}"""
        self.append_chat_history(hist, linebreak=True)

    # OUTPUT

    def ai_output(self, content):
        hist = "\n" + content.strip() + "\n\n"
        self.append_chat_history(hist)

    def offer_url(self, url, prompt="Open URL for more info?", allow_never=True):
        """Offer to open a URL in the browser, returns True if opened."""
        if url in self.never_prompts:
            return False
        if self.confirm_ask(prompt, subject=url, allow_never=allow_never):
            webbrowser.open(url)
            return True
        return False

    @restore_multiline
    def confirm_ask(
        self,
        question,
        default="y",
        subject=None,
        explicit_yes_required=False,
        group=None,
        allow_never=False,
    ):
        self.num_user_asks += 1

        # Ring the bell if needed
        self.ring_bell()

        question_id = (question, subject)

        if question_id in self.never_prompts:
            return False

        if group and not group.show_group:
            group = None
        if group:
            allow_never = True

        valid_responses = ["yes", "no", "skip", "all"]
        options = " (Y)es/(N)o"
        if group:
            if not explicit_yes_required:
                options += "/(A)ll"
            options += "/(S)kip all"
        if allow_never:
            options += "/(D)on't ask again"
            valid_responses.append("don't")

        if default.lower().startswith("y"):
            question += options + " [Yes]: "
        elif default.lower().startswith("n"):
            question += options + " [No]: "
        else:
            question += options + f" [{default}]: "

        if subject:
            self.tool_output()
            if "\n" in subject:
                lines = subject.splitlines()
                max_length = max(len(line) for line in lines)
                padded_lines = [line.ljust(max_length) for line in lines]
                padded_subject = "\n".join(padded_lines)
                self.tool_output(padded_subject, bold=True)
            else:
                self.tool_output(subject, bold=True)

        style = self._get_style()

        def is_valid_response(text):
            if not text:
                return True
            return text.lower() in valid_responses

        if self.yes is True:
            res = "n" if explicit_yes_required else "y"
        elif self.yes is False:
            res = "n"
        elif group and group.preference:
            res = group.preference
            self.user_input(f"{question}{res}", log_only=False)
        else:
            with safe_patch_stdout():
                while True:
                    try:
                        if self.prompt_session:
                            if get_running_loop():
                                from aider.async_utils import run_async_safely
                                res = run_async_safely(
                                    self.async_prompt_session.prompt_async(
                                        question,
                                        style=style,
                                        complete_while_typing=False,
                                    )
                                )
                            else:
                                res = self.prompt_session.prompt(
                                    question,
                                    style=style,
                                    complete_while_typing=False,
                                )
                        else:
                            res = input(question)
                    except EOFError:
                        # Treat EOF (Ctrl+D) as if the user pressed Enter
                        res = default
                        break

                    if not res:
                        res = default
                        break
                    res = res.lower()
                    good = any(valid_response.startswith(res) for valid_response in valid_responses)
                    if good:
                        break

                    error_message = f"Please answer with one of: {', '.join(valid_responses)}"
                    self.tool_error(error_message)

        res = res.lower()[0]

        if res == "d" and allow_never:
            self.never_prompts.add(question_id)
            hist = f"{question.strip()} {res}"
            self.append_chat_history(hist, linebreak=True, blockquote=True)
            return False

        if explicit_yes_required:
            is_yes = res == "y"
        else:
            is_yes = res in ("y", "a")

        is_all = res == "a" and group is not None and not explicit_yes_required
        is_skip = res == "s" and group is not None

        if group:
            if is_all and not explicit_yes_required:
                group.preference = "all"
            elif is_skip:
                group.preference = "skip"

        hist = f"{question.strip()} {res}"
        self.append_chat_history(hist, linebreak=True, blockquote=True)

        return is_yes

    @restore_multiline
    def prompt_ask(self, question, default="", subject=None):
        self.num_user_asks += 1

        # Ring the bell if needed
        self.ring_bell()

        if subject:
            self.tool_output()
            self.tool_output(subject, bold=True)

        style = self._get_style()

        if self.yes is True:
            res = "yes"
        elif self.yes is False:
            res = "no"
        else:
            with safe_patch_stdout():
                try:
                    if self.prompt_session:
                        res = self.prompt_session.prompt(
                            question + " ",
                            default=default,
                            style=style,
                            complete_while_typing=True,
                        )
                    else:
                        res = input(question + " ")
                except EOFError:
                    # Treat EOF (Ctrl+D) as if the user pressed Enter
                    res = default

        hist = f"{question.strip()} {res.strip()}"
        self.append_chat_history(hist, linebreak=True, blockquote=True)
        if self.yes in (True, False):
            self.tool_output(hist)

        return res

    def _tool_message(self, message="", strip=True, color=None):
        if message.strip():
            if "\n" in message:
                for line in message.splitlines():
                    self.append_chat_history(line, linebreak=True, blockquote=True, strip=strip)
            else:
                hist = message.strip() if strip else message
                self.append_chat_history(hist, linebreak=True, blockquote=True)

        if not isinstance(message, Text):
            message = Text(message)
        color = ensure_hash_prefix(color) if color else None
        style = dict(style=color) if self.pretty and color else dict()
        self._prepare_terminal_output()
        with safe_patch_stdout():
            try:
                self.console.print(message, **style)
            except UnicodeEncodeError:
                # Fallback to ASCII-safe output
                if isinstance(message, Text):
                    message = message.plain
                message = str(message).encode("ascii", errors="replace").decode("ascii")
                self.console.print(message, **style)

    def tool_error(self, message="", strip=True):
        self.num_error_outputs += 1
        self._tool_message(message, strip, self.tool_error_color)

    def tool_warning(self, message="", strip=True):
        self._tool_message(message, strip, self.tool_warning_color)

    def tool_output(self, *messages, log_only=False, bold=False):
        if messages:
            hist = " ".join(messages)
            hist = f"{hist.strip()}"
            self.append_chat_history(hist, linebreak=True, blockquote=True)

        if log_only:
            return

        messages = list(map(Text, messages))
        style = dict()
        if self.pretty:
            if self.tool_output_color:
                style["color"] = ensure_hash_prefix(self.tool_output_color)
            style["reverse"] = bold

        style = RichStyle(**style)
        self._prepare_terminal_output()
        self.console.print(*messages, style=style)

    def get_assistant_mdstream(self):
        mdargs = dict(
            style=self.assistant_output_color,
            code_theme=self.code_theme,
            inline_code_lexer="text",
        )
        mdStream = MarkdownStream(mdargs=mdargs, io=self)
        return mdStream

    def assistant_output(self, message, pretty=None):
        if not message:
            self.tool_warning("Empty response received from LLM. Check your provider account?")
            return

        show_resp = message

        # Coder will force pretty off if fence is not triple-backticks
        if pretty is None:
            pretty = self.pretty

        if pretty:
            show_resp = Markdown(
                message, style=self.assistant_output_color, code_theme=self.code_theme
            )
        else:
            show_resp = Text(message or "(empty response)")

        self._prepare_terminal_output()
        with safe_patch_stdout():
            self.console.print(show_resp)

    def set_placeholder(self, placeholder):
        """Set a one-time placeholder text for the next input prompt."""
        self.placeholder = placeholder

    def print(self, message=""):
        print(message)

    def llm_started(self):
        """Mark that the LLM has started processing, so we should ring the bell on next input"""
        self.bell_on_next_input = True

    def get_default_notification_command(self):
        """Return a default notification command based on the operating system."""
        import platform

        system = platform.system()

        if system == "Darwin":  # macOS
            # Check for terminal-notifier first
            if shutil.which("terminal-notifier"):
                return f"terminal-notifier -title 'Aider' -message '{NOTIFICATION_MESSAGE}'"
            # Fall back to osascript
            return (
                f'osascript -e \'display notification "{NOTIFICATION_MESSAGE}" with title "Aider"\''
            )
        elif system == "Linux":
            # Check for common Linux notification tools
            for cmd in ["notify-send", "zenity"]:
                if shutil.which(cmd):
                    if cmd == "notify-send":
                        return f"notify-send 'Aider' '{NOTIFICATION_MESSAGE}'"
                    elif cmd == "zenity":
                        return f"zenity --notification --text='{NOTIFICATION_MESSAGE}'"
            return None  # No known notification tool found
        elif system == "Windows":
            # PowerShell notification
            return (
                "powershell -command"
                " \"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
                f" [System.Windows.Forms.MessageBox]::Show('{NOTIFICATION_MESSAGE}',"
                " 'Aider')\""
            )

        return None  # Unknown system

    def ring_bell(self):
        """Ring the terminal bell if needed and clear the flag"""
        if self.bell_on_next_input and self.notifications:
            if self.notifications_command:
                try:
                    # SECURITY: Parse command with shlex to avoid shell injection
                    cmd_parts = shlex.split(self.notifications_command)
                    if not cmd_parts:
                        self.tool_warning("Invalid notifications command (empty after parsing)")
                    else:
                        result = subprocess.run(cmd_parts, shell=False, capture_output=True)
                        if result.returncode != 0 and result.stderr:
                            error_msg = result.stderr.decode("utf-8", errors="replace")
                            self.tool_warning(f"Failed to run notifications command: {error_msg}")
                except Exception as e:
                    self.tool_warning(f"Failed to run notifications command: {e}")
            else:
                print("\a", end="", flush=True)  # Ring the bell
            self.bell_on_next_input = False  # Clear the flag

    def toggle_multiline_mode(self):
        """Toggle between normal and multiline input modes"""
        self.multiline_mode = not self.multiline_mode
        if self.multiline_mode:
            self.tool_output(
                "Multiline mode: Enabled. Enter inserts newline, Alt-Enter submits text"
            )
        else:
            self.tool_output(
                "Multiline mode: Disabled. Alt-Enter inserts newline, Enter submits text"
            )

    def append_chat_history(self, text, linebreak=False, blockquote=False, strip=True):
        if blockquote:
            if strip:
                text = text.strip()
            text = "> " + text
        if linebreak:
            if strip:
                text = text.rstrip()
            text = text + "  \n"
        if not text.endswith("\n"):
            text += "\n"
        if self.chat_history_file is not None:
            try:
                self.chat_history_file.parent.mkdir(parents=True, exist_ok=True)
                with self.chat_history_file.open("a", encoding=self.encoding, errors="ignore") as f:
                    f.write(text)
            except (PermissionError, OSError) as err:
                print(f"Warning: Unable to write to chat history file {self.chat_history_file}.")
                print(err)
                self.chat_history_file = None  # Disable further attempts to write

    def format_files_for_input(self, rel_fnames, rel_read_only_fnames):
        if not self.pretty:
            read_only_files = []
            for full_path in sorted(rel_read_only_fnames or []):
                read_only_files.append(f"{full_path} (read only)")

            editable_files = []
            for full_path in sorted(rel_fnames):
                if full_path in rel_read_only_fnames:
                    continue
                editable_files.append(f"{full_path}")

            return "\n".join(read_only_files + editable_files) + "\n"

        output = StringIO()
        console = Console(file=output, force_terminal=False)

        read_only_files = sorted(rel_read_only_fnames or [])
        editable_files = [f for f in sorted(rel_fnames) if f not in rel_read_only_fnames]

        if read_only_files:
            # Use shorter of abs/rel paths for readonly files
            ro_paths = []
            for rel_path in read_only_files:
                abs_path = os.path.abspath(os.path.join(self.root, rel_path))
                ro_paths.append(Text(abs_path if len(abs_path) < len(rel_path) else rel_path))

            files_with_label = [Text("Readonly:")] + ro_paths
            read_only_output = StringIO()
            Console(file=read_only_output, force_terminal=False).print(Columns(files_with_label))
            read_only_lines = read_only_output.getvalue().splitlines()
            console.print(Columns(files_with_label))

        if editable_files:
            text_editable_files = [Text(f) for f in editable_files]
            files_with_label = text_editable_files
            if read_only_files:
                files_with_label = [Text("Editable:")] + text_editable_files
                editable_output = StringIO()
                Console(file=editable_output, force_terminal=False).print(Columns(files_with_label))
                editable_lines = editable_output.getvalue().splitlines()

                if len(read_only_lines) > 1 or len(editable_lines) > 1:
                    console.print()
            console.print(Columns(files_with_label))

        return output.getvalue()

    def set_running_state(self, running: bool):
        """Set the running state for the docked prompt UI."""
        if self._docked_prompt:
            self._docked_prompt.set_running(running)

    def is_async_mode(self) -> bool:
        """Check if running in async mode (always True as of v0.87+)."""
        return True

    # =============================================================================
    # UI Modernization Methods (for backward compatibility with tests)
    # =============================================================================
    
    def has_queued_input(self) -> bool:
        """Check if there's queued input."""
        if self._docked_prompt is not None:
            return self._docked_prompt.has_queued_input()
        if self._async_prompt_session is not None:
            return self._async_prompt_session.has_queued_input()
        return False
    
    def queue_input(self, message: str):
        """Queue input for later processing."""
        if self._docked_prompt is not None:
            self._docked_prompt.queue_input(message)
        elif self._async_prompt_session is not None:
            self._async_prompt_session.queue_input(message)
    
    def get_queued_input(self) -> Optional[str]:
        """Get queued input if any."""
        if self._docked_prompt is not None:
            return self._docked_prompt.get_queued_input()
        if self._async_prompt_session is not None:
            return self._async_prompt_session.get_queued_input()
        return None
    
    def set_footer_mode(self, mode: str):
        """Set the footer mode."""
        valid_modes = {"task_running", "composer_empty", "composer_has_draft"}
        if mode in valid_modes:
            self.status_data["footer_mode"] = mode
    
    def set_task_running(self, running: bool):
        """Update task running state in status bar."""
        self.status_data["is_task_running"] = running
        self.status_data["footer_mode"] = "task_running" if running else "composer_empty"
    
    def set_draft_status(self, has_draft: bool):
        """Update draft status in status bar."""
        self.status_data["has_draft"] = has_draft
        self.status_data["footer_mode"] = "composer_has_draft" if has_draft else "composer_empty"
    
    def toast(self, message: str, duration: float = 5.0, topic: str = None):
        """Show a toast notification immediately.
        
        Note: duration and topic are kept for API compatibility but 
        toasts are displayed immediately and not tracked for expiration.
        """
        # Store for potential UI integration (dashboard, etc.)
        self.toast_manager.toast(message, duration, topic)
        
        # Render immediately to console (one-shot, no cleanup needed)
        try:
            from rich.panel import Panel
            toast_panel = Panel(
                message,
                title="🔔 Notification",
                border_style="blue",
                width=min(80, self.console.width - 4) if self.console.width else 80
            )
            self.console.print(toast_panel)
        except Exception:
            # Fallback to simple output if rich fails
            self.tool_output(f"🔔 {message}")


def get_rel_fname(fname, root):
    try:
        return os.path.relpath(fname, root)
    except ValueError:
        return fname


# =============================================================================
# Backward Compatibility Aliases
# =============================================================================
# These aliases support tests and external code that depend on older API names.

# Alias for backward compatibility
AiderPromptSession = AsyncAiderPromptSession


class ToastManager:
    """
    Manager for temporary toast notifications.
    
    Backward compatibility class for tests and external integrations.
    """
    
    def __init__(self):
        self._toasts = []
        self._lock = threading.Lock()
    
    def toast(self, message: str, duration: float = 5.0, topic: str = None):
        """Add a toast message with optional topic for grouping."""
        with self._lock:
            # Remove existing toast with same topic
            if topic:
                self._toasts = [(msg, dur, exp, t) for msg, dur, exp, t in self._toasts if t != topic]
            # Add new toast
            expiration = time.time() + duration
            self._toasts.append((message, duration, expiration, topic))
    
    def get_active(self) -> List[str]:
        """Get all active (non-expired) toast messages."""
        self._cleanup_expired()
        with self._lock:
            return [msg for msg, _, _, _ in self._toasts]
    
    def clear_topic(self, topic: str):
        """Clear all toasts with the given topic."""
        with self._lock:
            self._toasts = [(msg, dur, exp, t) for msg, dur, exp, t in self._toasts if t != topic]
    
    def _cleanup_expired(self):
        """Remove expired toasts."""
        now = time.time()
        with self._lock:
            self._toasts = [(msg, dur, exp, t) for msg, dur, exp, t in self._toasts if exp > now]
