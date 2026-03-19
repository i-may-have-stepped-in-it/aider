import base64
import mimetypes
import re
from collections import defaultdict
from pathlib import Path

from aider.utils import is_audio_file, is_image_file, is_video_file


class BaseCoderFilesMixin:
    """File/context assembly and repo-map helper methods."""

    def get_abs_fnames_content(self):
        for fname in list(self.abs_fnames):
            content = self.io.read_text(fname)

            if content is None:
                relative_fname = self.get_rel_fname(fname)
                self.io.tool_warning(f"Dropping {relative_fname} from the chat.")
                self.abs_fnames.remove(fname)
            else:
                yield fname, content

    def choose_fence(self):
        all_content = ""
        for _fname, content in self.get_abs_fnames_content():
            all_content += content + "\n"
        for _fname in self.abs_read_only_fnames:
            content = self.io.read_text(_fname)
            if content is not None:
                all_content += content + "\n"

        lines = all_content.splitlines()
        good = False
        for fence_open, fence_close in self.fences:
            if any(line.startswith(fence_open) or line.startswith(fence_close) for line in lines):
                continue
            good = True
            break

        if good:
            self.fence = (fence_open, fence_close)
        else:
            self.fence = self.fences[0]
            self.io.tool_warning(
                "Unable to find a fencing strategy! Falling back to:"
                f" {self.fence[0]}...{self.fence[1]}"
            )
        return

    def get_files_content(self, fnames=None):
        if not fnames:
            fnames = self.abs_fnames

        prompt = ""
        for fname, content in self.get_abs_fnames_content():
            if not is_image_file(fname):
                relative_fname = self.get_rel_fname(fname)
                prompt += "\n"
                prompt += relative_fname
                prompt += f"\n{self.fence[0]}\n"
                prompt += content
                prompt += f"{self.fence[1]}\n"
        return prompt

    def get_read_only_files_content(self):
        prompt = ""
        for fname in self.abs_read_only_fnames:
            content = self.io.read_text(fname)
            if content is not None and not is_image_file(fname):
                relative_fname = self.get_rel_fname(fname)
                prompt += "\n"
                prompt += relative_fname
                prompt += f"\n{self.fence[0]}\n"
                prompt += content
                prompt += f"{self.fence[1]}\n"
        return prompt

    def get_cur_message_text(self):
        text = ""
        for msg in self.cur_messages:
            text += msg["content"] + "\n"
        return text

    def get_ident_mentions(self, text):
        words = set(re.split(r"\W+", text))
        return words

    def get_ident_filename_matches(self, idents):
        all_fnames = defaultdict(set)
        for fname in self.get_all_relative_files():
            if not fname or fname == ".":
                continue

            try:
                path = Path(fname)
                base = path.stem.lower()
                if len(base) >= 5:
                    all_fnames[base].add(fname)
            except ValueError:
                continue

        matches = set()
        for ident in idents:
            if len(ident) < 5:
                continue
            matches.update(all_fnames[ident.lower()])

        return matches

    def get_repo_map(self, force_refresh=False):
        if not self.repo_map:
            return

        cur_msg_text = self.get_cur_message_text()
        mentioned_fnames = self.get_file_mentions(cur_msg_text)
        mentioned_idents = self.get_ident_mentions(cur_msg_text)
        mentioned_fnames.update(self.get_ident_filename_matches(mentioned_idents))

        all_abs_files = set(self.get_all_abs_files())
        repo_abs_read_only_fnames = set(self.abs_read_only_fnames) & all_abs_files
        chat_files = set(self.abs_fnames) | repo_abs_read_only_fnames
        other_files = all_abs_files - chat_files

        repo_content = self.repo_map.get_repo_map(
            chat_files,
            other_files,
            mentioned_fnames=mentioned_fnames,
            mentioned_idents=mentioned_idents,
            force_refresh=force_refresh,
        )

        if not repo_content:
            repo_content = self.repo_map.get_repo_map(
                set(),
                all_abs_files,
                mentioned_fnames=mentioned_fnames,
                mentioned_idents=mentioned_idents,
            )

        if not repo_content:
            repo_content = self.repo_map.get_repo_map(
                set(),
                all_abs_files,
            )

        return repo_content

    def get_repo_messages(self):
        repo_messages = []
        repo_content = self.get_repo_map()
        if repo_content:
            repo_messages += [
                dict(role="user", content=repo_content),
                dict(
                    role="assistant",
                    content="Ok, I won't try and edit those files without asking first.",
                ),
            ]
        return repo_messages

    def get_readonly_files_messages(self):
        readonly_messages = []

        read_only_content = self.get_read_only_files_content()
        if read_only_content:
            readonly_messages += [
                dict(
                    role="user", content=self.gpt_prompts.read_only_files_prefix + read_only_content
                ),
                dict(
                    role="assistant",
                    content="Ok, I will use these files as references.",
                ),
            ]

        images_message = self.get_images_message(self.abs_read_only_fnames)
        if images_message is not None:
            readonly_messages += [
                images_message,
                dict(role="assistant", content="Ok, I will use these images as references."),
            ]

        return readonly_messages

    def get_chat_files_messages(self):
        chat_files_messages = []
        if self.abs_fnames:
            files_content = self.gpt_prompts.files_content_prefix
            files_content += self.get_files_content()
            files_reply = self.gpt_prompts.files_content_assistant_reply
        elif self.get_repo_map() and self.gpt_prompts.files_no_full_files_with_repo_map:
            files_content = self.gpt_prompts.files_no_full_files_with_repo_map
            files_reply = self.gpt_prompts.files_no_full_files_with_repo_map_reply
        else:
            files_content = self.gpt_prompts.files_no_full_files
            files_reply = "Ok."

        if files_content:
            chat_files_messages += [
                dict(role="user", content=files_content),
                dict(role="assistant", content=files_reply),
            ]

        images_message = self.get_images_message(self.abs_fnames)
        if images_message is not None:
            chat_files_messages += [
                images_message,
                dict(role="assistant", content="Ok."),
            ]

        return chat_files_messages

    def get_images_message(self, fnames):
        supports_images = self.main_model.info.get("supports_vision")
        supports_pdfs = self.main_model.info.get("supports_pdf_input") or self.main_model.info.get(
            "max_pdf_size_mb"
        )
        supports_video = self.main_model.info.get("supports_video_input")
        supports_audio = self.main_model.info.get("supports_audio_input")

        supports_pdfs = supports_pdfs or "claude-3-5-sonnet-20241022" in self.main_model.name

        if not (supports_images or supports_pdfs or supports_video or supports_audio):
            return None

        multimodal_messages = []
        for fname in fnames:
            rel_fname = self.get_rel_fname(fname)

            if is_video_file(fname) and supports_video:
                frames = self.io.read_video(fname)
                if frames:
                    multimodal_messages += [
                        {"type": "text", "text": f"Video file (frames): {rel_fname}"}
                    ]
                    for frame_base64 in frames:
                        multimodal_messages += [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{frame_base64}"},
                            }
                        ]
                continue

            if is_audio_file(fname) and supports_audio:
                audio_base64 = self.io.read_audio(fname)
                if audio_base64:
                    mime_type, _ = mimetypes.guess_type(fname)
                    audio_format = mime_type.split("/")[-1] if mime_type else "wav"
                    multimodal_messages += [
                        {"type": "text", "text": f"Audio file: {rel_fname}"},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_base64, "format": audio_format},
                        },
                    ]
                continue

            if not is_image_file(fname):
                continue

            mime_type, _ = mimetypes.guess_type(fname)
            if not mime_type:
                continue

            with open(fname, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            image_url = f"data:{mime_type};base64,{encoded_string}"

            if mime_type.startswith("image/") and supports_images:
                multimodal_messages += [
                    {"type": "text", "text": f"Image file: {rel_fname}"},
                    {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
                ]
            elif mime_type == "application/pdf" and supports_pdfs:
                multimodal_messages += [
                    {"type": "text", "text": f"PDF file: {rel_fname}"},
                    {"type": "image_url", "image_url": image_url},
                ]

        if not multimodal_messages:
            return None

        return {
            "role": "user",
            "content": multimodal_messages,
        }
