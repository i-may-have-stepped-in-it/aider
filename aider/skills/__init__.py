"""
Aider Skills - Reusable, composable capabilities with sub-agent support.

This module provides skills that can leverage the multi-agent system
to execute tasks in parallel.
"""

from .agent_skill import AgentSkillMixin
from .base import Skill, SkillContext, SkillResult
from .registry import (
    SkillRegistry,
    create_skill,
    get_registry,
    get_skill,
    list_all_skills,
    register_skill,
)

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
