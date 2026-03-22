import os
import tempfile
from pathlib import Path

import pyperclip
from PIL import Image, ImageGrab
from prompt_toolkit.completion import Completion, PathCompleter
from prompt_toolkit.document import Document

from aider import voice
from aider.llm import litellm
from aider.utils import is_image_file


def expand_subdir(file_path):
    if file_path.is_file():
        yield file_path
        return

    if file_path.is_dir():
        for file in file_path.rglob("*"):
            if file.is_file():
                yield file


class MiscCommandsMixin:
    """Token reporting, path completion, help, voice, and clipboard commands."""

    def cmd_cache(self, args):
        "Show token caching statistics and savings summary"
        self.coder.show_token_cache_summary()

    def cmd_cost(self, args):
        "Show session cost summary and budget status"
        # Get cost from coder
        total_cost = getattr(self.coder, 'total_cost', 0.0)
        
        # Get budget from multiple possible sources
        budget = None
        # Try cost_tracker first (most accurate source)
        if hasattr(self.coder, 'tool_router') and hasattr(self.coder.tool_router, 'cost_tracker'):
            budget = self.coder.tool_router.cost_tracker.max_budget
        # Fall back to SessionRuntime
        elif hasattr(self.coder, 'runtime') and hasattr(self.coder.runtime, 'max_budget'):
            budget = self.coder.runtime.max_budget
        
        self.io.tool_output("Session Cost Summary")
        self.io.tool_output("=" * 40)
        
        # Current cost
        self.io.tool_output(f"Current session cost: ${total_cost:.4f}")
        
        # Budget status
        if budget and budget > 0:
            pct = (total_cost / budget) * 100
            self.io.tool_output(f"Budget: ${budget:.2f} ({pct:.1f}% used)")
            
            if pct >= 100:
                self.io.tool_error("BUDGET EXCEEDED")
            elif pct >= 90:
                self.io.tool_warning("Budget almost exhausted (90%+)")
            elif pct >= 75:
                self.io.tool_warning("Budget 75% used")
        else:
            self.io.tool_output("Budget: No limit set (use --budget to set)")
        
        # Token usage
        tokens_sent = getattr(self.coder, 'total_tokens_sent', 0)
        tokens_received = getattr(self.coder, 'total_tokens_received', 0)
        if tokens_sent or tokens_received:
            self.io.tool_output(f"\nTokens sent:     {tokens_sent:,}")
            self.io.tool_output(f"Tokens received: {tokens_received:,}")
            self.io.tool_output(f"Total tokens:    {tokens_sent + tokens_received:,}")
        
        # Cache stats if available
        cache_hits = getattr(self.coder, 'total_cache_hit_tokens', 0)
        cache_writes = getattr(self.coder, 'total_cache_write_tokens', 0)
        if cache_hits or cache_writes:
            self.io.tool_output(f"\nCache hits:   {cache_hits:,}")
            self.io.tool_output(f"Cache writes: {cache_writes:,}")

    def cmd_tokens(self, args):
        "Report on the number of tokens used by the current chat context"

        res = []

        self.coder.choose_fence()

        main_sys = self.coder.fmt_system_prompt(self.coder.gpt_prompts.main_system)
        main_sys += "\n" + self.coder.fmt_system_prompt(self.coder.gpt_prompts.system_reminder)
        msgs = [
            dict(role="system", content=main_sys),
            dict(
                role="system",
                content=self.coder.fmt_system_prompt(self.coder.gpt_prompts.system_reminder),
            ),
        ]

        tokens = self.coder.main_model.token_count(msgs)
        res.append((tokens, "system messages", ""))

        msgs = self.coder.done_messages + self.coder.cur_messages
        if msgs:
            tokens = self.coder.main_model.token_count(msgs)
            res.append((tokens, "chat history", "use /clear to clear"))

        other_files = set(self.coder.get_all_abs_files()) - set(self.coder.abs_fnames)
        if self.coder.repo_map:
            repo_content = self.coder.repo_map.get_repo_map(self.coder.abs_fnames, other_files)
            if repo_content:
                tokens = self.coder.main_model.token_count(repo_content)
                res.append((tokens, "repository map", "use --map-tokens to resize"))

        fence = "`" * 3

        file_res = []
        for fname in self.coder.abs_fnames:
            relative_fname = self.coder.get_rel_fname(fname)
            content = self.io.read_text(fname)
            if is_image_file(relative_fname):
                tokens = self.coder.main_model.token_count_for_image(fname)
            else:
                content = f"{relative_fname}\n{fence}\n" + content + "{fence}\n"
                tokens = self.coder.main_model.token_count(content)
            file_res.append((tokens, f"{relative_fname}", "/drop to remove"))

        for fname in self.coder.abs_read_only_fnames:
            relative_fname = self.coder.get_rel_fname(fname)
            content = self.io.read_text(fname)
            if content is not None and not is_image_file(relative_fname):
                content = f"{relative_fname}\n{fence}\n" + content + "{fence}\n"
                tokens = self.coder.main_model.token_count(content)
                file_res.append((tokens, f"{relative_fname} (read-only)", "/drop to remove"))

        file_res.sort()
        res.extend(file_res)

        self.io.tool_output(
            f"Approximate context window usage for {self.coder.main_model.name}, in tokens:"
        )
        self.io.tool_output()

        width = 8
        cost_width = 9

        def fmt(v):
            return format(int(v), ",").rjust(width)

        col_width = max(len(row[1]) for row in res)

        cost_pad = " " * cost_width
        total = 0
        total_cost = 0.0
        for tk, msg, tip in res:
            total += tk
            cost = tk * (self.coder.main_model.info.get("input_cost_per_token") or 0)
            total_cost += cost
            msg = msg.ljust(col_width)
            self.io.tool_output(f"${cost:7.4f} {fmt(tk)} {msg} {tip}")

        self.io.tool_output("=" * (width + cost_width + 1))
        self.io.tool_output(f"${total_cost:7.4f} {fmt(total)} tokens total")

        limit = self.coder.main_model.info.get("max_input_tokens") or 0
        if not limit:
            return

        remaining = limit - total
        if remaining > 1024:
            self.io.tool_output(f"{cost_pad}{fmt(remaining)} tokens remaining in context window")
        elif remaining > 0:
            self.io.tool_error(
                f"{cost_pad}{fmt(remaining)} tokens remaining in context window (use /drop or"
                " /clear to make space)"
            )
        else:
            self.io.tool_error(
                f"{cost_pad}{fmt(remaining)} tokens remaining, window exhausted (use /drop or"
                " /clear to make space)"
            )
        self.io.tool_output(f"{cost_pad}{fmt(limit)} tokens max context window size")

    def quote_fname(self, fname):
        if " " in fname and '"' not in fname:
            fname = f'"{fname}"'
        return fname

    def completions_raw_read_only(self, document, complete_event):
        text = document.text_before_cursor
        after_command = text.split()[-1]
        new_document = Document(after_command, cursor_position=len(after_command))

        def get_paths():
            return [self.coder.root] if self.coder.root else None

        path_completer = PathCompleter(
            get_paths=get_paths,
            only_directories=False,
            expanduser=True,
        )

        adjusted_start_position = -len(after_command)
        all_completions = []

        for completion in path_completer.get_completions(new_document, complete_event):
            quoted_text = self.quote_fname(after_command + completion.text)
            all_completions.append(
                Completion(
                    text=quoted_text,
                    start_position=adjusted_start_position,
                    display=completion.display,
                    style=completion.style,
                    selected_style=completion.selected_style,
                )
            )

        add_completions = self.completions_add()
        for completion in add_completions:
            if after_command in completion:
                all_completions.append(
                    Completion(
                        text=completion,
                        start_position=adjusted_start_position,
                        display=completion,
                    )
                )

        sorted_completions = sorted(all_completions, key=lambda c: c.text)
        for completion in sorted_completions:
            yield completion

    def completions_add(self):
        files = set(self.coder.get_all_relative_files())
        files = files - set(self.coder.get_inchat_relative_files())
        files = [self.quote_fname(fn) for fn in files]
        return files

    def glob_filtered_to_repo(self, pattern):
        if not pattern.strip():
            return []
        try:
            if os.path.isabs(pattern):
                raw_matched_files = [Path(pattern)]
            else:
                try:
                    raw_matched_files = list(Path(self.coder.root).glob(pattern))
                except (IndexError, AttributeError):
                    raw_matched_files = []
        except ValueError as err:
            self.io.tool_error(f"Error matching {pattern}: {err}")
            raw_matched_files = []

        matched_files = []
        for fn in raw_matched_files:
            matched_files += expand_subdir(fn)

        matched_files = [
            fn.relative_to(self.coder.root)
            for fn in matched_files
            if fn.is_relative_to(self.coder.root)
        ]

        if self.coder.repo:
            git_files = self.coder.repo.get_tracked_files()
            matched_files = [fn for fn in matched_files if str(fn) in git_files]

        return list(map(str, matched_files))

    def get_help_md(self):
        "Show help about all commands in markdown"

        res = """
|Command|Aliases|Description|
|:------|:------|:----------|
"""
        for name, info in self.get_command_metadata().items():
            cmd = "/" + name
            aliases = ", ".join("**/" + alias + "**" for alias in info.get("aliases") or [])
            description = info.get("description") or ""
            res += f"| **{cmd}** | {aliases} | {description} |\n"

        res += "\n"
        return res

    def cmd_voice(self, args):
        "Record and transcribe voice input"

        if not self.voice:
            if "OPENAI_API_KEY" not in os.environ:
                self.io.tool_error("To use /voice you must provide an OpenAI API key.")
                return
            try:
                self.voice = voice.Voice(
                    audio_format=self.voice_format or "wav", device_name=self.voice_input_device
                )
            except voice.SoundDeviceError:
                self.io.tool_error(
                    "Unable to import `sounddevice` and/or `soundfile`, is portaudio installed?"
                )
                return

        try:
            text = self.voice.record_and_transcribe(None, language=self.voice_language)
        except litellm.OpenAIError as err:
            self.io.tool_error(f"Unable to use OpenAI whisper model: {err}")
            return

        if text:
            self.io.placeholder = text

    def cmd_copy(self, args):
        "Copy the last assistant response to clipboard"
        try:
            messages = self.coder.done_messages + self.coder.cur_messages
            
            # Find last assistant message
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if content:
                        pyperclip.copy(content)
                        # Show preview of copied content
                        preview = content[:100] + "..." if len(content) > 100 else content
                        self.io.tool_output(f"Copied last assistant message to clipboard. Preview: {preview}")
                        return
            
            self.io.tool_error("No assistant messages found to copy.")
            
        except Exception as e:
            self.io.tool_error(f"Failed to copy to clipboard: {e}")

    def cmd_wiki(self, args):
        "Search aider documentation"
        query = args.strip()
        if not query:
            self.io.tool_output("Aider Documentation Links:")
            self.io.tool_output("  Usage:        https://aider.chat/docs/usage.html")
            self.io.tool_output("  Commands:     https://aider.chat/docs/commands.html")
            self.io.tool_output("  FAQ:          https://aider.chat/docs/faq.html")
            self.io.tool_output("  Config:       https://aider.chat/docs/config.html")
            self.io.tool_output("\nSearch online docs: https://aider.chat/docs/search.html?q=" + query.replace(' ', '+'))
            return
        
        # Try to provide contextual help
        topics = {
            "commit": "Use /commit to commit changes, /undo to undo last commit",
            "add": "Use /add <file> to add files, /drop to remove them",
            "model": "Use /model <name> to switch models, see https://aider.chat/docs/llms.html",
            "cost": "Use /cost to see spending, --budget to set limit",
            "tokens": "Use /tokens to see context usage, /clear to free up space",
            "git": "Use /git <command> for any git operation",
            "test": "Use /test <command> to run tests",
            "lint": "Use /lint to check and fix code style",
        }
        
        query_lower = query.lower()
        for topic, help_text in topics.items():
            if topic in query_lower:
                self.io.tool_output(f"Help: {help_text}")
                return
        
        self.io.tool_output(f"No direct help for '{query}'.")
        self.io.tool_output(f"Search docs: https://aider.chat/docs/search.html?q={query.replace(' ', '+')}")

    def cmd_stats(self, args):
        "Show session statistics and usage summary"
        from datetime import datetime
        
        self.io.tool_output("Session Statistics")
        self.io.tool_output("=" * 40)
        
        # Token stats
        sent = getattr(self.coder, 'total_tokens_sent', 0)
        received = getattr(self.coder, 'total_tokens_received', 0)
        total = sent + received
        
        self.io.tool_output(f"Tokens:")
        self.io.tool_output(f"  Sent:     {sent:,}")
        self.io.tool_output(f"  Received: {received:,}")
        self.io.tool_output(f"  Total:    {total:,}")
        
        # Cost
        cost = getattr(self.coder, 'total_cost', 0.0)
        self.io.tool_output(f"\nCost: ${cost:.4f}")
        
        # Cache stats
        cache_hits = getattr(self.coder, 'total_cache_hit_tokens', 0)
        cache_writes = getattr(self.coder, 'total_cache_write_tokens', 0)
        if cache_hits or cache_writes:
            self.io.tool_output(f"\nCache:")
            self.io.tool_output(f"  Hits:  {cache_hits:,}")
            self.io.tool_output(f"  Writes: {cache_writes:,}")
            if cache_hits + cache_writes > 0:
                hit_rate = cache_hits / (cache_hits + cache_writes) * 100
                self.io.tool_output(f"  Hit rate: {hit_rate:.1f}%")
        
        # Messages
        messages = self.coder.done_messages + self.coder.cur_messages
        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
        self.io.tool_output(f"\nMessages:")
        self.io.tool_output(f"  User:      {user_msgs}")
        self.io.tool_output(f"  Assistant: {assistant_msgs}")
        self.io.tool_output(f"  Total:     {len(messages)}")
        
        # Files
        files = len(self.coder.get_inchat_relative_files())
        ro_files = len(self.coder.abs_read_only_fnames)
        self.io.tool_output(f"\nFiles in chat:")
        self.io.tool_output(f"  Editable:   {files}")
        self.io.tool_output(f"  Read-only:  {ro_files}")
        self.io.tool_output(f"  Total:      {files + ro_files}")

    def cmd_template(self, args):
        "Insert a code template (function, class, etc.)"
        templates = {
            "function": '''def function_name():
    """Description of function."""
    pass
''',
            "class": '''class ClassName:
    """Description of class."""
    
    def __init__(self):
        pass
''',
            "test": '''def test_something():
    """Test description."""
    # Arrange
    
    # Act
    
    # Assert
    pass
''',
            "main": '''if __name__ == "__main__":
    pass
''',
            "try": '''try:
    pass
except Exception as e:
    pass
''',
        }
        
        args_clean = args.strip().lower()
        
        if not args_clean or args_clean == "list":
            self.io.tool_output("Available templates:")
            for name in templates:
                self.io.tool_output(f"  {name}")
            self.io.tool_output("\nUsage: /template <name>")
            return
        
        if args_clean in templates:
            template = templates[args_clean]
            try:
                pyperclip.copy(template)
                self.io.tool_output(f"Template '{args_clean}' copied to clipboard.")
                self.io.tool_output("Paste into your file.")
            except Exception:
                self.io.tool_output(f"Template '{args_clean}':")
                self.io.tool_output("-" * 40)
                self.io.tool_output(template)
        else:
            self.io.tool_error(f"Unknown template: {args_clean}")
            self.io.tool_output(f"Available: {', '.join(templates.keys())}")

    def cmd_notify(self, args):
        "Send desktop notification when aider finishes"
        args_clean = args.strip().lower()
        
        if args_clean == "on":
            self.coder._notify_enabled = True
            self.io.tool_output("Notifications enabled.")
        elif args_clean == "off":
            self.coder._notify_enabled = False
            self.io.tool_output("Notifications disabled.")
        elif args_clean == "test":
            self._send_notification("Test notification from aider")
            self.io.tool_output("Test notification sent.")
        else:
            status = "enabled" if getattr(self.coder, '_notify_enabled', False) else "disabled"
            self.io.tool_output(f"Notifications: {status}")
            self.io.tool_output("Usage: /notify [on|off|test]")
    
    def _send_notification(self, message):
        """Send desktop notification if enabled"""
        try:
            import platform
            system = platform.system()
            
            if system == "Darwin":  # macOS
                import subprocess
                subprocess.run([
                    "osascript", "-e",
                    f'display notification "{message}" with title "Aider"'
                ])
            elif system == "Linux":
                import subprocess
                subprocess.run([
                    "notify-send", "Aider", message
                ])
            elif system == "Windows":
                try:
                    from win10toast import ToastNotifier
                    toaster = ToastNotifier()
                    toaster.show_toast("Aider", message, duration=5)
                except ImportError:
                    pass
        except Exception:
            pass

    def cmd_activity(self, args):
        "Show recent coding activity"
        messages = self.coder.done_messages + self.coder.cur_messages
        if not messages:
            self.io.tool_output("No activity recorded yet.")
            return
        
        # Count actions by type
        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
        
        # Estimate edits from commit history
        edits = 0
        if self.coder.repo and hasattr(self.coder, 'aider_commit_hashes'):
            edits = len(self.coder.aider_commit_hashes)
        
        self.io.tool_output("Session Activity:")
        self.io.tool_output("-" * 40)
        self.io.tool_output(f"Messages sent:     {user_msgs}")
        self.io.tool_output(f"Responses:         {assistant_msgs}")
        self.io.tool_output(f"Aider commits:     {edits}")
        
        # Show cost efficiency
        cost = getattr(self.coder, 'total_cost', 0.0)
        if assistant_msgs > 0:
            cost_per_response = cost / assistant_msgs
            self.io.tool_output(f"Cost/response:     ${cost_per_response:.4f}")

    def cmd_metrics(self, args):
        "Show detailed performance metrics"
        self.io.tool_output("Performance Metrics")
        self.io.tool_output("=" * 40)
        
        # Token efficiency
        sent = getattr(self.coder, 'total_tokens_sent', 0)
        received = getattr(self.coder, 'total_tokens_received', 0)
        cost = getattr(self.coder, 'total_cost', 0.0)
        
        if sent > 0:
            ratio = received / sent if sent > 0 else 0
            self.io.tool_output(f"Token Ratio (out/in): {ratio:.2f}")
        
        if received > 0 and cost > 0:
            cost_per_token = cost / received
            self.io.tool_output(f"Cost per output token: ${cost_per_token:.6f}")
        
        # Messages per cost
        messages = self.coder.done_messages + self.coder.cur_messages
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
        if assistant_msgs > 0 and cost > 0:
            cost_per_msg = cost / assistant_msgs
            self.io.tool_output(f"Cost per assistant msg: ${cost_per_msg:.4f}")
        
        # Cache efficiency
        cache_hits = getattr(self.coder, 'total_cache_hit_tokens', 0)
        cache_writes = getattr(self.coder, 'total_cache_write_tokens', 0)
        if cache_hits + cache_writes > 0:
            hit_rate = cache_hits / (cache_hits + cache_writes) * 100
            self.io.tool_output(f"\nCache hit rate: {hit_rate:.1f}%")
            self.io.tool_output(f"Cache savings: ~${cache_hits * 0.0000025:.4f}")  # Approximate
        
        # File stats
        files = self.coder.get_inchat_relative_files()
        if files:
            self.io.tool_output(f"\nFiles tracked: {len(files)}")
            # Estimate context window usage
            try:
                from aider.utils import token_count_for_text
                total_file_tokens = 0
                for fname in files:
                    content = self.io.read_text(self.coder.abs_root_path(fname))
                    if content:
                        total_file_tokens += len(content.split())  # Rough estimate
                self.io.tool_output(f"Est. file tokens: ~{total_file_tokens:,}")
            except Exception:
                pass

    def cmd_bookmark(self, args):
        "Bookmark important chat messages for later reference"
        args_clean = args.strip().lower()
        
        if not hasattr(self.coder, '_bookmarks'):
            self.coder._bookmarks = []
        
        if args_clean.startswith("add "):
            # Bookmark by message index or last message
            idx_str = args[4:].strip()
            messages = self.coder.done_messages + self.coder.cur_messages
            
            if idx_str == "last":
                idx = len(messages) - 1
            else:
                try:
                    idx = int(idx_str)
                except ValueError:
                    self.io.tool_error("Usage: /bookmark add <number|last>")
                    return
            
            if 0 <= idx < len(messages):
                msg = messages[idx]
                content = msg.get("content", "")[:100]
                # Store message hash for stability instead of index
                import hashlib
                msg_hash = hashlib.md5(content.encode()).hexdigest()[:8]
                self.coder._bookmarks.append((idx, msg_hash, msg.get("role", ""), content))
                self.io.tool_output(f"Bookmarked message {idx}")
            else:
                self.io.tool_error(f"Invalid message index: {idx}")
        elif args_clean == "list":
            if self.coder._bookmarks:
                self.io.tool_output("Bookmarks:")
                for i, (idx, msg_hash, role, content) in enumerate(self.coder._bookmarks, 1):
                    self.io.tool_output(f"  {i}. [{idx}] {role}: {content}...")
            else:
                self.io.tool_output("No bookmarks. Use '/bookmark add <number|last>'")
        elif args_clean.startswith("goto "):
            try:
                bm_idx = int(args[5:].strip()) - 1
                if 0 <= bm_idx < len(self.coder._bookmarks):
                    idx, msg_hash, role, content = self.coder._bookmarks[bm_idx]
                    self.io.tool_output(f"Bookmark {bm_idx + 1} (message ~{idx}):")
                    self.io.tool_output(f"  Role: {role}")
                    # Search for message by hash for stability
                    messages = self.coder.done_messages + self.coder.cur_messages
                    found = False
                    for msg in messages:
                        msg_content = msg.get("content", "")
                        if msg_content.startswith(content[:50]):
                            self.io.tool_output(f"  Content: {msg_content[:500]}")
                            found = True
                            break
                    if not found:
                        self.io.tool_output(f"  Content (cached): {content}...")
                else:
                    self.io.tool_error("Invalid bookmark number")
            except ValueError:
                self.io.tool_error("Usage: /bookmark goto <number>")
        elif args_clean.startswith("remove "):
            try:
                bm_idx = int(args[7:].strip()) - 1
                if 0 <= bm_idx < len(self.coder._bookmarks):
                    removed = self.coder._bookmarks.pop(bm_idx)
                    self.io.tool_output(f"Removed bookmark {bm_idx + 1}")
                else:
                    self.io.tool_error("Invalid bookmark number")
            except ValueError:
                self.io.tool_error("Usage: /bookmark remove <number>")
        elif args_clean == "clear":
            count = len(self.coder._bookmarks)
            self.coder._bookmarks = []
            self.io.tool_output(f"Cleared {count} bookmark(s)")
        else:
            self.io.tool_output("Bookmark commands:")
            self.io.tool_output("  /bookmark add <n|last>    - Bookmark a message")
            self.io.tool_output("  /bookmark list            - Show bookmarks")
            self.io.tool_output("  /bookmark goto <n>        - View bookmarked message")
            self.io.tool_output("  /bookmark remove <n>      - Remove bookmark")
            self.io.tool_output("  /bookmark clear           - Clear all bookmarks")

    def cmd_todo(self, args):
        "Manage TODO comments in code"
        import re
        args_clean = args.strip().lower()
        
        if not hasattr(self.coder, '_todo_items'):
            self.coder._todo_items = []
        
        if args_clean.startswith("add "):
            # Add manual TODO
            item = args[4:].strip()
            self.coder._todo_items.append((item, "manual"))
            self.io.tool_output(f"Added: {item}")
        elif args_clean == "scan":
            # Scan files for TODO/FIXME comments
            todos = []
            
            for rel_fname in self.coder.get_inchat_relative_files():
                abs_fname = self.coder.abs_root_path(rel_fname)
                try:
                    content = self.io.read_text(abs_fname)
                    if not content:
                        continue
                    
                    for i, line in enumerate(content.split('\n'), 1):
                        match = re.search(r'(TODO|FIXME|XXX|HACK)[\s:]*(.*)', line, re.IGNORECASE)
                        if match:
                            tag = match.group(1).upper()
                            text = match.group(2).strip()
                            todos.append((rel_fname, i, tag, text))
                except Exception:
                    pass
            
            # Add scanned items to list (avoid duplicates)
            existing = {item[0] for item in self.coder._todo_items}
            for fname, line, tag, text in todos:
                key = f"{fname}:{line} {text}"
                if key not in existing:
                    self.coder._todo_items.append((f"[{tag}] {fname}:{line} {text}", "scan"))
            
            if todos:
                self.io.tool_output(f"Found and added {len(todos)} TODO/FIXME item(s)")
            else:
                self.io.tool_output("No TODO/FIXME items found in chat files.")
        elif args_clean == "list":
            if self.coder._todo_items:
                self.io.tool_output(f"TODO items ({len(self.coder._todo_items)}):")
                for i, (item, source) in enumerate(self.coder._todo_items, 1):
                    self.io.tool_output(f"  {i}. [{source}] {item}")
            else:
                self.io.tool_output("No TODO items. Use '/todo add <text>' or '/todo scan'")
        elif args_clean.startswith("done "):
            try:
                idx = int(args[5:].strip()) - 1
                if 0 <= idx < len(self.coder._todo_items):
                    item = self.coder._todo_items.pop(idx)
                    self.io.tool_output(f"Completed: {item[0]}")
                else:
                    self.io.tool_error("Invalid item number")
            except ValueError:
                self.io.tool_error("Usage: /todo done <number>")
        elif args_clean == "clear":
            count = len(self.coder._todo_items)
            self.coder._todo_items = []
            self.io.tool_output(f"Cleared {count} TODO item(s)")
        else:
            self.io.tool_output("TODO commands:")
            self.io.tool_output("  /todo add <text>  - Add manual TODO")
            self.io.tool_output("  /todo scan        - Scan files for TODO/FIXME")
            self.io.tool_output("  /todo list        - Show all TODO items")
            self.io.tool_output("  /todo done <n>    - Mark item as done")
            self.io.tool_output("  /todo clear       - Clear all TODO items")

    def cmd_echo(self, args):
        "Echo text back (useful for testing or debugging)"
        if args.strip():
            self.io.tool_output(args)
        else:
            self.io.tool_output("(no text provided)")

    def cmd_timer(self, args):
        "Track time spent on the current task"
        import time
        from datetime import timedelta
        
        args_clean = args.strip().lower()
        
        # Initialize timer if not exists
        if not hasattr(self.coder, '_timer_start'):
            self.coder._timer_start = None
            self.coder._timer_sessions = []
        
        if args_clean == "start":
            self.coder._timer_start = time.time()
            self.io.tool_output("Timer started.")
        elif args_clean == "stop":
            if self.coder._timer_start is None:
                self.io.tool_error("No timer running. Use /timer start first.")
                return
            elapsed = time.time() - self.coder._timer_start
            self.coder._timer_sessions.append(elapsed)
            self.coder._timer_start = None
            self.io.tool_output(f"Timer stopped. Session: {timedelta(seconds=int(elapsed))}")
        elif args_clean == "total":
            total = sum(self.coder._timer_sessions)
            if self.coder._timer_start:
                total += time.time() - self.coder._timer_start
            self.io.tool_output(f"Total time: {timedelta(seconds=int(total))}")
            if self.coder._timer_sessions:
                self.io.tool_output(f"Sessions: {len(self.coder._timer_sessions)}")
        elif args_clean == "reset":
            self.coder._timer_start = None
            self.coder._timer_sessions = []
            self.io.tool_output("Timer reset.")
        else:
            self.io.tool_output("Timer commands:")
            self.io.tool_output("  /timer start  - Start the timer")
            self.io.tool_output("  /timer stop   - Stop and record session")
            self.io.tool_output("  /timer total  - Show total time")
            self.io.tool_output("  /timer reset  - Reset all timers")
            
            # Show current status
            if self.coder._timer_start:
                current = time.time() - self.coder._timer_start
                self.io.tool_output(f"\nCurrent session: {timedelta(seconds=int(current))}")
            total = sum(getattr(self.coder, '_timer_sessions', []))
            if total > 0:
                self.io.tool_output(f"Recorded time: {timedelta(seconds=int(total))}")

    def cmd_pr(self, args):
        "Create a pull request template with current context"
        from datetime import datetime
        
        title = args.strip() or "PR: (describe changes)"
        
        lines = [f"# {title}\n"]
        lines.append(f"\n## Summary\n")
        lines.append(f"(brief description of changes)\n")
        
        lines.append(f"\n## Changes Made\n")
        for fname in sorted(self.coder.get_inchat_relative_files()):
            lines.append(f"- Modified `{fname}`\n")
        
        lines.append(f"\n## Testing\n")
        lines.append(f"- [ ] Unit tests pass\n")
        lines.append(f"- [ ] Manual testing completed\n")
        lines.append(f"- [ ] No regressions introduced\n")
        
        lines.append(f"\n## Checklist\n")
        lines.append(f"- [ ] Code follows project style\n")
        lines.append(f"- [ ] Documentation updated (if needed)\n")
        lines.append(f"- [ ] Self-review completed\n")
        
        lines.append(f"\n## Related Issues\n")
        lines.append(f"Closes #(issue number)\n")
        
        report = "".join(lines)
        
        try:
            pyperclip.copy(report)
            self.io.tool_output("PR template copied to clipboard!")
        except Exception as e:
            self.io.tool_output("PR template:\n" + "-" * 40)
            self.io.tool_output(report)

    def cmd_issue(self, args):
        "Create a GitHub issue template with current context"
        from datetime import datetime
        
        title = args.strip() or "Issue: (describe the problem)"
        
        lines = [f"# {title}\n"]
        lines.append(f"\n## Environment\n")
        lines.append(f"- Model: {self.coder.main_model.name}\n")
        lines.append(f"- Edit format: {self.coder.edit_format}\n")
        
        # Git info
        if self.coder.repo:
            branch = self.coder.repo.get_branch_name() or "unknown"
            lines.append(f"- Branch: {branch}\n")
            # Try to get remote URL
            try:
                remote_url = self.coder.repo.repo.git.remote("get-url", "origin")
                if "github.com" in remote_url:
                    # Extract repo from URL
                    remote_url = remote_url.replace(".git", "")
                    if remote_url.startswith("https://github.com/"):
                        repo_path = remote_url.replace("https://github.com/", "")
                    elif remote_url.startswith("git@github.com:"):
                        repo_path = remote_url.replace("git@github.com:", "")
                    else:
                        repo_path = None
                    
                    if repo_path:
                        lines.append(f"- Repository: {repo_path}\n")
            except Exception:
                pass
        
        lines.append(f"\n## Files in Chat\n")
        for fname in sorted(self.coder.get_inchat_relative_files()):
            lines.append(f"- {fname}\n")
        
        lines.append(f"\n## Description\n")
        lines.append(f"(describe your issue here)\n")
        
        lines.append(f"\n## Steps to Reproduce\n")
        lines.append(f"1. \n2. \n3. \n")
        
        lines.append(f"\n## Expected Behavior\n")
        lines.append(f"(what did you expect?)\n")
        
        lines.append(f"\n## Actual Behavior\n")
        lines.append(f"(what happened instead?)\n")
        
        report = "".join(lines)
        
        try:
            pyperclip.copy(report)
            self.io.tool_output("Issue template copied to clipboard!")
            if self.coder.repo:
                try:
                    remote_url = self.coder.repo.repo.git.remote("get-url", "origin")
                    if "github.com" in remote_url:
                        remote_url = remote_url.replace(".git", "")
                        if remote_url.startswith("git@github.com:"):
                            remote_url = remote_url.replace("git@github.com:", "https://github.com/")
                        self.io.tool_output(f"Paste into: {remote_url}/issues/new")
                        return
                except Exception:
                    pass
            self.io.tool_output("Paste into your repository's issue tracker")
        except Exception as e:
            self.io.tool_output("Issue template:\n" + "-" * 40)
            self.io.tool_output(report)

    def cmd_bug(self, args):
        "Create a bug report template with current context"
        from datetime import datetime
        
        lines = ["# Aider Bug Report\n"]
        lines.append(f"Date: {datetime.now().isoformat()}\n")
        lines.append(f"Aider Version: {self.coder.__version__ if hasattr(self.coder, '__version__') else 'unknown'}\n")
        lines.append(f"Model: {self.coder.main_model.name}\n")
        lines.append(f"\n## Description\n")
        lines.append(f"{args or 'Describe the issue here...'}\n")
        lines.append(f"\n## Files in Chat\n")
        for fname in sorted(self.coder.get_inchat_relative_files()):
            lines.append(f"- {fname}\n")
        
        lines.append(f"\n## Recent Chat History\n")
        lines.append("```\n")
        messages = self.coder.done_messages + self.coder.cur_messages
        for msg in messages[-6:]:  # Last 6 messages
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]
            if role != "system":
                lines.append(f"{role}: {content}\n")
        lines.append("```\n")
        
        report = "".join(lines)
        
        try:
            pyperclip.copy(report)
            self.io.tool_output("Bug report template copied to clipboard!")
            self.io.tool_output("Paste it into a GitHub issue at:")
            self.io.tool_output("  https://github.com/Aider-AI/aider/issues/new")
        except Exception as e:
            self.io.tool_error(f"Could not copy to clipboard: {e}")
            self.io.tool_output("\nBug report template:")
            self.io.tool_output("-" * 40)
            self.io.tool_output(report)

    def cmd_paste(self, args):
        """Paste image/text from the clipboard into the chat.\
        Optionally provide a name for the image."""
        try:
            image = ImageGrab.grabclipboard()
            if isinstance(image, Image.Image):
                if args.strip():
                    filename = args.strip()
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in (".jpg", ".jpeg", ".png"):
                        basename = filename
                    else:
                        basename = f"{filename}.png"
                else:
                    basename = "clipboard_image.png"

                temp_dir = tempfile.mkdtemp()
                temp_file_path = os.path.join(temp_dir, basename)
                image_format = "PNG" if basename.lower().endswith(".png") else "JPEG"
                image.save(temp_file_path, image_format)

                abs_file_path = Path(temp_file_path).resolve()

                existing_file = next(
                    (f for f in self.coder.abs_fnames if Path(f).name == abs_file_path.name), None
                )
                if existing_file:
                    self.coder.abs_fnames.remove(existing_file)
                    self.io.tool_output(f"Replaced existing image in the chat: {existing_file}")

                self.coder.abs_fnames.add(str(abs_file_path))
                self.io.tool_output(f"Added clipboard image to the chat: {abs_file_path}")
                self.coder.check_added_files()
                return

            text = pyperclip.paste()
            if text:
                self.io.tool_output(text)
                return text

            self.io.tool_error("No image or text content found in clipboard.")
            return

        except Exception as e:
            self.io.tool_error(f"Error processing clipboard content: {e}")
