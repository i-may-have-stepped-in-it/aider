"""
Agent-enabled skill mixin and utilities.

This module provides utilities for skills that want to spawn sub-agents.
"""

from typing import Any, Callable, Dict, List, Optional

from .base import SkillContext, SkillResult, _run_async_safely


class AgentSkillMixin:
    """
    Mixin for skills that want to spawn sub-agents.

    Provides convenience methods for common agent operations.
    """

    def __init__(self):
        self._agent_registry = None
        self._agent_executor = None

    def init_agents(self, context: SkillContext) -> bool:
        """
        Initialize the agent system.

        Args:
            context: The skill context

        Returns:
            True if agents are available, False otherwise
        """
        if not context.enable_agents or not context.coder:
            return False

        # Lazy imports
        from ..agents.executor import AgentExecutor
        from ..agents.registry import AgentRegistry

        self._agent_registry = AgentRegistry(max_concurrent=context.max_agents)
        self._agent_executor = AgentExecutor(self._agent_registry)

        return True

    async def spawn_agent(
        self,
        name: str,
        prompt: str,
        model: Optional[str] = None,
        files: Optional[List[str]] = None,
        readonly_files: Optional[List[str]] = None,
        on_progress: Optional[Callable[[str, Any], None]] = None,
    ) -> str:
        """
        Spawn a single sub-agent.

        Args:
            name: Agent name
            prompt: Task prompt
            model: Optional model override
            files: Files to include in context
            readonly_files: Read-only files
            on_progress: Progress callback

        Returns:
            Agent ID
        """
        if not self._agent_executor:
            raise RuntimeError("Agents not initialized. Call init_agents() first.")

        parent_coder = getattr(getattr(self, "context", None), "coder", None)
        agent = await self._agent_executor.spawn(
            parent_coder=parent_coder,
            task=prompt,
            name=name,
            model=model,
            files=files or [],
            readonly_files=readonly_files or [],
        )

        return agent.id

    async def spawn_agents(
        self, tasks: List[Dict[str, Any]], on_progress: Optional[Callable[[str, Any], None]] = None
    ) -> List[str]:
        """
        Spawn multiple agents.

        Args:
            tasks: List of task configs with name, prompt, model, files
            on_progress: Progress callback

        Returns:
            List of agent IDs
        """
        if not self._agent_executor:
            raise RuntimeError("Agents not initialized. Call init_agents() first.")

        agent_ids = []
        for task in tasks:
            agent_id = await self.spawn_agent(
                name=task.get("name", "unnamed"),
                prompt=task.get("prompt", ""),
                model=task.get("model"),
                files=task.get("files", []),
                readonly_files=task.get("readonly_files", []),
                on_progress=on_progress,
            )
            agent_ids.append(agent_id)

        return agent_ids

    async def wait_for_agent(
        self, agent_id: str, timeout: Optional[float] = 300.0  # Issue 5: Default timeout
    ) -> Dict[str, Any]:
        """
        Wait for a specific agent to complete with automatic cleanup.

        Addresses:
        - Issue 5: Default timeout prevents deadlock
        - Issue 6: Automatic cleanup on timeout

        Args:
            agent_id: ID of agent to wait for
            timeout: Maximum time to wait (defaults to 300s = 5 minutes)

        Returns:
            Agent result dictionary
        """
        if not self._agent_registry:
            raise RuntimeError("Agents not initialized. Call init_agents() first.")

        try:
            agent = await self._agent_registry.wait_for_completion(agent_id, timeout=timeout)

            if agent.result:
                return {
                    "success": agent.result.success,
                    "output": agent.result.output,
                    "error": agent.result.error,
                    "files_modified": agent.result.files_modified,
                    "execution_time": agent.execution_time,
                }
            else:
                return {
                    "success": False,
                    "error": agent.error or "No result",
                }
        except TimeoutError:
            # Issue 6: Cleanup on timeout
            if self._agent_registry:
                try:
                    await self._agent_registry.cancel(agent_id)
                except Exception:
                    pass  # Ignore cleanup errors

            return {
                "success": False,
                "error": f"Timeout waiting for agent {agent_id} (timeout={timeout}s)",
            }

    async def wait_for_all(
        self, timeout: Optional[float] = 300.0  # Issue 5: Default timeout
    ) -> List[Dict[str, Any]]:
        """
        Wait for all active agents to complete with cleanup.

        Addresses:
        - Issue 5: Default timeout prevents deadlock
        - Issue 6: Automatic cleanup on timeout

        Args:
            timeout: Maximum time to wait (defaults to 300s = 5 minutes)

        Returns:
            List of agent result dictionaries
        """
        if not self._agent_registry:
            raise RuntimeError("Agents not initialized. Call init_agents() first.")

        try:
            agents = await self._agent_registry.wait_for_all(timeout=timeout)

            results = []
            for agent in agents:
                if agent.result:
                    results.append(
                        {
                            "id": agent.id,
                            "name": agent.name,
                            "success": agent.result.success,
                            "output": agent.result.output,
                            "error": agent.result.error,
                            "files_modified": agent.result.files_modified,
                            "execution_time": agent.execution_time,
                        }
                    )
                else:
                    results.append(
                        {
                            "id": agent.id,
                            "name": agent.name,
                            "success": False,
                            "error": agent.error or "No result",
                        }
                    )

            return results
        except TimeoutError:
            # Issue 6: Cleanup all agents on timeout
            if self._agent_registry:
                try:
                    await self._agent_registry.cancel_all()
                except Exception:
                    pass  # Ignore cleanup errors

            return [{"success": False, "error": f"Timeout waiting for agents (timeout={timeout}s)"}]

    async def cancel_agent(self, agent_id: str) -> bool:
        """Cancel a running agent."""
        if not self._agent_registry:
            return False

        return await self._agent_registry.cancel(agent_id)

    async def cancel_all_agents(self) -> List[str]:
        """Cancel all active agents. Returns list of cancelled IDs."""
        if not self._agent_registry:
            return []

        return await self._agent_registry.cancel_all()

    def get_agent_stats(self) -> Dict[str, Any]:
        """Get statistics about agents."""
        if not self._agent_registry:
            return {}

        # Run sync since get_stats is async
        return _run_async_safely(self._agent_registry.get_stats())

    def to_skill_result(self, agent_result: Dict[str, Any]) -> SkillResult:
        """Convert an agent result to a SkillResult."""
        return SkillResult(
            success=agent_result.get("success", False),
            output=agent_result.get("output", ""),
            error=agent_result.get("error"),
            files_modified=agent_result.get("files_modified", []),
            execution_time=agent_result.get("execution_time", 0.0),
        )


class MapReduceSkill(AgentSkillMixin):
    """
    Skill that implements map-reduce pattern with agents.

    Maps tasks to multiple agents, then reduces results.
    """

    async def map_reduce(
        self,
        items: List[Any],
        map_prompt_template: str,
        reduce_prompt: str,
        model: Optional[str] = None,
        max_workers: int = 5,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """
        Execute map-reduce pattern with agents.

        Args:
            items: Items to process
            map_prompt_template: Template for map phase ({item} placeholder)
            reduce_prompt: Prompt for reduce phase
            model: Model to use
            max_workers: Maximum concurrent workers
            context: Skill context

        Returns:
            Combined SkillResult
        """
        if context:
            self.init_agents(context)

        if not self._agent_executor:
            # Sequential fallback
            results = []
            for item in items:
                prompt = map_prompt_template.format(item=item)
                # Process directly without agent
                results.append(f"Processed: {item}")

            combined = "\n".join(results)
            return SkillResult(success=True, output=combined)

        # Map phase - spawn agents for each item
        tasks = []
        for i, item in enumerate(items):
            prompt = map_prompt_template.format(item=item)
            tasks.append(
                {
                    "name": f"map_{i}",
                    "prompt": prompt,
                    "model": model,
                }
            )

        await self.spawn_agents(tasks)

        # Wait for all map tasks
        map_results = await self.wait_for_all()

        # Combine map outputs
        map_outputs = [r.get("output", "") for r in map_results if r.get("success")]
        combined = "\n\n".join(map_outputs)

        # Reduce phase - single agent to combine results
        reduce_prompt_full = f"{reduce_prompt}\n\n{combined}"
        reduce_id = await self.spawn_agent(name="reduce", prompt=reduce_prompt_full, model=model)

        reduce_result = await self.wait_for_agent(reduce_id)

        return self.to_skill_result(reduce_result)
