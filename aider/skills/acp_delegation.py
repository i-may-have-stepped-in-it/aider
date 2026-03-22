"""
ACP Delegation Skill - Delegate tasks to other ACP agents.

Allows Aider to spawn and coordinate with other ACP agents (Claude, Codex, etc.)
as sub-agents for specialized tasks.
"""

import asyncio
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from .base import Skill, SkillContext, SkillResult
from .agent_skill import AgentSkillMixin


@dataclass
class ACPAgentConfig:
    """Configuration for an ACP agent."""
    name: str
    command: str
    description: str
    supports_oneshot: bool = True
    supports_session: bool = True


# ACP agent configurations
ACP_AGENTS = {
    "claude": ACPAgentConfig(
        name="claude",
        command="npx -y @zed-industries/claude-agent-acp",
        description="Claude Code - Best for complex reasoning and careful analysis",
        supports_oneshot=True,
        supports_session=True,
    ),
    "codex": ACPAgentConfig(
        name="codex",
        command="npx @zed-industries/codex-acp",
        description="OpenAI Codex - Best for OpenAI models and API integration",
        supports_oneshot=True,
        supports_session=True,
    ),
    "gemini": ACPAgentConfig(
        name="gemini",
        command="gemini --experimental-acp",
        description="Gemini CLI - Best for Google AI models",
        supports_oneshot=True,
        supports_session=True,
    ),
    "kimi": ACPAgentConfig(
        name="kimi",
        command="kimi acp",
        description="Kimi CLI - Best for Moonshot AI models",
        supports_oneshot=True,
        supports_session=True,
    ),
    "pi": ACPAgentConfig(
        name="pi",
        command="npx pi-acp",
        description="Pi Coding Agent - Lightweight agent for quick tasks",
        supports_oneshot=True,
        supports_session=True,
    ),
}


class ACPDelegationSkill(Skill, AgentSkillMixin):
    """
    Skill for delegating tasks to other ACP agents.
    
    Allows Aider to coordinate with Claude, Codex, Gemini, Kimi, and Pi
    as sub-agents for specialized tasks.
    """
    
    name = "acp-delegate"
    description = "Delegate tasks to other ACP agents (Claude, Codex, Gemini, Kimi, Pi)"
    supports_agents = True
    
    def get_parameters(self) -> Dict[str, Any]:
        return {
            "agent": {
                "type": "string",
                "enum": list(ACP_AGENTS.keys()),
                "description": "ACP agent to delegate to (claude, codex, gemini, kimi, pi)",
            },
            "task": {
                "type": "string",
                "description": "Task description for the agent",
            },
            "mode": {
                "type": "string",
                "enum": ["oneshot", "session"],
                "default": "oneshot",
                "description": "Execution mode: oneshot for single task, session for multi-turn",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Files to include in context",
            },
            "timeout": {
                "type": "number",
                "default": 300,
                "description": "Timeout in seconds",
            },
        }
    
    async def execute(self, **kwargs) -> SkillResult:
        """Execute task delegation to an ACP agent."""
        agent_name = kwargs.get("agent", "claude")
        task = kwargs.get("task", "")
        mode = kwargs.get("mode", "oneshot")
        files = kwargs.get("files", [])
        timeout = kwargs.get("timeout", 300)
        
        if agent_name not in ACP_AGENTS:
            return SkillResult(
                success=False,
                error=f"Unknown ACP agent: {agent_name}. Available: {list(ACP_AGENTS.keys())}",
            )
        
        agent_config = ACP_AGENTS[agent_name]
        
        if mode == "oneshot":
            return await asyncio.to_thread(
                self._execute_oneshot, self.context, agent_config, task, files, timeout
            )
        else:
            return await asyncio.to_thread(
                self._execute_session, self.context, agent_config, task, files, timeout
            )
    
    def _execute_oneshot(
        self,
        context: SkillContext,
        agent_config: ACPAgentConfig,
        task: str,
        files: List[str],
        timeout: float,
    ) -> SkillResult:
        """Execute a oneshot (non-interactive) task with an ACP agent."""
        start_time = time.time()
        
        if context.io and context.verbose:
            context.io.tool_output(f"🔄 Delegating oneshot task to {agent_config.name}...")
            context.io.tool_output(f"   Task: {task[:100]}...")
        
        try:
            # Build command for oneshot execution
            # Use exec mode or similar one-shot capability
            cmd_parts = agent_config.command.split()
            
            # Add task as argument (varies by agent)
            if agent_config.name == "codex":
                cmd_parts.extend(["exec", task])
            elif agent_config.name == "claude":
                cmd_parts.extend(["-p", task])  # -p for prompt/print mode
            else:
                # Generic: pass task as stdin or append
                cmd_parts.append(task)
            
            # Add files to context if specified
            if files:
                # Create a temp context file or pass as arguments
                file_list = " ".join(files)
                if context.io and context.verbose:
                    context.io.tool_output(f"   Files: {file_list}")
            
            # Execute with timeout
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=context.args.get("cwd") if context.args else None,
            )
            
            execution_time = time.time() - start_time
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if context.io and context.verbose:
                    context.io.tool_output(f"✅ {agent_config.name} completed in {execution_time:.1f}s")
                
                return SkillResult(
                    success=True,
                    output=output,
                    execution_time=execution_time,
                    data={
                        "agent": agent_config.name,
                        "mode": "oneshot",
                        "task": task,
                    },
                )
            else:
                error_msg = result.stderr.strip() or result.stdout.strip()
                if context.io:
                    context.io.tool_error(f"❌ {agent_config.name} failed: {error_msg}")
                
                return SkillResult(
                    success=False,
                    error=error_msg,
                    output=result.stdout.strip(),
                    execution_time=execution_time,
                )
                
        except subprocess.TimeoutExpired:
            if context.io:
                context.io.tool_error(f"⏱️ {agent_config.name} timed out after {timeout}s")
            return SkillResult(
                success=False,
                error=f"Timeout after {timeout} seconds",
                execution_time=timeout,
            )
        except Exception as e:
            if context.io:
                context.io.tool_error(f"❌ Error delegating to {agent_config.name}: {e}")
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )
    
    def _execute_session(
        self,
        context: SkillContext,
        agent_config: ACPAgentConfig,
        task: str,
        files: List[str],
        timeout: float,
    ) -> SkillResult:
        """Execute a session-based (multi-turn) task with an ACP agent."""
        start_time = time.time()
        
        if context.io:
            context.io.tool_output(f"🔄 Starting ACP session with {agent_config.name}...")
            context.io.tool_output(f"   Note: Session mode requires ACP runtime support")
        
        # For now, session mode falls back to oneshot
        # Full session support would require ACP protocol implementation
        if context.io:
            context.io.tool_output(f"   (Falling back to oneshot mode)")
        
        return self._execute_oneshot(context, agent_config, task, files, timeout)
    
    async def execute_with_agents(self, **kwargs) -> SkillResult:
        """Execute with parallel agent support for multi-agent coordination."""
        agents = kwargs.get("agents", ["claude"])  # List of agents to use
        task = kwargs.get("task", "")
        strategy = kwargs.get("strategy", "round_robin")  # round_robin, parallel, consensus
        
        if strategy == "parallel":
            return await asyncio.to_thread(
                self._execute_parallel, self.context, agents, task, kwargs
            )
        else:
            # Default to first agent
            return await self.execute(agent=agents[0], task=task, **kwargs)
    
    def _execute_parallel(
        self,
        context: SkillContext,
        agents: List[str],
        task: str,
        kwargs: Dict[str, Any],
    ) -> SkillResult:
        """Execute task with multiple ACP agents in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        if context.io:
            context.io.tool_output(f"🔄 Delegating to {len(agents)} ACP agents in parallel...")
        
        results = []
        
        with ThreadPoolExecutor(max_workers=len(agents)) as executor:
            futures = {}
            for agent_name in agents:
                future = executor.submit(
                    self.run,
                    agent=agent_name,
                    task=task,
                    **{k: v for k, v in kwargs.items() if k not in ["agents", "strategy"]},
                )
                futures[future] = agent_name
            
            for future in as_completed(futures):
                agent_name = futures[future]
                try:
                    result = future.result()
                    results.append({
                        "agent": agent_name,
                        "success": result.success,
                        "output": result.output,
                        "error": result.error,
                    })
                    if context.io:
                        status = "✅" if result.success else "❌"
                        context.io.tool_output(f"   {status} {agent_name} completed")
                except Exception as e:
                    results.append({
                        "agent": agent_name,
                        "success": False,
                        "error": str(e),
                    })
                    if context.io:
                        context.io.tool_output(f"   ❌ {agent_name} failed: {e}")
        
        # Aggregate results
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        
        aggregated_output = "\n\n".join([
            f"### {r['agent']}\n{r['output'][:500]}"
            for r in successful
        ])
        
        return SkillResult(
            success=len(failed) == 0,
            output=aggregated_output,
            error=f"Failed agents: {[r['agent'] for r in failed]}" if failed else None,
            data={
                "results": results,
                "successful_count": len(successful),
                "failed_count": len(failed),
            },
            agent_results=results,
        )


class ACPOneshotSkill(Skill):
    """
    Quick oneshot skill for simple ACP agent calls.
    
    Usage: /skill run acp-oneshot agent=codex task="fix this bug"
    """
    
    name = "acp-oneshot"
    description = "Quick oneshot call to ACP agents (no session persistence)"
    supports_agents = False
    
    def get_parameters(self) -> Dict[str, Any]:
        return {
            "agent": {
                "type": "string",
                "enum": list(ACP_AGENTS.keys()),
                "description": "ACP agent to call",
            },
            "task": {
                "type": "string",
                "description": "Task to execute",
            },
            "timeout": {
                "type": "number",
                "default": 120,
                "description": "Timeout in seconds",
            },
        }
    
    async def execute(self, **kwargs) -> SkillResult:
        """Execute a quick oneshot call."""
        # Delegate to main skill
        main_skill = ACPDelegationSkill(self.context)

        return await main_skill.execute(mode="oneshot", **kwargs)


class ACPCoordinationSkill(Skill, AgentSkillMixin):
    """
    Coordinate multiple ACP agents for complex tasks.
    
    Uses multiple ACP agents with different strategies:
    - round_robin: Each agent takes a turn
    - parallel: All agents work simultaneously
    - consensus: Agents must agree on solution
    """
    
    name = "acp-coordinate"
    description = "Coordinate multiple ACP agents (Claude + Codex + Gemini) for complex tasks"
    supports_agents = True
    
    def get_parameters(self) -> Dict[str, Any]:
        return {
            "task": {
                "type": "string",
                "description": "Complex task requiring multiple perspectives",
            },
            "agents": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["claude", "codex"],
                "description": "List of agents to coordinate",
            },
            "strategy": {
                "type": "string",
                "enum": ["parallel", "round_robin", "consensus"],
                "default": "parallel",
                "description": "Coordination strategy",
            },
            "timeout": {
                "type": "number",
                "default": 300,
                "description": "Timeout per agent in seconds",
            },
        }
    
    async def execute(self, **kwargs) -> SkillResult:
        """Execute coordinated multi-agent task."""
        main_skill = ACPDelegationSkill(self.context)

        return await main_skill.execute_with_agents(**kwargs)
