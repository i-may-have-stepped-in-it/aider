import threading


class BaseCoderHistoryMixin:
    """Chat history movement and summarization helpers."""

    def summarize_start(self):
        if not self.summarizer.too_big(self.done_messages):
            return

        self.summarize_end()

        if self.verbose:
            self.io.tool_output("Starting to summarize chat history.")

        hooks = self._get_hooks_manager()
        if hooks:
            try:
                hooks.execute("pre_summarize", messages=self.done_messages, coder=self)
            except Exception as e:
                if hooks.verbose:
                    self.io.tool_error(f"Hook error (pre_summarize): {e}")

        self.summarizer_thread = threading.Thread(target=self.summarize_worker)
        self.summarizer_thread.start()

    def summarize_worker(self):
        self.summarizing_messages = list(self.done_messages)
        try:
            self.summarized_done_messages = self.summarizer.summarize(self.summarizing_messages)
        except ValueError as err:
            self.io.tool_warning(err.args[0])

        if self.verbose:
            self.io.tool_output("Finished summarizing chat history.")

        hooks = self._get_hooks_manager()
        if hooks:
            try:
                hooks.execute(
                    "post_summarize",
                    original_messages=self.summarizing_messages,
                    summary=self.summarized_done_messages,
                    coder=self,
                )
            except Exception as e:
                if hooks.verbose:
                    self.io.tool_error(f"Hook error (post_summarize): {e}")

    def summarize_end(self):
        if self.summarizer_thread is None:
            return

        self.summarizer_thread.join()
        self.summarizer_thread = None

        if self.summarizing_messages == self.done_messages:
            self.done_messages = self.summarized_done_messages
        self.summarizing_messages = None
        self.summarized_done_messages = []

    def move_back_cur_messages(self, message):
        self.done_messages += self.cur_messages
        self.summarize_start()

        if message:
            self.done_messages += [
                dict(role="user", content=message),
                dict(role="assistant", content="Ok."),
            ]
        self.cur_messages = []
