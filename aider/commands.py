import difflib
import re
import shlex
import sys
from collections import OrderedDict

from aider.async_utils import run_async_safely
from aider.commands_collaboration import CollaborationCommandsMixin
from aider.commands_files import FileCommandsMixin
from aider.commands_misc import MiscCommandsMixin
from aider.commands_modes import ModeCommandsMixin
from aider.commands_tools import ToolCommandsMixin
from aider.commands_workflow import WorkflowCommandsMixin
from aider.hooks import get_hooks_manager
from aider.llm import litellm
from aider.repo import ANY_GIT_ERROR

from .dump import dump  # noqa: F401

_run_async_safely = run_async_safely
Scraper = None
install_playwright = None


class SwitchCoder(Exception):
    def __init__(self, placeholder=None, **kwargs):
        self.kwargs = kwargs
        self.placeholder = placeholder


class Commands(
    MiscCommandsMixin,
    WorkflowCommandsMixin,
    ToolCommandsMixin,
    ModeCommandsMixin,
    FileCommandsMixin,
    CollaborationCommandsMixin,
):
    command_aliases = {
        "?": "help",
        "search": "search-web",
        "a": "add",
        "d": "drop",
        "ro": "read-only",
        "c": "commit",
        "u": "undo",
        "q": "exit",
        "quit": "exit",
        "x": "exit",
        "gs": "gs",  # git status shorthand
        "gd": "gd",  # git diff shorthand
        "df": "diff",  # diff shorthand
        "ctx": "context",  # context shorthand
        "files": "context",  # files shorthand
        "install-hooks": "install-hook",
        "uninstall-hooks": "uninstall-hook",
    }
    command_usages = {
        "add": "/add <file|glob> [more files...]",
        "drop": "/drop <file|glob> [more files...]",
        "read-only": "/read-only <file|glob> [more files...]",
        "reset": "/reset [--force]",
        "save": "/save [filename]",
        "load": "/load <filename>",
        "reload": "/reload [--force] [--dry-run]",
        "find": "/find <pattern>",
        "exclude": "/exclude <pattern>",
        "size": "/size",
        "map": "/map",
        "rename": "/rename <old> <new>",
        "recent": "/recent",
        "untracked": "/untracked",
        "grep": "/grep <pattern>",
        "archive": "/archive",
        "pin": "/pin [file]",
        "checkpoint": "/checkpoint [message|list|restore <n>]",
        "open": "/open <file>",
        "tail": "/tail [-n N] <file>",
        "head": "/head [-n N] <file>",
        "wc": "/wc [file]",
        "tree": "/tree [-L N]",
        "compare": "/compare <file1> <file2>",
        "backup": "/backup",
        "verify": "/verify",
        "history": "/history [search term]",
        "export": "/export [filename]",
        "install-hook": "/install-hook [--force]",
        "uninstall-hook": "/uninstall-hook",
        "undo": "/undo [--force]",
        "test": "/test <command> | /test --history",
        "diff": "/diff",
        "merge": "/merge",
        "blame": "/blame [-n N] <file>",
        "context": "/context",
        "git": "/git <git args...>",
        "run": "/run <shell command>",
        "web": "/web <url>",
        "wiki": "/wiki [topic]",
        "search-web": "/search-web <query>",
        "models": "/models <partial model name>",
        "config": "/config [--all]",
        "cost": "/cost",
        "stats": "/stats",
        "timer": "/timer [start|stop|total|reset]",
        "bookmark": "/bookmark [add|list|goto|remove|clear]",
        "metrics": "/metrics",
        "activity": "/activity",
        "echo": "/echo <text>",
        "todo": "/todo [add|scan|list|done|clear]",
        "notify": "/notify [on|off|test]",
        "template": "/template [name]",
        "copy": "/copy",
        "bug": "/bug [description]",
        "issue": "/issue [title]",
        "pr": "/pr [title]",
        "shortcuts": "/shortcuts",
        "suggest": "/suggest",
        "settings": "/settings",
        "welcome": "/welcome",
        "index": "/index add <dir> | /index search <query> | /index status",
        "mcp": "/mcp add <name> <cmd...> | /mcp list | /mcp remove <name>",
        "skill": "/skill list | /skill run <skill> [...] | /skill info <skill>",
        "agent": "/agent <subcommand> [...]",
        "venice": "/venice [models|characters|character <slug>|web on|off|auto|use <model>]",
        "theme": "/theme [aurora|codex|gemini|classic]",
        "a2a": "/a2a <subcommand> [...]",
    }
    voice = None
    scraper = None

    def clone(self):
        return Commands(
            self.io,
            None,
            voice_language=self.voice_language,
            voice_input_device=self.voice_input_device,
            voice_format=self.voice_format,
            verify_ssl=self.verify_ssl,
            args=self.args,
            parser=self.parser,
            verbose=self.verbose,
            editor=self.editor,
            original_read_only_fnames=self.original_read_only_fnames,
            runtime=self.runtime,
        )

    def __init__(
        self,
        io,
        coder,
        voice_language=None,
        voice_input_device=None,
        voice_format=None,
        verify_ssl=True,
        args=None,
        parser=None,
        verbose=False,
        editor=None,
        original_read_only_fnames=None,
        runtime=None,
    ):
        self.io = io
        self.coder = coder
        self.parser = parser
        self.args = args
        self.verbose = verbose
        self.runtime = runtime or (getattr(coder, "runtime", None) if coder else None)

        self.verify_ssl = verify_ssl
        if voice_language == "auto":
            voice_language = None

        self.voice_language = voice_language
        self.voice_format = voice_format
        self.voice_input_device = voice_input_device

        self.help = None
        self.editor = editor
        self._agent_commands = None
        self._a2a_commands = None
        self._skill_command = None
        self._skills_registry = None
        self._skills_registry_owner = None
        self._skills_registry_override = False
        self._command_metadata = None

        # Store the original read-only filenames provided via args.read
        self.original_read_only_fnames = set(original_read_only_fnames or [])

    def _build_command_metadata(self):
        commands = OrderedDict()

        for attr in sorted(dir(self)):
            if not attr.startswith("cmd_"):
                continue
            name = attr[4:].replace("_", "-")
            method = getattr(self, attr, None)
            description = ""
            if method and method.__doc__:
                description = method.__doc__.strip()

            commands[name] = {
                "name": name,
                "method_name": attr,
                "description": description,
                "aliases": [],
                "usage": self.command_usages.get(name, ""),
            }

        for alias, target in self.command_aliases.items():
            if target in commands:
                commands[target]["aliases"].append(alias)

        return commands

    def get_command_metadata(self):
        if self._command_metadata is None:
            self._command_metadata = self._build_command_metadata()
        return self._command_metadata

    def invalidate_command_metadata_cache(self):
        self._command_metadata = None

    def _get_command_metadata_items(self):
        return self.get_command_metadata().items()

    def resolve_command_name(self, cmd_name):
        cmd_name = cmd_name.replace("_", "-")
        if cmd_name in self.command_aliases:
            return self.command_aliases[cmd_name]
        return cmd_name

    def _get_hooks_manager(self):
        """Get the hooks manager from runtime or coder state before global compatibility."""
        if self.runtime and self.runtime.hooks_manager:
            return self.runtime.hooks_manager
        if self.coder and getattr(self.coder, "hooks_manager", None):
            return self.coder.hooks_manager
        return get_hooks_manager()

    def sync_cached_helpers(self):
        """Refresh cached helper objects after command IO/runtime rebinding."""
        if self._agent_commands is not None:
            self._agent_commands.io = self.io
        if self._a2a_commands is not None:
            self._a2a_commands.io = self.io
        if self._skill_command is not None:
            self._skill_command.io = self.io
            self._skill_command.coder = self.coder
            self._skill_command.commands = self
            self._skill_command.verbose = self.verbose
        if self._skill_command is not None:
            self._skill_command.io = self.io
            self._skill_command.coder = self.coder
            self._skill_command.commands = self
            self._skill_command.verbose = self.verbose

    @property
    def skills_registry(self):
        """Resolve the active skill registry dynamically from the current runtime."""
        if self._skills_registry_override:
            return self._skills_registry

        owner = getattr(self.runtime, "skill_registry", None) if self.runtime else None
        if owner is None and self.coder is not None:
            owner = getattr(self.coder, "skills_registry", None)
        if owner is None:
            try:
                from aider.skills.registry import get_registry

                owner = get_registry()
            except ImportError:
                owner = None

        if self._skills_registry is not None and self._skills_registry_owner is not owner:
            self._skills_registry = None

        if self._skills_registry is None:
            self._skills_registry = owner
            self._skills_registry_owner = owner

        return self._skills_registry

    @skills_registry.setter
    def skills_registry(self, value):
        """Allow explicit skill registry injection for tests and compatibility."""
        self._skills_registry = value
        self._skills_registry_owner = value
        self._skills_registry_override = True

    def completions_model(self):
        models = litellm.model_cost.keys()
        return models

    def completions_help(self):
        """Return command names for /help tab completion."""
        return list(self.get_command_metadata().keys())

    def parse_shell_like_args(self, args, command_name=None):
        try:
            return shlex.split(args)
        except ValueError as err:
            if command_name:
                self.io.tool_error(f"Unable to parse {command_name} arguments: {err}")
            else:
                self.io.tool_error(f"Unable to parse arguments: {err}")
            return

    def parse_filename_args(self, args, command_name=None):
        parts = self.parse_shell_like_args(args, command_name=command_name)
        if parts is None:
            return
        return parts

    def is_command(self, inp):
        if not inp:
            return False
        return inp[0] in "/!"

    def get_raw_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = self.resolve_command_name(cmd[1:])
        cmd = cmd.replace("-", "_")

        raw_completer = getattr(self, f"completions_raw_{cmd}", None)
        return raw_completer

    def get_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = self.resolve_command_name(cmd[1:])
        cmd = cmd.replace("-", "_")
        fun = getattr(self, f"completions_{cmd}", None)
        if not fun:
            return
        return sorted(fun())

    def get_commands(self):
        return ["/" + name for name in self.get_command_metadata()]

    def do_run(self, cmd_name, args):
        cmd_name = self.resolve_command_name(cmd_name)
        cmd_name = cmd_name.replace("-", "_")
        cmd_method_name = f"cmd_{cmd_name}"
        cmd_method = getattr(self, cmd_method_name, None)
        if not cmd_method:
            self.io.tool_output(f"Error: Command {cmd_name} not found.")
            return

        # Execute pre-command hooks
        hooks = self._get_hooks_manager()
        if hooks:
            try:
                pre_result = hooks.execute("pre_command", cmd_name=cmd_name, args=args, io=self.io)
                # Hooks can modify args via return data
                if pre_result.get("data", {}).get("args") is not None:
                    args = pre_result["data"]["args"]
            except Exception as e:
                if hooks.verbose:
                    self.io.tool_error(f"Hook error (pre_command): {e}")

        try:
            result = cmd_method(args)

            # Execute post-command hooks
            if hooks:
                try:
                    hooks.execute(
                        "post_command", cmd_name=cmd_name, args=args, result=result, io=self.io
                    )
                except Exception as e:
                    if hooks.verbose:
                        self.io.tool_error(f"Hook error (post_command): {e}")

            return result
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete {cmd_name}: {err}")

    def matching_commands(self, inp):
        words = inp.strip().split()
        if not words:
            return

        first_word = words[0]
        rest_inp = inp[len(words[0]) :].strip()
        if not first_word.startswith("/"):
            return

        token = first_word[1:]
        metadata = self.get_command_metadata()
        aliases = {
            alias: target for target, info in metadata.items() for alias in info.get("aliases", [])
        }

        if token in metadata:
            return ["/" + token], first_word, rest_inp, token

        if token in aliases:
            canonical = aliases[token]
            return ["/" + canonical], first_word, rest_inp, canonical

        candidates = list(metadata)
        candidates.extend(aliases)
        matches = []
        for name in candidates:
            if name.startswith(token):
                canonical = aliases.get(name, name)
                cmd = "/" + canonical
                if cmd not in matches:
                    matches.append(cmd)

        return matches, first_word, rest_inp, None

    def format_command_summary(self, cmd):
        name = cmd[1:]
        metadata = self.get_command_metadata().get(name, {})
        description = metadata.get("description") or "No description available."
        aliases = metadata.get("aliases") or []
        alias_text = f" (aliases: {', '.join('/' + alias for alias in aliases)})" if aliases else ""
        return f"{cmd}{alias_text}: {description}"

    def show_command_usage(self, command_name, error=None):
        canonical = self.resolve_command_name(command_name.lstrip("/"))
        metadata = self.get_command_metadata().get(canonical, {})
        usage = metadata.get("usage")
        if error:
            self.io.tool_error(error)
        if usage:
            self.io.tool_output(f"Usage: {usage}")

    def run(self, inp):
        if inp.startswith("!"):
            self.coder.event("command_run")
            return self.do_run("run", inp[1:])

        res = self.matching_commands(inp)
        if res is None:
            return
        matching_commands, first_word, rest_inp, exact_canonical = res
        if exact_canonical:
            self.coder.event(f"command_{exact_canonical}")
            return self.do_run(exact_canonical, rest_inp)
        if len(matching_commands) == 1:
            command = matching_commands[0][1:]
            self.coder.event(f"command_{command}")
            return self.do_run(command, rest_inp)
        elif first_word in matching_commands:
            command = first_word[1:]
            self.coder.event(f"command_{command}")
            return self.do_run(command, rest_inp)
        elif len(matching_commands) > 1:
            self.io.tool_error(f"Ambiguous command: {first_word}")
            for cmd in matching_commands:
                self.io.tool_output("  " + self.format_command_summary(cmd))
        else:
            metadata = self.get_command_metadata()
            known_names = list(metadata)
            known_names.extend(
                alias for info in metadata.values() for alias in info.get("aliases", [])
            )
            suggestions = difflib.get_close_matches(first_word[1:], known_names, n=3, cutoff=0.5)
            self.io.tool_error(f"Invalid command: {first_word}")
            if suggestions:
                rendered = []
                for suggestion in suggestions:
                    canonical = self.command_aliases.get(suggestion, suggestion)
                    rendered.append("/" + canonical)
                rendered = list(dict.fromkeys(rendered))
                self.io.tool_output(f"Did you mean: {', '.join(rendered)}")
            self.io.tool_output("Use /help to see available commands.")

    # any method called cmd_xxx becomes a command automatically.
    # each one must take an args param.


def parse_quoted_filenames(args):
    filenames = re.findall(r"\"(.+?)\"|(\S+)", args)
    filenames = [name for sublist in filenames for name in sublist if name]
    return filenames


def get_help_md():
    md = Commands(None, None).get_help_md()
    return md


def main():
    md = get_help_md()
    print(md)


if __name__ == "__main__":
    status = main()
    sys.exit(status)
