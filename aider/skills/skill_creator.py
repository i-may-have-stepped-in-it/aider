"""
Skill Creator - A meta-skill that generates new skills for Aider.

Allows Aider to create its own YAML skills by generating definitions
based on natural language descriptions.

Usage:
    aider --skill run skill-creator name=my-linter description="Run eslint on files"
    
Or with more detail:
    aider --skill run skill-creator \
        name=api-tester \
        description="Test REST API endpoints" \
        type=shell \
        context="Uses curl and jq for testing APIs"
"""

import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from .base import Skill, SkillContext, SkillResult
from .agent_skill import AgentSkillMixin


class SkillCreatorSkill(Skill, AgentSkillMixin):
    """
    Create new skills for Aider or OpenClaw by describing what you want.
    
    This meta-skill allows Aider to extend itself with new capabilities
    without code changes. Can create:
    - Aider YAML skills (with handlers)
    - OpenClaw Markdown skills (with scripts/references/assets)
    
    Generated skills are immediately available for use.
    """
    
    name = "skill-creator"
    description = "Create new skills for Aider (YAML) or OpenClaw (Markdown) by describing what you want them to do"
    supports_agents = True
    max_agents = 2
    
    def get_parameters(self) -> Dict[str, Any]:
        return {
            "name": {
                "type": "string",
                "description": "Name for the new skill (lowercase, hyphens allowed, e.g., 'my-linter', 'api-tester')",
            },
            "description": {
                "type": "string",
                "description": "What this skill should do. Be specific about the task.",
            },
            "format": {
                "type": "string",
                "enum": ["aider", "openclaw"],
                "default": "aider",
                "description": "Skill format: 'aider' (YAML with handlers) or 'openclaw' (Markdown with resources)",
            },
            "type": {
                "type": "string",
                "enum": ["shell", "composite", "analysis", "lint", "test", "format", "search"],
                "default": "shell",
                "description": "Type of skill to create (for Aider format). Choose based on the primary action.",
            },
            "context": {
                "type": "string",
                "description": "Additional context: tools used, file patterns, special requirements",
                "default": "",
            },
            "save_location": {
                "type": "string",
                "enum": ["user", "project"],
                "default": "user",
                "description": "Where to save: user (~/.config/aider/skills/) or project (./.aider/skills/)",
            },
            "with_resources": {
                "type": "boolean",
                "default": False,
                "description": "Create with scripts/, references/, assets/ directories (for OpenClaw format)",
            },
        }
    
    async def execute(self, **kwargs) -> SkillResult:
        """Generate a new skill based on description."""
        context = self.context
        skill_name = kwargs.get("name", "").lower().replace(" ", "-")
        description = kwargs.get("description", "")
        skill_format = kwargs.get("format", "aider")
        skill_type = kwargs.get("type", "shell")
        extra_context = kwargs.get("context", "")
        save_location = kwargs.get("save_location", "user")
        with_resources = kwargs.get("with_resources", False)
        
        # Validate inputs
        if not skill_name or not description:
            return SkillResult(
                success=False,
                error="Both 'name' and 'description' are required. Example: name=api-tester description='Test REST APIs'",
            )
        
        if not re.match(r"^[a-z0-9-]+$", skill_name):
            return SkillResult(
                success=False,
                error=f"Invalid skill name '{skill_name}'. Use only lowercase letters, numbers, and hyphens.",
            )
        
        # Handle different formats
        if skill_format == "openclaw":
            return self._create_openclaw_skill(
                skill_name, description, with_resources, save_location, context
            )

        save_path = self._get_save_path(save_location, skill_name)
        
        # Generate skill content
        try:
            if with_resources:
                result = self._create_skill_with_resources(
                    skill_name, description, skill_type, extra_context, save_path
                )
            else:
                result = self._create_simple_skill(
                    skill_name, description, skill_type, extra_context, save_path
                )
            
            if context.io:
                context.io.tool_output(f"✅ Created new Aider skill: {skill_name}")
                context.io.tool_output(f"   Location: {save_path}")
                context.io.tool_output(f"   Type: {skill_type}")
                context.io.tool_output("")
                context.io.tool_output(f"Use it immediately:")
                context.io.tool_output(f"  aider --skill run {skill_name}")
                context.io.tool_output("")
                context.io.tool_output(f"Edit it later:")
                context.io.tool_output(f"  aider --skill run skill-editor skill={skill_name}")
            
            return result
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Failed to create skill: {e}",
            )
    
    def _create_simple_skill(
        self,
        name: str,
        description: str,
        skill_type: str,
        context: str,
        save_path: Path,
    ) -> SkillResult:
        """Create a simple YAML-only skill."""
        # Generate appropriate YAML based on type
        yaml_content = self._generate_yaml(name, description, skill_type, context)
        
        # Save file
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            f.write(yaml_content)
        
        return SkillResult(
            success=True,
            output=f"Created skill {name} at {save_path}",
            data={
                "skill_name": name,
                "skill_type": skill_type,
                "path": str(save_path),
                "yaml": yaml_content,
            },
            files_modified=[str(save_path)],
        )
    
    def _create_skill_with_resources(
        self,
        name: str,
        description: str,
        skill_type: str,
        context: str,
        save_path: Path,
    ) -> SkillResult:
        """Create a skill with resource directories."""
        skill_dir = save_path.parent / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        # Create SKILL.md (as YAML)
        skill_yaml = skill_dir / "SKILL.md"
        yaml_content = self._generate_yaml(name, description, skill_type, context)
        with open(skill_yaml, "w") as f:
            f.write(yaml_content)
        
        # Create resource directories
        (skill_dir / "scripts").mkdir(exist_ok=True)
        (skill_dir / "references").mkdir(exist_ok=True)
        (skill_dir / "assets").mkdir(exist_ok=True)
        
        # Create placeholder files
        with open(skill_dir / "scripts" / ".gitkeep", "w") as f:
            f.write(f"# Scripts for {name}: add executable helpers here.\n")
        with open(skill_dir / "references" / ".gitkeep", "w") as f:
            f.write(f"# References for {name}: add supporting notes and guides here.\n")
        with open(skill_dir / "assets" / ".gitkeep", "w") as f:
            f.write(f"# Assets for {name}: add templates, fixtures, or sample inputs here.\n")
        
        return SkillResult(
            success=True,
            output=f"Created skill {name} with resources at {skill_dir}",
            data={
                "skill_name": name,
                "skill_type": skill_type,
                "path": str(skill_dir),
                "yaml": yaml_content,
            },
            files_modified=[
                str(skill_yaml),
                str(skill_dir / "scripts" / ".gitkeep"),
                str(skill_dir / "references" / ".gitkeep"),
                str(skill_dir / "assets" / ".gitkeep"),
            ],
        )
    
    def _create_openclaw_skill(
        self,
        name: str,
        description: str,
        with_resources: bool,
        save_location: str,
        context: SkillContext,
    ) -> SkillResult:
        """Create an OpenClaw-compatible Markdown skill."""
        # Determine save path
        if save_location == "project":
            base_path = Path(".aider") / "skills"
        else:
            base_path = Path.home() / ".config" / "aider" / "skills"
        
        skill_dir = base_path / name
        
        # Check if exists
        if skill_dir.exists():
            return SkillResult(
                success=False,
                error=f"Skill '{name}' already exists at {skill_dir}",
            )
        
        # Create skill directory
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        # Create SKILL.md with OpenClaw format
        skill_md = skill_dir / "SKILL.md"
        md_content = self._generate_openclaw_markdown(name, description, context)
        with open(skill_md, "w") as f:
            f.write(md_content)
        
        files_modified = [str(skill_md)]
        
        # Create resource directories if requested
        if with_resources:
            (skill_dir / "scripts").mkdir(exist_ok=True)
            (skill_dir / "references").mkdir(exist_ok=True)
            (skill_dir / "assets").mkdir(exist_ok=True)
            
            with open(skill_dir / "scripts" / ".gitkeep", "w") as f:
                f.write(f"# Scripts for {name}: add executable helpers here.\n")
            with open(skill_dir / "references" / ".gitkeep", "w") as f:
                f.write(f"# References for {name}: add supporting notes and guides here.\n")
            with open(skill_dir / "assets" / ".gitkeep", "w") as f:
                f.write(f"# Assets for {name}: add templates, fixtures, or sample inputs here.\n")
            
            files_modified.extend([
                str(skill_dir / "scripts" / ".gitkeep"),
                str(skill_dir / "references" / ".gitkeep"),
                str(skill_dir / "assets" / ".gitkeep"),
            ])
        
        if context.io:
            context.io.tool_output(f"✅ Created OpenClaw skill: {name}")
            context.io.tool_output(f"   Location: {skill_dir}")
            context.io.tool_output("")
            context.io.tool_output(f"To use with OpenClaw:")
            context.io.tool_output(f"  cp -r {skill_dir} ~/.openclaw/skills/")
            context.io.tool_output("")
            context.io.tool_output(f"To package for distribution:")
            context.io.tool_output(f"  cd {base_path} && zip -r {name}.skill {name}")
        
        return SkillResult(
            success=True,
            output=f"Created OpenClaw skill {name} at {skill_dir}",
            data={
                "skill_name": name,
                "format": "openclaw",
                "path": str(skill_dir),
                "markdown": md_content,
            },
            files_modified=files_modified,
        )
    
    def _compact_text(self, text: str) -> str:
        """Collapse whitespace and strip surrounding space."""
        return " ".join(text.split()).strip()

    def _format_sentence(self, text: str, fallback: str = "") -> str:
        """Format text as a readable sentence without placeholder markers."""
        summary = self._compact_text(text)
        if not summary:
            return fallback
        if summary[-1] in ".!?":
            return summary
        return summary + "."

    def _generate_openclaw_markdown(self, name: str, description: str, context: str) -> str:
        """Generate OpenClaw SKILL.md content."""
        description_summary = self._format_sentence(description, "No description provided.")
        context_summary = self._format_sentence(
            context, "No additional context was provided when this skill was created."
        )
        title = name.replace("-", " ").title()
        user_request = description_summary.rstrip(".")

        return f'''---
name: {name}
description: {description}
---

# {title}

## Overview

This skill provides {description_summary}

## When to Use

Use this skill when you need to:
- Complete {description_summary.lower()}
- Reuse the workflow in similar projects or files
- Work with this context: {context_summary}

## Workflow

### Step 1: Review the request

Identify the files, inputs, and constraints before running the skill.

### Step 2: Run the workflow

Use the skill's scripts or documented steps to carry out the task.

### Step 3: Check the result

Confirm the output matches the request and capture any reusable follow-up notes.

## Resources

### scripts/
Executable scripts for this skill live here when the workflow needs code.

### references/
Reference notes, examples, and runbooks for this skill live here.

### assets/
Templates, fixtures, and sample inputs for this skill live here.

## Examples

### Example 1: {title}

**User:** "Use {name} to {user_request}"

**Skill workflow:**
1. Review the request and supporting files.
2. Execute the skill workflow.
3. Return the result and any follow-up notes.

## Notes

- Expand `scripts/` and `references/` as the skill matures.
- Keep reusable assets in `assets/` instead of embedding them in the workflow.
'''
    
    def _generate_yaml(self, name: str, description: str, skill_type: str, context: str) -> str:
        """Generate YAML content based on skill type."""
        generators = {
            "shell": self._generate_shell_yaml,
            "composite": self._generate_composite_yaml,
            "analysis": self._generate_analysis_yaml,
            "lint": self._generate_lint_yaml,
            "test": self._generate_test_yaml,
            "format": self._generate_format_yaml,
            "search": self._generate_search_yaml,
        }
        
        generator = generators.get(skill_type, self._generate_shell_yaml)
        return generator(name, description, context)
    
    def _generate_shell_yaml(self, name: str, description: str, context: str) -> str:
        """Generate a generic shell skill YAML."""
        description_summary = self._compact_text(description)
        context_summary = self._compact_text(context)
        context_note = (
            f'    # Context: {context_summary}\n' if context_summary else ""
        )
        return f'''name: {name}
description: "{description}"
supports_agents: false
parameters:
  input:
    type: string
    description: "Primary input for the skill"
handler:
  type: shell
  command: |
{context_note}    set -euo pipefail
    echo "Running {name}"
    echo "Description: {description_summary}"
    if [ -n "{{{{ input }}}}" ]; then
      printf '%s\n' "{{{{ input }}}}"
    fi
  timeout: 300
'''
    
    def _generate_lint_yaml(self, name: str, description: str, context: str) -> str:
        """Generate a linting skill YAML."""
        tool = "eslint" if "javascript" in context.lower() or "js" in context.lower() else "flake8"
        if "python" in context.lower():
            tool = "flake8"
        elif "rust" in context.lower():
            tool = "cargo clippy"
        elif "go" in context.lower():
            tool = "golint"
        
        return f'''name: {name}
description: "{description}"
supports_agents: false
parameters:
  files:
    type: string
    description: "Files or directories to lint"
    default: "src/"
  fix:
    type: boolean
    description: "Auto-fix issues where possible"
    default: false
handler:
  type: shell
  command: |
    if [ "{{{{ fix }}}}" = "true" ]; then
      {tool} --fix {{{{ files }}}}
    else
      {tool} {{{{ files }}}}
    fi
  timeout: 300
'''
    
    def _generate_test_yaml(self, name: str, description: str, context: str) -> str:
        """Generate a testing skill YAML."""
        framework = "pytest" if "python" in context.lower() else "jest"
        if "node" in context.lower() or "js" in context.lower():
            framework = "jest"
        
        return f'''name: {name}
description: "{description}"
supports_agents: true
max_agents: 4
parameters:
  test_path:
    type: string
    description: "Path to tests or source files"
    default: "tests/"
  coverage:
    type: boolean
    description: "Generate coverage report"
    default: true
handler:
  type: shell
  command: |
    if [ "{{{{ coverage }}}}" = "true" ]; then
      {framework} {{{{ test_path }}}} --coverage
    else
      {framework} {{{{ test_path }}}} -v
    fi
  timeout: 600
'''
    
    def _generate_format_yaml(self, name: str, description: str, context: str) -> str:
        """Generate a formatting skill YAML."""
        return f'''name: {name}
description: "{description}"
supports_agents: false
parameters:
  files:
    type: string
    description: "Files to format"
    default: "src/"
  check:
    type: boolean
    description: "Check only (don't write)"
    default: false
handler:
  type: shell
  command: |
    if [ "{{{{ check }}}}" = "true" ]; then
      prettier --check {{{{ files }}}}
    else
      prettier --write {{{{ files }}}}
    fi
  timeout: 300
'''
    
    def _generate_search_yaml(self, name: str, description: str, context: str) -> str:
        """Generate a search/grep skill YAML."""
        return f'''name: {name}
description: "{description}"
supports_agents: false
parameters:
  pattern:
    type: string
    description: "Pattern to search for"
  directory:
    type: string
    description: "Directory to search in"
    default: "."
  extension:
    type: string
    description: "File extension filter (e.g., 'py', 'js')"
    default: "*"
handler:
  type: shell
  command: |
    grep -r "{{{{ pattern }}}}" {{{{ directory }}}} --include="*.{{{{ extension }}}}"
  timeout: 60
'''
    
    def _generate_composite_yaml(self, name: str, description: str, context: str) -> str:
        """Generate a composite skill YAML."""
        return f'''name: {name}
description: "{description}"
supports_agents: true
max_agents: 3
parameters:
  target:
    type: string
    description: "Target files or directory"
    default: "src/"
handler:
  type: composite
  stop_on_error: true
  steps:
    - skill: security-audit
      files: "{{{{ target }}}}"
    - skill: code-review
      files: "{{{{ target }}}}"
    - skill: test-generation
      files: "{{{{ target }}}}"
'''
    
    def _generate_analysis_yaml(self, name: str, description: str, context: str) -> str:
        """Generate an analysis skill YAML using ACP agents."""
        return f'''name: {name}
description: "{description}"
supports_agents: true
max_agents: 2
parameters:
  target:
    type: string
    description: "Files or code to analyze"
  agent:
    type: string
    enum: [claude, codex, gemini]
    default: claude
    description: "ACP agent to use"
handler:
  type: composite
  steps:
    - skill: acp-delegate
      agent: "{{{{ agent }}}}"
      task: "{description} for: {{{{ target }}}}"
'''
    
    def _get_save_path(self, location: str, skill_name: str) -> Path:
        """Get the save path for a new skill."""
        if location == "project":
            return Path(".aider") / "skills" / f"{skill_name}.yaml"
        else:
            return Path.home() / ".config" / "aider" / "skills" / f"{skill_name}.yaml"


class SkillEditorSkill(Skill):
    """
    Edit, delete, or inspect existing YAML skills.
    
    Usage:
        aider --skill run skill-editor skill=my-skill action=show
        aider --skill run skill-editor skill=my-skill action=delete
    """
    
    name = "skill-editor"
    description = "Edit, delete, or inspect existing YAML skills"
    supports_agents = False
    
    def get_parameters(self) -> Dict[str, Any]:
        return {
            "skill": {
                "type": "string",
                "description": "Name of skill to edit",
            },
            "action": {
                "type": "string",
                "enum": ["show", "delete", "validate"],
                "default": "show",
                "description": "Action to perform",
            },
        }
    
    async def execute(self, **kwargs) -> SkillResult:
        """Edit an existing skill."""
        context = self.context
        skill_name = kwargs.get("skill", "")
        action = kwargs.get("action", "show")
        
        if not skill_name:
            return SkillResult(
                success=False,
                error="Skill name is required. Example: skill=my-linter",
            )
        
        # Find the skill file
        skill_path = self._find_skill_file(skill_name)
        
        if not skill_path:
            return SkillResult(
                success=False,
                error=f"Skill '{skill_name}' not found in ~/.config/aider/skills/ or ./.aider/skills/",
            )
        
        if action == "show":
            return self._show_skill(skill_name, skill_path, context)
        elif action == "delete":
            return self._delete_skill(skill_name, skill_path, context)
        elif action == "validate":
            return self._validate_skill(skill_name, skill_path, context)
        else:
            return SkillResult(
                success=False,
                error=f"Unknown action: {action}",
            )
    
    def _show_skill(self, name: str, path: Path, context: SkillContext) -> SkillResult:
        """Show skill content."""
        try:
            with open(path) as f:
                content = f.read()
            
            output = f"Skill: {name}\\n"
            output += f"Location: {path}\\n"
            output += "-" * 40 + "\\n"
            output += content
            
            if context.io:
                context.io.tool_output(output)
            
            return SkillResult(
                success=True,
                output=output,
                data={"path": str(path), "content": content},
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Failed to read skill: {e}",
            )
    
    def _delete_skill(self, name: str, path: Path, context: SkillContext) -> SkillResult:
        """Delete a skill."""
        try:
            path.unlink()
            
            if context.io:
                context.io.tool_output(f"🗑️ Deleted skill: {name}")
                context.io.tool_output(f"   Location: {path}")
            
            return SkillResult(
                success=True,
                output=f"Deleted skill {name}",
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Failed to delete: {e}",
            )
    
    def _validate_skill(self, name: str, path: Path, context: SkillContext) -> SkillResult:
        """Validate a skill's YAML format."""
        try:
            import yaml
            with open(path) as f:
                data = yaml.safe_load(f)
            
            errors = []
            if not data.get("name"):
                errors.append("Missing 'name' field")
            if not data.get("description"):
                errors.append("Missing 'description' field")
            if not data.get("handler"):
                errors.append("Missing 'handler' section")
            
            if errors:
                return SkillResult(
                    success=False,
                    error="Validation failed: " + "; ".join(errors),
                    data={"errors": errors},
                )
            
            if context.io:
                context.io.tool_output(f"✅ Skill {name} is valid")
            
            return SkillResult(
                success=True,
                output=f"Skill {name} is valid",
                data={"name": data.get("name"), "description": data.get("description")},
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Validation failed: {e}",
            )
    
    def _find_skill_file(self, skill_name: str) -> Path:
        """Find a skill file by name."""
        locations = [
            Path.home() / ".config" / "aider" / "skills" / f"{skill_name}.yaml",
            Path(".aider") / "skills" / f"{skill_name}.yaml",
        ]
        
        for path in locations:
            if path.exists():
                return path
        
        return None


class SkillPackageSkill(Skill):
    """
    Package skills into distributable .skill files (zip archives).
    
    Usage:
        aider --skill run skill-package skill=my-skill
    """
    
    name = "skill-package"
    description = "Package skills into distributable .skill files"
    supports_agents = False
    
    def get_parameters(self) -> Dict[str, Any]:
        return {
            "skill": {
                "type": "string",
                "description": "Name of skill to package",
            },
            "output_dir": {
                "type": "string",
                "description": "Output directory for .skill file",
                "default": "./",
            },
        }
    
    async def execute(self, **kwargs) -> SkillResult:
        """Package a skill into a .skill file."""
        context = self.context
        skill_name = kwargs.get("skill", "")
        output_dir = kwargs.get("output_dir", "./")
        
        if not skill_name:
            return SkillResult(
                success=False,
                error="Skill name is required",
            )
        
        # Find skill
        skill_path = self._find_skill(skill_name)
        if not skill_path:
            return SkillResult(
                success=False,
                error=f"Skill '{skill_name}' not found",
            )
        
        # Create output path
        output_path = Path(output_dir) / f"{skill_name}.skill"
        
        try:
            # Create zip file
            if skill_path.is_file():
                # Single file skill
                with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(skill_path, arcname=f"{skill_name}/SKILL.md")
            else:
                # Directory skill with resources
                with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for file_path in skill_path.rglob("*"):
                        if file_path.is_file():
                            arcname = f"{skill_name}/{file_path.relative_to(skill_path)}"
                            zf.write(file_path, arcname=arcname)
            
            if context.io:
                context.io.tool_output(f"📦 Packaged skill: {skill_name}")
                context.io.tool_output(f"   Output: {output_path}")
            
            return SkillResult(
                success=True,
                output=f"Packaged {skill_name} to {output_path}",
                files_modified=[str(output_path)],
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Failed to package: {e}",
            )
    
    def _find_skill(self, skill_name: str) -> Path:
        """Find skill file or directory."""
        locations = [
            Path.home() / ".config" / "aider" / "skills" / f"{skill_name}.yaml",
            Path.home() / ".config" / "aider" / "skills" / skill_name,
            Path(".aider") / "skills" / f"{skill_name}.yaml",
            Path(".aider") / "skills" / skill_name,
        ]
        
        for path in locations:
            if path.exists():
                return path
        
        return None
