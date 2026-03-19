"""
Enterprise Audit & Compliance Manager.

This module provides automated traceability and audit logging for AI-driven 
code changes, ensuring accountability and compliance in enterprise environments.
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

@dataclass
class AuditEvent:
    """Represents a single event in the session lifecycle."""
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SessionTraceability:
    """Complete traceability matrix for a single AI session."""
    session_id: str
    start_time: float = field(default_factory=time.time)
    user_request: str = ""
    librarian_files: List[str] = field(default_factory=list)
    architect_plan: str = ""
    security_status: str = "pending"
    security_violations: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    final_diffs: Dict[str, str] = field(default_factory=dict)
    total_cost: float = 0.0
    end_time: Optional[float] = None
    events: List[AuditEvent] = field(default_factory=list)

class AuditManager:
    """
    Manages session auditing and compliance reporting.
    """

    def __init__(self, root_dir: str):
        self.root = Path(root_dir)
        self.audit_dir = self.root / ".aider" / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize session traceability
        self.trace = SessionTraceability(
            session_id=f"audit_{int(time.time())}"
        )

    def log_event(self, event_type: str, **details):
        """Log a specific audit event."""
        event = AuditEvent(event_type=event_type, details=details)
        self.trace.events.append(event)
        
        # Update high-level trace fields based on event type
        if event_type == "librarian_complete":
            self.trace.librarian_files = details.get("files", [])
        elif event_type == "architect_complete":
            self.trace.architect_plan = details.get("plan", "")
        elif event_type == "security_scan":
            self.trace.security_status = "completed" if details.get("success") else "failed"
            self.trace.security_violations = details.get("violations", [])
        elif event_type == "tool_execution":
            self.trace.tool_calls.append(details)

    def finalize_report(self, cost: float, diffs: Dict[str, str]):
        """Generate and save the final audit report."""
        self.trace.end_time = time.time()
        self.trace.total_cost = cost
        self.trace.final_diffs = diffs
        
        report_path = self.audit_dir / f"{self.trace.session_id}.json"
        
        with open(report_path, "w") as f:
            json.dump(asdict(self.trace), f, indent=2)
            
        return report_path
