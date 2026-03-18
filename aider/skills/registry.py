"""
Skill Registry - Registry and factory for skills.
"""

import threading
from typing import Dict, List, Optional, Type

from .base import Skill, SkillContext
from .code_review import CodeReviewSkill, PerformanceReviewSkill, SecurityAuditSkill
from .documentation import ArchitectureDocSkill, DocumentationSkill
from .preview import ArtifactPreviewSkill
from .refactoring import CodeModernizationSkill, RefactoringSkill
from .swarm import SwarmSkill
from .test_generation import CoverageAnalysisSkill, TestGenerationSkill
from .web_delegation import DelegatedWebSkill


class SkillRegistry:
    """
    Registry for skills.

    Provides discovery and instantiation of skills.
    """

    def __init__(self):
        self._skills: Dict[str, Type[Skill]] = {}
        self._lock = threading.RLock()  # Issue 8: Thread safety
        self._register_builtin_skills()

    def _register_builtin_skills(self):
        """Register built-in skills."""
        builtin_skills = [
            CodeReviewSkill,
            SecurityAuditSkill,
            PerformanceReviewSkill,
            TestGenerationSkill,
            CoverageAnalysisSkill,
            RefactoringSkill,
            CodeModernizationSkill,
            DocumentationSkill,
            ArchitectureDocSkill,
            ArtifactPreviewSkill,
            SwarmSkill,
            DelegatedWebSkill,
        ]

        for skill_class in builtin_skills:
            self.register(skill_class)

    def register(self, skill_class: Type[Skill]) -> bool:
        """
        Register a skill class.

        Args:
            skill_class: The skill class to register

        Returns:
            True if registered successfully
        """
        if not hasattr(skill_class, "name") or not skill_class.name:
            return False

        self._skills[skill_class.name] = skill_class
        return True

    def unregister(self, name: str) -> bool:
        """Unregister a skill."""
        if name in self._skills:
            del self._skills[name]
            return True
        return False

    def get(self, name: str) -> Optional[Type[Skill]]:
        """Get a skill class by name."""
        return self._skills.get(name)

    def create(self, name: str, context: Optional[SkillContext] = None) -> Optional[Skill]:
        """
        Create a skill instance.

        Args:
            name: Skill name
            context: Optional skill context

        Returns:
            Skill instance or None if not found
        """
        skill_class = self.get(name)
        if skill_class:
            return skill_class(context)
        return None

    def list_skills(self, supports_agents: Optional[bool] = None) -> List[Dict[str, any]]:
        """
        List all registered skills.

        Args:
            supports_agents: Filter by agent support

        Returns:
            List of skill metadata dictionaries
        """
        skills = []

        for name, skill_class in self._skills.items():
            # Filter by agent support if specified
            if supports_agents is not None:
                if skill_class.supports_agents != supports_agents:
                    continue

            skills.append(
                {
                    "name": name,
                    "description": skill_class.description,
                    "version": getattr(skill_class, "version", "1.0.0"),
                    "supports_agents": skill_class.supports_agents,
                    "max_agents": getattr(skill_class, "max_agents", 0),
                }
            )

        return sorted(skills, key=lambda s: s["name"])

    def search(self, query: str) -> List[Dict[str, any]]:
        """
        Search for skills by name or description.

        Args:
            query: Search query

        Returns:
            List of matching skill metadata
        """
        query = query.lower()
        results = []

        for name, skill_class in self._skills.items():
            if query in name.lower() or query in skill_class.description.lower():
                results.append(
                    {
                        "name": name,
                        "description": skill_class.description,
                        "supports_agents": skill_class.supports_agents,
                    }
                )

        return sorted(results, key=lambda s: s["name"])

    def count(self) -> int:
        """Return the number of registered skills."""
        return len(self._skills)


# Global registry instance
_global_registry: Optional[SkillRegistry] = None


def get_registry() -> SkillRegistry:
    """Get the global skill registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry()
    return _global_registry


def set_registry(registry: SkillRegistry):
    """Set the global skill registry."""
    global _global_registry
    _global_registry = registry


def register_skill(skill_class: Type[Skill]) -> bool:
    """Register a skill with the global registry."""
    return get_registry().register(skill_class)


def get_skill(name: str) -> Optional[Type[Skill]]:
    """Get a skill class from the global registry."""
    return get_registry().get(name)


def create_skill(name: str, context: Optional[SkillContext] = None) -> Optional[Skill]:
    """Create a skill instance from the global registry."""
    return get_registry().create(name, context)


def list_all_skills() -> List[Dict[str, any]]:
    """List all skills in the global registry."""
    return get_registry().list_skills()
