from collections import OrderedDict

from aider.coders.coder_factory import create_coder


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
        
        # Show cost preview before switching
        input_cost = model.info.get("input_cost_per_token", 0) or 0
        output_cost = model.info.get("output_cost_per_token", 0) or 0
        
        if input_cost or output_cost:
            input_1k = input_cost * 1000
            output_1k = output_cost * 1000
            self.io.tool_output(f"Model: {model.name}")
            self.io.tool_output(f"Cost: ${input_1k:.2f} per 1K input, ${output_1k:.2f} per 1K output tokens")
            
            # Compare with current model
            old_input = self.coder.main_model.info.get("input_cost_per_token", 0) or 0
            old_output = self.coder.main_model.info.get("output_cost_per_token", 0) or 0
            
            if old_input and input_cost > old_input * 2:
                self.io.tool_warning(f"This model is {input_cost/old_input:.1f}x more expensive than {self.coder.main_model.name}")
        
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
        "Ask questions about aider or show help for a specific command"
        from aider.commands import SwitchCoder
        from aider.help import Help, install_help_extra
        
        args_clean = args.strip()
        if not args_clean:
            self.basic_help()
            return
        
        # Check if user is asking for help on a specific command
        if args_clean.startswith("/"):
            args_clean = args_clean[1:]  # Remove leading /
        
        metadata = self.get_command_metadata()
        if args_clean in metadata:
            info = metadata[args_clean]
            self.io.tool_output(f"Command: /{args_clean}")
            self.io.tool_output("-" * 40)
            if info["description"]:
                self.io.tool_output(f"Description: {info['description']}")
            if info["usage"]:
                self.io.tool_output(f"Usage: {info['usage']}")
            if info["aliases"]:
                aliases = ", ".join(f"/{a}" for a in info["aliases"])
                self.io.tool_output(f"Aliases: {aliases}")
            return
        
        # Check aliases
        from aider.commands import Commands
        if args_clean in Commands.command_aliases:
            target = Commands.command_aliases[args_clean]
            self.io.tool_output(f"Alias: /{args_clean} -> /{target}")
            # Show help for the target command
            if target in metadata:
                info = metadata[target]
                if info["usage"]:
                    self.io.tool_output(f"Usage: {info['usage']}")
                if info["description"]:
                    self.io.tool_output(f"Description: {info['description']}")
            return

        self.coder.event("interactive help")

    def cmd_welcome(self, args):
        "Show the welcome message and quick start guide"
        from aider import __version__
        
        self.io.tool_output("")
        self.io.tool_output(f"Aider v{__version__}")
        self.io.tool_output("=" * 50)
        self.io.tool_output("")
        self.io.tool_output("Quick Start:")
        self.io.tool_output("  /add <file>        Add files to the chat")
        self.io.tool_output("  /drop <file>       Remove files from chat")
        self.io.tool_output("  /commit            Commit changes to git")
        self.io.tool_output("  /help              Show all commands")
        self.io.tool_output("")
        self.io.tool_output("Useful Commands:")
        self.io.tool_output("  /cost              Check session cost")
        self.io.tool_output("  /tokens            Check token usage")
        self.io.tool_output("  /undo              Undo last commit")
        self.io.tool_output("  /diff              Show pending changes")
        self.io.tool_output("  /context           Show current context")
        self.io.tool_output("")
        self.io.tool_output("Tips:")
        self.io.tool_output("  - Use Tab for file completion")
        self.io.tool_output("  - Type naturally, aider will help you code")
        self.io.tool_output("  - Press Ctrl+C to cancel a request")
        self.io.tool_output("")
        
        # Show current context
        if self.coder:
            self.io.tool_output("Current Context:")
            files = self.coder.get_inchat_relative_files()
            if files:
                self.io.tool_output(f"  Files: {', '.join(files[:5])}")
                if len(files) > 5:
                    self.io.tool_output(f"         ... and {len(files) - 5} more")
            else:
                self.io.tool_output("  No files in chat yet. Use /add to add files.")

    def cmd_suggest(self, args):
        "Suggest aider commands based on current state"
        suggestions = []
        
        # Check for dirty files
        if self.coder.repo:
            dirty = self.coder.repo.get_dirty_files()
            dirty_in_chat = [f for f in dirty if f in self.coder.abs_fnames]
            if dirty_in_chat:
                suggestions.append(("/commit", f"Commit {len(dirty_in_chat)} modified file(s)"))
                suggestions.append(("/diff", "Review pending changes"))
        
        # Check if no files in chat
        if not self.coder.get_inchat_relative_files():
            suggestions.append(("/add .", "Add all files to chat"))
        
        # Check token usage
        if hasattr(self.coder, 'total_tokens_sent') and self.coder.total_tokens_sent > 5000:
            suggestions.append(("/tokens", "Check token usage"))
        
        # Check for test command
        if hasattr(self.coder, 'test_cmd') and self.coder.test_cmd:
            suggestions.append(("/test", f"Run tests ({self.coder.test_cmd})"))
        
        # Always suggest help
        suggestions.append(("/help", "List all commands"))
        
        if suggestions:
            self.io.tool_output("Suggested commands:")
            self.io.tool_output("-" * 40)
            for cmd, reason in suggestions:
                self.io.tool_output(f"  {cmd:<15} {reason}")
        else:
            self.io.tool_output("No specific suggestions. Type /help for all commands.")

    def cmd_settings(self, args):
        "Open aider settings file in editor"
        import platform
        import subprocess
        from pathlib import Path
        
        # Find settings file
        settings_path = Path.home() / ".aider.conf.yml"
        if not settings_path.exists():
            # Create template
            template = """# Aider Configuration File
# See https://aider.chat/docs/config/aider_conf.html

# Model settings
# model: gpt-4o

# Git settings
# auto-commits: true
# dirty-commits: true

# Editor settings
# editor: vim

# Other settings
# pretty: true
# stream: true
"""
            settings_path.write_text(template)
            self.io.tool_output(f"Created settings file: {settings_path}")
        
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.run(["open", str(settings_path)])
            elif system == "Linux":
                subprocess.run(["xdg-open", str(settings_path)])
            elif system == "Windows":
                subprocess.run(["start", str(settings_path)], shell=True)
            
            self.io.tool_output(f"Opening: {settings_path}")
        except Exception as e:
            self.io.tool_error(f"Could not open settings: {e}")
            self.io.tool_output(f"Edit manually: {settings_path}")

    def cmd_config(self, args):
        "Show current configuration settings"
        args_clean = args.strip().lower()
        
        # Get relevant config from args
        self.io.tool_output("Current Configuration:")
        self.io.tool_output("-" * 40)
        
        # Model info
        self.io.tool_output(f"Model: {self.coder.main_model.name}")
        if hasattr(self.coder.main_model, 'weak_model') and self.coder.main_model.weak_model:
            if self.coder.main_model.weak_model != self.coder.main_model:
                self.io.tool_output(f"Weak model: {self.coder.main_model.weak_model.name}")
        
        # Edit format
        self.io.tool_output(f"Edit format: {self.coder.edit_format}")
        
        # Auto settings
        self.io.tool_output(f"\nAuto-commit: {'enabled' if self.coder.auto_commits else 'disabled'}")
        self.io.tool_output(f"Auto-lint: {'enabled' if self.coder.auto_lint else 'disabled'}")
        self.io.tool_output(f"Auto-test: {'enabled' if self.coder.auto_test else 'disabled'}")
        
        # Repo settings
        if self.coder.repo:
            self.io.tool_output(f"\nGit repo: {self.coder.repo.get_rel_repo_dir()}")
            self.io.tool_output(f"Dirty commits: {'enabled' if self.coder.dirty_commits else 'disabled'}")
        
        # Show args if requested
        if args_clean == "--all" and hasattr(self.coder, 'args'):
            self.io.tool_output("\nAll settings (from args):")
            for attr in dir(self.coder.args):
                if not attr.startswith('_'):
                    val = getattr(self.coder.args, attr)
                    if not callable(val):
                        # Mask sensitive values
                        if any(s in attr.lower() for s in ['key', 'token', 'password', 'secret']):
                            val = '*' * 8 if val else None
                        self.io.tool_output(f"  {attr}: {val}")

    def cmd_shortcuts(self, args):
        "Show keyboard shortcuts and key bindings"
        shortcuts = [
            ("Ctrl+C", "Cancel/Interrupt"),
            ("Ctrl+Z", "Suspend (fg to resume)"),
            ("Ctrl+X Ctrl+E", "Open external editor"),
            ("Alt+Enter", "Newline (in multiline mode)"),
            ("Enter", "Submit message"),
            ("Up/Down", "Navigate command history"),
            ("Tab", "Autocomplete filenames"),
            ("Ctrl+K", "Cut to end of line"),
            ("Ctrl+U", "Cut entire line"),
            ("/", "Start command (at beginning of line)"),
        ]
        
        self.io.tool_output("Keyboard Shortcuts:")
        self.io.tool_output("-" * 40)
        for key, desc in shortcuts:
            self.io.tool_output(f"  {key:<20} {desc}")
        
        self.io.tool_output("\nCommands:")
        self.io.tool_output("-" * 40)
        self.io.tool_output("  /<command>           Run a slash command")
        self.io.tool_output("  !<shell command>     Execute shell command")

        if not self.help:
            res = install_help_extra(self.io)
            if not res:
                self.io.tool_error("Unable to initialize interactive help.")
                return
            self.help = Help()

        coder = create_coder(
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
        

        if not args.strip():
            return self.cmd_chat_mode(edit_format)

        coder = create_coder(
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
