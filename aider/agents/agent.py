"""
Core agent types for the Aider multi-agent system.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from aider.coders.base_coder import Coder


class AgentStatus(Enum):
    """Status of a sub-agent."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    ERROR = auto()
    CANCELLED = auto()


@dataclass
class AgentResult:
    """Result from a sub-agent execution."""

    success: bool
    output: str = ""
    error: Optional[str] = None
    files_modified: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    execution_time: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "files_modified": self.files_modified,
            "token_usage": self.token_usage,
            "execution_time": self.execution_time,
        }


@dataclass
class SubAgent:
    """
    A sub-agent spawned for a specific task.

    Inspired by kimi-cli's multi-agent system.
    Each sub-agent has isolated context while sharing the parent's
    repository and configuration.
    """

    id: str
    name: str
    task: str
    status: AgentStatus = AgentStatus.PENDING

    # Configuration
    model: Optional[str] = None
    edit_format: Optional[str] = None
    files: list[str] = field(default_factory=list)
    readonly_files: list[str] = field(default_factory=list)

    # Execution
    coder: Optional[Coder] = field(default=None, repr=False)
    result: Optional[AgentResult] = None
    error: Optional[str] = None

    # Metadata
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    parent_id: Optional[str] = None

    # Progress tracking
    progress: str = ""
    messages: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "task": self.task,
            "status": self.status.name,
            "model": self.model,
            "edit_format": self.edit_format,
            "files": self.files,
            "readonly_files": self.readonly_files,
            "result": self.result.to_dict() if self.result else None,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "parent_id": self.parent_id,
            "progress": self.progress,
        }

    @property
    def execution_time(self) -> float:
        """Calculate execution time."""
        if self.started_at is None:
            return 0.0
        end_time = self.completed_at or time.time()
        return end_time - self.started_at

    @property
    def is_active(self) -> bool:
        """Check if agent is currently running."""
        return self.status in (AgentStatus.PENDING, AgentStatus.RUNNING)

    def update_progress(self, message: str) -> None:
        """Update progress message."""
        self.progress = message
        self.messages.append(
            {
                "timestamp": time.time(),
                "message": message,
            }
        )
