#!/usr/bin/env python

import json
import logging
import os
import string

# Optional dependency: used to convert locale codes (eg ``en_US``)
# into human-readable language names (eg ``English``).
try:
    from babel import Locale  # type: ignore
except ImportError:  # Babel not installed - we will fall back to a small mapping
    Locale = None
from pathlib import Path

from aider import __version__, urls, utils
from aider.analytics import Analytics
from aider.commands import Commands
from aider.exceptions import LiteLLMExceptions
from aider.history import ChatSummary
from aider.io import InputOutput
from aider.linter import Linter
from aider.hooks import get_hooks_manager
from aider.reasoning_tags import (
    REASONING_TAG,
)
from aider.repo import ANY_GIT_ERROR, GitRepo
from aider.repomap import RepoMap
from aider.session_runtime import SessionRuntime
from aider.utils import format_content, format_messages, is_image_file

from ..dump import dump  # noqa: F401
from .base_coder_context import BaseCoderContextMixin
from .base_coder_control import BaseCoderControlMixin
from .base_coder_edits import BaseCoderEditsMixin
from .base_coder_files import BaseCoderFilesMixin
from .base_coder_history import BaseCoderHistoryMixin
from .base_coder_lifecycle import BaseCoderLifecycleMixin
from .base_coder_llm_output import BaseCoderLLMOutputMixin
from .base_coder_messages import BaseCoderMessagesMixin
from .base_coder_output import BaseCoderOutputMixin
from .base_coder_paths import BaseCoderPathsMixin
from .base_coder_reply import BaseCoderReplyMixin
from .base_coder_runtime import BaseCoderRuntimeMixin
from .base_coder_shell import BaseCoderShellMixin
from .chat_history import ChatHistory
from .coder_factory import create_coder

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


class UnknownEditFormat(ValueError):
    def __init__(self, edit_format, valid_formats):
        self.edit_format = edit_format
        self.valid_formats = valid_formats
        super().__init__(
            f"Unknown edit format {edit_format}. Valid formats are: {', '.join(valid_formats)}"
        )


class MissingAPIKeyError(ValueError):
    pass


class FinishReasonLength(Exception):
    pass


def wrap_fence(name):
    return f"<{name}>", f"</{name}>"


all_fences = [
    ("`" * 3, "`" * 3),
    ("`" * 4, "`" * 4),  # LLMs ignore and revert to triple-backtick, causing #2879
    wrap_fence("source"),
    wrap_fence("code"),
    wrap_fence("pre"),
    wrap_fence("codeblock"),
    wrap_fence("sourcecode"),
]


class SafeFormatter(string.Formatter):
    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            try:
                return kwargs[key]
            except KeyError:
                return "{" + key + "}"
        else:
            return super().get_value(key, args, kwargs)


class Coder(
    BaseCoderMessagesMixin,
    BaseCoderControlMixin,
    BaseCoderLifecycleMixin,
    BaseCoderShellMixin,
    BaseCoderEditsMixin,
    BaseCoderPathsMixin,
    BaseCoderLLMOutputMixin,
    BaseCoderReplyMixin,
    BaseCoderFilesMixin,
    BaseCoderOutputMixin,
    BaseCoderContextMixin,
    BaseCoderHistoryMixin,
    BaseCoderRuntimeMixin,
):
    abs_fnames = None
    abs_read_only_fnames = None
    repo = None
    last_aider_commit_hash = None
    aider_edited_files = None
    last_asked_for_commit_time = 0
    repo_map = None
    functions = None
    num_exhausted_context_windows = 0
    num_malformed_responses = 0
    last_keyboard_interrupt = None
    num_reflections = 0
    max_reflections = 3
    edit_format = None
    yield_stream = False
    temperature = None
    auto_lint = True
    auto_test = False
    test_cmd = None
    lint_outcome = None
    test_outcome = None
    multi_response_content = ""
    partial_response_content = ""
    commit_before_message = []
    message_cost = 0.0
    add_cache_headers = False
    cache_warming_thread = None
    num_cache_warming_pings = 0
    suggest_shell_commands = True
    detect_urls = True
    ignore_mentions = None
    chat_language = None
    commit_language = None
    file_watcher = None
    system_prompt_override = None
    FinishReasonLength = FinishReasonLength
    review_mode = False
    auto_review = False

    @property
    def done_messages(self):
        if not hasattr(self, "chat_history"):
            return []
        return self.chat_history.done_messages

    @done_messages.setter
    def done_messages(self, value):
        if not hasattr(self, "chat_history"):
            self.chat_history = ChatHistory(done_messages=value)
            return
        self.chat_history.done_messages = value

    @property
    def cur_messages(self):
        if not hasattr(self, "chat_history"):
            return []
        return self.chat_history.cur_messages

    @cur_messages.setter
    def cur_messages(self, value):
        if not hasattr(self, "chat_history"):
            self.chat_history = ChatHistory(cur_messages=value)
            return
        self.chat_history.cur_messages = value

    @property
    def summarizer(self):
        if not hasattr(self, "chat_history"):
            return None
        return self.chat_history.summarizer

    @summarizer.setter
    def summarizer(self, value):
        if not hasattr(self, "chat_history"):
            self.chat_history = ChatHistory(summarizer=value)
            return
        self.chat_history.summarizer = value

    @classmethod
    def create(
        cls,
        main_model=None,
        edit_format=None,
        io=None,
        from_coder=None,
        summarize_from_coder=True,
        **kwargs,
    ):
        """
        Factory method for creating Coder instances.

        This is a thin wrapper around CoderFactory for backward compatibility.
        New code should use get_coder_factory().create() or create_coder() directly.
        """
        from .coder_factory import UnknownEditFormat as FactoryUnknownEditFormat, get_coder_factory

        factory = get_coder_factory()
        try:
            return factory.create(
                main_model=main_model,
                edit_format=edit_format,
                io=io,
                from_coder=from_coder,
                summarize_from_coder=summarize_from_coder,
                **kwargs
            )
        except FactoryUnknownEditFormat as err:
            raise UnknownEditFormat(err.edit_format, err.valid_formats) from err

    def clone(self, **kwargs):
        new_coder = create_coder(from_coder=self, **kwargs)
        return new_coder

    def get_announcements(self):
        lines = []
        lines.append(f"Aider v{__version__}")

        # Model
        main_model = self.main_model
        weak_model = main_model.weak_model

        if weak_model is not main_model:
            prefix = "Main model"
        else:
            prefix = "Model"

        output = f"{prefix}: {main_model.name} with {self.edit_format} edit format"

        # Check for thinking token budget
        thinking_tokens = main_model.get_thinking_tokens()
        if thinking_tokens:
            output += f", {thinking_tokens} think tokens"

        # Check for reasoning effort
        reasoning_effort = main_model.get_reasoning_effort()
        if reasoning_effort:
            output += f", reasoning {reasoning_effort}"

        if self.add_cache_headers or main_model.caches_by_default:
            output += ", prompt cache"
        if main_model.info.get("supports_assistant_prefill"):
            output += ", infinite output"

        lines.append(output)

        if self.edit_format == "architect":
            output = (
                f"Editor model: {main_model.editor_model.name} with"
                f" {main_model.editor_edit_format} edit format"
            )
            lines.append(output)

        if weak_model is not main_model:
            output = f"Weak model: {weak_model.name}"
            lines.append(output)

        # Repo
        if self.repo:
            rel_repo_dir = self.repo.get_rel_repo_dir()
            num_files = len(self.repo.get_tracked_files())

            lines.append(f"Git repo: {rel_repo_dir} with {num_files:,} files")
            if num_files > 1000:
                lines.append(
                    "Warning: For large repos, consider using --subtree-only and .aiderignore"
                )
                lines.append(f"See: {urls.large_repos}")
        else:
            lines.append("Git repo: none")

        # Repo-map
        if self.repo_map:
            map_tokens = self.repo_map.max_map_tokens
            if map_tokens > 0:
                refresh = self.repo_map.refresh
                lines.append(f"Repo-map: using {map_tokens} tokens, {refresh} refresh")
                base_map_tokens = self.main_model.get_repo_map_tokens()
                if isinstance(base_map_tokens, (int, float)):
                    max_map_tokens = base_map_tokens * 2
                    if map_tokens > max_map_tokens:
                        lines.append(
                            f"Warning: map-tokens > {max_map_tokens} is not recommended. Too much"
                            " irrelevant code can confuse LLMs."
                        )
            else:
                lines.append("Repo-map: disabled because map_tokens == 0")
        else:
            lines.append("Repo-map: disabled")

        # Files
        for fname in self.get_inchat_relative_files():
            lines.append(f"Added {fname} to the chat.")

        for fname in self.abs_read_only_fnames:
            rel_fname = self.get_rel_fname(fname)
            lines.append(f"Added {rel_fname} to the chat (read-only).")

        if self.done_messages:
            lines.append("Restored previous conversation history.")

        if self.system_prompt_override:
            lines.append("Custom system prompt: Active (use /system reset to clear)")

        if self.io.multiline_mode:
            lines.append("Multiline mode: Enabled. Enter inserts newline, Alt-Enter submits text")
        
        # Show helpful hint for new users (only when no files added yet)
        if not self.abs_fnames and not self.done_messages:
            lines.append("")
            lines.append("Tip: Use /add <file> to add files, /help <command> for details, or just type to chat")

        return lines

    ok_to_warm_cache = False

    def __init__(
        self,
        main_model,
        io,
        repo=None,
        fnames=None,
        add_gitignore_files=False,
        read_only_fnames=None,
        show_diffs=False,
        auto_commits=True,
        dirty_commits=True,
        dry_run=False,
        map_tokens=1024,
        verbose=False,
        stream=True,
        use_git=True,
        cur_messages=None,
        done_messages=None,
        restore_chat_history=False,
        auto_lint=True,
        auto_test=False,
        lint_cmds=None,
        test_cmd=None,
        aider_commit_hashes=None,
        map_mul_no_files=8,
        commands=None,
        summarizer=None,
        total_cost=0.0,
        analytics=None,
        map_refresh="auto",
        cache_prompts=False,
        num_cache_warming_pings=0,
        suggest_shell_commands=True,
        chat_language=None,
        commit_language=None,
        detect_urls=True,
        ignore_mentions=None,
        total_tokens_sent=0,
        total_tokens_received=0,
        file_watcher=None,
        auto_copy_context=False,
        auto_accept_architect=True,
        use_semantic_index=False,
        background_semantic_index=True,
        system_prompt_override=None,
        runtime=None,
        review_mode=False,
        auto_review=False,
        total_cache_hit_tokens=0,
        total_cache_write_tokens=0,
        total_uncached_input_tokens=0,
    ):
        if io is None:
            io = InputOutput()

        self.review_mode = review_mode
        self.auto_review = auto_review

        # Fill in a dummy Analytics if needed, but it is never .enable()'d
        self.analytics = analytics if analytics is not None else Analytics()
        self.runtime = runtime or SessionRuntime.create(
            io=io,
            analytics=self.analytics,
            hooks_manager=get_hooks_manager(),
            resolve_defaults=False,
        )
        if hasattr(self.runtime, "bind_io"):
            self.runtime.bind_io(io)
        if hasattr(self.runtime, "bind_analytics"):
            self.runtime.bind_analytics(self.analytics)

        self.system_prompt_override = system_prompt_override

        self.use_semantic_index = use_semantic_index
        self._semantic_indexer_wrapper = None
        self._semantic_index_kwargs = {}
        self._background_semantic_index_enabled = bool(
            self.repo
            and background_semantic_index
            and not os.environ.get("AIDER_DISABLE_BACKGROUND_SEMANTIC_INDEX")
        )

        # Initialize semantic index manager for unified ownership

        if self.use_semantic_index:
            self._semantic_indexer_wrapper = self._get_semantic_index_manager()

        self._sync_runtime_services()
        if hasattr(self.runtime, "bind_coder"):
            self.runtime.bind_coder(self)

        self.event = self.analytics.event
        self.chat_language = chat_language
        self.commit_language = commit_language
        self.commit_before_message = []
        self.aider_commit_hashes = set()
        self.rejected_urls = set()
        self.abs_root_path_cache = {}

        self.auto_copy_context = auto_copy_context
        self.auto_accept_architect = auto_accept_architect

        self.ignore_mentions = ignore_mentions
        if not self.ignore_mentions:
            self.ignore_mentions = set()

        self.file_watcher = file_watcher
        if self.file_watcher:
            self.file_watcher.coder = self

        self.suggest_shell_commands = suggest_shell_commands
        self.detect_urls = detect_urls

        self.num_cache_warming_pings = num_cache_warming_pings

        if not fnames:
            fnames = []

        if aider_commit_hashes:
            self.aider_commit_hashes = aider_commit_hashes
        else:
            self.aider_commit_hashes = set()

        self.chat_completion_call_hashes = []
        self.chat_completion_response_hashes = []
        self.need_commit_before_edits = set()

        self.total_cost = total_cost
        self.total_tokens_sent = total_tokens_sent
        self.total_tokens_received = total_tokens_received
        self.message_tokens_sent = 0
        self.message_tokens_received = 0

        # Token caching statistics (accumulated across all messages)
        self.total_cache_hit_tokens = total_cache_hit_tokens
        self.total_cache_write_tokens = total_cache_write_tokens
        self.total_uncached_input_tokens = total_uncached_input_tokens

        self.verbose = verbose
        self.abs_fnames = set()
        self.abs_read_only_fnames = set()
        self.add_gitignore_files = add_gitignore_files

        self.dry_run = dry_run
        self.io = io
        self.pretty = self.io.pretty
        self.live_delegate = None

        if not auto_commits:
            dirty_commits = False

        self.auto_commits = auto_commits
        self.dirty_commits = dirty_commits

        self.main_model = main_model

        # Initialize ChatHistory
        self.chat_history = ChatHistory(
            summarizer=summarizer
            or ChatSummary(
                [self.main_model.weak_model, self.main_model],
                self.main_model.max_chat_history_tokens,
            ),
            done_messages=done_messages,
            cur_messages=cur_messages,
        )

        # Set the reasoning tag name based on model settings or default
        self.reasoning_tag_name = (
            self.main_model.reasoning_tag if self.main_model.reasoning_tag else REASONING_TAG
        )

        self.stream = stream and main_model.streaming

        if cache_prompts and self.main_model.cache_control:
            self.add_cache_headers = True

        self.show_diffs = show_diffs

        self.commands = commands or Commands(self.io, self, runtime=self.runtime)
        self.commands.coder = self
        self.commands.runtime = self.runtime

        self.repo = repo
        auto_detected_repo = False
        if use_git and self.repo is None:
            try:
                self.repo = GitRepo(
                    self.io,
                    fnames,
                    None,
                    models=main_model.commit_message_models(),
                )
                auto_detected_repo = self.repo is not None
            except FileNotFoundError:
                pass

        if auto_detected_repo and self.repo:
            repo_detection_errors = (ValueError, OSError) + ANY_GIT_ERROR
            try:
                repo_root = Path(self.repo.root).resolve()

                if fnames:
                    resolved_fnames = [Path(fname).resolve() for fname in fnames]
                    in_repo_root = all(
                        str(resolved_fname).startswith(str(repo_root) + os.sep)
                        or resolved_fname == repo_root
                        for resolved_fname in resolved_fnames
                    )
                    if not in_repo_root:
                        self.repo = None
                    else:
                        cwd = Path.cwd().resolve()
                        tracked_files = self.repo.get_tracked_files()
                        tracked_abs_fnames = {
                            Path(self.repo.abs_root_path(tracked_fname)).resolve()
                            for tracked_fname in tracked_files
                        }
                        has_tracked_explicit_files = any(
                            resolved_fname in tracked_abs_fnames
                            for resolved_fname in resolved_fnames
                        )
                        has_tracked_files_in_cwd_subtree = False
                        if cwd == repo_root:
                            has_tracked_files_in_cwd_subtree = bool(tracked_files)
                        else:
                            rel_cwd = cwd.relative_to(repo_root)
                            prefix = str(rel_cwd).replace("\\", "/").rstrip("/")
                            has_tracked_files_in_cwd_subtree = any(
                                tracked == prefix or tracked.startswith(prefix + "/")
                                for tracked in tracked_files
                            )

                        has_explicit_files_in_cwd_subtree = any(
                            str(resolved_fname).startswith(str(cwd) + os.sep)
                            or resolved_fname == cwd
                            for resolved_fname in resolved_fnames
                        )

                        keep_auto_detected_repo = (
                            cwd == repo_root
                            or has_tracked_explicit_files
                            or (
                                has_explicit_files_in_cwd_subtree
                                and has_tracked_files_in_cwd_subtree
                            )
                        )

                        if not keep_auto_detected_repo:
                            self.repo = None
                else:
                    cwd = Path.cwd().resolve()
                    if cwd != repo_root:
                        rel_cwd = cwd.relative_to(repo_root)
                        prefix = str(rel_cwd).replace("\\", "/").rstrip("/")
                        tracked_files = self.repo.get_tracked_files()
                        has_tracked_files_in_cwd = any(
                            tracked == prefix or tracked.startswith(prefix + "/")
                            for tracked in tracked_files
                        )
                        if not has_tracked_files_in_cwd:
                            self.repo = None
            except repo_detection_errors:
                self.repo = None

        if self.repo:
            self.root = self.repo.root

        for fname in fnames:
            fname = Path(fname)
            if self.repo and self.repo.git_ignored_file(fname) and not self.add_gitignore_files:
                self.io.tool_warning(f"Skipping {fname} that matches gitignore spec.")
                continue

            if self.repo and self.repo.ignored_file(fname):
                self.io.tool_warning(f"Skipping {fname} that matches aiderignore spec.")
                continue

            if not fname.exists():
                if utils.touch_file(fname):
                    self.io.tool_output(f"Creating empty file {fname}")
                else:
                    self.io.tool_warning(f"Can not create {fname}, skipping.")
                    continue

            if not fname.is_file():
                self.io.tool_warning(f"Skipping {fname} that is not a normal file.")
                continue

            fname = str(fname.resolve())

            self.abs_fnames.add(fname)
            self.check_added_files()

        if not self.repo:
            self.root = utils.find_common_root(self.abs_fnames)

        if self.use_semantic_index:
            if self.main_model.embedding_model_name and isinstance(
                self.main_model.embedding_model_name, str
            ):
                self._semantic_index_kwargs["model_name"] = self.main_model.embedding_model_name
            if self.main_model.embedding_api_base and isinstance(
                self.main_model.embedding_api_base, str
            ):
                self._semantic_index_kwargs["api_base"] = self.main_model.embedding_api_base

            self._background_semantic_index_enabled = bool(
                self.repo
                and background_semantic_index
                and not os.environ.get("AIDER_DISABLE_BACKGROUND_SEMANTIC_INDEX")
            )

        if read_only_fnames:
            self.abs_read_only_fnames = set()
            for fname in read_only_fnames:
                abs_fname = self.abs_root_path(fname)
                if os.path.exists(abs_fname):
                    self.abs_read_only_fnames.add(abs_fname)
                else:
                    self.io.tool_warning(f"Error: Read-only file {fname} does not exist. Skipping.")

        if map_tokens is None:
            use_repo_map = main_model.use_repo_map
            map_tokens = 1024
        else:
            use_repo_map = map_tokens > 0

        max_inp_tokens = self.main_model.info.get("max_input_tokens") or 0

        has_map_prompt = hasattr(self, "gpt_prompts") and self.gpt_prompts.repo_content_prefix

        if use_repo_map and self.repo and has_map_prompt:
            self.repo_map = RepoMap(
                map_tokens,
                self.root,
                self.main_model,
                io,
                self.gpt_prompts.repo_content_prefix,
                self.verbose,
                max_inp_tokens,
                map_mul_no_files=map_mul_no_files,
                refresh=map_refresh,
            )

        self.summarizer_thread = None
        self.summarized_done_messages = []
        self.summarizing_messages = None

        if not self.chat_history.done_messages and restore_chat_history:
            history_md = self.io.read_text(self.io.chat_history_file)
            if history_md:
                self.chat_history.done_messages = utils.split_chat_history_markdown(history_md)
                self.summarize_start()

        # Linting and testing
        self.linter = Linter(root=self.root, encoding=io.encoding)
        self.auto_lint = auto_lint
        self.setup_lint_cmds(lint_cmds)
        self.lint_cmds = lint_cmds
        self.auto_test = auto_test
        self.test_cmd = test_cmd

        # validate the functions jsonschema
        if self.functions:
            from jsonschema import Draft7Validator

            for function in self.functions:
                Draft7Validator.check_schema(function)

            if self.verbose:
                self.io.tool_output("JSON Schema:")
                self.io.tool_output(json.dumps(self.functions, indent=4))

    def get_semantic_indexer(self, start_background=False):
        """
        Get the semantic indexer, creating wrapper if needed.

        This method now delegates to the runtime-owned service when available,
        falling back to a coder-local wrapper for backward compatibility.
        """
        if not self.use_semantic_index:
            return None

        # Lazy-initialize the wrapper
        if self._semantic_indexer_wrapper is None:
            from aider.indexers.semantic_service import RuntimeBoundSemanticIndexer
            self._semantic_indexer_wrapper = RuntimeBoundSemanticIndexer(self)

        return self._semantic_indexer_wrapper.get_indexer(start_background=start_background)

    def _get_semantic_index_manager(self):
        """
        Create the semantic index manager for unified ownership.

        This method creates a RuntimeBoundSemanticIndexer that delegates
        to the runtime-owned SemanticIndexService when available.
        """
        from aider.indexers.semantic_service import RuntimeBoundSemanticIndexer
        return RuntimeBoundSemanticIndexer(self)

    def _ensure_background_semantic_index(self):
        """Ensure background indexing is started if enabled."""
        if not self._background_semantic_index_enabled:
            return

        # Delegate to the wrapper which handles the background logic
        self.get_semantic_indexer(start_background=True)

    def add_rel_fname(self, rel_fname):
        self.abs_fnames.add(self.abs_root_path(rel_fname))
        self.check_added_files()

    def drop_rel_fname(self, fname):
        abs_fname = self.abs_root_path(fname)
        if abs_fname in self.abs_fnames:
            self.abs_fnames.remove(abs_fname)
            return True

    def abs_root_path(self, path):
        key = path
        if key in self.abs_root_path_cache:
            return self.abs_root_path_cache[key]

        res = Path(self.root) / path
        res = utils.safe_abs_path(res)
        self.abs_root_path_cache[key] = res
        return res

    fences = all_fences
    fence = fences[0]

    def reply_completed(self):
        pass

    def __del__(self):
        """Cleanup when the Coder object is destroyed."""
        self.ok_to_warm_cache = False

    def get_final_assistant_output(self):
        if self.partial_response_content:
            return self.partial_response_content

    def send(self, messages, model=None, functions=None):
        self.got_reasoning_content = False
        self.ended_reasoning_content = False

        if not model:
            model = self.main_model

        self.partial_response_content = ""
        self.partial_response_function_call = dict()

        self.io.log_llm_history("TO LLM", format_messages(messages))

        completion = None
        try:
            hash_object, completion = model.send_completion(
                messages,
                functions,
                self.stream,
                self.temperature,
            )
            self.chat_completion_call_hashes.append(hash_object.hexdigest())

            if self.stream:
                yield from self.show_send_output_stream(completion)
            else:
                self.show_send_output(completion)

            # Calculate costs for successful responses
            self.calculate_and_show_tokens_and_cost(messages, completion)

        except LiteLLMExceptions().exceptions_tuple() as err:
            ex_info = LiteLLMExceptions().get_ex_info(err)
            if ex_info.name == "ContextWindowExceededError":
                # Still calculate costs for context window errors
                self.calculate_and_show_tokens_and_cost(messages, completion)
            raise
        except KeyboardInterrupt as kbi:
            self.keyboard_interrupt()
            raise kbi
        finally:
            self.io.log_llm_history(
                "LLM RESPONSE",
                format_content("ASSISTANT", self.partial_response_content),
            )

            final_output = self.get_final_assistant_output()
            if final_output:
                self.io.ai_output(final_output)

    def check_for_dirty_commit(self, path):
        if not self.repo:
            return
        if not self.dirty_commits:
            return
        if not self.repo.is_dirty(path):
            return

        # We need a committed copy of the file in order to /undo, so skip this
        # fullp = Path(self.abs_root_path(path))
        # if not fullp.stat().st_size:
        #     return

        self.io.tool_output(f"Committing {path} before applying edits.")
        self.need_commit_before_edits.add(path)

    def allowed_to_edit(self, path):
        full_path = self.abs_root_path(path)
        if self.repo:
            need_to_add = not self.repo.path_in_repo(path)
        else:
            need_to_add = False

        if full_path in self.abs_fnames:
            self.check_for_dirty_commit(path)
            return True

        if self.repo and self.repo.git_ignored_file(path):
            self.io.tool_warning(f"Skipping edits to {path} that matches gitignore spec.")
            return

        if not Path(full_path).exists():
            if not self.io.confirm_ask("Create new file?", subject=path):
                self.io.tool_output(f"Skipping edits to {path}")
                return

            if not self.dry_run:
                if not utils.touch_file(full_path):
                    self.io.tool_error(f"Unable to create {path}, skipping edits.")
                    return

                # Seems unlikely that we needed to create the file, but it was
                # actually already part of the repo.
                # But let's only add if we need to, just to be safe.
                if need_to_add and self.auto_commits:
                    self.repo.repo.git.add(full_path)

            self.abs_fnames.add(full_path)
            self.check_added_files()
            return True

        if not self.io.confirm_ask(
            "Allow edits to file that has not been added to the chat?",
            subject=path,
        ):
            self.io.tool_output(f"Skipping edits to {path}")
            return

        if need_to_add and self.auto_commits:
            self.repo.repo.git.add(full_path)

        self.abs_fnames.add(full_path)
        self.check_added_files()
        self.check_for_dirty_commit(path)

        return True

    warning_given = False

    def check_added_files(self):
        if self.warning_given:
            return

        warn_number_of_files = 4
        warn_number_of_tokens = 20 * 1024

        num_files = len(self.abs_fnames)
        if num_files < warn_number_of_files:
            return

        tokens = 0
        for fname in self.abs_fnames:
            if is_image_file(fname):
                continue
            content = self.io.read_text(fname)
            tokens += self.main_model.token_count(content)

        if tokens < warn_number_of_tokens:
            return

        self.io.tool_warning("Warning: it's best to only add files that need changes to the chat.")
        self.io.tool_warning(urls.edit_errors)
        self.warning_given = True

    # commits...

    def get_context_from_history(self, history):
        context = ""
        if history:
            for msg in history:
                context += "\n" + msg["role"].upper() + ": " + msg["content"] + "\n"

        return context

    def auto_commit(self, edited, context=None):
        if not self.repo or not self.auto_commits or self.dry_run:
            return

        if not context:
            context = self.get_context_from_history(self.cur_messages)

        try:
            res = self.repo.commit(fnames=edited, context=context, aider_edits=True, coder=self)
            if res:
                self.show_auto_commit_outcome(res)
                commit_hash, commit_message = res
                return self.gpt_prompts.files_content_gpt_edits.format(
                    hash=commit_hash,
                    message=commit_message,
                )

            return self.gpt_prompts.files_content_gpt_no_edits
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to commit: {str(err)}")
            return

    def show_auto_commit_outcome(self, res):
        commit_hash, commit_message = res
        self.last_aider_commit_hash = commit_hash
        self.aider_commit_hashes.add(commit_hash)
        self.last_aider_commit_message = commit_message
        if self.show_diffs:
            self.commands.cmd_diff()

    def show_undo_hint(self):
        if not self.commit_before_message:
            return
        if self.commit_before_message[-1] != self.repo.get_head_commit_sha():
            self.io.tool_output("You can use /undo to undo and discard each aider commit.")

    def dirty_commit(self):
        if not self.need_commit_before_edits:
            return
        if not self.dirty_commits:
            return
        if not self.repo:
            return

        self.repo.commit(fnames=self.need_commit_before_edits, coder=self)

        # files changed, move cur messages back behind the files messages
        # self.move_back_cur_messages(self.gpt_prompts.files_content_local_edits)
        return True

    def get_edits(self, mode="update"):
        return []

    def apply_edits(self, edits):
        return

    def apply_edits_dry_run(self, edits):
        return edits
