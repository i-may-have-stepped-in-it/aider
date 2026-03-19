import re
import sys
import threading
import time
from typing import List

from rich.console import Console

from aider.io import ConfirmGroup


class BaseCoderControlMixin:
    def run_stream(self, user_message):
        self.io.user_input(user_message)
        self.init_before_message()

        hooks = self._get_hooks_manager()
        if hooks:
            try:
                pre_result = hooks.execute("pre_send", message=user_message, coder=self)
                if pre_result.get("data", {}).get("message") is not None:
                    user_message = pre_result["data"]["message"]
            except Exception as e:
                if hooks.verbose:
                    self.io.tool_error(f"Hook error (pre_send): {e}")

        yield from self.send_message(user_message)

        if hooks:
            try:
                hooks.execute(
                    "post_send",
                    message=user_message,
                    response=self.partial_response_content,
                    coder=self,
                )
            except Exception as e:
                if hooks.verbose:
                    self.io.tool_error(f"Hook error (post_send): {e}")

    def run(self, with_message=None, preproc=True):
        try:
            if with_message:
                self.io.user_input(with_message)
                self.run_one(with_message, preproc)
                return self.partial_response_content
            while True:
                try:
                    if not self.io.placeholder:
                        self.copy_context()
                    user_message = self.get_input()
                    self.run_one(user_message, preproc)
                    self.show_undo_hint()
                except KeyboardInterrupt:
                    self.keyboard_interrupt()
        except EOFError:
            return

    def get_input(self):
        inchat_files = self.get_inchat_relative_files()
        read_only_files = [self.get_rel_fname(fname) for fname in self.abs_read_only_fnames]
        all_files = sorted(set(inchat_files + read_only_files))
        edit_format = "" if self.edit_format == self.main_model.edit_format else self.edit_format
        return self.io.get_input(
            self.root,
            all_files,
            self.get_addable_relative_files(),
            self.commands,
            self.abs_read_only_fnames,
            edit_format=edit_format,
        )

    def preproc_user_input(self, inp):
        if not inp:
            return

        if self.commands.is_command(inp):
            return self.commands.run(inp)

        self.check_for_file_mentions(inp)
        inp = self.check_for_urls(inp)

        return inp

    def run_one(self, user_message, preproc):
        self.init_before_message()

        if preproc:
            message = self.preproc_user_input(user_message)
        else:
            message = user_message

        while message:
            self.reflected_message = None
            list(self.send_message(message))

            if not self.reflected_message:
                last_assistant_msg = self.done_messages[-1] if self.done_messages else None
                if last_assistant_msg and last_assistant_msg.get("role") == "assistant":
                    content = last_assistant_msg.get("content", "")
                    if "```mermaid" in content or "```html" in content or "```svg" in content:

                        def run_preview():
                            try:
                                from aider.skills.base import SkillContext, _run_async_safely

                                preview_skill = self.skills_registry.create(
                                    "artifact-preview",
                                    SkillContext(coder=self, io=self.io),
                                )
                                if preview_skill:
                                    _run_async_safely(preview_skill.execute(content))
                            except Exception as e:
                                self.io.tool_error(f"Artifact preview failed: {e}")

                        threading.Thread(target=run_preview, daemon=True).start()
                break

            if self.num_reflections >= self.max_reflections:
                self.io.tool_warning(f"Only {self.max_reflections} reflections allowed, stopping.")
                return

            self.num_reflections += 1
            message = self.reflected_message

    def check_and_open_urls(self, exc, friendly_msg=None):
        text = str(exc)

        if friendly_msg:
            self.io.tool_warning(text)
            self.io.tool_error(f"{friendly_msg}")
        else:
            self.io.tool_error(text)

        url_pattern = re.compile(r'(https?://[^\s/$.?#].[^\s"]*)')
        urls = list(set(url_pattern.findall(text)))
        for url in urls:
            url = url.rstrip(".',\"}")
            self.io.offer_url(url)
        return urls

    def check_for_urls(self, inp: str) -> List[str]:
        if not self.detect_urls:
            return inp

        url_pattern = re.compile(r'(https?://[^\s/$.?#].[^\s"]*[^\s,.])')
        urls = list(set(url_pattern.findall(inp)))
        group = ConfirmGroup(urls)
        for url in urls:
            if url not in self.rejected_urls:
                url = url.rstrip(".',\"")
                if self.io.confirm_ask(
                    "Add URL to the chat?", subject=url, group=group, allow_never=True
                ):
                    inp += "\n\n"
                    inp += self.commands.cmd_web(url, return_content=True)
                else:
                    self.rejected_urls.add(url)

        return inp

    def keyboard_interrupt(self):
        Console().show_cursor(True)

        now = time.time()

        thresh = 2
        if self.last_keyboard_interrupt and now - self.last_keyboard_interrupt < thresh:
            self.io.tool_warning("\n\n^C KeyboardInterrupt")
            self.event("exit", reason="Control-C")
            sys.exit()

        self.io.tool_warning("\n\n^C again to exit")

        self.last_keyboard_interrupt = now
