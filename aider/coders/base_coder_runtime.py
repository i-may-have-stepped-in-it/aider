class BaseCoderRuntimeMixin:
    """Runtime ownership and session service synchronization helpers."""

    def run_autonomous_task(self, instruction, test_command=None, max_turns=5, max_cost=2.0):
        """Run an autonomous task through the session-owned agent service."""
        return self.agent_service.run_autonomous_task(
            self,
            instruction,
            test_command=test_command,
            max_turns=max_turns,
            max_cost=max_cost,
        )

    def _sync_runtime_services(self):
        """Refresh runtime-owned service references on the coder."""
        if getattr(self.runtime, "io", None) is not None:
            self.io = self.runtime.io
            self.pretty = self.io.pretty
            if hasattr(self, "commands") and self.commands is not None:
                self.commands.io = self.io
            if hasattr(self, "tool_router") and self.tool_router is not None:
                self.tool_router.io = self.io

        if getattr(self.runtime, "analytics", None) is not None:
            self.analytics = self.runtime.analytics
            self.event = self.analytics.event

        self.a2a_bus = self.runtime.a2a_bus
        self.skills_registry = self.runtime.skill_registry
        self.agent_service = self.runtime.agent_service
        self.agent_registry = self.runtime.agent_registry
        self.hooks_manager = self.runtime.hooks_manager
        if hasattr(self, "commands") and self.commands is not None:
            self.commands.runtime = self.runtime
            self.commands.coder = self
            self.commands.sync_cached_helpers()
        if hasattr(self, "tool_router") and self.tool_router is not None:
            self.tool_router.commands = self.commands
            self.tool_router.coder = self
        self.autonomous_agent = self.agent_service.create_autonomous_agent(
            self, max_turns=5, max_cost=2.0
        )

    def setup_lint_cmds(self, lint_cmds):
        if not lint_cmds:
            return
        for lang, cmd in lint_cmds.items():
            self.linter.set_linter(lang, cmd)

    def show_announcements(self):
        bold = True
        for line in self.get_announcements():
            self.io.tool_output(line, bold=bold)
            bold = False

    def _get_hooks_manager(self):
        """Get hooks manager from the bound coder/runtime before compatibility fallback."""
        if getattr(self, "hooks_manager", None):
            return self.hooks_manager
        if self.runtime and self.runtime.hooks_manager:
            return self.runtime.hooks_manager
        from aider.hooks import get_hooks_manager

        return get_hooks_manager()
