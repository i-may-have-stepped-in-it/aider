"""
YAML-based dynamic skill loader.

Allows skills to be defined in YAML files without code edits:
~/.config/aider/skills/*.yaml
./.aider/skills/*.yaml
"""

import inspect
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import yaml

from .base import Skill, SkillContext, SkillResult
from .discovery import SkillDescriptor


class YAMLDefinedSkill(Skill):
    """
    A skill defined entirely in YAML.
    
    No Python code required - just YAML definition.
    """
    
    def __init__(
        self,
        context: Optional[SkillContext] = None,
        definition: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(context)
        definition = definition or {}
        self._definition = definition
        self._name = definition.get("name", "unnamed")
        self._description = definition.get("description", "")
        self._supports_agents = definition.get("supports_agents", False)
        self._max_agents = definition.get("max_agents", 0)
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def description(self) -> str:
        return self._description
    
    @property
    def supports_agents(self) -> bool:
        return self._supports_agents
    
    def get_parameters(self) -> Dict[str, Any]:
        return self._definition.get("parameters", {})
    
    async def execute(self, **kwargs) -> SkillResult:
        """Execute the YAML-defined skill."""
        handler = self._definition.get("handler", {})
        handler_type = handler.get("type", "shell")
        
        if handler_type == "shell":
            return self._execute_shell(handler, kwargs)
        elif handler_type == "python":
            return self._execute_python(handler, kwargs)
        elif handler_type == "composite":
            return await self._execute_composite(handler, kwargs)
        else:
            return SkillResult(
                success=False,
                error=f"Unknown handler type: {handler_type}",
            )
    
    def _execute_shell(
        self,
        handler: Dict[str, Any],
        kwargs: Dict[str, Any]
    ) -> SkillResult:
        """Execute shell command handler."""
        import time
        
        start_time = time.time()
        
        # Get command template
        command_template = handler.get("command", "")
        
        # Substitute parameters
        command = self._substitute_template(command_template, kwargs)
        
        if self.context.io and self.context.verbose:
            self.context.io.tool_output(f"Running: {command}")
        
        try:
            if any(char in command for char in [";", "|", "&", "$", "`", "\n", "\r"]):
                return SkillResult(
                    success=False,
                    error="Unsafe shell metacharacters are not allowed in YAML skills",
                    execution_time=time.time() - start_time,
                )

            command_args = shlex.split(command)
            result = subprocess.run(
                command_args,
                capture_output=True,
                text=True,
                timeout=kwargs.get("timeout", handler.get("timeout", 300)),
                cwd=kwargs.get("cwd") or handler.get("cwd"),
            )
            
            execution_time = time.time() - start_time
            
            return SkillResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr.strip() if result.returncode != 0 else None,
                execution_time=execution_time,
            )
            
        except subprocess.TimeoutExpired:
            return SkillResult(
                success=False,
                error=f"Timeout after {handler.get('timeout', 300)}s",
                execution_time=time.time() - start_time,
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )
    
    def _execute_python(
        self,
        handler: Dict[str, Any],
        kwargs: Dict[str, Any]
    ) -> SkillResult:
        """Execute Python code handler."""
        import time
        
        start_time = time.time()
        
        code = handler.get("code", "")
        
        # Create safe execution environment
        local_vars = {
            "context": self.context,
            "kwargs": kwargs,
            "SkillResult": SkillResult,
        }
        
        try:
            if os.getenv("AIDER_ENABLE_UNSAFE_YAML_PYTHON") != "1":
                return SkillResult(
                    success=False,
                    error="Python YAML handlers are disabled unless AIDER_ENABLE_UNSAFE_YAML_PYTHON=1",
                    execution_time=time.time() - start_time,
                )

            # Execute the Python code
            exec(code, {"__builtins__": {}}, local_vars)
            
            # Get result from local_vars
            result = local_vars.get("result", SkillResult(
                success=True,
                output="Python handler executed",
            ))
            
            result.execution_time = time.time() - start_time
            return result
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )
    
    async def _execute_composite(
        self,
        handler: Dict[str, Any],
        kwargs: Dict[str, Any]
    ) -> SkillResult:
        """Execute composite skill (chain of other skills)."""
        from .registry import get_registry
        
        steps = handler.get("steps", [])
        results = []
        
        registry = get_registry()
        
        for i, step in enumerate(steps):
            skill_name = step.get("skill")
            step_params = {k: self._substitute_template(v, kwargs) 
                          for k, v in step.items() if k != "skill"}
            
            skill = registry.create(skill_name, self.context)
            if not skill:
                results.append({
                    "step": i,
                    "skill": skill_name,
                    "success": False,
                    "error": f"Skill not found: {skill_name}",
                })
                continue

            result = skill.execute(**step_params)
            if inspect.isawaitable(result):
                result = await result
            results.append({
                "step": i,
                "skill": skill_name,
                "success": result.success,
                "output": result.output[:500] if result.output else None,
            })
            
            # Stop on failure if configured
            if not result.success and handler.get("stop_on_error", True):
                break
        
        all_success = all(r["success"] for r in results)
        
        return SkillResult(
            success=all_success,
            output=f"Completed {len([r for r in results if r['success']])}/{len(steps)} steps",
            data={"steps": results},
        )
    
    def _substitute_template(self, template: str, params: Dict[str, Any]) -> str:
        """Substitute {{ param }} templates with values."""
        if not isinstance(template, str):
            return template
        
        def replacer(match):
            key = match.group(1).strip()
            return str(params.get(key, match.group(0)))
        
        return re.sub(r"\{\{\s*(\w+)\s*\}\}", replacer, template)


class YAMLSkillLoader:
    """Loader for YAML-defined skills."""
    
    def __init__(self):
        self._skills: Dict[str, Type[Skill]] = {}
    
    def get_skill_paths(self) -> List[Path]:
        """Get list of directories to search for YAML skills."""
        paths = []
        
        # User-global skills
        user_dir = Path.home() / ".config" / "aider" / "skills"
        if user_dir.exists():
            paths.append(user_dir)
        
        # Project-local skills
        local_dir = Path(".aider") / "skills"
        if local_dir.exists():
            paths.append(local_dir)
        
        # System-wide skills (if exists)
        system_dir = Path("/etc/aider/skills")
        if system_dir.exists():
            paths.append(system_dir)
        
        return paths
    
    def load_skills(self) -> List[Type[Skill]]:
        """Load all YAML-defined skills."""
        skills = []
        
        for path in self.get_skill_paths():
            for yaml_file in path.glob("*.yaml"):
                try:
                    with open(yaml_file) as f:
                        definition = yaml.safe_load(f)
                    
                    if not definition or "name" not in definition:
                        continue
                    
                    skill_class = self._create_skill_class(definition)
                    self._skills[definition["name"]] = skill_class
                    skills.append(skill_class)
                    
                except yaml.YAMLError as e:
                    print(f"Warning: Failed to parse {yaml_file}: {e}")
                except Exception as e:
                    print(f"Warning: Failed to load skill from {yaml_file}: {e}")
        
        return skills

    def load_skill_descriptors(self) -> List[SkillDescriptor]:
        """Load YAML skill descriptors without changing the public loader API."""
        descriptors = []
        for skill_class in self.load_skills():
            descriptors.append(
                SkillDescriptor(
                    name=skill_class.name,
                    description=getattr(skill_class, "description", ""),
                    version=getattr(skill_class, "version", "1.0.0"),
                    supports_agents=getattr(skill_class, "supports_agents", False),
                    max_agents=getattr(skill_class, "max_agents", 0),
                    source="yaml",
                    module_name=getattr(skill_class, "__module__", None),
                    class_name=getattr(skill_class, "__name__", None),
                    skill_class=skill_class,
                )
            )
        return descriptors
    
    def _create_skill_class(self, definition: Dict[str, Any]) -> Type[Skill]:
        """Create a skill class from YAML definition."""
        class_name = "".join(
            word.capitalize() 
            for word in definition["name"].replace("-", "_").split("_")
        ) + "Skill"
        
        def init_method(self, context=None, definition=definition):
            YAMLDefinedSkill.__init__(self, context=context, definition=definition)
        
        skill_class = type(
            class_name,
            (YAMLDefinedSkill,),
            {
                "__init__": init_method,
                "__module__": "aider.skills.yaml_loader",
                # Class-level attributes for registry
                "name": definition["name"],
                "description": definition.get("description", ""),
                "supports_agents": definition.get("supports_agents", False),
                "max_agents": definition.get("max_agents", 0),
            }
        )
        
        return skill_class
    
    def get_skill(self, name: str) -> Optional[Type[Skill]]:
        """Get a loaded skill by name."""
        return self._skills.get(name)
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """List all loaded YAML skills."""
        return [
            {
                "name": name,
                "type": "yaml-defined",
                "source": "yaml",
            }
            for name in self._skills.keys()
        ]
    
    def reload(self) -> List[Type[Skill]]:
        """Reload all YAML skills."""
        self._skills.clear()
        return self.load_skills()


# Global loader
_yaml_loader = YAMLSkillLoader()


def get_yaml_skills() -> List[Type[Skill]]:
    """Get all YAML-defined skills."""
    return _yaml_loader.load_skills()


def reload_yaml_skills() -> List[Type[Skill]]:
    """Reload all YAML skills."""
    return _yaml_loader.reload()
