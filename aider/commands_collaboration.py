import re

from aider.async_utils import run_async_safely


_run_async_safely = run_async_safely


class CollaborationCommandsMixin:
    """Collaboration, agenting, and integration command handlers."""

    def _get_skill_command(self):
        from aider.skills.command import SkillsCommand

        if self._skill_command is None:
            self._skill_command = SkillsCommand(
                io=self.io,
                coder=self.coder,
                commands=self,
                verbose=self.verbose,
            )
        else:
            self._skill_command.io = self.io
            self._skill_command.coder = self.coder
            self._skill_command.commands = self
            self._skill_command.verbose = self.verbose

        return self._skill_command

    def _get_agent_commands(self):
        from aider.agents.commands import AgentCommands

        if self._agent_commands is None:
            self._agent_commands = AgentCommands(self)
        return self._agent_commands

    def _get_a2a_commands(self):
        from aider.a2a.commands import A2ACommands

        if self._a2a_commands is None:
            self._a2a_commands = A2ACommands(self)
        return self._a2a_commands

    def cmd_auto(self, args):
        """Execute a task autonomously using the Architect workflow.

        This uses the full ArchitectCoder with:
        - Librarian phase: Auto-discovers relevant files
        - Architect phase: Plans with tool access
        - Reviewer phase: Self-critiques the plan
        - Editor phase: Executes with proper formatting
        - Self-correction: Retries on test failures

        Provides parity with Claude Code, Codex, and Gemini.

        Usage: /auto "task description" [--test "test command"]
        """
        from aider.coders.base_coder import Coder
        from aider.commands import SwitchCoder

        task = None
        test_cmd = None

        test_match = re.search(r'--test\s+"([^"]+)"', args)
        if test_match:
            test_cmd = test_match.group(1)
            args = re.sub(r'--test\s+"[^"]+"', "", args)
        elif test_match := re.search(r"--test\s+'([^']+)'", args):
            test_cmd = test_match.group(1)
            args = re.sub(r"--test\s+'[^']+'", "", args)

        task = args.strip().strip('"').strip("'")

        if not task:
            self.io.tool_output('Usage: /auto "task description" [--test "test command"]')
            return

        self.io.tool_output("Starting autonomous Architect workflow")
        self.io.tool_output(f"Task: {task}")
        if test_cmd:
            self.io.tool_output(f"Test: {test_cmd}")

        architect_kwargs = dict(
            io=self.io,
            from_coder=self.coder,
            edit_format="architect",
            summarize_from_coder=False,
            auto_test=bool(test_cmd),
            test_cmd=test_cmd,
        )

        if test_cmd:
            architect_kwargs["auto_accept_architect"] = True

        architect = Coder.create(**architect_kwargs)
        architect.run(with_message=task)

        raise SwitchCoder(
            edit_format=self.coder.edit_format,
            summarize_from_coder=False,
            from_coder=architect,
        )

    def cmd_swarm(self, args):
        """Solve a task using a collaborative swarm of agents.
        Usage: /swarm "task description" [--agents "architect,developer,reviewer"]
        """
        from aider.skills.base import SkillContext

        task = None
        agents_list = ["Architect", "Developer", "Reviewer"]

        agents_match = re.search(r'--agents\s+"([^"]+)"', args)
        if agents_match:
            agents_list = [a.strip() for a in agents_match.group(1).split(",")]
            args = re.sub(r'--agents\s+"[^"]+"', "", args)

        task = args.strip().strip('"').strip("'")

        if not task:
            self.io.tool_output('Usage: /swarm "task description" [--agents "arch,dev,test"]')
            return

        context = SkillContext(
            coder=self.coder,
            io=self.io,
            verbose=self.verbose,
        )
        swarm_skill = self.skills_registry.create("swarm", context)
        if swarm_skill:
            _run_async_safely(swarm_skill.execute(task=task, agents=agents_list))

    def cmd_watch(self, args):
        """Monitor background processes or toggle background auto-fix.
        Usage:
            /watch start <name> <cmd>    Start a background process
            /watch read <name> [lines]   Read the latest output
            /watch input <name> <text>   Send input to stdin
            /watch list                  List monitored processes
            /watch stop <name>           Stop a process
            /watch fix-on-save [on/off]  Toggle auto-fix on file save
        """
        args = args.strip()
        if not args:
            self.io.tool_output(
                "Use '/watch start', '/watch read', '/watch list', or '/watch fix-on-save'"
            )
            return

        if args.startswith("fix-on-save"):
            if not self.io.file_watcher:
                self.io.tool_error("File watcher not available.")
                return

            sub = args[11:].strip()
            if sub == "on":
                self.io.file_watcher.fix_on_save = True
            elif sub == "off":
                self.io.file_watcher.fix_on_save = False
            else:
                self.io.file_watcher.fix_on_save = not self.io.file_watcher.fix_on_save

            status = "Enabled" if self.io.file_watcher.fix_on_save else "Disabled"
            self.io.tool_output(f"Background auto-fix on save: {status}")
            return

        tool_router = getattr(self.coder, "tool_router", None)
        if not tool_router or not hasattr(tool_router, "terminal_watcher"):
            self.io.tool_error("Terminal watching not available in this coder mode.")
            return

        watcher = self.coder.tool_router.terminal_watcher

        if args.startswith("start "):
            parts = args[6:].split(None, 1)
            if len(parts) < 2:
                self.io.tool_error("Usage: /watch start <name> <cmd>")
                return
            name, cmd = parts
            if watcher.start_process(name, cmd, self.coder.root):
                self.io.tool_output(f"Started background process '{name}': {cmd}")
            else:
                self.io.tool_error(f"Failed to start process '{name}'")

        elif args.startswith("read "):
            parts = args[5:].split()
            name = parts[0]
            lines = int(parts[1]) if len(parts) > 1 else 50
            logs = watcher.get_logs(name, lines)
            self.io.tool_output(f"--- Logs for '{name}' ---")
            self.io.tool_output("\n".join(logs))
            self.io.tool_output("--- End of logs ---")

        elif args.startswith("input "):
            parts = args[6:].split(None, 1)
            if len(parts) < 2:
                self.io.tool_error("Usage: /watch input <name> <text>")
                return
            name, text = parts
            if watcher.send_input(name, text):
                self.io.tool_output(f"Sent input to '{name}'.")
            else:
                self.io.tool_error(f"Failed to send input to '{name}' (is it running?)")

        elif args.startswith("signal "):
            parts = args[7:].split()
            if len(parts) < 2:
                self.io.tool_error("Usage: /watch signal <name> <signal_number>")
                return
            name, sig = parts
            if watcher.send_signal(name, int(sig)):
                self.io.tool_output(f"Sent signal {sig} to '{name}'.")
            else:
                self.io.tool_error(f"Failed to send signal to '{name}' (is it running?)")

        elif args == "list":
            if not watcher.processes:
                self.io.tool_output("No active background processes.")
                return
            for name, proc in watcher.processes.items():
                status = "Running" if proc.running else "Stopped"
                self.io.tool_output(f"- {name}: {status} ({' '.join(proc.command)})")

        elif args.startswith("stop "):
            name = args[5:].strip()
            watcher.stop_process(name)
            self.io.tool_output(f"Stopped process '{name}'.")
        else:
            self.io.tool_error(f"Unknown watch action: {args}")

    def cmd_skill(self, args):
        """
        Execute OpenClaw skills with optional agent support.

        Usage:
            /skill list [--agents]           List available skills
            /skill run <skill> [options]     Run a skill
            /skill info <skill>              Show skill information
            /skill search <query>            Search for skills
        """
        return self._get_skill_command().cmd_skill(args)

    def completions_skill(self):
        """Provide completions for the /skill command."""
        return self._get_skill_command().completions_skill()

    def cmd_agent(self, args):
        """Manage sub-agents for parallel task execution."""
        return self._get_agent_commands().cmd_agent(args)

    def completions_agent(self, document, complete_event):
        """Provide completions for the /agent command."""
        return self._get_agent_commands().completions_agent(document, complete_event)

    def cmd_a2a(self, args):
        """Manage agent-to-agent communication."""
        return self._get_a2a_commands().cmd_a2a(args)

    def completions_a2a(self, document, complete_event):
        """Provide completions for the /a2a command."""
        return self._get_a2a_commands().completions_a2a(document, complete_event)
