from collections import OrderedDict


class ModeCommandsMixin:
    """Model, mode-switching, and help/chat command handlers."""

    def cmd_model(self, args):
        "Switch the Main Model to a new LLM"
        from aider import models
        from aider.commands import SwitchCoder

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

        old_model_edit_format = self.coder.main_model.edit_format
        current_edit_format = self.coder.edit_format

        new_edit_format = current_edit_format
        if current_edit_format == old_model_edit_format:
            new_edit_format = model.edit_format

        raise SwitchCoder(main_model=model, edit_format=new_edit_format)

    def cmd_editor_model(self, args):
        "Switch the Editor Model to a new LLM"
        from aider import models
        from aider.commands import SwitchCoder

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
        from aider import models
        from aider.commands import SwitchCoder

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
        from aider.commands import SwitchCoder

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
                        " them. Use --dashboard to enable the live dashboard UI."
                    ),
                ),
                ("context", "Automatically identify which files will need to be edited."),
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

    def basic_help(self):
        metadata = self.get_command_metadata()
        commands = ["/" + name for name in metadata]
        pad = max(len(cmd) for cmd in commands)
        pad = "{cmd:" + str(pad) + "}"
        for cmd in commands:
            info = metadata[cmd[1:]]
            alias_text = ""
            if info["aliases"]:
                alias_text = " [" + ", ".join("/" + alias for alias in info["aliases"]) + "]"
            desc = info["description"] or "No description available."
            self.io.tool_output(f"{pad.format(cmd=cmd)} {desc}{alias_text}")
        self.io.tool_output()
        self.io.tool_output(
            "Use `/help <question>` to ask questions about how to use aider."
        )

    def cmd_help(self, args):
        "Ask questions about aider"
        from aider.commands import SwitchCoder
        from aider.help import Help, install_help_extra
        from aider.coders.base_coder import Coder

        if not args.strip():
            self.basic_help()
            return

        self.coder.event("interactive help")

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
        from aider.io import CommandCompletionException

        raise CommandCompletionException()

    def completions_code(self):
        from aider.io import CommandCompletionException

        raise CommandCompletionException()

    def completions_architect(self):
        from aider.io import CommandCompletionException

        raise CommandCompletionException()

    def completions_context(self):
        from aider.io import CommandCompletionException

        raise CommandCompletionException()

    def cmd_ask(self, args):
        """Ask questions about the code base without editing any files. If no prompt provided, switches to ask mode."""  # noqa
        return self._generic_chat_command(args, "ask")

    def cmd_code(self, args):
        """Ask for changes to your code. If no prompt provided, switches to code mode."""  # noqa
        return self._generic_chat_command(args, self.coder.main_model.edit_format)

    def cmd_architect(self, args):
        """Enter architect/editor mode using 2 different models. Use --dashboard to enable the live dashboard UI. If no prompt provided, switches to architect/editor mode."""  # noqa
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
        from aider.commands import SwitchCoder
        from aider.coders.base_coder import Coder

        if not args.strip():
            return self.cmd_chat_mode(edit_format)

        coder = Coder.create(
            io=self.io,
            from_coder=self.coder,
            edit_format=edit_format,
            summarize_from_coder=False,
        )

        coder.run(args)

        raise SwitchCoder(
            edit_format=self.coder.edit_format,
            summarize_from_coder=False,
            from_coder=coder,
            show_announcements=False,
            placeholder=placeholder,
        )
