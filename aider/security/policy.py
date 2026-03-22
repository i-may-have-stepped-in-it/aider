"""
Security Policy Engine for Automated AI Guardrails.

This module provides an enterprise-grade security policy engine to scan 
AI-generated plans and code for vulnerabilities (secrets, command injection, etc).
"""

import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

@dataclass
class SecurityViolation:
    """Represents a specific security violation."""
    rule_name: str
    severity: str  # "CRITICAL", "WARNING", "INFO"
    message: str
    context: Optional[str] = None
    line_no: Optional[int] = None

@dataclass
class PolicyResult:
    """Consolidated result from a security policy scan."""
    success: bool
    violations: List[SecurityViolation] = field(default_factory=list)
    
    @property
    def has_critical(self) -> bool:
        """Check if any violations are critical."""
        return any(v.severity == "CRITICAL" for v in self.violations)

class SecurityRule(ABC):
    """Abstract Base Class for security rules."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Rule name."""
        pass

    @abstractmethod
    def scan(self, content: str) -> List[SecurityViolation]:
        """Scan content for violations of this rule."""
        pass

class SecretScannerRule(SecurityRule):
    """Detects API keys and other secrets using regex."""
    
    name = "Secret Scanner"
    
    # Common secret patterns
    PATTERNS = {
        "Generic API Key": r"(?:key|api|token|secret|password|auth)[\"']?\s*[:=]\s*[\"']([a-zA-Z0-9\-]{16,})[\"']",
        "AWS Access Key": r"AKIA[0-9A-Z]{16}",
        "Stripe API Key": r"sk_live_[0-9a-zA-Z]{24}",
        "Slack Token": r"xox[baprs]-[0-9a-zA-Z]{10,48}",
    }

    def scan(self, content: str) -> List[SecurityViolation]:
        violations = []
        for label, pattern in self.PATTERNS.items():
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                violations.append(SecurityViolation(
                    rule_name=self.name,
                    severity="CRITICAL",
                    message=f"Potential {label} detected.",
                    context=match.group(0)
                ))
        return violations

class UnsafeShellRule(SecurityRule):
    """Detects unsafe shell execution patterns."""
    
    name = "Unsafe Shell"
    
    PATTERNS = [
        (r"shell=True", "CRITICAL", "Dangerous 'shell=True' found in subprocess call."),
        (r"os\.system\(", "CRITICAL", "Dangerous 'os.system' call found."),
        (r"subprocess\.Popen\(", "WARNING", "Review subprocess.Popen usage for command injection."),
    ]

    def scan(self, content: str) -> List[SecurityViolation]:
        violations = []
        for pattern, severity, message in self.PATTERNS:
            if re.search(pattern, content):
                violations.append(SecurityViolation(
                    rule_name=self.name,
                    severity=severity,
                    message=message
                ))
        return violations

class PathTraversalRule(SecurityRule):
    """Detects potential path traversal attempts."""
    
    name = "Path Traversal"
    
    PATTERNS = [
        (r"\.\.\/", "CRITICAL", "Potential path traversal detected ('../')."),
        (r"\/etc\/passwd", "CRITICAL", "Attempt to access sensitive system file (/etc/passwd)."),
        (r"\/etc\/shadow", "CRITICAL", "Attempt to access sensitive system file (/etc/shadow)."),
    ]

    def scan(self, content: str) -> List[SecurityViolation]:
        violations = []
        for pattern, severity, message in self.PATTERNS:
            if re.search(pattern, content):
                violations.append(SecurityViolation(
                    rule_name=self.name,
                    severity=severity,
                    message=message
                ))
        return violations

class PolicyEngine:
    """Orchestrates security rules to scan AI generated content."""
    
    def __init__(self, rules: Optional[List[SecurityRule]] = None):
        self.rules = rules or [
            SecretScannerRule(),
            UnsafeShellRule(),
            PathTraversalRule(),
        ]

    def scan(self, content: str) -> PolicyResult:
        """Run all security rules against the provided content."""
        all_violations = []
        for rule in self.rules:
            try:
                all_violations.extend(rule.scan(content))
            except Exception as e:
                logger.error(f"Security rule '{rule.name}' failed: {e}")
        
        # If any CRITICAL violations found, scan fails
        success = not any(v.severity == "CRITICAL" for v in all_violations)
        return PolicyResult(success=success, violations=all_violations)
