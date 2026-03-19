import os
import threading
import time

from aider.llm import litellm
from aider.utils import format_tokens, is_image_file

from .chat_chunks import ChatChunks


class BaseCoderMessagesMixin:
    def show_pretty(self):
        if not self.pretty:
            return False

        if self.fence[0][0] != "`":
            return False

        return True

    def _stop_waiting_spinner(self):
        spinner = getattr(self, "waiting_spinner", None)
        if spinner:
            try:
                spinner.stop()
            finally:
                self.waiting_spinner = None

    def init_before_message(self):
        self.aider_edited_files = set()
        self.reflected_message = None
        self.num_reflections = 0
        self.lint_outcome = None
        self.test_outcome = None
        self.shell_commands = []
        self.message_cost = 0

        if self.repo:
            self.commit_before_message.append(self.repo.get_head_commit_sha())

    def copy_context(self):
        if self.auto_copy_context:
            self.commands.cmd_copy_context()

    def format_chat_chunks(self):
        self.choose_fence()
        prompt_source = self.system_prompt_override or self.gpt_prompts.main_system
        main_sys = self.fmt_system_prompt(prompt_source)
        if self.main_model.system_prompt_prefix:
            main_sys = self.main_model.system_prompt_prefix + "\n" + main_sys

        example_messages = []
        if self.main_model.examples_as_sys_msg:
            if self.gpt_prompts.example_messages:
                main_sys += "\n# Example conversations:\n\n"
            for msg in self.gpt_prompts.example_messages:
                role = msg["role"]
                content = self.fmt_system_prompt(msg["content"])
                main_sys += f"## {role.upper()}: {content}\n\n"
            main_sys = main_sys.strip()
        else:
            for msg in self.gpt_prompts.example_messages:
                example_messages.append(
                    dict(
                        role=msg["role"],
                        content=self.fmt_system_prompt(msg["content"]),
                    )
                )
            if self.gpt_prompts.example_messages:
                example_messages += [
                    dict(
                        role="user",
                        content=(
                            "I switched to a new code base. Please don't consider the above files"
                            " or try to edit them any longer."
                        ),
                    ),
                    dict(role="assistant", content="Ok."),
                ]

        if self.gpt_prompts.system_reminder and not self.system_prompt_override:
            main_sys += "\n" + self.fmt_system_prompt(self.gpt_prompts.system_reminder)

        chunks = ChatChunks()

        if self.main_model.use_system_prompt:
            chunks.system = [
                dict(role="system", content=main_sys),
            ]
        else:
            chunks.system = [
                dict(role="user", content=main_sys),
                dict(role="assistant", content="Ok."),
            ]

        chunks.examples = example_messages

        self.summarize_end()
        chunks.done = self.done_messages

        chunks.repo = self.get_repo_messages()
        chunks.readonly_files = self.get_readonly_files_messages()
        chunks.chat_files = self.get_chat_files_messages()

        if self.gpt_prompts.system_reminder and not self.system_prompt_override:
            reminder_message = [
                dict(
                    role="system", content=self.fmt_system_prompt(self.gpt_prompts.system_reminder)
                ),
            ]
        else:
            reminder_message = []

        chunks.cur = list(self.cur_messages)
        chunks.reminder = []

        messages_tokens = self.main_model.token_count(chunks.all_messages())
        reminder_tokens = self.main_model.token_count(reminder_message)
        cur_tokens = self.main_model.token_count(chunks.cur)
        multimodal_tokens = self._get_multimodal_image_tokens()

        if None not in (messages_tokens, reminder_tokens, cur_tokens):
            total_tokens = messages_tokens + reminder_tokens + cur_tokens + multimodal_tokens
        else:
            total_tokens = 0

        if chunks.cur:
            final = chunks.cur[-1]
        else:
            final = None

        max_input_tokens = self.main_model.info.get("max_input_tokens") or 0
        if (
            not max_input_tokens
            or total_tokens < max_input_tokens
            and self.gpt_prompts.system_reminder
            and not self.system_prompt_override
        ):
            if self.main_model.reminder == "sys":
                chunks.reminder = reminder_message
            elif self.main_model.reminder == "user" and final and final["role"] == "user":
                new_content = (
                    final["content"]
                    + "\n\n"
                    + self.fmt_system_prompt(self.gpt_prompts.system_reminder)
                )
                chunks.cur[-1] = dict(role=final["role"], content=new_content)

        return chunks

    def _get_multimodal_image_tokens(self):
        tokens = 0
        seen = set()
        for fname in list(self.abs_fnames) + list(self.abs_read_only_fnames):
            if fname in seen:
                continue
            seen.add(fname)
            if is_image_file(fname):
                try:
                    tokens += self.main_model.token_count_for_image(fname)
                except Exception:
                    continue
        return tokens

    def format_messages(self):
        chunks = self.format_chat_chunks()
        if self.add_cache_headers:
            chunks.add_cache_control_headers()

        return chunks

    def warm_cache(self, chunks):
        if not self.add_cache_headers:
            return
        if not self.num_cache_warming_pings:
            return
        if not self.ok_to_warm_cache:
            return

        delay = 5 * 60 - 5
        delay = float(os.environ.get("AIDER_CACHE_KEEPALIVE_DELAY", delay))
        self.next_cache_warm = time.time() + delay
        self.warming_pings_left = self.num_cache_warming_pings
        self.cache_warming_chunks = chunks

        if self.cache_warming_thread:
            return

        def warm_cache_worker():
            while self.ok_to_warm_cache:
                time.sleep(1)
                if self.warming_pings_left <= 0:
                    continue
                now = time.time()
                if now < self.next_cache_warm:
                    continue

                self.warming_pings_left -= 1
                self.next_cache_warm = time.time() + delay

                if getattr(self.main_model, "_is_openclaw_endpoint", lambda: False)():
                    continue

                kwargs = dict(self.main_model.extra_params) or dict()
                kwargs["max_tokens"] = 1

                try:
                    completion = litellm.completion(
                        model=self.main_model.name,
                        messages=self.cache_warming_chunks.cacheable_messages(),
                        stream=False,
                        **kwargs,
                    )
                except Exception as err:
                    self.io.tool_warning(f"Cache warming error: {str(err)}")
                    continue

                cache_hit_tokens = getattr(
                    completion.usage, "prompt_cache_hit_tokens", 0
                ) or getattr(completion.usage, "cache_read_input_tokens", 0)

                if self.verbose:
                    self.io.tool_output(f"Warmed {format_tokens(cache_hit_tokens)} cached tokens.")

        self.cache_warming_thread = threading.Timer(0, warm_cache_worker)
        self.cache_warming_thread.daemon = True
        self.cache_warming_thread.start()

        return chunks
