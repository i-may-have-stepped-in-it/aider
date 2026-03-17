#!/usr/bin/env python3
"""
OpenClaw Bridge - Core integration module for Aider.

This module provides integration between Aider and OpenClaw skills, enabling:
- Discovery of OpenClaw skills
- Loading and parsing skill metadata
- Execution of skill scripts
- Conversion of skill output to Aider-compatible formats
"""

import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Configure logging
logger = logging.getLogger(__name__)

# Default paths for OpenClaw skills
DEFAULT_OPENCLAW_PATHS = [
    Path("/home/openclaw/openclaw/skills"),
    Path("/home/openclaw/.openclaw/skills"),
    Path.home() / ".openclaw" / "skills",
]

# Environment variable override
OPENCLAW_SKILLS_PATH_ENV = "OPENCLAW_SKILLS_PATH"


@dataclass
class SkillMetadata:
    """Represents parsed metadata from a SKILL.md file."""
    
    name: str
    description: str
    emoji: str = "🔧"
    requires: Dict[str, Any] = field(default_factory=dict)
    install: List[Dict[str, Any]] = field(default_factory=list)
    homepage: Optional[str] = None
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def full_name(self) -> str:
        """Return the full display name with emoji."""
        return f"{self.emoji} {self.name}"


@dataclass
class SkillExecutionResult:
    """Result of executing a skill script."""
    
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    skill_name: str
    action: str
    error_message: Optional[str] = None
    
    def to_aider_format(self) -> str:
        """Convert result to Aider-compatible output format."""
        lines = []
        
        if self.success:
            lines.append(f"✅ Skill '{self.skill_name}' executed successfully")
        else:
            lines.append(f"❌ Skill '{self.skill_name}' failed (exit code: {self.exit_code})")
        
        if self.stdout:
            lines.append("\n📤 Output:")
            lines.append(self.stdout)
        
        if self.stderr:
            lines.append("\n⚠️  Errors:")
            lines.append(self.stderr)
        
        if self.error_message:
            lines.append(f"\n💥 Error: {self.error_message}")
        
        lines.append(f"\n⏱️  Duration: {self.duration_ms}ms")
        
        return "\n".join(lines)
    
    def to_json(self) -> Dict[str, Any]:
        """Convert result to JSON-serializable dict."""
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "skill_name": self.skill_name,
            "action": self.action,
            "error_message": self.error_message,
        }


class SkillDiscoveryError(Exception):
    """Raised when skill discovery fails."""
    pass


class SkillExecutionError(Exception):
    """Raised when skill execution fails."""
    pass


class OpenClawBridge:
    """
    Core bridge class for integrating OpenClaw skills with Aider.
    
    Handles skill discovery, metadata loading, and script execution.
    """
    
    def __init__(self, skills_paths: Optional[List[Path]] = None):
        """
        Initialize the OpenClaw bridge.
        
        Args:
            skills_paths: Optional list of paths to search for skills.
                         Defaults to standard OpenClaw skill paths.
        """
        self.skills_paths = skills_paths or self._get_default_paths()
        self._skills_cache: Dict[str, Path] = {}
        self._metadata_cache: Dict[str, SkillMetadata] = {}
        
        logger.debug(f"OpenClawBridge initialized with paths: {self.skills_paths}")
    
    def _get_default_paths(self) -> List[Path]:
        """Get default skill search paths."""
        paths = []
        
        # Check environment variable first
        env_path = os.environ.get(OPENCLAW_SKILLS_PATH_ENV)
        if env_path:
            paths.extend([Path(p.strip()) for p in env_path.split(os.pathsep)])
        
        # Add default paths
        paths.extend(DEFAULT_OPENCLAW_PATHS)
        
        # Filter to existing paths
        return [p for p in paths if p.exists()]
    
    def discover_skills(self, force_refresh: bool = False) -> Dict[str, Path]:
        """
        Discover all available OpenClaw skills.
        
        Args:
            force_refresh: If True, ignore cache and rescan.
        
        Returns:
            Dictionary mapping skill names to their directory paths.
        
        Raises:
            SkillDiscoveryError: If no skills can be discovered.
        """
        if self._skills_cache and not force_refresh:
            return self._skills_cache.copy()
        
        skills: Dict[str, Path] = {}
        
        for base_path in self.skills_paths:
            if not base_path.exists():
                logger.debug(f"Skills path does not exist: {base_path}")
                continue
            
            logger.debug(f"Scanning for skills in: {base_path}")
            
            try:
                for skill_dir in base_path.iterdir():
                    if not skill_dir.is_dir():
                        continue
                    
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        skill_name = skill_dir.name
                        
                        # Handle duplicates - prefer first found
                        if skill_name not in skills:
                            skills[skill_name] = skill_dir
                            logger.debug(f"Found skill: {skill_name} at {skill_dir}")
            
            except PermissionError as e:
                logger.warning(f"Permission denied accessing {base_path}: {e}")
            except Exception as e:
                logger.warning(f"Error scanning {base_path}: {e}")
        
        if not skills:
            raise SkillDiscoveryError(
                f"No OpenClaw skills found in paths: {self.skills_paths}"
            )
        
        self._skills_cache = skills
        logger.info(f"Discovered {len(skills)} skills")
        return skills.copy()
    
    def get_skill_path(self, skill_name: str) -> Optional[Path]:
        """
        Get the directory path for a specific skill.
        
        Args:
            skill_name: Name of the skill.
        
        Returns:
            Path to the skill directory, or None if not found.
        """
        # Check cache first
        if skill_name in self._skills_cache:
            return self._skills_cache[skill_name]
        
        # Try to discover
        try:
            skills = self.discover_skills()
            return skills.get(skill_name)
        except SkillDiscoveryError:
            return None
    
    def load_skill_metadata(self, skill_name: str) -> Optional[SkillMetadata]:
        """
        Load and parse metadata for a specific skill.
        
        Args:
            skill_name: Name of the skill.
        
        Returns:
            Parsed SkillMetadata, or None if skill not found.
        
        Raises:
            SkillDiscoveryError: If the skill metadata is invalid.
        """
        # Check cache
        if skill_name in self._metadata_cache:
            return self._metadata_cache[skill_name]
        
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            logger.warning(f"Skill not found: {skill_name}")
            return None
        
        skill_md_path = skill_path / "SKILL.md"
        
        try:
            content = skill_md_path.read_text(encoding="utf-8")
            metadata = self._parse_skill_md(content, skill_name)
            self._metadata_cache[skill_name] = metadata
            return metadata
        
        except FileNotFoundError:
            logger.error(f"SKILL.md not found for {skill_name}")
            return None
        except Exception as e:
            raise SkillDiscoveryError(f"Error parsing {skill_md_path}: {e}")
    
    def _parse_skill_md(self, content: str, skill_name: str) -> SkillMetadata:
        """
        Parse SKILL.md content to extract metadata.
        
        Args:
            content: Raw content of SKILL.md.
            skill_name: Name of the skill (fallback if not in frontmatter).
        
        Returns:
            Parsed SkillMetadata object.
        """
        # Parse YAML frontmatter
        frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        
        if not frontmatter_match:
            # No frontmatter - use defaults
            return SkillMetadata(
                name=skill_name,
                description=self._extract_description(content) or f"OpenClaw skill: {skill_name}",
            )
        
        frontmatter = frontmatter_match.group(1)
        
        # Parse frontmatter fields
        name = skill_name
        description = ""
        emoji = "🔧"
        requires = {}
        install = []
        homepage = None
        raw_metadata = {}
        
        # Simple YAML parsing for common patterns
        # Extract name
        name_match = re.search(r'^name:\s*(.+)$', frontmatter, re.MULTILINE)
        if name_match:
            name = name_match.group(1).strip().strip('"\'')
        
        # Extract description
        desc_match = re.search(r'^description:\s*["\']?(.+?)["\']?$', frontmatter, re.MULTILINE | re.DOTALL)
        if desc_match:
            description = desc_match.group(1).strip().replace('\n', ' ')
        
        # Extract homepage
        homepage_match = re.search(r'^homepage:\s*(\S+)$', frontmatter, re.MULTILINE)
        if homepage_match:
            homepage = homepage_match.group(1).strip()
        
        # Extract openclaw metadata
        openclaw_match = re.search(
            r'metadata:\s*\n?\s*openclaw:\s*\n?(.*?)(?:\n\w|\n---|$)',
            frontmatter, re.MULTILINE | re.DOTALL
        )
        
        if openclaw_match:
            oc_section = openclaw_match.group(1)
            
            # Extract emoji
            emoji_match = re.search(r'emoji:\s*["\']?(.+?)["\']?\s*$', oc_section, re.MULTILINE)
            if emoji_match:
                emoji = emoji_match.group(1).strip()
            
            # Try to parse as JSON if it looks like JSON
            try:
                # Look for JSON-style metadata
                json_match = re.search(r'metadata:\s*(\{.*?\})', frontmatter, re.DOTALL)
                if json_match:
                    raw_metadata = json.loads(json_match.group(1))
                    if 'openclaw' in raw_metadata:
                        oc_data = raw_metadata['openclaw']
                        emoji = oc_data.get('emoji', emoji)
                        requires = oc_data.get('requires', {})
                        install = oc_data.get('install', [])
            except json.JSONDecodeError:
                pass
        
        # Fallback description extraction from body
        if not description:
            description = self._extract_description(content) or f"OpenClaw skill: {name}"
        
        return SkillMetadata(
            name=name,
            description=description,
            emoji=emoji,
            requires=requires,
            install=install,
            homepage=homepage,
            raw_metadata=raw_metadata,
        )
    
    def _extract_description(self, content: str) -> Optional[str]:
        """Extract description from markdown body (first paragraph)."""
        # Remove frontmatter
        body = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL)
        
        # Find first non-empty paragraph
        paragraphs = body.split('\n\n')
        for para in paragraphs:
            para = para.strip()
            # Skip headings and empty lines
            if para and not para.startswith('#') and not para.startswith('---'):
                # Remove markdown links
                para = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', para)
                # Remove inline code backticks for display
                para = re.sub(r'`([^`]+)`', r'\1', para)
                return para[:200] + ('...' if len(para) > 200 else '')
        
        return None
    
    def list_skills(self, category: Optional[str] = None) -> List[SkillMetadata]:
        """
        List all available skills with their metadata.
        
        Args:
            category: Optional category filter.
        
        Returns:
            List of SkillMetadata objects.
        """
        skills = self.discover_skills()
        result = []
        
        for skill_name in sorted(skills.keys()):
            metadata = self.load_skill_metadata(skill_name)
            if metadata:
                result.append(metadata)
        
        return result
    
    def find_skill_scripts(self, skill_name: str) -> List[Path]:
        """
        Find all executable scripts for a skill.
        
        Args:
            skill_name: Name of the skill.
        
        Returns:
            List of script paths.
        """
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            return []
        
        scripts_dir = skill_path / "scripts"
        if not scripts_dir.exists():
            return []
        
        scripts = []
        for script in scripts_dir.iterdir():
            if script.is_file() and not script.name.startswith('.'):
                # Check if executable or has known script extension
                if self._is_executable_script(script):
                    scripts.append(script)
        
        return sorted(scripts)
    
    def _is_executable_script(self, path: Path) -> bool:
        """Check if a file is an executable script."""
        # Check for shebang or executable permission
        if os.access(path, os.X_OK):
            return True
        
        # Check for known extensions
        known_extensions = {'.py', '.sh', '.bash', '.zsh', '.rb', '.pl', '.js'}
        if path.suffix in known_extensions:
            return True
        
        # Check for shebang
        try:
            with open(path, 'rb') as f:
                first_line = f.readline()
                if first_line.startswith(b'#!'):
                    return True
        except Exception:
            pass
        
        return False
    
    def execute_skill(
        self,
        skill_name: str,
        action: str = "run",
        args: Optional[List[str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: int = 300,
        working_dir: Optional[Path] = None,
    ) -> SkillExecutionResult:
        """
        Execute a skill script.
        
        Args:
            skill_name: Name of the skill to execute.
            action: Action to perform (default: "run").
            args: Additional arguments to pass to the script.
            env_vars: Additional environment variables.
            timeout: Maximum execution time in seconds.
            working_dir: Working directory for execution.
        
        Returns:
            SkillExecutionResult with execution details.
        
        Raises:
            SkillExecutionError: If the skill cannot be executed.
        """
        import time
        
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            return SkillExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=0,
                skill_name=skill_name,
                action=action,
                error_message=f"Skill '{skill_name}' not found",
            )
        
        # Find the script to execute
        script = self._find_script(skill_path, skill_name, action)
        if not script:
            return SkillExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=0,
                skill_name=skill_name,
                action=action,
                error_message=f"No executable script found for skill '{skill_name}' action '{action}'",
            )
        
        # Build command
        cmd = [str(script)]
        if args:
            cmd.extend(args)
        
        # Prepare environment
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        
        # Add skill context to environment
        env["OPENCLAW_SKILL_NAME"] = skill_name
        env["OPENCLAW_SKILL_PATH"] = str(skill_path)
        env["OPENCLAW_ACTION"] = action
        
        # Set working directory
        cwd = working_dir or skill_path
        
        logger.info(f"Executing skill: {skill_name} (action: {action}, script: {script})")
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return SkillExecutionResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=duration_ms,
                skill_name=skill_name,
                action=action,
            )
        
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start_time) * 1000)
            return SkillExecutionResult(
                success=False,
                exit_code=124,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                skill_name=skill_name,
                action=action,
                error_message=f"Execution timed out after {timeout}s",
            )
        
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return SkillExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                skill_name=skill_name,
                action=action,
                error_message=f"Execution failed: {e}",
            )
    
    def _find_script(self, skill_path: Path, skill_name: str, action: str) -> Optional[Path]:
        """Find the appropriate script for a skill action."""
        scripts_dir = skill_path / "scripts"
        if not scripts_dir.exists():
            return None
        
        # Priority order for script names
        candidates = [
            scripts_dir / f"{action}.py",
            scripts_dir / f"{action}.sh",
            scripts_dir / action,
            scripts_dir / f"{skill_name}.py",
            scripts_dir / f"{skill_name}.sh",
            scripts_dir / skill_name,
            scripts_dir / "run.py",
            scripts_dir / "run.sh",
            scripts_dir / "run",
        ]
        
        for candidate in candidates:
            if candidate.exists() and self._is_executable_script(candidate):
                return candidate
        
        return None
    
    def search_skills(self, query: str) -> List[Tuple[SkillMetadata, float]]:
        """
        Search skills by query string.
        
        Args:
            query: Search query.
        
        Returns:
            List of (metadata, relevance_score) tuples.
        """
        query_lower = query.lower()
        results = []
        
        for metadata in self.list_skills():
            score = 0.0
            
            # Name match (highest weight)
            if query_lower in metadata.name.lower():
                score += 1.0
            
            # Description match
            if query_lower in metadata.description.lower():
                score += 0.5
            
            # Partial word match
            query_words = query_lower.split()
            desc_words = metadata.description.lower().split()
            for word in query_words:
                if word in desc_words:
                    score += 0.3
            
            if score > 0:
                results.append((metadata, score))
        
        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results
    
    def validate_skill(self, skill_name: str) -> Dict[str, Any]:
        """
        Validate a skill's structure and requirements.
        
        Args:
            skill_name: Name of the skill to validate.
        
        Returns:
            Validation results dictionary.
        """
        result = {
            "skill": skill_name,
            "valid": False,
            "checks": {},
            "errors": [],
            "warnings": [],
        }
        
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            result["errors"].append("Skill not found")
            return result
        
        # Check SKILL.md exists
        skill_md = skill_path / "SKILL.md"
        result["checks"]["has_skill_md"] = skill_md.exists()
        if not skill_md.exists():
            result["errors"].append("Missing SKILL.md")
        
        # Try to load metadata
        metadata = None
        try:
            metadata = self.load_skill_metadata(skill_name)
            result["checks"]["metadata_valid"] = metadata is not None
            if metadata:
                result["metadata"] = {
                    "name": metadata.name,
                    "description": metadata.description[:100] + "..." if len(metadata.description) > 100 else metadata.description,
                    "emoji": metadata.emoji,
                }
        except Exception as e:
            result["checks"]["metadata_valid"] = False
            result["errors"].append(f"Metadata error: {e}")
        
        # Check for scripts
        scripts = self.find_skill_scripts(skill_name)
        result["checks"]["has_scripts"] = len(scripts) > 0
        result["checks"]["script_count"] = len(scripts)
        result["scripts"] = [s.name for s in scripts]
        
        if not scripts:
            result["warnings"].append("No executable scripts found")
        
        # Check requirements
        if metadata and metadata.requires:
            bins = metadata.requires.get("bins", [])
            missing_bins = []
            for binary in bins:
                if not self._check_binary(binary):
                    missing_bins.append(binary)
            
            result["checks"]["requirements_met"] = len(missing_bins) == 0
            if missing_bins:
                result["warnings"].append(f"Missing binaries: {', '.join(missing_bins)}")
        
        # Overall validity
        result["valid"] = len(result["errors"]) == 0
        
        return result
    
    def _check_binary(self, binary: str) -> bool:
        """Check if a binary is available in PATH."""
        try:
            subprocess.run(
                ["which", binary],
                capture_output=True,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False


# Singleton instance for reuse
_bridge_instance: Optional[OpenClawBridge] = None


def get_bridge(skills_paths: Optional[List[Path]] = None) -> OpenClawBridge:
    """
    Get or create the singleton OpenClawBridge instance.
    
    Args:
        skills_paths: Optional paths to initialize with.
    
    Returns:
        OpenClawBridge instance.
    """
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = OpenClawBridge(skills_paths)
    return _bridge_instance


def reset_bridge():
    """Reset the singleton instance (useful for testing)."""
    global _bridge_instance
    _bridge_instance = None
