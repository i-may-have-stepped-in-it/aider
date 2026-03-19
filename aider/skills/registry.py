"""
Skill Registry - Auto-discovering registry for skills.

No manual registration needed - skills are auto-discovered from:
1. Python modules in aider/skills/*.py
2. ACP agents from ~/.acpx/config.json
3. YAML files in ~/.config/aider/skills/*.yaml
"""

import importlib
import inspect
import threading

from .base import Skill
from .discovery import SkillDescriptor, discover_all_skills


class SkillRegistry:
    """
    Auto-discovering registry for skills.

    Skills are automatically discovered from:
    - Python modules: Any class inheriting from Skill in aider/skills/
    - ACP config: Agents defined in ~/.acpx/config.json
    - YAML files: Skills defined in ~/.config/aider/skills/*.yaml

    No code edits needed to add new skills!
    """

    def __init__(self, load_dynamic=True):
        self._skills = {}
        self._lock = threading.RLock()
        self._discovered = not load_dynamic

        if load_dynamic:
            self._discover_skills()

    def _discover_skills(self):
        """Auto-discover all skills from available sources."""
        with self._lock:
            self._skills = discover_all_skills()
            self._discovered = True

    def _ensure_discovered(self):
        """Discover skills lazily on first access."""
        if not self._discovered:
            self._discover_skills()

    def _descriptor_from_class(self, skill_class, source="python"):
        """Create a descriptor from an already loaded skill class."""
        return SkillDescriptor(
            name=skill_class.name,
            description=getattr(skill_class, "description", ""),
            version=getattr(skill_class, "version", "1.0.0"),
            supports_agents=getattr(skill_class, "supports_agents", False),
            max_agents=getattr(skill_class, "max_agents", 0),
            source=source,
            module_name=getattr(skill_class, "__module__", None),
            class_name=getattr(skill_class, "__name__", None),
            skill_class=skill_class,
        )

    def _resolve_descriptor(self, descriptor):
        """Resolve a descriptor into a concrete skill class."""
        if inspect.isclass(descriptor):
            if not issubclass(descriptor, Skill):
                return None
            return descriptor

        if descriptor.skill_class is not None:
            if not issubclass(descriptor.skill_class, Skill):
                return None
            return descriptor.skill_class

        if descriptor.module_name and descriptor.class_name:
            module = importlib.import_module(descriptor.module_name)
            skill_class = getattr(module, descriptor.class_name)
            if not inspect.isclass(skill_class) or not issubclass(skill_class, Skill):
                return None
            descriptor.skill_class = skill_class
            descriptor.description = getattr(skill_class, "description", descriptor.description)
            descriptor.version = getattr(skill_class, "version", descriptor.version)
            descriptor.supports_agents = getattr(
                skill_class, "supports_agents", descriptor.supports_agents
            )
            descriptor.max_agents = getattr(skill_class, "max_agents", descriptor.max_agents)
            return skill_class

        return None

    def _get_descriptor(self, name):
        """Get a descriptor by name."""
        self._ensure_discovered()
        with self._lock:
            return self._skills.get(name)

    def register(self, skill_class):
        """
        Manually register a skill class (for testing or edge cases).

        Args:
            skill_class: The skill class to register

        Returns:
            True if registered successfully
        """
        if not inspect.isclass(skill_class) or not issubclass(skill_class, Skill):
            return False

        if not hasattr(skill_class, "name") or not skill_class.name:
            return False

        with self._lock:
            self._skills[skill_class.name] = self._descriptor_from_class(skill_class)
            self._discovered = True
        return True

    def unregister(self, name):
        """Unregister a skill."""
        with self._lock:
            if name in self._skills:
                del self._skills[name]
                return True
        return False

    def get(self, name):
        """Get a skill class by name."""
        descriptor = self._get_descriptor(name)
        if descriptor is None:
            return None
        return self._resolve_descriptor(descriptor)

    def create(self, name, context=None):
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
            try:
                return skill_class(context)
            except TypeError:
                skill = skill_class()
                if hasattr(skill, "context"):
                    skill.context = context
                return skill
        return None

    def list_skills(self, supports_agents=None):
        """
        List all registered skills.

        Args:
            supports_agents: Filter by agent support

        Returns:
            List of skill metadata
        """
        self._ensure_discovered()
        with self._lock:
            skills = []
            for name, descriptor in self._skills.items():
                # Filter by agent support if specified
                if supports_agents is not None:
                    if descriptor.supports_agents != supports_agents:
                        continue

                skills.append(
                    {
                        "name": name,
                        "description": descriptor.description,
                        "version": descriptor.version,
                        "supports_agents": descriptor.supports_agents,
                        "max_agents": descriptor.max_agents,
                        "source": descriptor.source,
                    }
                )

            return sorted(skills, key=lambda s: s["name"])

    def search(self, query):
        """
        Search for skills by name or description.

        Args:
            query: Search query

        Returns:
            List of matching skill metadata
        """
        self._ensure_discovered()
        query = query.lower()
        results = []

        with self._lock:
            for name, descriptor in self._skills.items():
                if query in name.lower() or query in descriptor.description.lower():
                    results.append(
                        {
                            "name": name,
                            "description": descriptor.description,
                            "supports_agents": descriptor.supports_agents,
                            "source": descriptor.source,
                        }
                    )

        return results

    def get_metadata(self, name):
        """Get skill metadata without forcing immediate execution."""
        descriptor = self._get_descriptor(name)
        if descriptor is None:
            return None

        metadata = {
            "name": descriptor.name,
            "description": descriptor.description,
            "version": descriptor.version,
            "supports_agents": descriptor.supports_agents,
            "max_agents": descriptor.max_agents,
            "source": descriptor.source,
        }
        metadata.update(descriptor.metadata or {})

        skill_class = self._resolve_descriptor(descriptor)
        if skill_class:
            metadata["parameters"] = self._get_parameters_for_class(skill_class)
        else:
            metadata["parameters"] = {}

        return metadata

    def _get_parameters_for_class(self, skill_class):
        """Extract parameter metadata from a skill class."""
        try:
            skill = skill_class()
        except TypeError:
            return {}
        get_parameters = getattr(skill, "get_parameters", None)
        if callable(get_parameters):
            return get_parameters() or {}
        return {}

    def reload(self):
        """Reload all skills from disk."""
        with self._lock:
            self._discovered = False
        self._discover_skills()

    def count(self):
        """Return the number of registered skills."""
        self._ensure_discovered()
        with self._lock:
            return len(self._skills)


# Global registry instance
_registry = None
_registry_lock = threading.Lock()


def get_registry():
    """Get the global skill registry."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = SkillRegistry()
        return _registry


def get_skill(name):
    """Get a skill by name from the global registry."""
    return get_registry().get(name)


def create_skill(name, context=None):
    """Create a skill instance from the global registry."""
    return get_registry().create(name, context)


def register_skill(skill_class):
    """Register a skill in the global registry."""
    return get_registry().register(skill_class)


def list_all_skills():
    """List all skills from the global registry."""
    return get_registry().list_skills()
