"""
Agent executor for spawning and running sub-agents.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .cli_agent import is_cli_model
from .gateway import configure_gateway
from .governor import get_governor

if TYPE_CHECKING:
    from aider.coders.base_coder import Coder

    from .agent import AgentResult, SubAgent
    from .registry import AgentRegistry

logger = logging.getLogger(__name__)


class AgentExecutor:
    """
    Executes sub-agents in isolated contexts.

    Similar to kimi-cli's Task tool but integrated with Aider's Coder system.
    """

    def __init__(self, registry: AgentRegistry, io: Optional[object] = None):
        self.registry = registry
        self.io = io

    async def spawn(
        self,
        parent_coder: Coder,
        task: str,
        name: Optional[str] = None,
        model: Optional[str] = None,
        edit_format: Optional[str] = None,
        files: Optional[list[str]] = None,
        readonly_files: Optional[list[str]] = None,
        depth: int = 1,
    ) -> SubAgent:
        """
        Spawn a new sub-agent for a task with safety governance.
        """
        import uuid

        from .agent import AgentStatus, SubAgent

        governor = get_governor()
        agent_id = str(uuid.uuid4())[:8]

        # Safety Check
        if not governor.check_safety(agent_id, depth):
            raise RuntimeError(
                f"Mission Governor blocked agent spawning at depth {depth} due to safety limits."
            )

        # Check if this is a CLI model (preserves existing routing)
        if is_cli_model(model or parent_coder.main_model.name):
            # CLI path - create regular agent, don't wrap in A2AEnabledAgent
            # CLI agents have their own communication mechanism
            agent = SubAgent(
                id=agent_id,
                name=name or f"agent-{agent_id}",
                task=task,
                status=AgentStatus.PENDING,
                model=model or parent_coder.main_model.name,
                edit_format=edit_format or parent_coder.edit_format,
                files=files or [],
                readonly_files=readonly_files or [],
            )
        else:
            # Regular path - create A2A-enabled agent
            from ..a2a.agent import A2AEnabledAgent

            agent = A2AEnabledAgent(
                id=agent_id,
                name=name or f"agent-{agent_id}",
                task=task,
                status=AgentStatus.PENDING,
                model=model or parent_coder.main_model.name,
                edit_format=edit_format or parent_coder.edit_format,
                files=files or [],
                readonly_files=readonly_files or [],
                a2a_bus=self.registry.a2a_bus,  # Always provided
            )

        await self.registry.register(agent)
        governor.register_agent(agent_id, depth)

        # Start execution in background
        task_obj = asyncio.create_task(
            self._run_agent(agent, parent_coder),
            name=f"agent-{agent_id}",
        )
        agent._task = task_obj

        return agent

    async def spawn_and_run(self, parent_coder: Coder, task: str, **kwargs) -> AgentResult:
        """Helper to spawn and immediately wait for an agent."""
        agent = await self.spawn(parent_coder, task, **kwargs)
        # Record the turn in the governor
        get_governor().record_turn()
        return await agent.wait_for_completion()

    async def spawn_parallel(
        self, parent_coder: Coder, subtasks: List[Dict[str, Any]], **kwargs
    ) -> List[AgentResult]:
        """
        Execute multiple subtasks in parallel.
        Handles partial failures gracefully.
        """
        agents = []
        for subtask in subtasks:
            try:
                agent = await self.spawn(
                    parent_coder=parent_coder,
                    task=subtask["description"],
                    name=subtask["name"],
                    files=subtask.get("relevant_files", []),
                    **kwargs,
                )
                agents.append(agent)
            except Exception as e:
                logger.error(f"Failed to spawn parallel subtask '{subtask['name']}': {e}")

        if not agents:
            return []

        self.io.tool_output(f"Running {len(agents)} parallel sub-missions...")

        # Wait for all agents to complete or fail
        tasks = [agent.wait_for_completion() for agent in agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle exceptions
        final_results = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"Parallel subtask '{agents[i].name}' crashed: {res}")
                final_results.append(
                    AgentResult(
                        success=False, error=str(res), output=f"Task execution crashed: {res}"
                    )
                )
            else:
                final_results.append(res)

        return final_results

    async def _run_agent(
        self,
        agent: SubAgent,
        parent_coder: Coder,
    ) -> None:
        """Run the sub-agent in an isolated context."""
        from ..a2a.agent import A2AEnabledAgent
        from .agent import AgentResult, AgentStatus

        # Acquire slot for concurrent execution
        async with self.registry.acquire_slot():
            agent.status = AgentStatus.RUNNING
            agent.started_at = time.time()

            try:
                # Start A2A agent inside try so stop() runs even if start() fails
                if isinstance(agent, A2AEnabledAgent):
                    await agent.start()  # Starts handshake

                # CLI agents short-circuit the litellm backend entirely
                if is_cli_model(agent.model or ""):
                    result = await self._execute_cli_agent(agent, parent_coder)
                else:
                    # Create isolated coder for sub-agent
                    sub_coder = await self._create_sub_coder(agent, parent_coder)
                    agent.coder = sub_coder

                    # Run the task
                    agent.update_progress("Starting task execution...")

                    # Execute task in the sub-coder
                    result = await self._execute_task(sub_coder, agent.task)

                agent.result = result
                agent.status = AgentStatus.COMPLETED if result.success else AgentStatus.ERROR
                agent.error = result.error

            except asyncio.CancelledError:
                agent.status = AgentStatus.CANCELLED
                agent.error = "Agent was cancelled"
                raise

            except Exception as e:
                logger.exception(f"Agent {agent.id} failed")
                agent.status = AgentStatus.ERROR
                agent.error = str(e)
                agent.result = AgentResult(
                    success=False,
                    error=str(e),
                    output=traceback.format_exc(),
                )

            finally:
                agent.completed_at = time.time()
                # Cleanup A2A agent
                if isinstance(agent, A2AEnabledAgent):
                    await agent.stop()  # Unregisters from bus and cancels pending futures
                if agent.coder:
                    # Cleanup sub-coder
                    pass

    async def _create_sub_coder(
        self,
        agent: SubAgent,
        parent_coder: Coder,
    ) -> Coder:
        """Create an isolated coder for the sub-agent."""
        from aider.coders import Coder
        from aider.models import Model

        # Determine model name - use agent's model or parent's
        # For OpenClaw gateway, we can use tier prefixes like @intel, @speed, @uncen
        model_name = agent.model or parent_coder.main_model.name

        # Ensure we're using the OpenClaw gateway
        # This routes through http://127.0.0.1:18789/v1
        configure_gateway()

        # Convert model name for gateway if needed
        # Supports tier prefixes like @intel, @speed, @uncen
        if model_name.startswith("@"):
            gateway_model = model_name
        elif model_name in ("chat", "default"):
            gateway_model = "chat"
        else:
            # Pass through specific model names - gateway handles routing
            gateway_model = model_name

        # Create model for sub-agent
        model = Model(gateway_model)

        # Create fresh IO for isolation
        io = parent_coder.io

        # Use ToolEnabledCoderV2 for sub-agents if parent is using it
        from aider.coders.tool_coder_v2 import ToolEnabledCoderV2

        coder_class = Coder
        if isinstance(parent_coder, ToolEnabledCoderV2):
            coder_class = ToolEnabledCoderV2

        # Create coder with isolated context
        sub_coder = coder_class.create(
            main_model=model,
            edit_format=agent.edit_format or parent_coder.edit_format,
            io=io,
            repo=parent_coder.repo,  # Share repo for file access
            fnames=agent.files,
            read_only_fnames=agent.readonly_files,
            map_tokens=parent_coder.map_tokens,
            verbose=parent_coder.verbose,
            # Don't inherit parent's conversation history
            from_coder=None,
            system_prompt_override=parent_coder.system_prompt_override,
        )

        # Share global stateful managers from parent to sub-agent if both are
        # ToolEnabledCoderV2
        if hasattr(parent_coder, "tool_router") and hasattr(sub_coder, "tool_router"):
            # Share the MCP Manager so agents can see the same external tools
            if hasattr(parent_coder.tool_router, "mcp_manager"):
                sub_coder.tool_router.mcp_manager = parent_coder.tool_router.mcp_manager
            # Share the Terminal Watcher so agents can interact with the same background processes
            if hasattr(parent_coder.tool_router, "terminal_watcher"):
                sub_coder.tool_router.terminal_watcher = parent_coder.tool_router.terminal_watcher

        # Add task as system message with persona if available
        persona_prompt = f"You are a sub-agent working on: {agent.task}"

        if agent.name:
            name = agent.name.lower()
            if "librarian" in name or "discovery" in name:
                from aider.coders.librarian_prompts import LibrarianPrompts

                persona_prompt = LibrarianPrompts().main_system
            elif "investigator" in name or "explorer" in name or "research" in name:
                from aider.coders.investigator_prompts import InvestigatorPrompts

                persona_prompt = InvestigatorPrompts().main_system
            elif "reviewer" in name or "audit" in name:
                from aider.coders.reviewer_prompts import ReviewerPrompts

                persona_prompt = ReviewerPrompts().main_system

        sub_coder.cur_messages.append(
            {
                "role": "system",
                "content": (
                    f"{persona_prompt}\n\nTask: {agent.task}\n\n"
                    "Complete this task and return your results. "
                    "Be concise and focus only on the assigned task."
                ),
            }
        )

        return sub_coder

    async def _execute_task(
        self,
        coder: Coder,
        task: str,
    ) -> AgentResult:
        """Execute the task in the sub-coder."""
        from .agent import AgentResult

        start_time = time.time()

        try:
            # Run the coder in a thread executor to avoid blocking the event loop.
            # coder.run() makes blocking LLM API calls (30-120s) — running it
            # directly in async context would stall all concurrent sub-agents.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: coder.run(with_message=task))

            # Collect results
            files_modified = list(coder.affected_files) if hasattr(coder, "affected_files") else []

            # Get the last assistant message as output
            output = ""
            for msg in reversed(coder.cur_messages):
                if msg.get("role") == "assistant":
                    output = msg.get("content", "")
                    break

            # Get token usage if available
            token_usage = {}
            if hasattr(coder, "total_cost") and coder.total_cost:
                token_usage["cost"] = coder.total_cost

            execution_time = time.time() - start_time

            return AgentResult(
                success=True,
                output=output,
                files_modified=files_modified,
                token_usage=token_usage,
                execution_time=execution_time,
            )

        except Exception as e:
            return AgentResult(
                success=False,
                error=str(e),
                output=traceback.format_exc(),
                execution_time=time.time() - start_time,
            )

    async def _execute_cli_agent(
        self,
        agent: SubAgent,
        parent_coder: Coder,
    ) -> AgentResult:
        """
        Execute a task via a native CLI tool (gemini, claude, codex, kimi).

        Used when agent.model starts with 'cli:' or is a known CLI alias.
        The prompt is built from agent.task; file context is prepended when
        agent.files is non-empty.
        """
        from .agent import AgentResult
        from .cli_agent import CliAgent, CliAgentError, cli_name_from_model

        start_time = time.time()
        cli_name = cli_name_from_model(agent.model or "gemini")
        cwd = getattr(parent_coder, "root", None)

        # Build prompt: prepend file contents for context if any
        prompt = agent.task
        if agent.files:
            file_context_parts = []
            for fpath in agent.files:
                try:
                    with open(fpath) as fh:
                        file_context_parts.append(f"=== {fpath} ===\n{fh.read()}")
                except OSError:
                    pass
            if file_context_parts:
                prompt = "\n\n".join(file_context_parts) + "\n\nTask: " + agent.task

        agent.update_progress(f"Calling {cli_name} CLI...")

        try:
            cli_agent = CliAgent(cli_name)
            output = await asyncio.get_running_loop().run_in_executor(
                None, lambda: cli_agent.run(prompt, cwd=cwd)
            )
            return AgentResult(
                success=True,
                output=output,
                execution_time=time.time() - start_time,
            )
        except CliAgentError as e:
            return AgentResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )

    async def run_sync(
        self,
        agent: SubAgent,
        parent_coder: Coder,
        timeout: Optional[float] = None,
    ) -> AgentResult:
        """
        Run an agent synchronously and wait for completion.

        Args:
            agent: The agent to run
            parent_coder: The parent coder
            timeout: Maximum time to wait

        Returns:
            The agent's result
        """
        await self._run_agent(agent, parent_coder)
        return agent.result
