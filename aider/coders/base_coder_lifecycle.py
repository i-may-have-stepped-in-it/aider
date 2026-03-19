import time
import traceback

from aider import urls, utils
from aider.exceptions import LiteLLMExceptions
from aider.models import RETRY_TIMEOUT
from aider.waiting import WaitingSpinner


class BaseCoderLifecycleMixin:
    def check_tokens(self, messages):
        """Check if the messages will fit within the model's token limits."""
        input_tokens = self.main_model.token_count(messages)
        max_input_tokens = self.main_model.info.get("max_input_tokens") or 0

        if max_input_tokens and input_tokens >= max_input_tokens:
            self.io.tool_error(
                f"Your estimated chat context of {input_tokens:,} tokens exceeds the"
                f" {max_input_tokens:,} token limit for {self.main_model.name}!"
            )
            self.io.tool_output("To reduce the chat context:")
            self.io.tool_output("- Use /drop to remove unneeded files from the chat")
            self.io.tool_output("- Use /clear to clear the chat history")
            self.io.tool_output("- Break your code into smaller files")
            self.io.tool_output(
                "It's probably safe to try and send the request, most providers won't charge if"
                " the context limit is exceeded."
            )

            if not self.io.confirm_ask("Try to proceed anyway?"):
                return False
        return True

    def send_message(self, inp):
        self.event("message_send_starting")

        self.io.llm_started()

        self.cur_messages += [
            dict(role="user", content=inp),
        ]

        chunks = self.format_messages()
        messages = chunks.all_messages()
        if not self.check_tokens(messages):
            return
        self.warm_cache(chunks)

        if self.verbose:
            utils.show_messages(messages, functions=self.functions)

        self.multi_response_content = ""
        if self.show_pretty():
            self.waiting_spinner = WaitingSpinner("Waiting for " + self.main_model.name)
            self.waiting_spinner.start()
            if self.stream:
                self.mdstream = self.io.get_assistant_mdstream()
            else:
                self.mdstream = None
        else:
            self.mdstream = None

        retry_delay = 0.125

        litellm_ex = LiteLLMExceptions()

        self.usage_report = None
        exhausted = False
        interrupted = False
        try:
            while True:
                try:
                    yield from self.send(messages, functions=self.functions)
                    break
                except litellm_ex.exceptions_tuple() as err:
                    ex_info = litellm_ex.get_ex_info(err)

                    if ex_info.name == "ContextWindowExceededError":
                        exhausted = True
                        break

                    should_retry = ex_info.retry
                    if should_retry:
                        retry_delay *= 2
                        if retry_delay > RETRY_TIMEOUT:
                            should_retry = False

                    if not should_retry:
                        self.mdstream = None
                        self.check_and_open_urls(err, ex_info.description)
                        break

                    err_msg = str(err)
                    if ex_info.description:
                        self.io.tool_warning(err_msg)
                        self.io.tool_error(ex_info.description)
                    else:
                        self.io.tool_error(err_msg)

                    self.io.tool_output(f"Retrying in {retry_delay:.1f} seconds...")
                    time.sleep(retry_delay)
                    continue
                except KeyboardInterrupt:
                    interrupted = True
                    break
                except self.FinishReasonLength:
                    if not self.main_model.info.get("supports_assistant_prefill"):
                        exhausted = True
                        break

                    self.multi_response_content = self.get_multi_response_content_in_progress()

                    if messages[-1]["role"] == "assistant":
                        messages[-1]["content"] = self.multi_response_content
                    else:
                        messages.append(
                            dict(role="assistant", content=self.multi_response_content, prefix=True)
                        )
                except Exception as err:
                    self.mdstream = None
                    lines = traceback.format_exception(type(err), err, err.__traceback__)
                    self.io.tool_warning("".join(lines))
                    self.io.tool_error(str(err))
                    self.event("message_send_exception", exception=str(err))
                    return
        finally:
            if self.mdstream:
                self.live_incremental_response(True)
                self.mdstream = None

            self._stop_waiting_spinner()

            self.partial_response_content = self.get_multi_response_content_in_progress(True)
            self.remove_reasoning_content()
            self.multi_response_content = ""

        self.io.tool_output()
        self.show_usage_report()
        self.add_assistant_reply_to_cur_messages()

        if exhausted:
            if self.cur_messages and self.cur_messages[-1]["role"] == "user":
                self.cur_messages += [
                    dict(
                        role="assistant",
                        content="FinishReasonLength exception: you sent too many tokens",
                    ),
                ]

            self.show_exhausted_error()
            self.num_exhausted_context_windows += 1
            return

        if self.partial_response_function_call:
            args = self.parse_partial_args()
            if args:
                content = args.get("explanation") or ""
            else:
                content = ""
        elif self.partial_response_content:
            content = self.partial_response_content
        else:
            content = ""

        if not interrupted:
            add_rel_files_message = self.check_for_file_mentions(content)
            if add_rel_files_message:
                if self.reflected_message:
                    self.reflected_message += "\n\n" + add_rel_files_message
                else:
                    self.reflected_message = add_rel_files_message
                return

            try:
                if self.reply_completed():
                    return
            except KeyboardInterrupt:
                interrupted = True

        if interrupted:
            if self.cur_messages and self.cur_messages[-1]["role"] == "user":
                self.cur_messages[-1]["content"] += "\n^C KeyboardInterrupt"
            else:
                self.cur_messages += [dict(role="user", content="^C KeyboardInterrupt")]
            self.cur_messages += [
                dict(role="assistant", content="I see that you interrupted my previous reply.")
            ]
            return

        edited = self.apply_updates()

        if edited:
            self.aider_edited_files.update(edited)
            saved_message = self.auto_commit(edited)

            if not saved_message and hasattr(self.gpt_prompts, "files_content_gpt_edits_no_repo"):
                saved_message = self.gpt_prompts.files_content_gpt_edits_no_repo

            self.move_back_cur_messages(saved_message)

        if self.reflected_message:
            return

        if edited and self.auto_lint:
            lint_errors = self.lint_edited(edited)
            self.auto_commit(edited, context="Ran the linter")
            self.lint_outcome = not lint_errors
            if lint_errors:
                ok = self.io.confirm_ask("Attempt to fix lint errors?")
                if ok:
                    self.reflected_message = lint_errors
                    return

        shared_output = self.run_shell_commands()
        if shared_output:
            self.cur_messages += [
                dict(role="user", content=shared_output),
                dict(role="assistant", content="Ok"),
            ]

        if edited and self.auto_test:
            test_errors = self.commands.cmd_test(self.test_cmd)
            self.test_outcome = not test_errors
            if test_errors:
                ok = self.io.confirm_ask("Attempt to fix test errors?")
                if ok:
                    self.reflected_message = test_errors
                    return

    def show_exhausted_error(self):
        output_tokens = 0
        if self.partial_response_content:
            output_tokens = self.main_model.token_count(self.partial_response_content)
        max_output_tokens = self.main_model.info.get("max_output_tokens") or 0

        input_tokens = self.main_model.token_count(self.format_messages().all_messages())
        input_tokens += self._get_multimodal_image_tokens()
        max_input_tokens = self.main_model.info.get("max_input_tokens") or 0

        total_tokens = input_tokens + output_tokens

        fudge = 0.7

        out_err = ""
        if output_tokens >= max_output_tokens * fudge:
            out_err = " -- possibly exceeded output limit!"

        inp_err = ""
        if input_tokens >= max_input_tokens * fudge:
            inp_err = " -- possibly exhausted context window!"

        tot_err = ""
        if total_tokens >= max_input_tokens * fudge:
            tot_err = " -- possibly exhausted context window!"

        res = ["", ""]
        res.append(f"Model {self.main_model.name} has hit a token limit!")
        res.append("Token counts below are approximate.")
        res.append("")
        res.append(f"Input tokens: ~{input_tokens:,} of {max_input_tokens:,}{inp_err}")
        res.append(f"Output tokens: ~{output_tokens:,} of {max_output_tokens:,}{out_err}")
        res.append(f"Total tokens: ~{total_tokens:,} of {max_input_tokens:,}{tot_err}")

        if output_tokens >= max_output_tokens:
            res.append("")
            res.append("To reduce output tokens:")
            res.append("- Ask for smaller changes in each request.")
            res.append("- Break your code into smaller source files.")
            if "diff" not in self.main_model.edit_format:
                res.append("- Use a stronger model that can return diffs.")

        if input_tokens >= max_input_tokens or total_tokens >= max_input_tokens:
            res.append("")
            res.append("To reduce input tokens:")
            res.append("- Use /tokens to see token usage.")
            res.append("- Use /drop to remove unneeded files from the chat session.")
            res.append("- Use /clear to clear the chat history.")
            res.append("- Break your code into smaller source files.")

        res = "".join([line + "\n" for line in res])
        self.io.tool_error(res)
        self.io.offer_url(urls.token_limits)

    def lint_edited(self, fnames):
        res = ""
        for fname in fnames:
            if not fname:
                continue
            errors = self.linter.lint(self.abs_root_path(fname))

            if errors:
                res += "\n"
                res += errors
                res += "\n"

        if res:
            self.io.tool_warning(res)

        return res
