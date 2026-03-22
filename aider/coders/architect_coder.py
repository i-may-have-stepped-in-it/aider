import asyncio
import logging
import os
from dataclasses import asdict
from pathlib import Path

from ..audit.manager import AuditManager
from ..memory.vector_store import ProjectMemory
from ..security.policy import PolicyEngine
from .architect_prompts import ArchitectPrompts
from .base_coder import Coder
from .coder_factory import create_coder
from .librarian_prompts import LibrarianPrompts
from .reviewer_prompts import ReviewerPrompts
from .tool_coder_v2 import ToolEnabledCoderV2

logger = logging.getLogger(__name__)


class ArchitectCoder(ToolEnabledCoderV2):
    edit_format = "architect"
    gpt_prompts = ArchitectPrompts()
    auto_accept_architect = False
    num_critiques = 0
    max_critiques = 1
    research_done = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy_engine = PolicyEngine()
        self.project_memory = ProjectMemory(root_dir=self.root)
        self.audit_manager = AuditManager(root_dir=self.root)
        # Circuit breaker for recursive critique loops
        self._critique_count = 0
        self._critique_lock = asyncio.Lock()

        # Coordination-only mode (Shift+Tab equivalent)
        # When True, architect can only coordinate, not implement directly
        self.coordination_only = kwargs.get("coordination_only", False)

        # Register self on the A2A bus for autonomous collaboration
        if hasattr(self, "a2a_bus"):
            self.a2a_bus.register("architect", self._on_a2a_message)
            self.a2a_bus.register("system", self._on_system_request)

    def _on_a2a_message(self, message):
        """Handle messages from other agents."""
        pass

    def _on_system_request(self, message, max_retries=3, retry_delay=1.0):
        """
        Handles requests from the Architect to the System for file discovery.
        This provides the 'Autonomous Explorer' capability.
        Includes retry logic for A2A communication failures.

        Args:
            message: The A2A message to process
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Delay between retries in seconds (default: 1.0)
        """
        from aider.a2a.types import A2AResponse

        content = message.content
        if not isinstance(content, dict):
            return

        cmd = content.get("command")
        params = content.get("parameters", {})

        result = None
        if cmd == "find_file":
            pattern = params.get("pattern", "*")
            # Search filesystem autonomously
            found = []
            for path in Path(self.root).rglob(pattern):
                if path.is_file():
                    found.append(str(path.relative_to(self.root)))
            result = {"found": found[:10]}  # Limit to 10 for context safety

        if result is not None:
            response = A2AResponse(success=True, result=result)
            last_error = None

            # Retry logic for A2A communication
            for attempt in range(max_retries):
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    # If no loop in this thread, use the one from the bus if available
                    loop = getattr(self.a2a_bus, "_loop", None)

                if loop and loop.is_running():
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self.a2a_bus.send(message.reply(response, sender_id="system")), loop
                        )
                        # Success - exit retry loop
                        break
                    except Exception as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            # Exponential backoff
                            delay = retry_delay * (2**attempt)
                            logger.warning(
                                f"A2A send failed (attempt {attempt + 1}/{max_retries}): {e}. "
                                f"Retrying in {delay}s..."
                            )
                            import time

                            time.sleep(delay)
                        else:
                            # Final attempt failed
                            logger.error(
                                f"A2A send failed after {max_retries} attempts: {last_error}"
                            )
                else:
                    # Fallback to local execution if loop is not available
                    logger.warning("No event loop available, skipping A2A send")
                    break
            else:
                # All retries failed
                if last_error:
                    logger.error(f"A2A message failed after {max_retries} attempts: {last_error}")

    def _trigger_ui_phase(self, phase: str, status: str = "running"):
        """Notify UI of autonomous phase change."""
        if hasattr(self, "hooks_manager") and self.hooks_manager:
            from aider.hooks_manager import HookPoint

            try:
                self.hooks_manager.trigger(
                    HookPoint.UI_PHASE_UPDATE,
                    phase=phase,
                    status=status,
                    coder=self,
                )
            except Exception as e:
                logger.debug(f"Error triggering UI_PHASE_UPDATE hook: {e}")

    def perform_research(self, user_request):
        """
        PARITY+: Librarian Phase. Find all relevant files before planning.
        """
        self._trigger_ui_phase("Librarian")
        logger.info("Librarian: Identifying relevant project context...")

        # Semantic retrieval from past tasks
        past_context = self.project_memory.get_relevant_past_tasks(user_request)
        if past_context:
            self.io.tool_output("Librarian: Retrieved relevant context from project memory.")
            user_request = f"{past_context}\n\nUser Request: {user_request}"

        self.audit_manager.trace.user_request = user_request

        # Create a temporary coder with the Librarian persona
        # Use the @speed tier for efficient discovery
        librarian_kwargs = dict(
            main_model=self.main_model.weak_model or self.main_model,
            io=self.io,
            from_coder=self,
            edit_format="tool",  # Librarian needs tool access (now V2)
            summarize_from_coder=False,
        )

        librarian = create_coder(**librarian_kwargs)
        librarian.gpt_prompts = LibrarianPrompts()

        research_msg = f"Research Task: Find all files related to this request: '{user_request}'"

        # Run the librarian loop (it will use index_search, find, etc.)
        librarian_output = librarian.run(with_message=research_msg, preproc=False)

        # Extract file paths from the output
        if "FILES:" in librarian_output:
            paths_section = librarian_output.split("FILES:")[1].strip()
            # Split by lines and clean up punctuation/markdown
            lines = paths_section.splitlines()
            added_count = 0
            for line in lines:
                # Clean up the line: remove markdown bullets, backticks, and trailing punctuation
                path = line.strip().lstrip("- ").lstrip("* ").strip("`").rstrip(".,:;")
                if not path:
                    continue

                # Verify it looks like a path and exists in the root
                abs_path = self.abs_root_path(path)
                if os.path.isfile(abs_path):
                    if abs_path not in self.abs_fnames:
                        self.add_rel_fname(path)
                        added_count += 1

            if added_count > 0:
                self.io.tool_output(
                    f"Librarian: Added {added_count} relevant files to chat context."
                )

        self.research_done = True
        self.audit_manager.log_event("librarian_complete", files=list(self.abs_fnames))

    def run(self, with_message=None, preproc=True, **kwargs):
        """
        Override run to ensure research is performed before the plan.
        """
        if with_message:
            self.current_task = with_message

        if with_message and not self.research_done:
            # First turn of a new request: perform research
            if preproc:
                self.perform_research(with_message)

        if not kwargs.get("is_reviewer"):
            self._trigger_ui_phase("Architect")
            self.audit_manager.log_event("architect_start")
            if getattr(self.io, "enable_dashboard", False):
                self.io.show_dashboard()

        try:
            result = super().run(with_message=with_message, preproc=preproc, **kwargs)
            if not kwargs.get("is_reviewer"):
                self.audit_manager.log_event("architect_complete", plan=result)
            return result
        finally:
            if not kwargs.get("is_reviewer") and getattr(self.io, "enable_dashboard", False):
                self.io.hide_dashboard()

    def critique_plan(self, plan):
        """
        Structural Self-Critique: Spawns a reviewer to find flaws in the plan.
        """
        self._trigger_ui_phase("Reviewer")
        logger.debug("Initiating structural self-critique...")

        # Create a temporary coder with the Reviewer persona
        reviewer_kwargs = dict(
            main_model=self.main_model,  # Use the @intel tier
            io=self.io,
            from_coder=self,
            edit_format="ask",  # We just want a response, not a code change
            summarize_from_coder=False,
        )

        reviewer = create_coder(**reviewer_kwargs)
        reviewer.gpt_prompts = ReviewerPrompts()

        # The reviewer sees the user request and the architect's plan
        critique_msg = (
            "Please review the following plan for the user request: "
            f"'{self.cur_messages[0]['content']}'\n\n"
            f"ARCHITECT PLAN:\n{plan}"
        )

        critique = reviewer.run(with_message=critique_msg)
        return critique

    def reply_completed(self):
        # This is called after the Tool Loop in ToolEnabledCoderV2.run() finishes
        # and we have a final plan from the Architect.
        content = self.partial_response_content

        if not content or not content.strip():
            return

        # PARITY+: Structural Self-Critique Loop with Circuit Breaker
        # Check circuit breaker to prevent infinite recursion
        if self._critique_count >= self.max_critiques:
            self.io.tool_warning(
                f"Circuit breaker: Maximum critique iterations ({self.max_critiques}) "
                "reached. Proceeding with current plan."
            )
        elif self.num_critiques < self.max_critiques:
            # Increment both counters for circuit breaker protection
            self.num_critiques += 1
            self._critique_count += 1

            critique = self.critique_plan(content)

            if "PASSED" not in critique.upper():
                self.io.tool_warning("Review found issues, self-correcting...")
                correction_prompt = (
                    "Your plan was reviewed and the following issues were found:\n\n"
                    f"{critique}\n\n"
                    "Please provide a refined plan that addresses all these issues."
                )
                # Loop back to Architect for refinement
                return self.run(with_message=correction_prompt, preproc=False)
            else:
                logger.debug("Structural review: PASSED")
                # Reset circuit breaker on success
                self._critique_count = 0

        # PHASE: Security Scan
        self._trigger_ui_phase("Security Scan")
        logger.debug("Scanning plan for security vulnerabilities...")

        policy_result = self.policy_engine.scan(content)

        self.audit_manager.log_event(
            "security_scan",
            success=policy_result.success,
            violations=[asdict(v) for v in policy_result.violations],
        )

        # Trigger Hook for UI
        if hasattr(self, "hooks_manager") and self.hooks_manager:
            from aider.hooks_manager import HookPoint

            self.hooks_manager.execute_hooks(
                HookPoint.UI_POLICY_CHECK,
                {"result": policy_result},
            )

        if not policy_result.success:
            self.io.tool_error("SECURITY BLOCKER: Potential vulnerabilities detected in the plan.")
            self._trigger_ui_phase("Security Scan", status="failed")

            # If there are critical violations, we must stop unless forced (enterprise safety)
            if policy_result.has_critical:
                self.io.tool_error("Implementation ABORTED due to critical security risks.")
                return

        self._trigger_ui_phase("Security Scan", status="complete")

        # Proceed to Editor Phase
        # COORDINATION-ONLY MODE: Prevent direct implementation
        if self.coordination_only:
            self._trigger_ui_phase("Coordination", status="complete")
            self.io.tool_output(
                "Coordination-only mode: Plan complete. Ready for delegation to specialists."
            )
            self.io.tool_output("To implement, spawn specialist agents using the 'delegate' tool.")
            self.io.tool_output("To disable coordination-only mode, set coordination_only=False")
            return

        if not self.auto_accept_architect and not self.io.confirm_ask("Edit the files?"):
            self._trigger_ui_phase("Architect", status="complete")
            return

        self._trigger_ui_phase("Editor")
        kwargs = dict()

        # Use the editor_model from the main_model if it exists, otherwise use the main_model itself
        editor_model = self.main_model.editor_model or self.main_model

        kwargs["main_model"] = editor_model
        kwargs["edit_format"] = self.main_model.editor_edit_format
        kwargs["suggest_shell_commands"] = False
        kwargs["map_tokens"] = 0
        kwargs["total_cost"] = self.total_cost
        kwargs["cache_prompts"] = False
        kwargs["num_cache_warming_pings"] = 0
        kwargs["summarize_from_coder"] = False

        new_kwargs = dict(io=self.io, from_coder=self)
        new_kwargs.update(kwargs)

        # Inherit review settings for the editor phase
        new_kwargs["review_mode"] = self.review_mode
        new_kwargs["auto_review"] = self.auto_review

        editor_coder = create_coder(**new_kwargs)
        editor_coder.cur_messages = []
        editor_coder.done_messages = []

        if self.verbose:
            editor_coder.show_announcements()

        editor_coder.run(with_message=content)

        self.move_back_cur_messages("I made those changes to the files.")
        self.total_cost = editor_coder.total_cost
        self.aider_commit_hashes = editor_coder.aider_commit_hashes

        # Record implementation in project memory
        self.project_memory.record_decision(
            task=getattr(self, "current_task", None) or content,
            plan=content,
        )

        # PARITY+: Autonomous Recursive Verification with Circuit Breaker
        if self.auto_test and self.test_cmd:
            self.io.tool_output(f"Running tests: {self.test_cmd}")
            # Use the integrated run_command from Coder
            success, output = self.run_shell_command(self.test_cmd)

            if not success:
                # Check circuit breaker to prevent infinite test correction loops
                if self._critique_count >= self.max_critiques:
                    self.io.tool_error(
                        "Circuit breaker: Maximum test correction iterations "
                        f"({self.max_critiques}) reached. Stopping autonomous correction."
                    )
                    self.io.tool_error(f"Test output:\n{output}")
                else:
                    self.io.tool_error("Tests failed! Initiating autonomous self-correction...")
                    self._critique_count += 1

                    # Feed the failure back into the Architect
                    correction_prompt = (
                        "The changes were applied, but the tests failed with the following "
                        f"output:\n\n```\n{output}\n```\n\n"
                        "Please analyze this failure and provide a corrected plan."
                    )
                    # Recurse: Call self.run again with the test failure context
                    return self.run(with_message=correction_prompt, preproc=False)
            else:
                self.io.tool_output("Tests passed! Work verified.")
                # Reset circuit breaker on test success
                self._critique_count = 0

        self._trigger_ui_phase("Architect", status="complete")

        # PARITY+: Proactive Terminal Monitoring
        if hasattr(self, "tool_router") and self.tool_router.terminal_watcher.processes:
            self.io.tool_output("Architect: Monitoring background processes for health...")
            for name, proc in self.tool_router.terminal_watcher.processes.items():
                # Check if process is still running before monitoring
                if not hasattr(proc, "is_running") or not proc.is_running():
                    self.io.tool_warning(
                        f"Proactive Monitor: Background process '{name}' has stopped!"
                    )
                    continue

                try:
                    logs = proc.get_logs(lines=10)
                    # Simple error detection in logs
                    log_text = "\n".join(logs).lower()
                    errors = ["error", "exception", "traceback", "failed", "crash"]
                    if any(err in log_text for err in errors):
                        self.io.tool_warning(
                            "Proactive Monitor: Detected potential issue in background "
                            f"process '{name}'!"
                        )
                        # Feed the logs back into context for a potential proactive fix
                        monitor_prompt = (
                            f"I noticed a potential error in the background process '{name}'. "
                            f"Here are the recent logs:\n\n```\n{log_text}\n```\n\n"
                            "Should we investigate or fix this?"
                        )
                        # This triggers a new autonomous thought turn
                        return self.run(with_message=monitor_prompt)
                except Exception as e:
                    # Handle any errors in log retrieval gracefully
                    logger.warning(f"Failed to retrieve logs for process '{name}': {e}")
                    continue
