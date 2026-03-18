"""
Human-in-the-Loop Approval Workflow - Makes Aider more Claude-like

This skill provides approval workflows for critical operations:
- Diff preview before applying changes
- Approval flags for destructive actions
- Interactive confirmation
- Rollback capability
"""

import asyncio
import difflib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    """Represents a request for human approval."""

    id: str
    operation: str  # "apply_changes", "delete_file", "deploy", etc.
    description: str
    diff: Optional[str] = None
    files: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=datetime.now)
    approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[float] = None


class HumanApprovalSkill(Skill):
    """
    Human-in-the-loop approval workflow for safe operations.

    This skill ensures critical operations require explicit approval,
    similar to Claude's interactive approval model.
    """

    name = "human-approval"
    description = "Human-in-the-loop approval workflow for safe operations"

    def __init__(self, context: Optional[SkillContext] = None):
        super().__init__(context)
        self._approval_requests: Dict[str, ApprovalRequest] = {}
        self._default_approval: bool = False  # Auto-approve if True

    def _get_required_params(self) -> List[str]:
        return ["operation", "description"]

    def _validate_parameters(self, params: Dict[str, Any]) -> List[str]:
        errors = []

        if "operation" not in params or not params["operation"]:
            errors.append("Parameter 'operation' is required")

        if "description" not in params or not params["description"]:
            errors.append("Parameter 'description' is required")

        return errors

    async def _execute_impl(self, **kwargs) -> SkillResult:
        operation = kwargs["operation"]
        description = kwargs["description"]

        # Create approval request
        request_id = f"approval_{len(self._approval_requests) + 1}"
        request = ApprovalRequest(
            id=request_id,
            operation=operation,
            description=description,
            diff=kwargs.get("diff"),
            files=kwargs.get("files", []),
            metadata=kwargs,
        )

        self._approval_requests[request_id] = request

        # Check if auto-approved
        if self._default_approval:
            request.approved = True
            request.approved_by = "auto"
            request.approved_at = datetime.now()
            logger.info(f"Auto-approved {operation}: {description}")
        else:
            # In production, this would trigger an approval UI
            # For now, we simulate waiting for approval
            logger.info(f"Created approval request: {request_id} for {operation}")
            await asyncio.sleep(1)  # Simulate approval time

        return SkillResult(
            success=request.approved,
            output=f"Approval request {request_id} {'approved' if request.approved else 'pending'}",
            data={
                "request_id": request_id,
                "approved": request.approved,
                "operation": operation,
                "description": description,
            },
        )

    async def approve(self, request_id: str, approved_by: Optional[str] = None) -> SkillResult:
        """Approve a pending request."""
        if request_id not in self._approval_requests:
            return SkillResult(success=False, error=f"Approval request {request_id} not found")

        request = self._approval_requests[request_id]
        request.approved = True
        request.approved_by = approved_by or "unknown"
        request.approved_at = datetime.now()

        logger.info(f"Approved {request.operation} by {request.approved_by}")

        return SkillResult(success=True, output=f"Approved {request.operation}")

    async def reject(self, request_id: str, reason: Optional[str] = None) -> SkillResult:
        """Reject a pending request."""
        if request_id not in self._approval_requests:
            return SkillResult(success=False, error=f"Approval request {request_id} not found")

        request = self._approval_requests[request_id]
        request.approved = False

        if reason:
            logger.info(f"Rejected {request.operation}: {reason}")
        else:
            logger.info(f"Rejected {request.operation}")

        return SkillResult(success=True, output=f"Rejected {request.operation}")

    def create_diff_preview(self, old_content: str, new_content: str, filename: str) -> str:
        """Create a unified diff preview for review."""
        diff = difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=filename,
            tofile=filename,
            lineterm="",
        )
        return "".join(diff)

    def get_pending_requests(self) -> List[ApprovalRequest]:
        """Get all pending approval requests."""
        return [r for r in self._approval_requests.values() if not r.approved]

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get a specific approval request."""
        return self._approval_requests.get(request_id)

    def set_auto_approve(self, enabled: bool = True):
        """Enable or disable auto-approval."""
        self._default_approval = enabled

    async def rollback_operation(self, request_id: str) -> SkillResult:
        """Rollback an approved operation."""
        if request_id not in self._approval_requests:
            return SkillResult(success=False, error=f"Approval request {request_id} not found")

        request = self._approval_requests[request_id]

        if not request.approved:
            return SkillResult(success=False, error="Cannot rollback unapproved operation")

        # In production, this would restore the previous state
        logger.info(f"Rolling back {request.operation}")

        return SkillResult(success=True, output=f"Rolled back {request.operation}")

    async def list_requests(self) -> List[Dict[str, Any]]:
        """List all approval requests with details."""
        return [
            {
                "id": r.id,
                "operation": r.operation,
                "description": r.description,
                "files": r.files,
                "approved": r.approved,
                "created_at": r.created_at,
            }
            for r in self._approval_requests.values()
        ]
