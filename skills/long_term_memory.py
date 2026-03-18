"""
Long-term Memory - Makes Aider more Claude/Kimi-like

This skill provides persistent context across sessions:
- Project knowledge base
- Code pattern learning
- User preference memory
- Context retention
"""

import json
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .base import Skill, SkillContext, SkillResult


@dataclass
class MemoryEntry:
    """Represents a memory entry."""
    id: str
    type: str  # "code_pattern", "user_preference", "project_knowledge", "decision"
    content: str
    tags: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=datetime.now)
    last_accessed: float = field(default_factory=datetime.now)
    access_count: int = 0
    relevance_score: float = 0.0


@dataclass
class ProjectKnowledge:
    """Project-specific knowledge."""
    project_name: str
    files: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: float = field(default_factory=datetime.now)


class LongTermMemorySkill(Skill):
    """
    Persistent memory across sessions.

    Similar to Claude's memory and Kimi's context retention.
    """

    name = "long-term-memory"
    description = "Persistent memory across sessions"

    def __init__(self, context: Optional[SkillContext] = None):
        super().__init__(context)
        self._memory: Dict[str, MemoryEntry] = {}
        self._projects: Dict[str, ProjectKnowledge] = {}
        self._max_entries: int = 1000
        self._entry_ttl: int = 30 * 24 * 60 * 60  # 30 days in seconds

    def _get_required_params(self) -> List[str]:
        return ["type", "content"]

    def _validate_parameters(self, params: Dict[str, Any]) -> List[str]:
        errors = []

        if "type" not in params or not params["type"]:
            errors.append("Parameter 'type' is required")

        if "content" not in params or not params["content"]:
            errors.append("Parameter 'content' is required")

        return errors

    async def _execute_impl(self, **kwargs) -> SkillResult:
        mem_type = kwargs["type"]
        content = kwargs["content"]

        # Create memory entry
        entry_id = f"memory_{len(self._memory) + 1}"
        entry = MemoryEntry(
            id=entry_id,
            type=mem_type,
            content=content,
            tags=kwargs.get("tags", []),
            context=kwargs.get("context", {})
        )

        self._memory[entry_id] = entry

        # Update project knowledge if applicable
        project_name = kwargs.get("project")
        if project_name:
            self._update_project(project_name, entry)

        return SkillResult(
            success=True,
            output=f"Memory entry created: {entry_id}",
            data={
                "entry_id": entry_id,
                "type": mem_type,
                "content": content[:100] + "..." if len(content) > 100 else content
            }
        )

    def _update_project(self, project_name: str, entry: MemoryEntry):
        """Update project knowledge with memory entry."""
        if project_name not in self._projects:
            self._projects[project_name] = ProjectKnowledge(project_name=project_name)

        project = self._projects[project_name]

        # Add to patterns if applicable
        if entry.type == "code_pattern":
            project.patterns.append(entry.content[:200])

        # Add to decisions if applicable
        if entry.type == "decision":
            project.decisions.append({
                "content": entry.content,
                "created_at": entry.created_at,
                "context": entry.context
            })

        # Keep only recent decisions
        if len(project.decisions) > 50:
            project.decisions = project.decisions[-50:]

        project.last_updated = datetime.now()

    def add_memory(
        self,
        mem_type: str,
        content: str,
        tags: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        project: Optional[str] = None
    ) -> str:
        """Add a memory entry."""
        entry_id = f"memory_{len(self._memory) + 1}"
        entry = MemoryEntry(
            id=entry_id,
            type=mem_type,
            content=content,
            tags=tags or [],
            context=context or {},
            relevance_score=0.0
        )

        self._memory[entry_id] = entry

        if project:
            self._update_project(project, entry)

        return entry_id

    def retrieve_memory(
        self,
        query: str,
        limit: int = 10
    ) -> List[MemoryEntry]:
        """Retrieve relevant memories."""
        # Simple keyword matching
        relevant = []

        for entry in self._memory.values():
            # Update last accessed
            entry.last_accessed = datetime.now()
            entry.access_count += 1

            # Check relevance
            query_lower = query.lower()
            content_lower = entry.content.lower()
            tags_lower = [tag.lower() for tag in entry.tags]

            score = 0.0

            # Check content
            if query_lower in content_lower:
                score += 2.0

            # Check tags
            for tag in tags_lower:
                if query_lower in tag:
                    score += 1.0

            # Check context
            for key, value in entry.context.items():
                if query_lower in str(value).lower():
                    score += 0.5

            if score > 0:
                entry.relevance_score = score
                relevant.append(entry)

        # Sort by relevance
        relevant.sort(key=lambda x: x.relevance_score, reverse=True)

        return relevant[:limit]

    def get_project_knowledge(self, project_name: str) -> ProjectKnowledge:
        """Get project-specific knowledge."""
        if project_name not in self._projects:
            return ProjectKnowledge(project_name=project_name)
        return self._projects[project_name]

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        total_entries = len(self._memory)
        total_projects = len(self._projects)

        # Calculate by type
        by_type = {}
        for entry in self._memory.values():
            entry_type = entry.type
            if entry_type not in by_type:
                by_type[entry_type] = 0
            by_type[entry_type] += 1

        # Calculate by tag
        by_tag = {}
        for entry in self._memory.values():
            for tag in entry.tags:
                if tag not in by_tag:
                    by_tag[tag] = 0
                by_tag[tag] += 1

        return {
            "total_entries": total_entries,
            "total_projects": total_projects,
            "by_type": by_type,
            "by_tag": dict(sorted(by_tag.items(), key=lambda x: x[1], reverse=True)[:10])
        }

    def clear_memory(self, entry_id: Optional[str] = None):
        """Clear memory entries."""
        if entry_id:
            if entry_id in self._memory:
                del self._memory[entry_id]
        else:
            self._memory.clear()

    def save_to_file(self, filepath: str):
        """Save memory to file."""
        data = {
            "memory": {
                entry_id: {
                    "type": entry.type,
                    "content": entry.content,
                    "tags": entry.tags,
                    "context": entry.context,
                    "created_at": entry.created_at,
                    "last_accessed": entry.last_accessed,
                    "access_count": entry.access_count
                }
                for entry_id, entry in self._memory.items()
            },
            "projects": {
                name: {
                    "files": project.files,
                    "patterns": project.patterns,
                    "decisions": project.decisions,
                    "last_updated": project.last_updated
                }
                for name, project in self._projects.items()
            }
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def load_from_file(self, filepath: str):
        """Load memory from file."""
        with open(filepath, 'r') as f:
            data = json.load(f)

        self._memory.clear()

        for entry_id, entry_data in data.get("memory", {}).items():
            self._memory[entry_id] = MemoryEntry(
                id=entry_id,
                type=entry_data["type"],
                content=entry_data["content"],
                tags=entry_data.get("tags", []),
                context=entry_data.get("context", {}),
                created_at=entry_data.get("created_at", datetime.now()),
                last_accessed=entry_data.get("last_accessed", datetime.now()),
                access_count=entry_data.get("access_count", 0)
            )

        self._projects.clear()

        for project_name, project_data in data.get("projects", {}).items():
            self._projects[project_name] = ProjectKnowledge(
                project_name=project_name,
                files=project_data.get("files", []),
                patterns=project_data.get("patterns", []),
                decisions=project_data.get("decisions", []),
                last_updated=project_data.get("last_updated", datetime.now())
            )

    async def get_relevant_context(
        self,
        query: str,
        max_entries: int = 10,
        project: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get relevant context for a query."""
        # Get project-specific knowledge
        project_knowledge = {}
        if project:
            project_data = self.get_project_knowledge(project)
            project_knowledge = {
                "project": project,
                "files": project_data.files,
                "patterns": project_data.patterns[-10:],  # Last 10 patterns
                "decisions": project_data.decisions[-5:]  # Last 5 decisions
            }

        # Get relevant memories
        memories = self.retrieve_memory(query, limit=max_entries)

        return {
            "project_knowledge": project_knowledge,
            "memories": [
                {
                    "id": m.id,
                    "type": m.type,
                    "content": m.content,
                    "tags": m.tags,
                    "relevance": m.relevance_score
                }
                for m in memories
            ]
        }

    async def forget_old_memories(self):
        """Forget memories older than TTL."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self._entry_ttl)

        to_remove = [
            entry_id
            for entry_id, entry in self._memory.items()
            if entry.created_at < cutoff
        ]

        for entry_id in to_remove:
            del self._memory[entry_id]

        return len(to_remove)
