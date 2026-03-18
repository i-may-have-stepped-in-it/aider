import asyncio
import uuid
from typing import List, Optional

from ..a2a.bus import A2AMessageBus
from ..agents.executor import AgentExecutor
from ..agents.registry import AgentRegistry
from .base import Skill, SkillContext, SkillResult


class SwarmSkill(Skill):
    """
    Orchestrate a swarm of agents to solve a task collaboratively.
    Parity with AutoGen/OpenDevin swarms.
    """

    # Class-level attributes required by SkillRegistry.register()
    name = "swarm"
    description = "Solve a task using a swarm of collaborating specialized agents."

    def __init__(self, context: Optional[SkillContext] = None):
        super().__init__(context)
        self.bus = A2AMessageBus()
        # AgentExecutor requires a registry; we create one here for swarm use
        self._registry = AgentRegistry()
        self._executor = AgentExecutor(registry=self._registry)

    async def execute(self, task: str, agents: Optional[List[str]] = None) -> SkillResult:
        """
        Run a swarm session.
        Example: agents=['Architect', 'Developer', 'Reviewer']
        """
        if not agents:
            agents = ["Architect", "Developer", "Reviewer"]

        self.output(f"Spawning a swarm of {len(agents)} agents for: {task}")

        # Require a coder in context to build sub-coders
        parent_coder = self.context.coder
        if not parent_coder:
            return SkillResult(success=False, error="SwarmSkill requires a coder in context")

        # 1. Spawn A2AEnabledAgents connected to shared bus
        agent_instances = []
        for agent_name in agents:
            from ..a2a.agent import A2AEnabledAgent
            from ..agents.agent import AgentStatus

            agent = A2AEnabledAgent(
                id=str(uuid.uuid4())[:8],
                name=agent_name,
                task=task,
                status=AgentStatus.PENDING,
                model=parent_coder.main_model.name,
                a2a_bus=self.bus,
            )
            agent_instances.append(agent)

        # 2. Collaborative discussion rounds
        for round_num in range(2):
            self.output(f"\n--- Swarm Discussion Round {round_num + 1} ---")
            discussion_tasks = []
            for agent in agent_instances:
                peer_ids = [a.id for a in agent_instances if a.id != agent.id]
                # Provide sub-coder if not yet assigned
                if not hasattr(agent, "coder") or agent.coder is None:
                    from ..coders.base_coder import Coder

                    agent.coder = Coder.create(
                        main_model=parent_coder.main_model,
                        io=parent_coder.io,
                    )
                discussion_tasks.append(agent.discuss(task, peer_ids, max_rounds=1))
            await asyncio.gather(*discussion_tasks)

        # 3. Execution phase — developer applies consensus
        developer = next(
            (a for a in agent_instances if "Developer" in a.name),
            agent_instances[0],
        )
        self.output(f"\nSwarm consensus reached. {developer.name} is applying the fix...")

        final_history = developer.get_discussion_context()
        developer.coder.run(
            with_message=(
                f"Task: {task}\n\n"
                f"Consensus from swarm discussion:\n{final_history}\n\n"
                "Apply the final code changes."
            )
        )

        return SkillResult(success=True, output="Swarm task completed successfully.")
