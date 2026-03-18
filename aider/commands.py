import glob
import os
import re
import subprocess
import sys
import tempfile
from collections import OrderedDict
from os.path import expanduser
from pathlib import Path

import pyperclip
from PIL import Image, ImageGrab
from prompt_toolkit.completion import Completion, PathCompleter
from prompt_toolkit.document import Document

from aider import models, prompts, voice
from aider.editor import pipe_editor
from aider.format_settings import format_settings
from aider.help import Help, install_help_extra
from aider.io import CommandCompletionException
from aider.llm import litellm
from aider.repo import ANY_GIT_ERROR
from aider.run_cmd import run_cmd
from aider.scrape import Scraper, install_playwright
from aider.utils import is_image_file, is_video_file, is_audio_file
from aider.hooks import get_hooks_manager

from .dump import dump  # noqa: F401


class SwitchCoder(Exception):
    def __init__(self, placeholder=None, **kwargs):
        self.kwargs = kwargs
        self.placeholder = placeholder


class Commands:
    voice = None
    scraper = None

    def clone(self):
        return Commands(
            self.io,
            None,
            voice_language=self.voice_language,
            verify_ssl=self.verify_ssl,
            args=self.args,
            parser=self.parser,
            verbose=self.verbose,
            editor=self.editor,
            original_read_only_fnames=self.original_read_only_fnames,
        )

    def __init__(
        self,
        io,
        coder,
        voice_language=None,
        voice_input_device=None,
        voice_format=None,
        verify_ssl=True,
        args=None,
        parser=None,
        verbose=False,
        editor=None,
        original_read_only_fnames=None,
    ):
        self.io = io
        self.coder = coder
        self.parser = parser
        self.args = args
        self.verbose = verbose

        self.verify_ssl = verify_ssl
        if voice_language == "auto":
            voice_language = None

        self.voice_language = voice_language
        self.voice_format = voice_format
        self.voice_input_device = voice_input_device

        self.help = None
        self.editor = editor

        # Store the original read-only filenames provided via args.read
        self.original_read_only_fnames = set(original_read_only_fnames or [])

    def cmd_model(self, args):
        "Switch the Main Model to a new LLM"

        model_name = args.strip()
        if not model_name:
            announcements = "\n".join(self.coder.get_announcements())
            self.io.tool_output(announcements)
            return

        model = models.Model(
            model_name,
            editor_model=self.coder.main_model.editor_model.name,
            weak_model=self.coder.main_model.weak_model.name,
        )
        models.sanity_check_models(self.io, model)

        # Check if the current edit format is the default for the old model
        old_model_edit_format = self.coder.main_model.edit_format
        current_edit_format = self.coder.edit_format

        new_edit_format = current_edit_format
        if current_edit_format == old_model_edit_format:
            # If the user was using the old model's default, switch to the new model's default
            new_edit_format = model.edit_format

        raise SwitchCoder(main_model=model, edit_format=new_edit_format)

    def cmd_editor_model(self, args):
        "Switch the Editor Model to a new LLM"

        model_name = args.strip()
        model = models.Model(
            self.coder.main_model.name,
            editor_model=model_name,
            weak_model=self.coder.main_model.weak_model.name,
        )
        models.sanity_check_models(self.io, model)
        raise SwitchCoder(main_model=model)

    def cmd_weak_model(self, args):
        "Switch the Weak Model to a new LLM"

        model_name = args.strip()
        model = models.Model(
            self.coder.main_model.name,
            editor_model=self.coder.main_model.editor_model.name,
            weak_model=model_name,
        )
        models.sanity_check_models(self.io, model)
        raise SwitchCoder(main_model=model)

    def cmd_chat_mode(self, args):
        "Switch to a new chat mode"

        from aider import coders

        ef = args.strip()
        valid_formats = OrderedDict(
            sorted(
                (
                    coder.edit_format,
                    coder.__doc__.strip().split("\n")[0] if coder.__doc__ else "No description",
                )
                for coder in coders.__all__
                if getattr(coder, "edit_format", None)
            )
        )

        show_formats = OrderedDict(
            [
                ("help", "Get help about using aider (usage, config, troubleshoot)."),
                ("ask", "Ask questions about your code without making any changes."),
                ("code", "Ask for changes to your code (using the best edit format)."),
                (
                    "architect",
                    (
                        "Work with an architect model to design code changes, and an editor to make"
                        " them."
                    ),
                ),
                (
                    "context",
                    "Automatically identify which files will need to be edited.",
                ),
            ]
        )

        if ef not in valid_formats and ef not in show_formats:
            if ef:
                self.io.tool_error(f'Chat mode "{ef}" should be one of these:\n')
            else:
                self.io.tool_output("Chat mode should be one of these:\n")

            max_format_length = max(len(format) for format in valid_formats.keys())
            for format, description in show_formats.items():
                self.io.tool_output(f"- {format:<{max_format_length}} : {description}")

            self.io.tool_output("\nOr a valid edit format:\n")
            for format, description in valid_formats.items():
                if format not in show_formats:
                    self.io.tool_output(f"- {format:<{max_format_length}} : {description}")

            return

        summarize_from_coder = True
        edit_format = ef

        if ef == "code":
            edit_format = self.coder.main_model.edit_format
            summarize_from_coder = False
        elif ef == "ask":
            summarize_from_coder = False

        raise SwitchCoder(
            edit_format=edit_format,
            summarize_from_coder=summarize_from_coder,
        )

    def completions_model(self):
        models = litellm.model_cost.keys()
        return models

    def cmd_models(self, args):
        "Search the list of available models"

        args = args.strip()

        if args:
            models.print_matching_models(self.io, args)
        else:
            self.io.tool_output("Please provide a partial model name to search for.")

    def cmd_web(self, args, return_content=False):
        "Scrape a webpage, convert to markdown and send in a message"

        url = args.strip()
        if not url:
            self.io.tool_error("Please provide a URL to scrape.")
            return

        self.io.tool_output(f"Scraping {url}...")
        if not self.scraper:
            disable_playwright = getattr(self.args, "disable_playwright", False)
            if disable_playwright:
                res = False
            else:
                res = install_playwright(self.io)
                if not res:
                    self.io.tool_warning("Unable to initialize playwright.")

            self.scraper = Scraper(
                print_error=self.io.tool_error,
                playwright_available=res,
                verify_ssl=self.verify_ssl,
            )

        content = self.scraper.scrape(url) or ""
        content = f"Here is the content of {url}:\n\n" + content
        if return_content:
            return content

        self.io.tool_output("... added to chat.")

        self.coder.cur_messages += [
            dict(role="user", content=content),
            dict(role="assistant", content="Ok."),
        ]

    def is_command(self, inp):
        return inp[0] in "/!"

    def get_raw_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = cmd[1:]
        cmd = cmd.replace("-", "_")

        raw_completer = getattr(self, f"completions_raw_{cmd}", None)
        return raw_completer

    def get_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = cmd[1:]

        cmd = cmd.replace("-", "_")
        fun = getattr(self, f"completions_{cmd}", None)
        if not fun:
            return
        return sorted(fun())

    def get_commands(self):
        commands = []
        for attr in dir(self):
            if not attr.startswith("cmd_"):
                continue
            cmd = attr[4:]
            cmd = cmd.replace("_", "-")
            commands.append("/" + cmd)

        return commands

    def do_run(self, cmd_name, args):
        cmd_name = cmd_name.replace("-", "_")
        cmd_method_name = f"cmd_{cmd_name}"
        cmd_method = getattr(self, cmd_method_name, None)
        if not cmd_method:
            self.io.tool_output(f"Error: Command {cmd_name} not found.")
            return

        # Execute pre-command hooks
        hooks = get_hooks_manager()
        if hooks:
            try:
                pre_result = hooks.execute("pre_command", cmd_name=cmd_name, args=args, io=self.io)
                # Hooks can modify args via return data
                if pre_result.get("data", {}).get("args") is not None:
                    args = pre_result["data"]["args"]
            except Exception as e:
                if hooks.verbose:
                    self.io.tool_error(f"Hook error (pre_command): {e}")

        try:
            result = cmd_method(args)
            
            # Execute post-command hooks
            if hooks:
                try:
                    hooks.execute(
                        "post_command", cmd_name=cmd_name, args=args, result=result, io=self.io
                    )
                except Exception as e:
                    if hooks.verbose:
                        self.io.tool_error(f"Hook error (post_command): {e}")
            
            return result
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete {cmd_name}: {err}")

    def matching_commands(self, inp):
        words = inp.strip().split()
        if not words:
            return

        first_word = words[0]
        rest_inp = inp[len(words[0]) :].strip()

        all_commands = self.get_commands()
        matching_commands = [cmd for cmd in all_commands if cmd.startswith(first_word)]
        return matching_commands, first_word, rest_inp

    def run(self, inp):
        if inp.startswith("!"):
            self.coder.event("command_run")
            return self.do_run("run", inp[1:])

        res = self.matching_commands(inp)
        if res is None:
            return
        matching_commands, first_word, rest_inp = res
        if len(matching_commands) == 1:
            command = matching_commands[0][1:]
            self.coder.event(f"command_{command}")
            return self.do_run(command, rest_inp)
        elif first_word in matching_commands:
            command = first_word[1:]
            self.coder.event(f"command_{command}")
            return self.do_run(command, rest_inp)
        elif len(matching_commands) > 1:
            self.io.tool_error(f"Ambiguous command: {', '.join(matching_commands)}")
        else:
            self.io.tool_error(f"Invalid command: {first_word}")

    # any method called cmd_xxx becomes a command automatically.
    # each one must take an args param.

    def cmd_commit(self, args=None):
        "Commit edits to the repo made outside the chat (commit message optional)"
        try:
            self.raw_cmd_commit(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete commit: {err}")

    def raw_cmd_commit(self, args=None):
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        if not self.coder.repo.is_dirty():
            self.io.tool_warning("No more changes to commit.")
            return

        commit_message = args.strip() if args else None
        self.coder.repo.commit(message=commit_message, coder=self.coder)

    def cmd_lint(self, args="", fnames=None):
        "Lint and fix in-chat files or all dirty files if none in chat"

        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        if not fnames:
            fnames = self.coder.get_inchat_relative_files()

        # If still no files, get all dirty files in the repo
        if not fnames and self.coder.repo:
            fnames = self.coder.repo.get_dirty_files()

        if not fnames:
            self.io.tool_warning("No dirty files to lint.")
            return

        fnames = [self.coder.abs_root_path(fname) for fname in fnames]

        lint_coder = None
        for fname in fnames:
            try:
                errors = self.coder.linter.lint(fname)
            except FileNotFoundError as err:
                self.io.tool_error(f"Unable to lint {fname}")
                self.io.tool_output(str(err))
                continue

            if not errors:
                continue

            self.io.tool_output(errors)
            if not self.io.confirm_ask(f"Fix lint errors in {fname}?", default="y"):
                continue

            # Commit everything before we start fixing lint errors
            if self.coder.repo.is_dirty() and self.coder.dirty_commits:
                self.cmd_commit("")

            if not lint_coder:
                lint_coder = self.coder.clone(
                    # Clear the chat history, fnames
                    cur_messages=[],
                    done_messages=[],
                    fnames=None,
                )

            lint_coder.add_rel_fname(fname)
            lint_coder.run(errors)
            lint_coder.abs_fnames = set()

        if lint_coder and self.coder.repo.is_dirty() and self.coder.auto_commits:
            self.cmd_commit("")

    def cmd_clear(self, args):
        "Clear the chat history"

        self._clear_chat_history()
        self.io.tool_output("All chat history cleared.")

    def _drop_all_files(self):
        self.coder.abs_fnames = set()

        # When dropping all files, keep those that were originally provided via args.read
        if self.original_read_only_fnames:
            # Keep only the original read-only files
            to_keep = set()
            for abs_fname in self.coder.abs_read_only_fnames:
                rel_fname = self.coder.get_rel_fname(abs_fname)
                if (
                    abs_fname in self.original_read_only_fnames
                    or rel_fname in self.original_read_only_fnames
                ):
                    to_keep.add(abs_fname)
            self.coder.abs_read_only_fnames = to_keep
        else:
            self.coder.abs_read_only_fnames = set()

    def _clear_chat_history(self):
        self.coder.done_messages = []
        self.coder.cur_messages = []

    def cmd_reset(self, args):
        "Drop all files and clear the chat history"
        self._drop_all_files()
        self._clear_chat_history()
        self.io.tool_output("All files dropped and chat history cleared.")

    def cmd_tokens(self, args):
        "Report on the number of tokens used by the current chat context"

        res = []

        self.coder.choose_fence()

        # system messages
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

        # chat history
        msgs = self.coder.done_messages + self.coder.cur_messages
        if msgs:
            tokens = self.coder.main_model.token_count(msgs)
            res.append((tokens, "chat history", "use /clear to clear"))

        # repo map
        other_files = set(self.coder.get_all_abs_files()) - set(self.coder.abs_fnames)
        if self.coder.repo_map:
            repo_content = self.coder.repo_map.get_repo_map(self.coder.abs_fnames, other_files)
            if repo_content:
                tokens = self.coder.main_model.token_count(repo_content)
                res.append((tokens, "repository map", "use --map-tokens to resize"))

        fence = "`" * 3

        file_res = []
        # files
        for fname in self.coder.abs_fnames:
            relative_fname = self.coder.get_rel_fname(fname)
            content = self.io.read_text(fname)
            if is_image_file(relative_fname):
                tokens = self.coder.main_model.token_count_for_image(fname)
            else:
                # approximate
                content = f"{relative_fname}\n{fence}\n" + content + "{fence}\n"
                tokens = self.coder.main_model.token_count(content)
            file_res.append((tokens, f"{relative_fname}", "/drop to remove"))

        # read-only files
        for fname in self.coder.abs_read_only_fnames:
            relative_fname = self.coder.get_rel_fname(fname)
            content = self.io.read_text(fname)
            if content is not None and not is_image_file(relative_fname):
                # approximate
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
            self.io.tool_output(f"${cost:7.4f} {fmt(tk)} {msg} {tip}")  # noqa: E231

        self.io.tool_output("=" * (width + cost_width + 1))
        self.io.tool_output(f"${total_cost:7.4f} {fmt(total)} tokens total")  # noqa: E231

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

    def cmd_undo(self, args):
        "Undo the last git commit if it was done by aider"
        try:
            self.raw_cmd_undo(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete undo: {err}")

    def raw_cmd_undo(self, args):
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        last_commit = self.coder.repo.get_head_commit()
        if not last_commit or not last_commit.parents:
            self.io.tool_error("This is the first commit in the repository. Cannot undo.")
            return

        last_commit_hash = self.coder.repo.get_head_commit_sha(short=True)
        last_commit_message = self.coder.repo.get_head_commit_message("(unknown)").strip()
        last_commit_message = (last_commit_message.splitlines() or [""])[0]
        if last_commit_hash not in self.coder.aider_commit_hashes:
            self.io.tool_error("The last commit was not made by aider in this chat session.")
            self.io.tool_output(
                "You could try `/git reset --hard HEAD^` but be aware that this is a destructive"
                " command!"
            )
            return

        if len(last_commit.parents) > 1:
            self.io.tool_error(
                f"The last commit {last_commit.hexsha} has more than 1 parent, can't undo."
            )
            return

        prev_commit = last_commit.parents[0]
        changed_files_last_commit = [item.a_path for item in last_commit.diff(prev_commit)]

        for fname in changed_files_last_commit:
            if self.coder.repo.repo.is_dirty(path=fname):
                self.io.tool_error(
                    f"The file {fname} has uncommitted changes. Please stash them before undoing."
                )
                return

            # Check if the file was in the repo in the previous commit
            try:
                prev_commit.tree[fname]
            except KeyError:
                self.io.tool_error(
                    f"The file {fname} was not in the repository in the previous commit. Cannot"
                    " undo safely."
                )
                return

        local_head = self.coder.repo.repo.git.rev_parse("HEAD")
        current_branch = self.coder.repo.repo.active_branch.name
        try:
            remote_head = self.coder.repo.repo.git.rev_parse(f"origin/{current_branch}")
            has_origin = True
        except ANY_GIT_ERROR:
            has_origin = False

        if has_origin:
            if local_head == remote_head:
                self.io.tool_error(
                    "The last commit has already been pushed to the origin. Undoing is not"
                    " possible."
                )
                return

        # Reset only the files which are part of `last_commit`
        restored = set()
        unrestored = set()
        for file_path in changed_files_last_commit:
            try:
                self.coder.repo.repo.git.checkout("HEAD~1", file_path)
                restored.add(file_path)
            except ANY_GIT_ERROR:
                unrestored.add(file_path)

        if unrestored:
            self.io.tool_error(f"Error restoring {file_path}, aborting undo.")
            self.io.tool_output("Restored files:")
            for file in restored:
                self.io.tool_output(f"  {file}")
            self.io.tool_output("Unable to restore files:")
            for file in unrestored:
                self.io.tool_output(f"  {file}")
            return

        # Move the HEAD back before the latest commit
        self.coder.repo.repo.git.reset("--soft", "HEAD~1")

        self.io.tool_output(f"Removed: {last_commit_hash} {last_commit_message}")

        # Get the current HEAD after undo
        current_head_hash = self.coder.repo.get_head_commit_sha(short=True)
        current_head_message = self.coder.repo.get_head_commit_message("(unknown)").strip()
        current_head_message = (current_head_message.splitlines() or [""])[0]
        self.io.tool_output(f"Now at:  {current_head_hash} {current_head_message}")

        if self.coder.main_model.send_undo_reply:
            return prompts.undo_command_reply

    def cmd_diff(self, args=""):
        "Display the diff of changes since the last message"
        try:
            self.raw_cmd_diff(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete diff: {err}")

    def raw_cmd_diff(self, args=""):
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        current_head = self.coder.repo.get_head_commit_sha()
        if current_head is None:
            self.io.tool_error("Unable to get current commit. The repository might be empty.")
            return

        if len(self.coder.commit_before_message) < 2:
            commit_before_message = current_head + "^"
        else:
            commit_before_message = self.coder.commit_before_message[-2]

        if not commit_before_message or commit_before_message == current_head:
            self.io.tool_warning("No changes to display since the last message.")
            return

        self.io.tool_output(f"Diff since {commit_before_message[:7]}...")

        if self.coder.pretty:
            run_cmd(f"git diff {commit_before_message}")
            return

        diff = self.coder.repo.diff_commits(
            self.coder.pretty,
            commit_before_message,
            "HEAD",
        )

        self.io.print(diff)

    def quote_fname(self, fname):
        if " " in fname and '"' not in fname:
            fname = f'"{fname}"'
        return fname

    def completions_raw_read_only(self, document, complete_event):
        # Get the text before the cursor
        text = document.text_before_cursor

        # Skip the first word and the space after it
        after_command = text.split()[-1]

        # Create a new Document object with the text after the command
        new_document = Document(after_command, cursor_position=len(after_command))

        def get_paths():
            return [self.coder.root] if self.coder.root else None

        path_completer = PathCompleter(
            get_paths=get_paths,
            only_directories=False,
            expanduser=True,
        )

        # Adjust the start_position to replace all of 'after_command'
        adjusted_start_position = -len(after_command)

        # Collect all completions
        all_completions = []

        # Iterate over the completions and modify them
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

        # Add completions from the 'add' command
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

        # Sort all completions based on their text
        sorted_completions = sorted(all_completions, key=lambda c: c.text)

        # Yield the sorted completions
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
                # Handle absolute paths
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

        # if repo, filter against it
        if self.coder.repo:
            git_files = self.coder.repo.get_tracked_files()
            matched_files = [fn for fn in matched_files if str(fn) in git_files]

        res = list(map(str, matched_files))
        return res

    def cmd_add(self, args):
        "Add files to the chat so aider can edit them or review them in detail"

        all_matched_files = set()

        filenames = parse_quoted_filenames(args)
        for word in filenames:
            if Path(word).is_absolute():
                fname = Path(word)
            else:
                fname = Path(self.coder.root) / word

            if self.coder.repo and self.coder.repo.ignored_file(fname):
                self.io.tool_warning(f"Skipping {fname} due to aiderignore or --subtree-only.")
                continue

            if fname.exists():
                if fname.is_file():
                    all_matched_files.add(str(fname))
                    continue
                # an existing dir, escape any special chars so they won't be globs
                word = re.sub(r"([\*\?\[\]])", r"[\1]", word)

            matched_files = self.glob_filtered_to_repo(word)
            if matched_files:
                all_matched_files.update(matched_files)
                continue

            if "*" in str(fname) or "?" in str(fname):
                self.io.tool_error(
                    f"No match, and cannot create file with wildcard characters: {fname}"
                )
                continue

            if fname.exists() and fname.is_dir() and self.coder.repo:
                self.io.tool_error(f"Directory {fname} is not in git.")
                self.io.tool_output(f"You can add to git with: /git add {fname}")
                continue

            if self.io.confirm_ask(f"No files matched '{word}'. Do you want to create {fname}?"):
                try:
                    fname.parent.mkdir(parents=True, exist_ok=True)
                    fname.touch()
                    all_matched_files.add(str(fname))
                except OSError as e:
                    self.io.tool_error(f"Error creating file {fname}: {e}")

        for matched_file in sorted(all_matched_files):
            abs_file_path = self.coder.abs_root_path(matched_file)

            if (
                not abs_file_path.startswith(self.coder.root)
                and not is_image_file(matched_file)
                and self.coder.auto_commits
            ):
                self.io.tool_error(
                    f"Can not add {abs_file_path}, which is not within {self.coder.root}"
                )
                continue

            if (
                self.coder.repo
                and self.coder.repo.git_ignored_file(matched_file)
                and not self.coder.add_gitignore_files
            ):
                self.io.tool_error(f"Can't add {matched_file} which is in gitignore")
                continue

            if abs_file_path in self.coder.abs_fnames:
                self.io.tool_error(f"{matched_file} is already in the chat as an editable file")
                continue
            elif abs_file_path in self.coder.abs_read_only_fnames:
                # Determine if file can be promoted to editable
                if self.coder.repo:
                    can_edit = self.coder.repo.path_in_repo(matched_file)
                else:
                    can_edit = abs_file_path.startswith(self.coder.root)

                if can_edit:
                    self.coder.abs_read_only_fnames.remove(abs_file_path)
                    self.coder.abs_fnames.add(abs_file_path)
                    self.io.tool_output(
                        f"Moved {matched_file} from read-only to editable files in the chat"
                    )
                else:
                    self.io.tool_error(
                        f"Cannot add {matched_file} as it's not part of the repository"
                    )
            else:
                from aider.utils import validate_multimodal_file
                is_valid, error = validate_multimodal_file(matched_file, self.coder.main_model)
                if not is_valid:
                    self.io.tool_error(error)
                    continue
                
                content = self.io.read_text(abs_file_path)
                if content is None:
                    self.io.tool_error(f"Unable to read {matched_file}")
                else:
                    self.coder.abs_fnames.add(abs_file_path)
                    fname = self.coder.get_rel_fname(abs_file_path)
                    self.io.tool_output(f"Added {fname} to the chat")
                    self.coder.check_added_files()

    def completions_drop(self):
        files = self.coder.get_inchat_relative_files()
        read_only_files = [self.coder.get_rel_fname(fn) for fn in self.coder.abs_read_only_fnames]
        all_files = files + read_only_files
        all_files = [self.quote_fname(fn) for fn in all_files]
        return all_files

    def cmd_drop(self, args=""):
        "Remove files from the chat session to free up context space"

        if not args.strip():
            if self.original_read_only_fnames:
                self.io.tool_output(
                    "Dropping all files from the chat session except originally read-only files."
                )
            else:
                self.io.tool_output("Dropping all files from the chat session.")
            self._drop_all_files()
            return

        filenames = parse_quoted_filenames(args)
        for word in filenames:
            # Expand tilde in the path
            expanded_word = os.path.expanduser(word)

            # Handle read-only files with substring matching and samefile check
            read_only_matched = []
            for f in self.coder.abs_read_only_fnames:
                if expanded_word in f:
                    read_only_matched.append(f)
                    continue

                # Try samefile comparison for relative paths
                try:
                    abs_word = os.path.abspath(expanded_word)
                    if os.path.samefile(abs_word, f):
                        read_only_matched.append(f)
                except (FileNotFoundError, OSError):
                    continue

            for matched_file in read_only_matched:
                self.coder.abs_read_only_fnames.remove(matched_file)
                self.io.tool_output(f"Removed read-only file {matched_file} from the chat")

            # For editable files, use glob if word contains glob chars, otherwise use substring
            if any(c in expanded_word for c in "*?[]"):
                matched_files = self.glob_filtered_to_repo(expanded_word)
            else:
                # Use substring matching like we do for read-only files
                matched_files = [
                    self.coder.get_rel_fname(f) for f in self.coder.abs_fnames if expanded_word in f
                ]

            if not matched_files:
                matched_files.append(expanded_word)

            for matched_file in matched_files:
                abs_fname = self.coder.abs_root_path(matched_file)
                if abs_fname in self.coder.abs_fnames:
                    self.coder.abs_fnames.remove(abs_fname)
                    self.io.tool_output(f"Removed {matched_file} from the chat")

    def cmd_git(self, args):
        "Run a git command (output excluded from chat)"
        combined_output = None
        try:
            args = "git " + args
            env = dict(subprocess.os.environ)
            env["GIT_EDITOR"] = "true"
            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                shell=True,
                encoding=self.io.encoding,
                errors="replace",
            )
            combined_output = result.stdout
        except Exception as e:
            self.io.tool_error(f"Error running /git command: {e}")

        if combined_output is None:
            return

        self.io.tool_output(combined_output)

    def cmd_test(self, args):
        "Run a shell command and add the output to the chat on non-zero exit code"
        if not args and self.coder.test_cmd:
            args = self.coder.test_cmd

        if not args:
            return

        if not callable(args):
            if type(args) is not str:
                raise ValueError(repr(args))
            return self.cmd_run(args, True)

        errors = args()
        if not errors:
            return

        self.io.tool_output(errors)
        return errors

    def cmd_shell(self, args):
        "Run an interactive shell (exit to return to aider)"
        # Determine the shell to use
        shell = os.environ.get("SHELL", "/bin/bash")
        shell_name = os.path.basename(shell)
        
        self.io.tool_output(f"Spawning interactive {shell_name} shell. Type 'exit' to return to aider.")
        self.io.tool_output("")
        
        # Prepare environment
        env = dict(os.environ)
        env["PS1"] = f"(aider-shell) $ "
        env["PS2"] = "(aider-shell) > "
        
        # Handle optional command
        if args.strip():
            # Run a specific command in the shell
            result = subprocess.run(
                [shell, "-c", args],
                cwd=self.coder.root,
                env=env,
                encoding=self.io.encoding,
                errors="replace",
            )
        else:
            # Interactive shell session
            result = subprocess.run(
                [shell],
                cwd=self.coder.root,
                env=env,
                encoding=self.io.encoding,
                errors="replace",
            )
        
        self.io.tool_output("")
        self.io.tool_output(f"Exited {shell_name} shell (exit code: {result.returncode})")
        self.io.tool_output("Type a message to continue chatting with aider.")

    def cmd_run(self, args, add_on_nonzero_exit=False):
        "Run a shell command and optionally add the output to the chat (alias: !)"
        exit_status, combined_output = run_cmd(
            args, verbose=self.verbose, error_print=self.io.tool_error, cwd=self.coder.root
        )

        if combined_output is None:
            return

        # Calculate token count of output
        token_count = self.coder.main_model.token_count(combined_output)
        k_tokens = token_count / 1000

        if add_on_nonzero_exit:
            add = exit_status != 0
        else:
            add = self.io.confirm_ask(f"Add {k_tokens:.1f}k tokens of command output to the chat?")

        if add:
            num_lines = len(combined_output.strip().splitlines())
            line_plural = "line" if num_lines == 1 else "lines"
            self.io.tool_output(f"Added {num_lines} {line_plural} of output to the chat.")

            msg = prompts.run_output.format(
                command=args,
                output=combined_output,
            )

            self.coder.cur_messages += [
                dict(role="user", content=msg),
                dict(role="assistant", content="Ok."),
            ]

            if add_on_nonzero_exit and exit_status != 0:
                # Return the formatted output message for test failures
                return msg
            elif add and exit_status != 0:
                self.io.placeholder = "What's wrong? Fix"

        # Return None if output wasn't added or command succeeded
        return None

    def cmd_exit(self, args):
        "Exit the application"
        self.coder.event("exit", reason="/exit")
        sys.exit()

    def cmd_quit(self, args):
        "Exit the application"
        self.cmd_exit(args)

    def cmd_ls(self, args):
        "List all known files and indicate which are included in the chat session"

        files = self.coder.get_all_relative_files()

        other_files = []
        chat_files = []
        read_only_files = []
        for file in files:
            abs_file_path = self.coder.abs_root_path(file)
            if abs_file_path in self.coder.abs_fnames:
                chat_files.append(file)
            else:
                other_files.append(file)

        # Add read-only files
        for abs_file_path in self.coder.abs_read_only_fnames:
            rel_file_path = self.coder.get_rel_fname(abs_file_path)
            read_only_files.append(rel_file_path)

        if not chat_files and not other_files and not read_only_files:
            self.io.tool_output("\nNo files in chat, git repo, or read-only list.")
            return

        if other_files:
            self.io.tool_output("Repo files not in the chat:\n")
        for file in other_files:
            self.io.tool_output(f"  {file}")

        if read_only_files:
            self.io.tool_output("\nRead-only files:\n")
        for file in read_only_files:
            self.io.tool_output(f"  {file}")

        if chat_files:
            self.io.tool_output("\nFiles in chat:\n")
        for file in chat_files:
            self.io.tool_output(f"  {file}")

    def basic_help(self):
        commands = sorted(self.get_commands())
        pad = max(len(cmd) for cmd in commands)
        pad = "{cmd:" + str(pad) + "}"
        for cmd in commands:
            cmd_method_name = f"cmd_{cmd[1:]}".replace("-", "_")
            cmd_method = getattr(self, cmd_method_name, None)
            cmd = pad.format(cmd=cmd)
            if cmd_method:
                description = cmd_method.__doc__
                self.io.tool_output(f"{cmd} {description}")
            else:
                self.io.tool_output(f"{cmd} No description available.")
        self.io.tool_output()
        self.io.tool_output("Use `/help <question>` to ask questions about how to use aider.")

    def cmd_help(self, args):
        "Ask questions about aider"

        if not args.strip():
            self.basic_help()
            return

        self.coder.event("interactive help")
        from aider.coders.base_coder import Coder

        if not self.help:
            res = install_help_extra(self.io)
            if not res:
                self.io.tool_error("Unable to initialize interactive help.")
                return

            self.help = Help()

        coder = Coder.create(
            io=self.io,
            from_coder=self.coder,
            edit_format="help",
            summarize_from_coder=False,
            map_tokens=512,
            map_mul_no_files=1,
        )
        user_msg = self.help.ask(args)
        user_msg += """
# Announcement lines from when this session of aider was launched:

"""
        user_msg += "\n".join(self.coder.get_announcements()) + "\n"

        coder.run(user_msg, preproc=False)

        if self.coder.repo_map:
            map_tokens = self.coder.repo_map.max_map_tokens
            map_mul_no_files = self.coder.repo_map.map_mul_no_files
        else:
            map_tokens = 0
            map_mul_no_files = 1

        raise SwitchCoder(
            edit_format=self.coder.edit_format,
            summarize_from_coder=False,
            from_coder=coder,
            map_tokens=map_tokens,
            map_mul_no_files=map_mul_no_files,
            show_announcements=False,
        )

    def completions_ask(self):
        raise CommandCompletionException()

    def completions_code(self):
        raise CommandCompletionException()

    def completions_architect(self):
        raise CommandCompletionException()

    def completions_context(self):
        raise CommandCompletionException()

    def cmd_ask(self, args):
        """Ask questions about the code base without editing any files. If no prompt provided, switches to ask mode."""  # noqa
        return self._generic_chat_command(args, "ask")

    def cmd_code(self, args):
        """Ask for changes to your code. If no prompt provided, switches to code mode."""  # noqa
        return self._generic_chat_command(args, self.coder.main_model.edit_format)

    def cmd_architect(self, args):
        """Enter architect/editor mode using 2 different models. If no prompt provided, switches to architect/editor mode."""  # noqa
        return self._generic_chat_command(args, "architect")

    def cmd_context(self, args):
        """Enter context mode to see surrounding code context. If no prompt provided, switches to context mode."""  # noqa
        return self._generic_chat_command(args, "context", placeholder=args.strip() or None)

    def cmd_ok(self, args):
        "Alias for `/code Ok, please go ahead and make those changes.` (any args are appended)"
        msg = "Ok, please go ahead and make those changes."
        extra = (args or "").strip()
        if extra:
            msg = f"{msg} {extra}"
        return self.cmd_code(msg)

    def _generic_chat_command(self, args, edit_format, placeholder=None):
        if not args.strip():
            # Switch to the corresponding chat mode if no args provided
            return self.cmd_chat_mode(edit_format)

        from aider.coders.base_coder import Coder

        coder = Coder.create(
            io=self.io,
            from_coder=self.coder,
            edit_format=edit_format,
            summarize_from_coder=False,
        )

        user_msg = args
        coder.run(user_msg)

        # Use the provided placeholder if any
        raise SwitchCoder(
            edit_format=self.coder.edit_format,
            summarize_from_coder=False,
            from_coder=coder,
            show_announcements=False,
            placeholder=placeholder,
        )

    def get_help_md(self):
        "Show help about all commands in markdown"

        res = """
|Command|Description|
|:------|:----------|
"""
        commands = sorted(self.get_commands())
        for cmd in commands:
            cmd_method_name = f"cmd_{cmd[1:]}".replace("-", "_")
            cmd_method = getattr(self, cmd_method_name, None)
            if cmd_method:
                description = cmd_method.__doc__
                res += f"| **{cmd}** | {description} |\n"
            else:
                res += f"| **{cmd}** | |\n"

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

    def cmd_paste(self, args):
        """Paste image/text from the clipboard into the chat.\
        Optionally provide a name for the image."""
        try:
            # Check for image first
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

                # Check if a file with the same name already exists in the chat
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

            # If not an image, try to get text
            text = pyperclip.paste()
            if text:
                self.io.tool_output(text)
                return text

            self.io.tool_error("No image or text content found in clipboard.")
            return

        except Exception as e:
            self.io.tool_error(f"Error processing clipboard content: {e}")

    def cmd_read_only(self, args):
        "Add files to the chat that are for reference only, or turn added files to read-only"
        if not args.strip():
            # Convert all files in chat to read-only
            for fname in list(self.coder.abs_fnames):
                self.coder.abs_fnames.remove(fname)
                self.coder.abs_read_only_fnames.add(fname)
                rel_fname = self.coder.get_rel_fname(fname)
                self.io.tool_output(f"Converted {rel_fname} to read-only")
            return

        filenames = parse_quoted_filenames(args)
        all_paths = []

        # First collect all expanded paths
        for pattern in filenames:
            expanded_pattern = expanduser(pattern)
            path_obj = Path(expanded_pattern)
            is_abs = path_obj.is_absolute()
            if not is_abs:
                path_obj = Path(self.coder.root) / path_obj

            matches = []
            # Check for literal path existence first
            if path_obj.exists():
                matches = [path_obj]
            else:
                # If literal path doesn't exist, try globbing
                if is_abs:
                    # For absolute paths, glob it
                    matches = [Path(p) for p in glob.glob(expanded_pattern)]
                else:
                    # For relative paths and globs, use glob from the root directory
                    matches = list(Path(self.coder.root).glob(expanded_pattern))

            if not matches:
                self.io.tool_error(f"No matches found for: {pattern}")
            else:
                all_paths.extend(matches)

        # Then process them in sorted order
        for path in sorted(all_paths):
            abs_path = self.coder.abs_root_path(path)
            if os.path.isfile(abs_path):
                self._add_read_only_file(abs_path, path)
            elif os.path.isdir(abs_path):
                self._add_read_only_directory(abs_path, path)
            else:
                self.io.tool_error(f"Not a file or directory: {abs_path}")

    def _add_read_only_file(self, abs_path, original_name):
        from aider.utils import validate_multimodal_file
        is_valid, error = validate_multimodal_file(original_name, self.coder.main_model)
        if not is_valid:
            self.io.tool_error(error)
            return

        if abs_path in self.coder.abs_fnames:

            self.io.tool_error(f"{original_name} is already in the chat as a read-only file")
            return
        elif abs_path in self.coder.abs_fnames:
            self.coder.abs_fnames.remove(abs_path)
            self.coder.abs_read_only_fnames.add(abs_path)
            self.io.tool_output(
                f"Moved {original_name} from editable to read-only files in the chat"
            )
        else:
            self.coder.abs_read_only_fnames.add(abs_path)
            self.io.tool_output(f"Added {original_name} to read-only files.")

    def _add_read_only_directory(self, abs_path, original_name):
        added_files = 0
        for root, _, files in os.walk(abs_path):
            for file in files:
                file_path = os.path.join(root, file)
                if (
                    file_path not in self.coder.abs_fnames
                    and file_path not in self.coder.abs_read_only_fnames
                ):
                    self.coder.abs_read_only_fnames.add(file_path)
                    added_files += 1

        if added_files > 0:
            self.io.tool_output(
                f"Added {added_files} files from directory {original_name} to read-only files."
            )
        else:
            self.io.tool_output(f"No new files added from directory {original_name}.")

    def cmd_map(self, args):
        "Print out the current repository map"
        repo_map = self.coder.get_repo_map()
        if repo_map:
            self.io.tool_output(repo_map)
        else:
            self.io.tool_output("No repository map available.")

    def cmd_map_refresh(self, args):
        "Force a refresh of the repository map"
        repo_map = self.coder.get_repo_map(force_refresh=True)
        if repo_map:
            self.io.tool_output("The repo map has been refreshed, use /map to view it.")

    def cmd_system(self, args):
        """Set a custom system prompt, load from file, or reset to default.
        Usage:
            /system "prompt"           Set system prompt (replaces default)
            /system --append "text"    Append text to the default prompt
            /system --prepend "text"   Prepend text to the default prompt
            /system -f file            Load system prompt from file
            /system reset              Reset to the default system prompt
            /system view               Show the final rendered system prompt and variables
        """
        args = args.strip()
        if not args:
            if self.coder.system_prompt_override:
                self.io.tool_output("Current custom system prompt:")
                self.io.tool_output(self.coder.system_prompt_override)
            else:
                self.io.tool_output("Using default system prompt.")
            return

        if args == "view":
            chunks = self.coder.format_chat_chunks()
            self.io.tool_output("Final rendered system prompt:")
            self.io.tool_output("---")
            self.io.tool_output(chunks.system[0]["content"])
            self.io.tool_output("---")
            self.io.tool_output("\nAvailable Template Variables:")
            self.io.tool_output("  {fence}, {quad_backtick_reminder}, {final_reminders},")
            self.io.tool_output("  {platform}, {shell_cmd_prompt}, {rename_with_shell},")
            self.io.tool_output("  {shell_cmd_reminder}, {go_ahead_tip}, {language}")
            return

        new_prompt = None
        mode = "replace"

        if args.startswith("--append "):
            mode = "append"
            args = args[len("--append ") :].strip()
        elif args.startswith("--prepend "):
            mode = "prepend"
            args = args[len("--prepend ") :].strip()

        if args == "reset":
            new_prompt = None
            self.io.tool_output("System prompt reset to default.")
        elif args.startswith("-f ") or args.startswith("--file "):
            filename = args.split(None, 1)[1]
            try:
                content = self.io.read_text(filename)
                if content is None:
                    self.io.tool_error(f"Unable to read file: {filename}")
                    return
                new_prompt = content
                self.io.tool_output(f"Loaded system prompt from {filename}")
            except Exception as e:
                self.io.tool_error(f"Error reading system prompt from {filename}: {e}")
                return
        else:
            # Handle quoted or unquoted string
            if args.startswith('"') and args.endswith('"') and len(args) >= 2:
                new_prompt = args[1:-1]
            else:
                new_prompt = args

        if new_prompt and mode == "append":
            new_prompt = self.coder.gpt_prompts.main_system + "\n\n" + new_prompt
            self.io.tool_output("Appended to system prompt.")
        elif new_prompt and mode == "prepend":
            new_prompt = new_prompt + "\n\n" + self.coder.gpt_prompts.main_system
            self.io.tool_output("Prepended to system prompt.")
        elif new_prompt:
            self.io.tool_output("System prompt updated (replaces default).")

        raise SwitchCoder(system_prompt_override=new_prompt)

    def cmd_search_web(self, args):
        """Search the web for information via OpenClaw Gateway.
        Usage: /search-web <query>
        """
        query = args.strip()
        if not query:
            self.io.tool_error("Please provide a search query.")
            return

        if not hasattr(self.coder, "tool_router"):
            self.io.tool_error("Tool mode not available.")
            return

        self.io.tool_output(f"Searching the web via OpenClaw for: {query}...")
        result = self.coder.tool_router.execute("search_web", {"query": query})
        
        if result.success:
            self.io.tool_output(result.output)
        else:
            self.io.tool_error(f"Search failed: {result.error}")

    def cmd_index(self, args):
        """Index external directories or search the global semantic index.
        Usage:
            /index add <dir>    Index the specified directory (and its subdirs)
            /index doc <url>    Crawl and index a documentation site
            /index search <q>   Query the global index for information
            /index status       Show status of the global index
        """
        from aider.indexers.semantic import SemanticIndexer
        from aider.scrape import DocCrawler
        
        args = args.strip()
        if not args:
            self.io.tool_output("Use '/index add <dir>', '/index doc <url>', or '/index search <query>'")
            return

        indexer = SemanticIndexer.get_global()
        
        if args.startswith("add "):
            # ... (existing add logic)
            path_str = args[len("add ") :].strip()
            path = Path(path_str).resolve()
            if not path.exists() or not path.is_dir():
                self.io.tool_error(f"Directory not found: {path_str}")
                return
            
            self.io.tool_output(f"Indexing {path} (Global Index)...")
            files = []
            for root, _, fs in os.walk(path):
                for f in fs:
                    if f.endswith(('.py', '.js', '.ts', '.c', '.cpp', '.rs', '.go', '.md')):
                        files.append(str(Path(root) / f))
            
            indexer.update_index(files)
            self.io.tool_output(f"Indexed {len(files)} files.")

        elif args.startswith("doc "):
            self.io.tool_error("/index doc is currently disabled.")
            return
            # url = args[len("doc ") :].strip()
            # self.io.tool_output(f"🔍 Crawling documentation: {url}...")
            # crawler = DocCrawler(url)
            # 
            # count = 0
            # for page_url, content in crawler.crawl():
            #     self.io.tool_output(f"  - Indexed: {page_url}")
            #     # We reuse update_index by passing a virtual filename or updating directly
            #     # For this demo, we'll implement a simple content-indexing method
            #     indexer.add_content(page_url, content)
            #     count += 1
            # 
            # self.io.tool_output(f"✅ Success! Indexed {count} documentation pages.")
            
        elif args.startswith("search "):
            query = args[len("search ") :].strip()
            self.io.tool_output(f"Searching global index for: {query}...")
            results = indexer.query(query)
            if results:
                self.io.tool_output("Matches found in global index:")
                for path, score in results:
                    self.io.tool_output(f"  [{score:.2f}] {path}")
            else:
                self.io.tool_output("No matches found.")
        elif args == "status":
            with sqlite3.connect(indexer.db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM file_cache").fetchone()[0]
            self.io.tool_output(f"Global index contains {count} files.")
        else:
            self.io.tool_error(f"Unknown index action: {args}")

    def cmd_mcp(self, args):
        """Manage MCP (Model Context Protocol) servers.
        Usage:
            /mcp add <name> <cmd> [args...]    Add an MCP server
            /mcp list                         List active MCP servers and tools
            /mcp remove <name>                Remove an MCP server
        """
        args = args.strip()
        if not args:
            self.io.tool_output("Use '/mcp add', '/mcp list', or '/mcp remove'")
            return

        if not hasattr(self.coder, "tool_router") or not hasattr(self.coder.tool_router, "mcp_manager"):
            self.io.tool_error("MCP support not available in this coder mode.")
            return

        manager = self.coder.tool_router.mcp_manager

        if args.startswith("add "):
            parts = args[4:].split()
            if len(parts) < 2:
                self.io.tool_error("Usage: /mcp add <name> <cmd> [args...]")
                return
            name = parts[0]
            cmd = parts[1:]
            self.io.tool_output(f"Starting MCP server '{name}'...")
            if manager.add_server(name, cmd):
                self.io.tool_output(f"MCP server '{name}' added successfully.")
            else:
                self.io.tool_error(f"Failed to start MCP server '{name}'.")
        
        elif args == "list":
            if not manager.servers:
                self.io.tool_output("No active MCP servers.")
                return
            for name, server in manager.servers.items():
                self.io.tool_output(f"Server: {name} ({' '.join(server.command)})")
                if server.tools:
                    self.io.tool_output("  Tools:")
                    for tool in server.tools:
                        self.io.tool_output(f"    - {tool.name}: {tool.description}")
                if server.resources:
                    self.io.tool_output("  Resources:")
                    for r in server.resources:
                        self.io.tool_output(f"    - {r.name} ({r.uri})")
                if server.prompts:
                    self.io.tool_output("  Prompts:")
                    for p in server.prompts:
                        self.io.tool_output(f"    - {p.name}: {p.description}")
        
        elif args.startswith("resource "):
            uri = args[9:].strip()
            self.io.tool_output(f"Reading MCP resource: {uri}...")
            try:
                res = manager.read_resource(uri)
                for item in res.get("contents", []):
                    if "text" in item:
                        self.io.tool_output(item["text"])
                    else:
                        self.io.tool_output(f"[Binary data: {item.get('mimeType')}]")
            except Exception as e:
                self.io.tool_error(f"Error reading resource: {e}")

        elif args.startswith("remove "):
            name = args[7:].strip()
            if name in manager.servers:
                manager.servers[name].stop()
                del manager.servers[name]
                self.io.tool_output(f"MCP server '{name}' removed.")
            else:
                self.io.tool_error(f"MCP server '{name}' not found.")
        else:
            self.io.tool_error(f"Unknown mcp action: {args}")

    def cmd_auto(self, args):
        """Execute a task autonomously using the Architect workflow.
        
        This uses the full ArchitectCoder with:
        - Librarian phase: Auto-discovers relevant files
        - Architect phase: Plans with tool access
        - Reviewer phase: Self-critiques the plan
        - Editor phase: Executes with proper formatting
        - Self-correction: Retries on test failures
        
        Provides parity with Claude Code, Codex, and Gemini.
        
        Usage: /auto "task description" [--test "test command"]
        """
        import re
        
        # Parse arguments
        task = None
        test_cmd = None
        
        # Extract test command if present
        test_match = re.search(r'--test\s+"([^"]+)"', args)
        if test_match:
            test_cmd = test_match.group(1)
            args = re.sub(r'--test\s+"[^"]+"', '', args)
        elif test_match := re.search(r"--test\s+'([^']+)'", args):
            test_cmd = test_match.group(1)
            args = re.sub(r"--test\s+'[^']+'", '', args)
            
        task = args.strip().strip('"').strip("'")
        
        if not task:
            self.io.tool_output("Usage: /auto \"task description\" [--test \"test command\"]")
            return

        # Use ArchitectCoder for full autonomous workflow
        from aider.coders.base_coder import Coder
        
        self.io.tool_output(f"🚀 Starting autonomous Architect workflow")
        self.io.tool_output(f"📝 Task: {task}")
        if test_cmd:
            self.io.tool_output(f"🎯 Test: {test_cmd}")
        
        # Create architect coder with test configuration
        architect_kwargs = dict(
            io=self.io,
            from_coder=self.coder,
            edit_format="architect",
            summarize_from_coder=False,
            auto_test=bool(test_cmd),
            test_cmd=test_cmd,
        )
        
        # Only set auto_accept_architect if test command provided
        # Otherwise let user review the plan
        if test_cmd:
            architect_kwargs['auto_accept_architect'] = True  # Auto-execute if tests pass
        
        architect = Coder.create(**architect_kwargs)
        
        # Run the task through the architect workflow
        # This handles: discovery, planning, critique, editing, and self-correction
        architect.run(with_message=task)
        
        # Switch back to original mode
        raise SwitchCoder(
            edit_format=self.coder.edit_format,
            summarize_from_coder=False,
            from_coder=architect,
        )

    def cmd_swarm(self, args):
        """Solve a task using a collaborative swarm of agents.
        Usage: /swarm "task description" [--agents "architect,developer,reviewer"]
        """
        import re
        import asyncio
        
        # Parse arguments
        task = None
        agents_list = ["Architect", "Developer", "Reviewer"]
        
        # Extract agents if present
        agents_match = re.search(r'--agents\s+"([^"]+)"', args)
        if agents_match:
            agents_list = [a.strip() for a in agents_match.group(1).split(',')]
            args = re.sub(r'--agents\s+"[^"]+"', '', args)
            
        task = args.strip().strip('"').strip("'")
        
        if not task:
            self.io.tool_output("Usage: /swarm \"task description\" [--agents \"arch,dev,test\"]")
            return

        swarm_skill = self.skills_registry.create("swarm", self.coder)
        if swarm_skill:
            asyncio.run(swarm_skill.execute(task, agents_list))

    def cmd_watch(self, args):
        """Monitor background processes or toggle background auto-fix.
        Usage:
            /watch start <name> <cmd>    Start a background process
            /watch read <name> [lines]   Read the latest output
            /watch input <name> <text>   Send input to stdin
            /watch list                  List monitored processes
            /watch stop <name>           Stop a process
            /watch fix-on-save [on/off]  Toggle auto-fix on file save
        """
        args = args.strip()
        if not args:
            self.io.tool_output("Use '/watch start', '/watch read', '/watch list', or '/watch fix-on-save'")
            return

        if args.startswith("fix-on-save"):
            if not self.io.file_watcher:
                self.io.tool_error("File watcher not available.")
                return
            
            sub = args[11:].strip()
            if sub == "on":
                self.io.file_watcher.fix_on_save = True
            elif sub == "off":
                self.io.file_watcher.fix_on_save = False
            else:
                self.io.file_watcher.fix_on_save = not self.io.file_watcher.fix_on_save
            
            status = "Enabled" if self.io.file_watcher.fix_on_save else "Disabled"
            self.io.tool_output(f"Background auto-fix on save: {status}")
            return

        if not hasattr(self.coder, "tool_router") or not hasattr(self.coder.tool_router, "terminal_watcher"):
            self.io.tool_error("Terminal watching not available in this coder mode.")
            return

        watcher = self.coder.tool_router.terminal_watcher

        if args.startswith("start "):
            parts = args[6:].split(None, 1)
            if len(parts) < 2:
                self.io.tool_error("Usage: /watch start <name> <cmd>")
                return
            name, cmd = parts
            if watcher.start_process(name, cmd, self.coder.root):
                self.io.tool_output(f"Started background process '{name}': {cmd}")
            else:
                self.io.tool_error(f"Failed to start process '{name}'")
        
        elif args.startswith("read "):
            parts = args[5:].split()
            name = parts[0]
            lines = int(parts[1]) if len(parts) > 1 else 50
            logs = watcher.get_logs(name, lines)
            self.io.tool_output(f"--- Logs for '{name}' ---")
            self.io.tool_output("\n".join(logs))
            self.io.tool_output(f"--- End of logs ---")

        elif args.startswith("input "):
            parts = args[6:].split(None, 1)
            if len(parts) < 2:
                self.io.tool_error("Usage: /watch input <name> <text>")
                return
            name, text = parts
            if watcher.send_input(name, text):
                self.io.tool_output(f"Sent input to '{name}'.")
            else:
                self.io.tool_error(f"Failed to send input to '{name}' (is it running?)")

        elif args.startswith("signal "):
            parts = args[7:].split()
            if len(parts) < 2:
                self.io.tool_error("Usage: /watch signal <name> <signal_number>")
                return
            name, sig = parts
            if watcher.send_signal(name, int(sig)):
                self.io.tool_output(f"Sent signal {sig} to '{name}'.")
            else:
                self.io.tool_error(f"Failed to send signal to '{name}' (is it running?)")
            
        elif args == "list":
            if not watcher.processes:
                self.io.tool_output("No active background processes.")
                return
            for name, proc in watcher.processes.items():
                status = "Running" if proc.running else "Stopped"
                self.io.tool_output(f"- {name}: {status} ({' '.join(proc.command)})")
        
        elif args.startswith("stop "):
            name = args[5:].strip()
            watcher.stop_process(name)
            self.io.tool_output(f"Stopped process '{name}'.")
        else:
            self.io.tool_error(f"Unknown watch action: {args}")

    def cmd_settings(self, args):
        "Print out the current settings"
        settings = format_settings(self.parser, self.args)
        announcements = "\n".join(self.coder.get_announcements())

        # Build metadata for the active models (main, editor, weak)
        model_sections = []
        active_models = [
            ("Main model", self.coder.main_model),
            ("Editor model", getattr(self.coder.main_model, "editor_model", None)),
            ("Weak model", getattr(self.coder.main_model, "weak_model", None)),
        ]
        for label, model in active_models:
            if not model:
                continue
            info = getattr(model, "info", {}) or {}
            if not info:
                continue
            model_sections.append(f"{label} ({model.name}):")
            for k, v in sorted(info.items()):
                model_sections.append(f"  {k}: {v}")
            model_sections.append("")  # blank line between models

        model_metadata = "\n".join(model_sections)

        output = f"{announcements}\n{settings}"
        if model_metadata:
            output += "\n" + model_metadata
        self.io.tool_output(output)

    def completions_raw_load(self, document, complete_event):
        return self.completions_raw_read_only(document, complete_event)

    def cmd_load(self, args):
        "Load and execute commands from a file"
        if not args.strip():
            self.io.tool_error("Please provide a filename containing commands to load.")
            return

        try:
            with open(args.strip(), "r", encoding=self.io.encoding, errors="replace") as f:
                commands = f.readlines()
        except FileNotFoundError:
            self.io.tool_error(f"File not found: {args}")
            return
        except Exception as e:
            self.io.tool_error(f"Error reading file: {e}")
            return

        for cmd in commands:
            cmd = cmd.strip()
            if not cmd or cmd.startswith("#"):
                continue

            self.io.tool_output(f"\nExecuting: {cmd}")
            try:
                self.run(cmd)
            except SwitchCoder:
                self.io.tool_error(
                    f"Command '{cmd}' is only supported in interactive mode, skipping."
                )

    def completions_raw_save(self, document, complete_event):
        return self.completions_raw_read_only(document, complete_event)

    def cmd_save(self, args):
        "Save commands to a file that can reconstruct the current chat session's files"
        if not args.strip():
            self.io.tool_error("Please provide a filename to save the commands to.")
            return

        try:
            with open(args.strip(), "w", encoding=self.io.encoding) as f:
                f.write("/drop\n")
                # Write commands to add editable files
                for fname in sorted(self.coder.abs_fnames):
                    rel_fname = self.coder.get_rel_fname(fname)
                    f.write(f"/add       {rel_fname}\n")

                # Write commands to add read-only files
                for fname in sorted(self.coder.abs_read_only_fnames):
                    # Use absolute path for files outside repo root, relative path for files inside
                    if Path(fname).is_relative_to(self.coder.root):
                        rel_fname = self.coder.get_rel_fname(fname)
                        f.write(f"/read-only {rel_fname}\n")
                    else:
                        f.write(f"/read-only {fname}\n")

            self.io.tool_output(f"Saved commands to {args.strip()}")
        except Exception as e:
            self.io.tool_error(f"Error saving commands to file: {e}")

    def cmd_multiline_mode(self, args):
        "Toggle multiline mode (swaps behavior of Enter and Meta+Enter)"
        self.io.toggle_multiline_mode()

    def cmd_copy(self, args):
        "Copy the last assistant message to the clipboard"
        all_messages = self.coder.done_messages + self.coder.cur_messages
        assistant_messages = [msg for msg in reversed(all_messages) if msg["role"] == "assistant"]

        if not assistant_messages:
            self.io.tool_error("No assistant messages found to copy.")
            return

        last_assistant_message = assistant_messages[0]["content"]

        try:
            pyperclip.copy(last_assistant_message)
            preview = (
                last_assistant_message[:50] + "..."
                if len(last_assistant_message) > 50
                else last_assistant_message
            )
            self.io.tool_output(f"Copied last assistant message to clipboard. Preview: {preview}")
        except pyperclip.PyperclipException as e:
            self.io.tool_error(f"Failed to copy to clipboard: {str(e)}")
            self.io.tool_output(
                "You may need to install xclip or xsel on Linux, or pbcopy on macOS."
            )
        except Exception as e:
            self.io.tool_error(f"An unexpected error occurred while copying to clipboard: {str(e)}")

    def cmd_report(self, args):
        "Report a problem by opening a GitHub Issue"
        from aider.report import report_github_issue

        announcements = "\n".join(self.coder.get_announcements())
        issue_text = announcements

        if args.strip():
            title = args.strip()
        else:
            title = None

        report_github_issue(issue_text, title=title, confirm=False)

    def cmd_editor(self, initial_content=""):
        "Open an editor to write a prompt"

        user_input = pipe_editor(initial_content, suffix="md", editor=self.editor)
        if user_input.strip():
            self.io.set_placeholder(user_input.rstrip())

    def cmd_edit(self, args=""):
        "Alias for /editor: Open an editor to write a prompt"
        return self.cmd_editor(args)

    def cmd_think_tokens(self, args):
        """Set the thinking token budget, eg: 8096, 8k, 10.5k, 0.5M, or 0 to disable."""
        model = self.coder.main_model

        if not args.strip():
            # Display current value if no args are provided
            formatted_budget = model.get_thinking_tokens()
            if formatted_budget is None:
                self.io.tool_output("Thinking tokens are not currently set.")
            else:
                budget = model.get_raw_thinking_tokens()
                self.io.tool_output(
                    f"Current thinking token budget: {budget:,} tokens ({formatted_budget})."
                )
            return

        value = args.strip()
        model.set_thinking_tokens(value)

        # Handle the special case of 0 to disable thinking tokens
        if value == "0":
            self.io.tool_output("Thinking tokens disabled.")
        else:
            formatted_budget = model.get_thinking_tokens()
            budget = model.get_raw_thinking_tokens()
            self.io.tool_output(
                f"Set thinking token budget to {budget:,} tokens ({formatted_budget})."
            )

        self.io.tool_output()

        # Output announcements
        announcements = "\n".join(self.coder.get_announcements())
        self.io.tool_output(announcements)

    def cmd_reasoning_effort(self, args):
        "Set the reasoning effort level (values: number or low/medium/high depending on model)"
        model = self.coder.main_model

        if not args.strip():
            # Display current value if no args are provided
            reasoning_value = model.get_reasoning_effort()
            if reasoning_value is None:
                self.io.tool_output("Reasoning effort is not currently set.")
            else:
                self.io.tool_output(f"Current reasoning effort: {reasoning_value}")
            return

        value = args.strip()
        model.set_reasoning_effort(value)
        reasoning_value = model.get_reasoning_effort()
        self.io.tool_output(f"Set reasoning effort to {reasoning_value}")
        self.io.tool_output()

        # Output announcements
        announcements = "\n".join(self.coder.get_announcements())
        self.io.tool_output(announcements)

    def cmd_auto(self, args):
        """
        Toggle autonomous tool execution mode.
        
        In auto mode, the LLM can execute tools without asking for confirmation
        for each call. Safety limits (cost, iteration count) still apply.
        
        Usage:
            /auto on          Enable autonomous mode
            /auto off         Disable autonomous mode (confirm each tool)
            /auto             Show current status
            /auto --limit 20  Set max 20 tool calls
            /auto --cost 2.0  Set $2 cost limit
            /auto --safe      Only auto-confirm SAFE tools
        
        Examples:
            /auto on
            /auto --limit 10 --cost 1.0
        
        Safety:
            Even in auto mode, these limits are enforced:
            - max_tool_calls: Maximum number of tool executions (default: 50)
            - max_tool_cost: Maximum cost in dollars (default: $5)
            - Sandbox: Shell commands run in firejail/unshare sandbox
        """
        if not hasattr(self.coder, 'tool_router'):
            self.io.tool_error(
                "Tool mode not available. "
                "Use --edit-format tool or /chat-mode tool to enable."
            )
            return
        
        args = args.strip()
        
        # Parse arguments
        show_status = True
        i = 0
        parts = args.split()
        
        while i < len(parts):
            arg = parts[i]
            
            if arg == "on":
                self.coder.auto_confirm_tools = True
                self.coder.tool_router.auto_confirm = True
                self.io.tool_output("Auto mode enabled - tools will execute without confirmation")
                show_status = False
                
            elif arg == "off":
                self.coder.auto_confirm_tools = False
                self.coder.tool_router.auto_confirm = False
                self.io.tool_output("Auto mode disabled - will confirm each tool call")
                show_status = False
                
            elif arg == "--limit" and i + 1 < len(parts):
                try:
                    limit = int(parts[i + 1])
                    self.coder.max_tool_calls = limit
                    self.io.tool_output(f"Max tool calls set to: {limit}")
                    show_status = False
                except ValueError:
                    self.io.tool_error(f"Invalid limit: {parts[i + 1]}")
                i += 1
                
            elif arg == "--cost" and i + 1 < len(parts):
                try:
                    cost = float(parts[i + 1])
                    self.coder.max_tool_cost = cost
                    self.coder.cost_tracker.max_cost = cost
                    self.io.tool_output(f"Cost limit set to: ${cost:.2f}")
                    show_status = False
                except ValueError:
                    self.io.tool_error(f"Invalid cost: {parts[i + 1]}")
                i += 1
                
            elif arg == "--safe":
                from aider.tools.risk import RiskLevel
                self.coder.tool_router.risk_confirm_threshold = RiskLevel.NORMAL
                self.io.tool_output("Safe mode: only SAFE tools auto-confirm")
                show_status = False
                
            else:
                self.io.tool_error(f"Unknown option: {arg}")
                
            i += 1
        
        # Show status
        if show_status or True:  # Always show status after changes
            status = "on" if self.coder.auto_confirm_tools else "off"
            self.io.tool_output(f"\nCurrent settings:")
            self.io.tool_output(f"  Auto mode: {status}")
            self.io.tool_output(f"  Max tool calls: {self.coder.max_tool_calls}")
            self.io.tool_output(f"  Cost limit: ${self.coder.max_tool_cost:.2f}")
            self.io.tool_output(f"  Risk threshold: {self.coder.tool_router.risk_confirm_threshold.name}")
            
            # Show budget status
            if hasattr(self.coder, 'cost_tracker'):
                remaining = self.coder.cost_tracker.remaining_budget
                self.io.tool_output(f"  Remaining budget: ${remaining:.2f}")

    def cmd_copy_context(self, args=None):
        """Copy the current chat context as markdown, suitable to paste into a web UI"""

        chunks = self.coder.format_chat_chunks()

        markdown = ""

        # Only include specified chunks in order
        for messages in [chunks.repo, chunks.readonly_files, chunks.chat_files]:
            for msg in messages:
                # Only include user messages
                if msg["role"] != "user":
                    continue

                content = msg["content"]

                # Handle image/multipart content
                if isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            markdown += part["text"] + "\n\n"
                else:
                    markdown += content + "\n\n"

        args = args or ""
        markdown += f"""
Just tell me how to edit the files to make the changes.
Don't give me back entire files.
Just show me the edits I need to make.

{args}
"""

        try:
            pyperclip.copy(markdown)
            self.io.tool_output("Copied code context to clipboard.")
        except pyperclip.PyperclipException as e:
            self.io.tool_error(f"Failed to copy to clipboard: {str(e)}")
            self.io.tool_output(
                "You may need to install xclip or xsel on Linux, or pbcopy on macOS."
            )
        except Exception as e:
            self.io.tool_error(f"An unexpected error occurred while copying to clipboard: {str(e)}")

    def cmd_skill(self, args):
        """
        Execute OpenClaw skills with optional agent support.
        
        Usage:
            /skill list [--agents]           List available skills
            /skill run <skill> [options]     Run a skill
            /skill info <skill>              Show skill information
            /skill search <query>            Search for skills
        
        Examples:
            /skill list --agents
            /skill run code-review -f auth.py --agents
            /skill info test-generation
        """
        from aider.skills.command import SkillsCommand
        
        skill_cmd = SkillsCommand(
            io=self.io,
            coder=self.coder,
            verbose=self.verbose,
        )
        return skill_cmd.cmd_skill(args)
    
    def completions_skill(self):
        """Provide completions for the /skill command."""
        from aider.skills.command import SkillsCommand
        
        skill_cmd = SkillsCommand(
            io=self.io,
            coder=self.coder,
            verbose=self.verbose,
        )
        return skill_cmd.completions_skill()


def expand_subdir(file_path):
    if file_path.is_file():
        yield file_path
        return

    if file_path.is_dir():
        for file in file_path.rglob("*"):
            if file.is_file():
                yield file


def parse_quoted_filenames(args):
    filenames = re.findall(r"\"(.+?)\"|(\S+)", args)
    filenames = [name for sublist in filenames for name in sublist if name]
    return filenames


def get_help_md():
    md = Commands(None, None).get_help_md()
    return md


def main():
    md = get_help_md()
    print(md)


if __name__ == "__main__":
    status = main()
    sys.exit(status)
