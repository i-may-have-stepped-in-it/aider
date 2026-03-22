import hashlib
import json
import sys

from aider.reasoning_tags import (
    REASONING_TAG,
    format_reasoning_content,
    replace_reasoning_tags,
)


class BaseCoderLLMOutputMixin:
    """LLM response rendering and streaming output helpers."""

    def show_send_output(self, completion):
        self._stop_waiting_spinner()

        if self.verbose:
            print(completion)

        if not completion.choices:
            self.io.tool_error(str(completion))
            return

        show_func_err = None
        show_content_err = None
        try:
            if completion.choices[0].message.tool_calls:
                self.partial_response_function_call = (
                    completion.choices[0].message.tool_calls[0].function
                )
        except AttributeError as func_err:
            show_func_err = func_err

        try:
            reasoning_content = completion.choices[0].message.reasoning_content
        except AttributeError:
            try:
                reasoning_content = completion.choices[0].message.reasoning
            except AttributeError:
                reasoning_content = None

        try:
            self.partial_response_content = completion.choices[0].message.content or ""
        except AttributeError as content_err:
            show_content_err = content_err

        resp_hash = dict(
            function_call=str(self.partial_response_function_call),
            content=self.partial_response_content,
        )
        resp_hash = hashlib.sha1(json.dumps(resp_hash, sort_keys=True).encode())
        self.chat_completion_response_hashes.append(resp_hash.hexdigest())

        if show_func_err and show_content_err:
            self.io.tool_error(show_func_err)
            self.io.tool_error(show_content_err)
            raise Exception("No data found in LLM response!")

        show_resp = self.render_incremental_response(True)

        if reasoning_content:
            formatted_reasoning = format_reasoning_content(
                reasoning_content, self.reasoning_tag_name
            )
            show_resp = formatted_reasoning + show_resp

        show_resp = replace_reasoning_tags(show_resp, self.reasoning_tag_name)

        self.io.assistant_output(show_resp, pretty=self.show_pretty())

        if (
            hasattr(completion.choices[0], "finish_reason")
            and completion.choices[0].finish_reason == "length"
        ):
            raise type(self).FinishReasonLength()

    def show_send_output_stream(self, completion):
        received_content = False
        self.interrupted = False

        for chunk in completion:
            if self.interrupted:
                self.io.tool_warning("\n[bold red]Generation interrupted by user.[/bold red]")
                break

            if len(chunk.choices) == 0:
                continue

            if (
                hasattr(chunk.choices[0], "finish_reason")
                and chunk.choices[0].finish_reason == "length"
            ):
                raise type(self).FinishReasonLength()

            try:
                func = chunk.choices[0].delta.function_call
                for k, v in func.items():
                    if k in self.partial_response_function_call:
                        self.partial_response_function_call[k] += v
                    else:
                        self.partial_response_function_call[k] = v
                received_content = True
            except AttributeError:
                pass

            text = ""

            try:
                reasoning_content = chunk.choices[0].delta.reasoning_content
            except AttributeError:
                try:
                    reasoning_content = chunk.choices[0].delta.reasoning
                except AttributeError:
                    reasoning_content = None

            if reasoning_content:
                if not self.got_reasoning_content:
                    text += f"<{REASONING_TAG}>\n\n"
                text += reasoning_content
                self.got_reasoning_content = True
                received_content = True

            try:
                content = chunk.choices[0].delta.content
                if content:
                    if self.got_reasoning_content and not self.ended_reasoning_content:
                        text += f"\n\n</{self.reasoning_tag_name}>\n\n"
                        self.ended_reasoning_content = True

                    text += content
                    received_content = True
            except AttributeError:
                pass

            if received_content:
                self._stop_waiting_spinner()

            # If we have a live delegate (background prompt), forward the new text chunk
            if self.live_delegate and text:
                # Pass thinking status if we are in a reasoning block
                is_thinking = self.got_reasoning_content and not self.ended_reasoning_content
                self.live_delegate.append_content(text, is_thinking=is_thinking)

            self.partial_response_content += text

            if self.show_pretty():
                self.live_incremental_response(False)
            elif text:
                text = replace_reasoning_tags(text, self.reasoning_tag_name)
                try:
                    sys.stdout.write(text)
                except UnicodeEncodeError:
                    safe_text = text.encode(sys.stdout.encoding, errors="backslashreplace").decode(
                        sys.stdout.encoding
                    )
                    sys.stdout.write(safe_text)
                sys.stdout.flush()
                yield text

        if not received_content:
            self.io.tool_warning("Empty response received from LLM. Check your provider account?")
