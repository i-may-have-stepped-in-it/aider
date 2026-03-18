"""
Test Generation Skill - Parallel test generation using sub-agents.

This skill spawns multiple agents to generate tests for different
parts of the codebase simultaneously.
"""

import time
from typing import List, Optional

from .agent_skill import AgentSkillMixin
from .base import Skill, SkillContext, SkillResult


class TestGenerationSkill(Skill, AgentSkillMixin):
    """
    Skill for parallel test generation.

    Spawns multiple sub-agents to generate tests for different
    modules or functions simultaneously.
    """

    name = "test-generation"
    description = "Generate tests in parallel using multiple agents"
    version = "1.0.0"
    supports_agents = True
    max_agents = 8

    def __init__(self, context: Optional[SkillContext] = None):
        Skill.__init__(self, context)
        AgentSkillMixin.__init__(self)

    async def execute(
        self,
        files: List[str],
        test_framework: str = "pytest",
        model: Optional[str] = None,
        coverage_target: Optional[float] = None,
        **kwargs,
    ) -> SkillResult:
        """
        Generate tests for the specified files.

        Args:
            files: Source files to generate tests for
            test_framework: Testing framework (pytest, unittest, etc.)
            model: Model to use
            coverage_target: Target coverage percentage

        Returns:
            SkillResult with generated tests
        """
        if not files:
            return SkillResult(success=False, error="No source files specified")

        agents_available = self.init_agents(self.context)

        if not agents_available:
            return await self._sequential_generate(files, test_framework, model, coverage_target)

        self.output(f"🧪 Generating tests for {len(files)} files...")
        self.output(f"   Framework: {test_framework}")

        # Create generation tasks
        tasks = []
        for i, filepath in enumerate(files):
            prompt = self._create_test_prompt(filepath, test_framework, coverage_target)
            tasks.append(
                {
                    "name": f"test_gen_{i}",
                    "prompt": prompt,
                    "model": model,
                    "files": [filepath],
                }
            )

        # Spawn agents
        start_time = time.monotonic()
        agent_ids = await self.spawn_agents(tasks)

        self.output(f"   Spawned {len(agent_ids)} test generation agents")

        # Wait for completion
        results = await self.wait_for_all()

        elapsed = time.monotonic() - start_time

        # Process results
        successful = sum(1 for r in results if r.get("success"))
        test_files = []

        outputs = []
        for i, result in enumerate(results):
            filepath = files[i] if i < len(files) else "unknown"
            test_file = self._get_test_filename(filepath, test_framework)

            outputs.append(f"\n{'=' * 60}")
            outputs.append(f"Tests for: {filepath}")
            outputs.append(f"Output file: {test_file}")
            outputs.append(f"{'=' * 60}")

            if result.get("success"):
                outputs.append(result.get("output", ""))
                test_files.append(test_file)
            else:
                outputs.append(f"Error: {result.get('error', 'Unknown error')}")

        combined_output = "\n".join(outputs)

        summary = f"""
Test Generation Summary
{'=' * 60}
Source files: {len(files)}
Successful: {successful}/{len(files)}
Test files created: {len(test_files)}
Time elapsed: {elapsed:.2f}s
"""

        self.output(summary)

        return SkillResult(
            success=successful == len(files),
            output=combined_output,
            files_modified=test_files,
            data={
                "source_files": len(files),
                "successful": successful,
                "test_files": test_files,
                "elapsed_time": elapsed,
            },
            execution_time=elapsed,
            agent_results=results,
        )

    async def _sequential_generate(
        self,
        files: List[str],
        test_framework: str,
        model: Optional[str],
        coverage_target: Optional[float],
    ) -> SkillResult:
        """Sequential fallback."""
        import time

        self.output(f"Generating tests sequentially for {len(files)} files...")

        outputs = []
        test_files = []
        start = time.time()

        for filepath in files:
            self.output(f"  Generating tests for: {filepath}")
            test_file = self._get_test_filename(filepath, test_framework)
            outputs.append(f"Tests for {filepath} -> {test_file} (simulated)")
            test_files.append(test_file)

        elapsed = time.time() - start

        return SkillResult(
            success=True,
            output="\n".join(outputs),
            files_modified=test_files,
            execution_time=elapsed,
            data={"mode": "sequential"},
        )

    def _create_test_prompt(
        self, filepath: str, test_framework: str, coverage_target: Optional[float]
    ) -> str:
        """Create a test generation prompt."""

        coverage_text = ""
        if coverage_target:
            coverage_text = f"\nAim for at least {coverage_target}% code coverage."

        framework_specific = {
            "pytest": """
Use pytest style:
- Function-based tests
- Use fixtures where appropriate
- Use parametrize for multiple test cases
- Use pytest.raises for exception testing
""",
            "unittest": """
Use unittest style:
- Class-based tests inheriting from unittest.TestCase
- Use setUp/tearDown methods if needed
- Use self.assertX methods
""",
        }

        style = framework_specific.get(test_framework, "Use standard testing practices.")

        return f"""Generate comprehensive tests for the code in '{filepath}'.

Framework: {test_framework}
{style}
Include tests for:
- Normal operation (happy path)
- Edge cases
- Error conditions
- Invalid inputs
{coverage_text}

Output the complete test file content.
"""

    def _get_test_filename(self, source_file: str, test_framework: str) -> str:
        """Generate test file name from source file name."""
        import re

        # Remove extension
        base = re.sub(r"\.py$", "", source_file)

        # Add test prefix/suffix based on convention
        if test_framework == "pytest":
            return f"test_{base}.py"
        else:
            return f"test_{base}.py"


class CoverageAnalysisSkill(Skill, AgentSkillMixin):
    """
    Skill for analyzing test coverage gaps.

    Identifies untested code and generates tests to improve coverage.
    """

    name = "coverage-analysis"
    description = "Analyze and improve test coverage"
    supports_agents = True

    def __init__(self, context: Optional[SkillContext] = None):
        Skill.__init__(self, context)
        AgentSkillMixin.__init__(self)

    async def execute(
        self, files: List[str], coverage_file: str = ".coverage", target: float = 80.0, **kwargs
    ) -> SkillResult:
        """
        Analyze coverage and generate missing tests.

        Args:
            files: Source files to analyze
            coverage_file: Path to coverage data file
            target: Target coverage percentage

        Returns:
            SkillResult with coverage analysis
        """
        self.output("📊 Analyzing test coverage...")
        self.output(f"   Target: {target}%")

        # This would typically run coverage analysis tool
        # For now, we'll simulate finding coverage gaps

        agents_available = self.init_agents(self.context)

        if agents_available:
            # Spawn agents to analyze each file
            tasks = []
            for filepath in files:
                tasks.append(
                    {
                        "name": f"coverage_{filepath}",
                        "prompt": f"""Analyze test coverage for '{filepath}'.
Identify:
1. Functions/methods without tests
2. Branches not covered
3. Edge cases not tested

Output a list of specific test cases needed to improve coverage.
""",
                    }
                )

            await self.spawn_agents(tasks)
            results = await self.wait_for_all()

            # Aggregate coverage gaps
            gaps = []
            for r in results:
                if r.get("success"):
                    gaps.append(r.get("output", ""))

            return SkillResult(
                success=True,
                output="\n\n".join(gaps),
                data={"files_analyzed": len(files), "gaps_found": len(gaps)},
            )
        else:
            return SkillResult(
                success=True,
                output="Coverage analysis (sequential mode)",
                data={"files_analyzed": len(files), "mode": "sequential"},
            )
