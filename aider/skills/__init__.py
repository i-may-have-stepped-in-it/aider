"""
Aider Skills - Reusable, composable capabilities with sub-agent support.

This module provides skills that can leverage the multi-agent system
to execute tasks in parallel.
"""

from .base import Skill, SkillContext, SkillResult
from .registry import (
    SkillRegistry,
    get_registry,
    create_skill,
    get_skill,
    list_all_skills,
    register_skill,
)
from .agent_skill import AgentSkillMixin

__all__ = [
    "Skill",
    "SkillContext", 
    "SkillResult",
    "SkillRegistry",
    "get_registry",
    "create_skill",
    "get_skill",
    "list_all_skills",
    "register_skill",
    "AgentSkillMixin",
]
