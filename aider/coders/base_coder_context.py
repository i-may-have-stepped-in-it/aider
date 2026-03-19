import locale
import os
import platform
from datetime import datetime
from pathlib import Path


class BaseCoderContextMixin:
    """Prompt, language, and environment context helpers."""

    def normalize_language(self, lang_code):
        """
        Convert a locale code such as ``en_US`` or ``fr`` into a readable
        language name (e.g. ``English`` or ``French``).  If Babel is
        available it is used for reliable conversion; otherwise a small
        built-in fallback map handles common languages.
        """
        from .base_coder import Locale

        if not lang_code:
            return None

        if lang_code.upper() in ("C", "POSIX"):
            return None

        if (
            len(lang_code) > 3
            and "_" not in lang_code
            and "-" not in lang_code
            and lang_code[0].isupper()
        ):
            return lang_code

        if Locale is not None:
            try:
                loc = Locale.parse(lang_code.replace("-", "_"))
                return loc.get_display_name("en").capitalize()
            except Exception:
                pass

        fallback = {
            "en": "English",
            "fr": "French",
            "es": "Spanish",
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
            "ru": "Russian",
        }
        primary_lang_code = lang_code.replace("-", "_").split("_")[0].lower()
        return fallback.get(primary_lang_code, lang_code)

    def get_user_language(self):
        """Detect the user's language preference."""
        if self.chat_language:
            return self.normalize_language(self.chat_language)

        try:
            lang = locale.getlocale()[0]
            if lang:
                lang = self.normalize_language(lang)
            if lang:
                return lang
        except Exception:
            pass

        for env_var in ("LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES"):
            lang = os.environ.get(env_var)
            if lang:
                lang = lang.split(".")[0]
                return self.normalize_language(lang)

        return None

    def get_platform_info(self):
        platform_text = ""
        try:
            platform_text = f"- Platform: {platform.platform()}\n"
        except KeyError:
            platform_text = "- Platform information unavailable\n"

        shell_var = "COMSPEC" if os.name == "nt" else "SHELL"
        shell_val = os.getenv(shell_var)
        platform_text += f"- Shell: {shell_var}={shell_val}\n"

        user_lang = self.get_user_language()
        if user_lang:
            platform_text += f"- Language: {user_lang}\n"

        dt = datetime.now().astimezone().strftime("%Y-%m-%d")
        platform_text += f"- Current date: {dt}\n"

        if self.repo:
            platform_text += "- The user is operating inside a git repository\n"

        if self.lint_cmds:
            if self.auto_lint:
                platform_text += (
                    "- The user's pre-commit runs these lint commands, don't suggest running"
                    " them:\n"
                )
            else:
                platform_text += "- The user prefers these lint commands:\n"
            for lang, cmd in self.lint_cmds.items():
                if lang is None:
                    platform_text += f"  - {cmd}\n"
                else:
                    platform_text += f"  - {lang}: {cmd}\n"

        if self.test_cmd:
            if self.auto_test:
                platform_text += (
                    "- The user's pre-commit runs this test command, don't suggest running them: "
                )
            else:
                platform_text += "- The user prefers this test command: "
            platform_text += self.test_cmd + "\n"

        return platform_text

    def get_project_instructions(self):
        """Load project-specific instructions from standard files."""
        rule_files = [".aider.instructions.md", ".cursorrules", ".aider.rules.md", ".aider.rules"]
        for rule_file in rule_files:
            path = Path(self.root) / rule_file
            if path.exists():
                try:
                    content = self.io.read_text(path)
                    if content:
                        return f"\nPROJECT RULES ({rule_file}):\n{content}\n"
                except Exception:
                    pass
        return ""

    def fmt_system_prompt(self, prompt):
        from .base_coder import SafeFormatter

        final_reminders = []
        if self.main_model.lazy:
            final_reminders.append(self.gpt_prompts.lazy_prompt)
        if self.main_model.overeager:
            final_reminders.append(self.gpt_prompts.overeager_prompt)

        user_lang = self.get_user_language()
        if user_lang:
            final_reminders.append(f"Reply in {user_lang}.\n")

        platform_text = self.get_platform_info()

        if self.suggest_shell_commands:
            shell_cmd_prompt = self.gpt_prompts.shell_cmd_prompt.format(platform=platform_text)
            shell_cmd_reminder = self.gpt_prompts.shell_cmd_reminder.format(platform=platform_text)
            rename_with_shell = self.gpt_prompts.rename_with_shell
        else:
            shell_cmd_prompt = self.gpt_prompts.no_shell_cmd_prompt.format(platform=platform_text)
            shell_cmd_reminder = self.gpt_prompts.no_shell_cmd_reminder.format(
                platform=platform_text
            )
            rename_with_shell = ""

        if user_lang:
            language = user_lang
        else:
            language = "the same language they are using"

        if self.fence[0] == "`" * 4:
            quad_backtick_reminder = (
                "\nIMPORTANT: Use *quadruple* backticks ```` as fences, not triple backticks!\n"
            )
        else:
            quad_backtick_reminder = ""

        final_reminders = "\n\n".join(final_reminders)

        formatter = SafeFormatter()
        prompt = formatter.format(
            prompt,
            fence=self.fence,
            quad_backtick_reminder=quad_backtick_reminder,
            final_reminders=final_reminders,
            platform=platform_text,
            shell_cmd_prompt=shell_cmd_prompt,
            rename_with_shell=rename_with_shell,
            shell_cmd_reminder=shell_cmd_reminder,
            go_ahead_tip=self.gpt_prompts.go_ahead_tip,
            language=language,
            project_rules=self.get_project_instructions(),
        )

        return prompt
