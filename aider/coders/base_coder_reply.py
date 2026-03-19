import os

from aider import prompts
from aider.io import ConfirmGroup


class BaseCoderReplyMixin:
    """Reply post-processing and file-mention helper methods."""

    def add_assistant_reply_to_cur_messages(self):
        if self.partial_response_content:
            self.cur_messages += [dict(role="assistant", content=self.partial_response_content)]
        if self.partial_response_function_call:
            self.cur_messages += [
                dict(
                    role="assistant",
                    content=None,
                    function_call=self.partial_response_function_call,
                )
            ]

    def get_file_mentions(self, content, ignore_current=False):
        words = set(word for word in content.split())

        words = set(word.rstrip(",.!;:?") for word in words)

        quotes = "\"'`*_"
        words = set(word.strip(quotes) for word in words)

        if ignore_current:
            addable_rel_fnames = self.get_all_relative_files()
            existing_basenames = {}
        else:
            addable_rel_fnames = self.get_addable_relative_files()
            existing_basenames = {os.path.basename(f) for f in self.get_inchat_relative_files()} | {
                os.path.basename(self.get_rel_fname(f)) for f in self.abs_read_only_fnames
            }

        mentioned_rel_fnames = set()
        fname_to_rel_fnames = {}
        for rel_fname in addable_rel_fnames:
            normalized_rel_fname = rel_fname.replace("\\", "/")
            normalized_words = set(word.replace("\\", "/") for word in words)
            if normalized_rel_fname in normalized_words:
                mentioned_rel_fnames.add(rel_fname)

            fname = os.path.basename(rel_fname)
            if "/" in fname or "\\" in fname or "." in fname or "_" in fname or "-" in fname:
                if fname not in fname_to_rel_fnames:
                    fname_to_rel_fnames[fname] = []
                fname_to_rel_fnames[fname].append(rel_fname)

        for fname, rel_fnames in fname_to_rel_fnames.items():
            if fname in existing_basenames:
                continue
            if len(rel_fnames) == 1 and fname in words:
                mentioned_rel_fnames.add(rel_fnames[0])

        return mentioned_rel_fnames

    def check_for_file_mentions(self, content):
        mentioned_rel_fnames = self.get_file_mentions(content)

        new_mentions = mentioned_rel_fnames - self.ignore_mentions

        if not new_mentions:
            return

        added_fnames = []
        group = ConfirmGroup(new_mentions)
        for rel_fname in sorted(new_mentions):
            if self.io.confirm_ask(
                "Add file to the chat?", subject=rel_fname, group=group, allow_never=True
            ):
                self.add_rel_fname(rel_fname)
                added_fnames.append(rel_fname)
            else:
                self.ignore_mentions.add(rel_fname)

        if added_fnames:
            return prompts.added_files.format(fnames=", ".join(added_fnames))
