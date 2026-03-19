"""
Dynamic skill discovery system.

Auto-discovers skills from:
1. aider/skills/*.py - Python skill modules
2. ~/.config/aider/skills/*.yaml - User YAML skills
3. ./.aider/skills/*.yaml - Project YAML skills

No registry.py edits needed!
"""

import importlib
import inspect
import pkgutil

from .base import Skill


def discover_python_skills():
    """
    Auto-discover Python skill classes from the skills package.

    Finds all classes that inherit from Skill in aider/skills/*.py

    Note: Classes with property-based names (like DynamicACPAgentSkill,
    YAMLDefinedSkill) are skipped here and discovered through their
    specialized loaders instead.
    """
    skills = {}

    # Get the skills package
    from . import __name__ as skills_pkg

    # Walk through all modules in the package
    for importer, modname, ispkg in pkgutil.iter_modules(
        __import__(skills_pkg, fromlist=[""]).__path__, skills_pkg + "."
    ):
        try:
            # Import the module
            module = importlib.import_module(modname)

            # Find all Skill subclasses
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Skill) and obj is not Skill and hasattr(obj, "name"):
                    # Skip classes with property-based names (handled by specialized loaders)
                    name_attr = getattr(type(obj), "name", None)
                    if isinstance(name_attr, property):
                        continue

                    # Skip if name is not a string or is empty
                    if not isinstance(obj.name, str) or not obj.name:
                        continue

                    skills[obj.name] = obj

        except Exception as e:
            # Log but don't fail - broken modules shouldn't stop discovery
            print(f"Warning: Could not load skill from {modname}: {e}")

    return skills


def discover_yaml_skills():
    """Auto-discover YAML-defined skills."""
    from .yaml_loader import YAMLSkillLoader

    loader = YAMLSkillLoader()
    skill_classes = loader.load_skills()

    return {skill_class.name: skill_class for skill_class in skill_classes}


def discover_acp_skills():
    """Auto-discover ACP agent skills."""
    from .dynamic_loader import DynamicSkillLoader

    loader = DynamicSkillLoader()
    skill_classes = loader.load_acp_agents()

    return {skill_class.name: skill_class for skill_class in skill_classes}


def discover_all_skills():
    """Discover all skills from all sources."""
    skills = {}

    # 1. Discover Python skills (from aider/skills/*.py)
    python_skills = discover_python_skills()
    skills.update(python_skills)

    # 2. Discover ACP agent skills (from ~/.acpx/config.json)
    acp_skills = discover_acp_skills()
    skills.update(acp_skills)

    # 3. Discover YAML skills (from ~/.config/aider/skills/*.yaml)
    yaml_skills = discover_yaml_skills()
    skills.update(yaml_skills)

    return skills
