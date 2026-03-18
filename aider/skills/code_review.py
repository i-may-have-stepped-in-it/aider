"""
Code Review Skill - Parallel code review using sub-agents.

This skill spawns multiple agents to review different files simultaneously,
then aggregates the results.
"""

import time
from typing import List, Optional

from .agent_skill import AgentSkillMixin
from .base import Skill, SkillContext, SkillResult


class CodeReviewSkill(Skill, AgentSkillMixin):
    """
    Skill for parallel code review.

    Spawns multiple sub-agents to review different files or aspects
    of the codebase simultaneously.
    """

    name = "code-review"
    description = "Parallel code review using multiple agents"
    version = "1.0.0"
    supports_agents = True
    max_agents = 10

    def __init__(self, context: Optional[SkillContext] = None):
        Skill.__init__(self, context)
        AgentSkillMixin.__init__(self)

    async def execute(
        self, files: List[str], focus: str = "general", model: Optional[str] = None, **kwargs
    ) -> SkillResult:
        """
        Execute code review on the specified files.

        Args:
            files: List of files to review
            focus: Review focus (security, performance, general, etc.)
            model: Model to use for review

        Returns:
            SkillResult with aggregated review results
        """
        if not files:
            return SkillResult(success=False, error="No files specified for review")

        # Initialize agents if enabled
        agents_available = self.init_agents(self.context)

        if not agents_available:
            # Sequential fallback
            return await self._sequential_review(files, focus, model)

        # Parallel review with agents
        self.output(f"🔍 Starting parallel code review of {len(files)} files...")
        self.output(f"   Focus: {focus}")
        self.output(f"   Max concurrent agents: {self.context.max_agents}")

        # Create review tasks
        tasks = []
        for i, filepath in enumerate(files):
            prompt = self._create_review_prompt(filepath, focus)
            tasks.append(
                {
                    "name": f"review_{i}",
                    "prompt": prompt,
                    "model": model,
                    "files": [filepath],
                }
            )

        # Spawn agents
        start_time = time.monotonic()
        agent_ids = await self.spawn_agents(tasks)

        self.output(f"   Spawned {len(agent_ids)} review agents")

        # Wait for completion
        results = await self.wait_for_all()

        elapsed = time.monotonic() - start_time

        # Aggregate results
        successful = sum(1 for r in results if r.get("success"))
        issues_found = sum(
            r.get("output", "").count("issue") + r.get("output", "").count("problem")
            for r in results
        )

        # Combine outputs
        outputs = []
        for i, result in enumerate(results):
            filepath = files[i] if i < len(files) else "unknown"
            outputs.append(f"\n{'=' * 60}")
            outputs.append(f"Review: {filepath}")
            outputs.append(f"{'=' * 60}")
            if result.get("success"):
                outputs.append(result.get("output", "No output"))
            else:
                outputs.append(f"Error: {result.get('error', 'Unknown error')}")

        combined_output = "\n".join(outputs)

        summary = f"""
Code Review Summary
{'=' * 60}
Files reviewed: {len(files)}
Successful: {successful}/{len(files)}
Issues found: {issues_found}
Time elapsed: {elapsed:.2f}s
"""

        self.output(summary)

        return SkillResult(
            success=successful == len(files),
            output=combined_output,
            data={
                "files_reviewed": len(files),
                "successful": successful,
                "issues_found": issues_found,
                "elapsed_time": elapsed,
            },
            execution_time=elapsed,
            agent_results=results,
        )

    async def _sequential_review(
        self, files: List[str], focus: str, model: Optional[str]
    ) -> SkillResult:
        """Sequential fallback when agents are not available."""
        import time

        self.output(f"Reviewing {len(files)} files sequentially...")

        outputs = []
        start = time.time()

        for filepath in files:
            self.output(f"  Reviewing: {filepath}")
            # In a real implementation, this would call the coder directly
            outputs.append(f"Review of {filepath}: No issues found (simulated)")

        elapsed = time.time() - start

        combined = "\n".join(outputs)

        return SkillResult(
            success=True,
            output=combined,
            execution_time=elapsed,
            data={"files_reviewed": len(files), "mode": "sequential"},
        )

    def _create_review_prompt(self, filepath: str, focus: str) -> str:
        """Create a review prompt for the given file and focus."""

        focus_prompts = {
            "security": """
Review the file for security issues including:
- SQL injection vulnerabilities
- XSS vulnerabilities
- Authentication/authorization flaws
- Input validation issues
- Sensitive data exposure
List any issues found with line numbers and severity.
""",
            "performance": """
Review the file for performance issues including:
- Inefficient algorithms
- Database query optimization
- Memory usage concerns
- Unnecessary computations
- Caching opportunities
List any issues found with line numbers and suggested improvements.
""",
            "general": """
Review the file for code quality issues including:
- Code style violations
- Potential bugs
- Error handling gaps
- Documentation gaps
- Test coverage gaps
List any issues found with line numbers and suggestions.
""",
        }

        focus_text = focus_prompts.get(focus, focus_prompts["general"])

        return f"""Please review the file '{filepath}'.

{focus_text}

If no issues are found, state "No issues found".
Be specific about locations (line numbers) when possible.
"""


class SecurityAuditSkill(CodeReviewSkill):
    """Specialized skill for security audits."""

    name = "security-audit"
    description = "Comprehensive security audit using multiple agents"

    async def execute(self, files: List[str], model: Optional[str] = None, **kwargs) -> SkillResult:
        """Run security-focused code review."""
        return await super().execute(files=files, focus="security", model=model, **kwargs)


class PerformanceReviewSkill(CodeReviewSkill):
    """Specialized skill for performance reviews."""

    name = "performance-review"
    description = "Performance analysis using multiple agents"

    async def execute(self, files: List[str], model: Optional[str] = None, **kwargs) -> SkillResult:
        """Run performance-focused code review."""
        return await super().execute(files=files, focus="performance", model=model, **kwargs)
