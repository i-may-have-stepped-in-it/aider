"""
Dynamic skill discovery system.

Auto-discovers skills from:
1. aider/skills/*.py - Python skill modules
2. ~/.config/aider/skills/*.yaml - User YAML skills
3. ./.aider/skills/*.yaml - Project YAML skills

No registry.py edits needed!
"""

import ast
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillDescriptor:
    """Metadata and lazy-loading information for a skill."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    supports_agents: bool = False
    max_agents: int = 0
    source: str = "python"
    module_name: Optional[str] = None
    class_name: Optional[str] = None
    skill_class: Optional[type] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def discover_python_skills():
    """
    Auto-discover Python skill metadata from the skills package.

    This avoids importing every module during discovery. Skills are resolved
    lazily by the registry when they are instantiated or explicitly inspected.
    """
    skills = {}

    # Get the skills package
    from . import __name__ as skills_pkg

    # Walk through all modules in the package
    for importer, modname, ispkg in pkgutil.iter_modules(
        __import__(skills_pkg, fromlist=[""]).__path__, skills_pkg + "."
    ):
        if ispkg or modname.rsplit(".", 1)[-1].startswith("_"):
            continue
        try:
            spec = importer.find_spec(modname)
            if not spec or not spec.origin or not spec.origin.endswith(".py"):
                continue

            with open(spec.origin, "r", encoding="utf-8") as handle:
                module_ast = ast.parse(handle.read(), filename=spec.origin)

            for node in module_ast.body:
                if not isinstance(node, ast.ClassDef):
                    continue

                class_meta = _extract_skill_metadata(node)
                if not class_meta or not class_meta["name"]:
                    continue

                skills[class_meta["name"]] = SkillDescriptor(
                    name=class_meta["name"],
                    description=class_meta["description"],
                    version=class_meta["version"],
                    supports_agents=class_meta["supports_agents"],
                    max_agents=class_meta["max_agents"],
                    source="python",
                    module_name=modname,
                    class_name=node.name,
                )

        except Exception as e:
            # Log but don't fail - broken modules shouldn't stop discovery
            logger.warning("Could not load skill from %s: %s", modname, e)

    return skills


def _extract_skill_metadata(node: ast.ClassDef) -> Optional[Dict[str, Any]]:
    """Extract static metadata from a class definition if it looks like a skill."""
    if not _looks_like_skill_class(node):
        return None

    values = {
        "name": None,
        "description": "",
        "version": "1.0.0",
        "supports_agents": False,
        "max_agents": 0,
    }

    for stmt in node.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name) or target.id not in values:
            continue
        constant = _literal_value(stmt.value)
        if constant is not None:
            values[target.id] = constant

    if not isinstance(values["name"], str) or not values["name"]:
        return None

    return values


def _looks_like_skill_class(node: ast.ClassDef) -> bool:
    """Require a plausible Skill inheritance chain before discovery."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id.endswith("Skill"):
            return True
        if isinstance(base, ast.Attribute) and base.attr.endswith("Skill"):
            return True
    return False


def _literal_value(node: ast.AST):
    """Return a safe literal value from an AST node or None."""
    if isinstance(node, ast.Constant):
        return node.value
    return None


def discover_yaml_skills():
    """Auto-discover YAML-defined skills."""
    from .yaml_loader import YAMLSkillLoader

    loader = YAMLSkillLoader()
    skill_descriptors = loader.load_skill_descriptors()

    return {descriptor.name: descriptor for descriptor in skill_descriptors}


def discover_acp_skills():
    """Auto-discover ACP agent skills."""
    from .dynamic_loader import DynamicSkillLoader

    loader = DynamicSkillLoader()
    skill_descriptors = loader.load_acp_agent_descriptors()

    return {descriptor.name: descriptor for descriptor in skill_descriptors}


def discover_openclaw_skills():
    """Discover OpenClaw bridge skills and expose them as shared skill descriptors."""
    from aider.openclaw_bridge import OpenClawBridge

    from .openclaw_adapter import create_openclaw_skill_class

    bridge = OpenClawBridge()
    descriptors = {}

    try:
        for metadata in bridge.list_skills():
            skill_class = create_openclaw_skill_class(metadata.name, metadata, bridge=bridge)
            descriptors[metadata.name] = SkillDescriptor(
                name=metadata.name,
                description=metadata.description,
                version="openclaw",
                supports_agents=False,
                max_agents=0,
                source="openclaw",
                skill_class=skill_class,
                metadata={
                    "homepage": metadata.homepage,
                    "requires": metadata.requires,
                    "install": metadata.install,
                    "emoji": metadata.emoji,
                },
            )
    except Exception as e:
        logger.warning("Could not load OpenClaw skills: %s", e)

    return descriptors


def _merge_skill_sources(skills, discovered, source_name):
    """Merge discovered skills without silently overwriting previous sources."""
    for name, descriptor in discovered.items():
        if name in skills:
            logger.warning(
                "Duplicate skill name '%s' from %s ignored; keeping existing source '%s'",
                name,
                source_name,
                getattr(skills[name], "source", "unknown"),
            )
            continue
        skills[name] = descriptor


def discover_all_skills():
    """Discover all skills from all sources."""
    skills = {}

    # 1. Discover Python skills (from aider/skills/*.py)
    _merge_skill_sources(skills, discover_python_skills(), "python")

    # 2. Discover ACP agent skills (from ~/.acpx/config.json)
    _merge_skill_sources(skills, discover_acp_skills(), "acp")

    # 3. Discover YAML skills (from ~/.config/aider/skills/*.yaml)
    _merge_skill_sources(skills, discover_yaml_skills(), "yaml")

    # 4. Discover OpenClaw bridge skills
    _merge_skill_sources(skills, discover_openclaw_skills(), "openclaw")

    return skills
