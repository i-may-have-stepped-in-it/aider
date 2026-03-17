"""A2A commands for Aider (/a2a send, /a2a request, etc.)"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from aider.commands import Commands
    from aider.coders.base_coder import Coder

logger = logging.getLogger(__name__)


class A2ACommands:
    """
    Commands for agent-to-agent communication.
    
    Adds:
    - /a2a send <agent-id> <message>
    - /a2a request <agent-id> <capability> [args...]
    - /a2a broadcast <message>
    - /a2a delegate <agent-id> <task>
    - /a2a list
    - /a2a history [<agent-id>]
    """
    
    def __init__(self, commands: Commands):
        self.commands = commands
        self.coder: Coder = commands.coder
        self.io = commands.io
        self._registry = None
    
    @property
    def registry(self):
        """Get the agent registry from the coder."""
        if self._registry is None:
            if hasattr(self.coder, 'agent_registry'):
                self._registry = self.coder.agent_registry
            else:
                # Lazy initialization
                from ..agents.registry import AgentRegistry
                self._registry = AgentRegistry()
                self.coder.agent_registry = self._registry
        return self._registry
    
    def cmd_a2a(self, args: str) -> Optional[str]:
        """
        Agent-to-agent communication commands.
        
        Usage:
        /a2a send <agent-id> <message>
        /a2a request <agent-id> <capability> [--param key=value ...]
        /a2a broadcast <message>
        /a2a delegate <agent-id> <task>
        /a2a list
        /a2a history [<agent-id>]
        
        Examples:
        /a2a send abc123 "Hello from main agent"
        /a2a request abc123 review_code --param file=auth.py
        /a2a broadcast "All agents report status"
        /a2a delegate abc123 "Refactor user.py to use async"
        /a2a list
        /a2a history abc123
        """
        if not args.strip():
            return self.cmd_a2a.__doc__
        
        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0] if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""
        
        handler = getattr(self, f"_handle_{subcmd}", None)
        if handler:
            return handler(subargs)
        else:
            self.io.tool_error(f"Unknown a2a subcommand: {subcmd}")
            return self.cmd_a2a.__doc__
    
    def _handle_send(self, args: str) -> str:
        """Handle /a2a send"""
        import asyncio
        import shlex
        
        parts = shlex.split(args) if args else []
        if len(parts) < 2:
            return "Error: Usage: /a2a send <agent-id> <message>"
        
        agent_id = parts[0]
        message = " ".join(parts[1:])
        
        async def do_send():
            from ..a2a.types import A2AMessageType, A2AContentType
            
            # Get the agent from registry
            agent = await self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")
            
            # Check if agent supports A2A
            if not hasattr(agent, 'send'):
                raise ValueError(f"Agent {agent_id} does not support A2A")
            
            await agent.send(
                recipient_id=agent_id,
                content=message,
                msg_type=A2AMessageType.NOTIFICATION,
                content_type=A2AContentType.TEXT,
            )
            return True
        
        try:
            asyncio.run(do_send())
            return f"Message sent to agent {agent_id}"
        except Exception as e:
            self.io.tool_error(f"Failed to send message: {e}")
            return None
    
    def _handle_request(self, args: str) -> str:
        """Handle /a2a request"""
        import asyncio
        import shlex
        
        parts = shlex.split(args) if args else []
        if len(parts) < 2:
            return "Error: Usage: /a2a request <agent-id> <capability> [--param key=value ...]"
        
        agent_id = parts[0]
        capability = parts[1]
        
        # Parse parameters
        params = {}
        i = 2
        while i < len(parts):
            if parts[i] == "--param" and i + 1 < len(parts):
                param_str = parts[i + 1]
                if "=" in param_str:
                    key, value = param_str.split("=", 1)
                    params[key] = value
                i += 2
            else:
                i += 1
        
        async def do_request():
            # Get the agent from registry
            agent = await self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")
            
            # Check if agent supports A2A
            if not hasattr(agent, 'request'):
                raise ValueError(f"Agent {agent_id} does not support A2A requests")
            
            result = await agent.request(
                recipient_id=agent_id,
                capability=capability,
                parameters=params,
            )
            return result
        
        try:
            self.io.tool_output(f"Requesting '{capability}' from agent {agent_id}...")
            result = asyncio.run(do_request())
            return f"Response from {agent_id}:\n{result}"
        except Exception as e:
            self.io.tool_error(f"Request failed: {e}")
            return None
    
    def _handle_broadcast(self, args: str) -> str:
        """Handle /a2a broadcast"""
        import asyncio
        
        if not args.strip():
            return "Error: Message required"
        
        message = args.strip()
        
        async def do_broadcast():
            from ..a2a.types import A2AContentType
            
            # Get all A2A-enabled agents and broadcast from the first one
            agents = await self.registry.list_agents()
            a2a_agents = [a for a in agents if hasattr(a, 'broadcast')]
            
            if not a2a_agents:
                raise ValueError("No A2A-enabled agents found")
            
            # Use the first agent to broadcast
            await a2a_agents[0].broadcast(
                content=message,
                content_type=A2AContentType.TEXT,
            )
            return True
        
        try:
            asyncio.run(do_broadcast())
            return f"Broadcast sent to all agents"
        except Exception as e:
            self.io.tool_error(f"Failed to broadcast: {e}")
            return None
    
    def _handle_delegate(self, args: str) -> str:
        """Handle /a2a delegate"""
        import asyncio
        import shlex
        
        parts = shlex.split(args) if args else []
        if len(parts) < 2:
            return "Error: Usage: /a2a delegate <agent-id> <task>"
        
        agent_id = parts[0]
        task = " ".join(parts[1:])
        
        async def do_delegate():
            # Get the agent from registry
            agent = await self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")
            
            # Check if agent supports A2A
            if not hasattr(agent, 'delegate'):
                raise ValueError(f"Agent {agent_id} does not support A2A delegation")
            
            await agent.delegate(
                recipient_id=agent_id,
                task=task,
            )
            return True
        
        try:
            asyncio.run(do_delegate())
            return f"Task delegated to agent {agent_id}"
        except Exception as e:
            self.io.tool_error(f"Failed to delegate: {e}")
            return None
    
    def _handle_list(self, args: str) -> str:
        """Handle /a2a list"""
        import asyncio
        
        async def do_list():
            agents = await self.registry.list_agents()
            return agents
        
        try:
            agents = asyncio.run(do_list())
            if not agents:
                return "No agents found"
            
            lines = [f"{'ID':<10} {'Name':<20} {'A2A':<5} {'Task':<40}"]
            lines.append("-" * 80)
            for agent in agents:
                task_short = agent.task[:37] + "..." if len(agent.task) > 40 else agent.task
                has_a2a = "Yes" if hasattr(agent, 'send') else "No"
                lines.append(f"{agent.id:<10} {agent.name:<20} {has_a2a:<5} {task_short}")
            
            return "\n".join(lines)
        except Exception as e:
            self.io.tool_error(f"Failed to list agents: {e}")
            return None
    
    def _handle_history(self, args: str) -> str:
        """Handle /a2a history"""
        import asyncio
        
        agent_id = args.strip() if args else None
        
        async def do_history():
            # Get history from bus
            if not self.registry.a2a_bus:
                return []
            history = self.registry.a2a_bus.get_history(agent_id=agent_id)
            return history
        
        try:
            history = asyncio.run(do_history())
            if not history:
                return "No A2A messages found"
            
            lines = []
            for msg in history[-20:]:  # Last 20 messages
                lines.append(f"[{msg.timestamp:.0f}] {msg.type.value}: {msg.sender_id} -> {msg.recipient_id or 'all'}")
                lines.append(f"  Content: {str(msg.content)[:100]}")
            
            return "\n".join(lines)
        except Exception as e:
            self.io.tool_error(f"Failed to get history: {e}")
            return None
    
    def completions_a2a(self, document, complete_event):
        """Tab completion for /a2a command"""
        from prompt_toolkit.completion import Completion
        
        text = document.text.lower()
        subcommands = ["send", "request", "broadcast", "delegate", "list", "history"]
        
        for cmd in subcommands:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))


def install_a2a_commands(commands: Commands) -> None:
    """
    Install A2A commands into Aider's command system.
    
    Call this from aider/commands.py or during Coder initialization.
    """
    a2a_cmds = A2ACommands(commands)
    
    # Add cmd_a2a method to Commands class
    commands.cmd_a2a = a2a_cmds.cmd_a2a
    commands.completions_a2a = a2a_cmds.completions_a2a
    
    # Store references for access
    commands._a2a_commands = a2a_cmds
    
    logger.info("A2A commands installed")
