"""
Dynamic skill loader for ACP agents and external skill definitions.

Allows skills to be:
1. Auto-generated from ~/.acpx/config.json agents
2. Loaded from YAML/JSON skill definitions
3. Discovered from plugin entry points
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from .acp_delegation import ACPDelegationSkill
from .base import Skill, SkillContext, SkillResult
from .discovery import SkillDescriptor

logger = logging.getLogger(__name__)


class DynamicACPAgentSkill(Skill):
    """
    Dynamically generated skill for an ACP agent.
    
    Created at runtime from ~/.acpx/config.json agents.
    """
    
    # Class-level attributes for registry inspection
    _agent_name: str = ""
    _agent_config: Dict[str, Any] = None
    
    def __init__(
        self,
        context: Optional[SkillContext] = None,
        agent_name: str = None,
        agent_config: Dict[str, Any] = None,
    ):
        super().__init__(context)
        # Use provided args or fall back to class attributes
        self.agent_name = agent_name or self._agent_name
        self.agent_config = agent_config or self._agent_config or {}
    
    @property
    def name(self) -> str:
        return f"acp-{self.agent_name}"
    
    @property
    def description(self) -> str:
        return f"Delegate tasks to {self.agent_name} ACP agent"
    
    @property
    def supports_agents(self) -> bool:
        return True
    
    def get_parameters(self) -> Dict[str, Any]:
        return {
            "task": {
                "type": "string",
                "description": f"Task to delegate to {self.agent_name}",
            },
            "mode": {
                "type": "string",
                "enum": ["oneshot", "session"],
                "default": "oneshot",
                "description": "Execution mode",
            },
            "timeout": {
                "type": "number",
                "default": 300,
                "description": "Timeout in seconds",
            },
        }
    
    async def execute(self, **kwargs) -> SkillResult:
        """Execute task using the underlying ACP agent."""
        # Delegate to the generic ACP delegation skill
        delegate_skill = ACPDelegationSkill(self.context)

        return await delegate_skill.execute(
            agent=self.agent_name,
            **kwargs
        )


class DynamicSkillLoader:
    """
    Dynamic skill loader that creates skills from configuration.
    
    Loads skills from:
    1. ~/.acpx/config.json - ACP agents
    2. ~/.config/aider/skills/ - User skill definitions
    3. Plugin entry points (future)
    """
    
    def __init__(self):
        self._dynamic_skills: Dict[str, Type[Skill]] = {}
        self._acp_agents: Dict[str, Dict[str, Any]] = {}
    
    def load_acp_agents(self) -> List[Type[Skill]]:
        """
        Load ACP agents from ~/.acpx/config.json and create skills for each.
        
        Returns:
            List of dynamically generated skill classes
        """
        skills = []
        config_path = Path.home() / ".acpx" / "config.json"
        
        if not config_path.exists():
            return skills
        
        try:
            with open(config_path) as f:
                config = json.load(f)
            
            agents = config.get("agents", {})
            
            for agent_name, agent_config in agents.items():
                # Create a dynamic skill class for this agent
                skill_class = self._create_agent_skill_class(agent_name, agent_config)
                self._dynamic_skills[f"acp-{agent_name}"] = skill_class
                self._acp_agents[agent_name] = agent_config
                skills.append(skill_class)
                
        except (json.JSONDecodeError, IOError) as e:
            # Log error but don't fail - skills just won't be available
            logger.warning("Could not load ACP agents from %s: %s", config_path, e)
        
        return skills

    def load_acp_agent_descriptors(self) -> List[SkillDescriptor]:
        """Load ACP agent descriptors."""
        descriptors = []
        for skill_class in self.load_acp_agents():
            descriptors.append(
                SkillDescriptor(
                    name=skill_class.name,
                    description=getattr(skill_class, "description", ""),
                    version=getattr(skill_class, "version", "1.0.0"),
                    supports_agents=getattr(skill_class, "supports_agents", False),
                    max_agents=getattr(skill_class, "max_agents", 0),
                    source="acp",
                    module_name=getattr(skill_class, "__module__", None),
                    class_name=getattr(skill_class, "__name__", None),
                    skill_class=skill_class,
                )
            )
        return descriptors
    
    def _create_agent_skill_class(
        self,
        agent_name: str,
        agent_config: Dict[str, Any]
    ) -> Type[Skill]:
        """
        Dynamically create a skill class for an ACP agent.
        
        Args:
            agent_name: Name of the agent (claude, codex, etc.)
            agent_config: Agent configuration from acpx config
            
        Returns:
            Dynamically created skill class
        """
        # Create a new class dynamically
        class_name = f"ACP{agent_name.title()}Skill"
        
        # Create the class with class-level attributes
        # Override name as class attribute so registry can access it without instantiation
        skill_class = type(
            class_name,
            (DynamicACPAgentSkill,),
            {
                "_agent_name": agent_name,
                "_agent_config": agent_config,
                "__module__": "aider.skills.dynamic_loader",
                # Class-level overrides for registry compatibility
                "name": f"acp-{agent_name}",
                "description": f"Delegate tasks to {agent_name} ACP agent",
                "supports_agents": True,
            }
        )
        
        return skill_class
    
    def get_skill(self, name: str) -> Optional[Type[Skill]]:
        """Get a dynamically loaded skill by name."""
        return self._dynamic_skills.get(name)
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """List all dynamically loaded skills."""
        return [
            {
                "name": name,
                "type": "acp-agent",
                "agent": name.replace("acp-", ""),
                "config": self._acp_agents.get(name.replace("acp-", "")),
            }
            for name in self._dynamic_skills.keys()
        ]
    
    def reload(self) -> List[Type[Skill]]:
        """Reload all dynamic skills."""
        self._dynamic_skills.clear()
        self._acp_agents.clear()
        return self.load_acp_agents()


# Global loader instance
_dynamic_loader = DynamicSkillLoader()


def get_dynamic_skills() -> List[Type[Skill]]:
    """Get all dynamically loaded skills."""
    return _dynamic_loader.load_acp_agents()


def get_acp_agent_skill(agent_name: str) -> Optional[Type[Skill]]:
    """Get a specific ACP agent skill."""
    skills = _dynamic_loader.load_acp_agents()
    for skill_class in skills:
        if getattr(skill_class, "name", None) == f"acp-{agent_name}":
            return skill_class
    return None


def reload_dynamic_skills() -> List[Type[Skill]]:
    """Reload all dynamic skills."""
    return _dynamic_loader.reload()
