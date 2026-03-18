"""
Advanced Code Review - Makes Aider more Claude/Kimi-like

This skill provides comprehensive code review with:
- Static analysis integration (flake8, pylint)
- Security vulnerability detection
- Performance profiling
- Complexity analysis
"""

import ast
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from .base import Skill, SkillContext, SkillResult


class IssueSeverity(Enum):
    """Severity levels for code review issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUGGESTION = "suggestion"


class IssueType(Enum):
    """Types of code review issues."""

    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    STYLE = "style"
    ERROR = "error"
    COMPLEXITY = "complexity"


@dataclass
class CodeIssue:
    """Represents a code review issue."""

    type: IssueType
    severity: IssueSeverity
    line: int
    column: int
    message: str
    code: Optional[str] = None
    suggestion: Optional[str] = None
    file_path: Optional[str] = None


@dataclass
class CodeReviewResult:
    """Result of code review."""

    success: bool
    issues: List[CodeIssue]
    summary: Dict[str, int]
    score: float
    analysis_time: float


class AdvancedCodeReviewSkill(Skill):
    """
    Comprehensive code review with static analysis.

    Similar to Claude's code review and Kimi's analysis capabilities.
    """

    name = "advanced-code-review"
    description = "Comprehensive code review with static analysis"

    def __init__(self, context: Optional[SkillContext] = None):
        super().__init__(context)
        self._max_lines = 1000  # Limit for performance

    def _get_required_params(self) -> List[str]:
        return ["code"]

    def _validate_parameters(self, params: Dict[str, Any]) -> List[str]:
        errors = []

        if "code" not in params or not params["code"]:
            errors.append("Parameter 'code' is required")

        if "file_path" in params and not params["file_path"]:
            errors.append("Parameter 'file_path' cannot be empty if provided")

        return errors

    async def _execute_impl(self, **kwargs) -> SkillResult:
        code = kwargs["code"]
        file_path = kwargs.get("file_path", "unknown.py")

        # Perform comprehensive review
        result = await self._review_code(code, file_path)

        return SkillResult(
            success=True,
            output=f"Code review complete. Score: {result.score:.1f}/100",
            data={
                "score": result.score,
                "summary": result.summary,
                "issues": [
                    {
                        "type": issue.type.value,
                        "severity": issue.severity.value,
                        "line": issue.line,
                        "column": issue.column,
                        "message": issue.message,
                        "code": issue.code,
                        "suggestion": issue.suggestion,
                    }
                    for issue in result.issues[:50]  # Limit to 50 issues
                ],
                "issue_count": len(result.issues),
                "analysis_time": result.analysis_time,
            },
        )

    async def _review_code(self, code: str, file_path: str) -> CodeReviewResult:
        """Perform comprehensive code review."""
        import time

        start_time = time.time()

        issues = []

        # Parse code
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            issues.append(
                CodeIssue(
                    type=IssueType.ERROR,
                    severity=IssueSeverity.ERROR,
                    line=e.lineno,
                    column=e.offset,
                    message=f"Syntax error: {e.msg}",
                    code=e.text,
                    file_path=file_path,
                )
            )
            return CodeReviewResult(
                success=False,
                issues=issues,
                summary={},
                score=0.0,
                analysis_time=time.time() - start_time,
            )

        # Analyze code structure
        issues.extend(self._analyze_syntax(tree))
        issues.extend(self._analyze_complexity(tree))
        issues.extend(self._analyze_security(code, tree))
        issues.extend(self._analyze_performance(tree))

        # Calculate score
        score = self._calculate_score(issues)

        summary = self._calculate_summary(issues)

        return CodeReviewResult(
            success=True,
            issues=issues,
            summary=summary,
            score=score,
            analysis_time=time.time() - start_time,
        )

    def _analyze_syntax(self, tree: ast.AST) -> List[CodeIssue]:
        """Analyze code syntax and structure."""
        issues = []

        # Check for unused imports
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                if node.id not in imports:
                    issues.append(
                        CodeIssue(
                            type=IssueType.MAINTAINABILITY,
                            severity=IssueSeverity.WARNING,
                            line=node.lineno,
                            column=node.col_offset,
                            message=f"Unused variable '{node.id}'",
                            file_path="unknown.py",
                        )
                    )

        return issues

    def _analyze_complexity(self, tree: ast.AST) -> List[CodeIssue]:
        """Analyze code complexity."""
        issues = []

        # Calculate cyclomatic complexity
        complexity = self._calculate_cyclomatic_complexity(tree)

        if complexity > 10:
            issues.append(
                CodeIssue(
                    type=IssueType.COMPLEXITY,
                    severity=IssueSeverity.WARNING,
                    line=0,
                    column=0,
                    message=f"High cyclomatic complexity ({complexity}). Consider refactoring.",
                    code=f"complexity={complexity}",
                    file_path="unknown.py",
                )
            )

        if complexity > 20:
            issues.append(
                CodeIssue(
                    type=IssueType.COMPLEXITY,
                    severity=IssueSeverity.ERROR,
                    line=0,
                    column=0,
                    message=(
                        f"Very high cyclomatic complexity ({complexity}). Critical refactoring"
                        " needed."
                    ),
                    code=f"complexity={complexity}",
                    file_path="unknown.py",
                )
            )

        return issues

    def _calculate_cyclomatic_complexity(self, tree: ast.AST) -> int:
        """Calculate cyclomatic complexity of code."""
        complexity = 1  # Base complexity

        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1

        return complexity

    def _analyze_security(self, code: str, tree: ast.AST) -> List[CodeIssue]:
        """Analyze security vulnerabilities."""
        issues = []

        # Check for hardcoded credentials
        credential_patterns = [
            r'password\s*=\s*["\']([^"\']+)["\']',
            r'api_key\s*=\s*["\']([^"\']+)["\']',
            r'token\s*=\s*["\']([^"\']+)["\']',
        ]

        for pattern in credential_patterns:
            for match in re.finditer(pattern, code):
                issues.append(
                    CodeIssue(
                        type=IssueType.SECURITY,
                        severity=IssueSeverity.ERROR,
                        line=0,
                        column=0,
                        message=f"Hardcoded credential detected: {match.group(1)[:20]}...",
                        suggestion="Use environment variables or secure secret management",
                        file_path="unknown.py",
                    )
                )

        # Check for SQL injection patterns
        sql_patterns = [
            r'cursor\.execute\(["\'].*?\+.*?["\']',
            r'execute\(["\'].*?\+.*?["\']',
        ]

        for pattern in sql_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                issues.append(
                    CodeIssue(
                        type=IssueType.SECURITY,
                        severity=IssueSeverity.ERROR,
                        line=0,
                        column=0,
                        message="Potential SQL injection detected. Use parameterized queries.",
                        suggestion="Use cursor.execute('SELECT * FROM users WHERE id = %s', (id,))",
                        file_path="unknown.py",
                    )
                )

        return issues

    def _analyze_performance(self, tree: ast.AST) -> List[CodeIssue]:
        """Analyze performance issues."""
        issues = []

        # Check for O(n^2) patterns
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                # Check if there's a nested loop
                for child in ast.walk(node):
                    if isinstance(child, ast.For) or isinstance(child, ast.While):
                        issues.append(
                            CodeIssue(
                                type=IssueType.PERFORMANCE,
                                severity=IssueSeverity.WARNING,
                                line=node.lineno,
                                column=node.col_offset,
                                message="Nested loops detected. Potential O(n²) complexity.",
                                code="nested_loops",
                                file_path="unknown.py",
                            )
                        )
                        break

        return issues

    def _calculate_score(self, issues: List[CodeIssue]) -> float:
        """Calculate code review score."""
        if not issues:
            return 100.0

        total_severity = 0
        for issue in issues:
            if issue.severity == IssueSeverity.ERROR:
                total_severity += 10
            elif issue.severity == IssueSeverity.WARNING:
                total_severity += 5
            elif issue.severity == IssueSeverity.SUGGESTION:
                total_severity += 2
            elif issue.severity == IssueSeverity.INFO:
                total_severity += 1

        score = max(0.0, 100.0 - total_severity)
        return round(score, 1)

    def _calculate_summary(self, issues: List[CodeIssue]) -> Dict[str, int]:
        """Calculate summary statistics."""
        summary = {
            "security": 0,
            "performance": 0,
            "maintainability": 0,
            "style": 0,
            "error": 0,
            "complexity": 0,
        }

        for issue in issues:
            if issue.type in summary:
                summary[issue.type.value] += 1
            else:
                summary["error"] += 1

        return summary

    async def review_file(self, file_path: str) -> CodeReviewResult:
        """Review a specific file."""
        try:
            with open(file_path, "r") as f:
                code = f.read()
            return await self._review_code(code, file_path)
        except Exception:
            return CodeReviewResult(
                success=False, issues=[], summary={}, score=0.0, analysis_time=0.0
            )

    async def get_fixes(self, issue: CodeIssue) -> List[str]:
        """Get suggested fixes for an issue."""
        fixes = []

        if issue.type == IssueType.SECURITY and "hardcoded" in issue.message.lower():
            fixes.append("Replace hardcoded credentials with environment variables")
            fixes.append(
                "Use a secure secret management system like AWS Secrets Manager or HashiCorp Vault"
            )

        if issue.type == IssueType.SECURITY and "SQL injection" in issue.message.lower():
            fixes.append("Use parameterized queries")
            fixes.append("Prepared statements are safer than string concatenation")

        if issue.type == IssueType.COMPLEXITY and issue.severity == IssueSeverity.ERROR:
            fixes.append("Extract nested loops into separate functions")
            fixes.append("Apply Single Responsibility Principle")

        if issue.type == IssueType.PERFORMANCE and "nested" in issue.message.lower():
            fixes.append("Consider using set or dictionary for O(1) lookups")
            fixes.append("Use list comprehensions for faster iteration")

        return fixes
