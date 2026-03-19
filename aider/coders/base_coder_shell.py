from aider.io import ConfirmGroup
from aider.run_cmd import run_cmd


class BaseCoderShellMixin:
    """Suggested shell-command execution helpers."""

    def run_shell_commands(self):
        if not self.suggest_shell_commands:
            return ""

        done = set()
        group = ConfirmGroup(set(self.shell_commands))
        accumulated_output = ""
        for command in self.shell_commands:
            if command in done:
                continue
            done.add(command)
            output = self.handle_shell_commands(command, group)
            if output:
                accumulated_output += output + "\n\n"
        return accumulated_output

    def handle_shell_commands(self, commands_str, group):
        commands = commands_str.strip().splitlines()
        command_count = sum(
            1 for cmd in commands if cmd.strip() and not cmd.strip().startswith("#")
        )
        prompt = "Run shell command?" if command_count == 1 else "Run shell commands?"
        if not self.io.confirm_ask(
            prompt,
            subject="\n".join(commands),
            explicit_yes_required=True,
            group=group,
            allow_never=True,
        ):
            return

        accumulated_output = ""
        for command in commands:
            command = command.strip()
            if not command or command.startswith("#"):
                continue

            self.io.tool_output()
            self.io.tool_output(f"Running {command}")
            self.io.add_to_input_history(f"/run {command.strip()}")
            exit_status, output = run_cmd(command, error_print=self.io.tool_error, cwd=self.root)
            if output:
                accumulated_output += f"Output from {command}\n{output}\n"

        if accumulated_output.strip() and self.io.confirm_ask(
            "Add command output to the chat?", allow_never=True
        ):
            num_lines = len(accumulated_output.strip().splitlines())
            line_plural = "line" if num_lines == 1 else "lines"
            self.io.tool_output(f"Added {num_lines} {line_plural} of output to the chat.")
            return accumulated_output
