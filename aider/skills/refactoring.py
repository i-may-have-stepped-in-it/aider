"""
Refactoring Skill - Parallel refactoring using sub-agents.

This skill coordinates multiple agents to refactor different parts
of the codebase simultaneously while maintaining consistency.
"""

from typing import Any, Dict, List, Optional

from .agent_skill import AgentSkillMixin
from .base import Skill, SkillContext, SkillResult


class RefactoringSkill(Skill, AgentSkillMixin):
    """
    Skill for coordinated parallel refactoring.

    Refactors multiple files while maintaining consistency
    across the codebase.
    """

    name = "refactoring"
    description = "Parallel code refactoring with consistency checks"
    version = "1.0.0"
    supports_agents = True
    max_agents = 6

    def __init__(self, context: Optional[SkillContext] = None):
        Skill.__init__(self, context)
        AgentSkillMixin.__init__(self)

    async def execute(
        self,
        files: List[str],
        refactoring_type: str = "extract-method",
        model: Optional[str] = None,
        dry_run: bool = False,
        **kwargs,
    ) -> SkillResult:
        """
        Execute refactoring across multiple files.

        Args:
            files: Files to refactor
            refactoring_type: Type of refactoring to perform
            model: Model to use
            dry_run: If True, only show planned changes

        Returns:
            SkillResult with refactoring results
        """
        if not files:
            return SkillResult(success=False, error="No files specified")

        agents_available = self.init_agents(self.context)

        self.output(f"🔧 Starting {refactoring_type} refactoring...")
        self.output(f"   Files: {len(files)}")
        self.output(f"   Mode: {'dry-run' if dry_run else 'apply'}")

        if not agents_available:
            return await self._sequential_refactor(files, refactoring_type, model, dry_run)

        # Phase 1: Analysis - understand the codebase structure
        self.output("\n📋 Phase 1: Analyzing codebase...")
        analysis = await self._analyze_files(files, model)

        # Phase 2: Plan refactoring for each file
        self.output("\n📐 Phase 2: Planning refactoring...")
        plans = await self._plan_refactoring(files, refactoring_type, analysis, model)

        # Phase 3: Execute refactoring
        if dry_run:
            self.output("\n📄 Phase 3: Planned changes (dry run)")
            return self._format_dry_run_results(plans)

        self.output("\n⚡ Phase 3: Executing refactoring...")
        results = await self._execute_refactoring(plans, model)

        # Phase 4: Consistency check
        self.output("\n✓ Phase 4: Checking consistency...")
        consistency_issues = await self._check_consistency(files, model)

        # Aggregate results
        successful = sum(1 for r in results if r.get("success"))
        files_modified = [r.get("files_modified", []) for r in results]
        files_modified = list(set(sum(files_modified, [])))

        summary = f"""
Refactoring Summary
{'=' * 60}
Type: {refactoring_type}
Files processed: {len(files)}
Successful: {successful}/{len(files)}
Files modified: {len(files_modified)}
Consistency issues: {len(consistency_issues)}
"""

        if consistency_issues:
            summary += "\n⚠️  Consistency issues found:\n"
            for issue in consistency_issues:
                summary += f"  - {issue}\n"

        self.output(summary)

        return SkillResult(
            success=successful == len(files) and not consistency_issues,
            output=summary,
            files_modified=files_modified,
            data={
                "type": refactoring_type,
                "files_processed": len(files),
                "successful": successful,
                "consistency_issues": consistency_issues,
            },
            agent_results=results,
        )

    async def _analyze_files(self, files: List[str], model: Optional[str]) -> Dict[str, Any]:
        """Analyze files to understand structure."""
        tasks = []
        for i, filepath in enumerate(files):
            tasks.append(
                {
                    "name": f"analyze_{i}",
                    "prompt": f"""Analyze the file '{filepath}' and provide:
1. Main classes and functions
2. Dependencies on other files
3. Public APIs
4. Complex code sections

Keep the analysis concise but comprehensive.
""",
                    "model": model,
                    "files": [filepath],
                }
            )

        await self.spawn_agents(tasks)
        results = await self.wait_for_all()

        analysis = {}
        for i, result in enumerate(results):
            if i < len(files):
                analysis[files[i]] = result.get("output", "")

        return analysis

    async def _plan_refactoring(
        self,
        files: List[str],
        refactoring_type: str,
        analysis: Dict[str, Any],
        model: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Plan refactoring for each file."""
        plans = []

        for i, filepath in enumerate(files):
            other_files = [f for f in files if f != filepath]
            other_analysis = {f: analysis.get(f, "") for f in other_files[:3]}

            prompt = f"""Plan {refactoring_type} refactoring for '{filepath}'.

Current file analysis:
{analysis.get(filepath, '')}

Related files context:
{chr(10).join(f"{f}: {a[:200]}..." for f, a in other_analysis.items())}

Provide a detailed refactoring plan including:
1. Specific changes to make
2. Order of operations
3. Dependencies to update
4. Potential risks
"""

            plans.append(
                {
                    "file": filepath,
                    "prompt": prompt,
                    "model": model,
                }
            )

        return plans

    async def _execute_refactoring(
        self, plans: List[Dict[str, Any]], model: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Execute the refactoring plans."""
        tasks = []
        for i, plan in enumerate(plans):
            tasks.append(
                {
                    "name": f"refactor_{i}",
                    "prompt": plan["prompt"],
                    "model": model or plan.get("model"),
                    "files": [plan["file"]],
                }
            )

        await self.spawn_agents(tasks)
        results = await self.wait_for_all()

        return results

    async def _check_consistency(self, files: List[str], model: Optional[str]) -> List[str]:
        """Check for consistency issues after refactoring."""
        # Spawn a single agent to check consistency
        prompt = f"""Check for consistency issues across these refactored files:
{chr(10).join(files)}

Look for:
1. Import/export mismatches
2. API signature changes not propagated
3. Naming inconsistencies
4. Missing updates in dependent files

List any issues found, or state "No consistency issues found".
"""

        agent_id = await self.spawn_agent(
            name="consistency_check", prompt=prompt, model=model, files=files
        )

        result = await self.wait_for_agent(agent_id)

        if result.get("success"):
            output = result.get("output", "")
            if "no consistency issues" in output.lower():
                return []
            else:
                # Parse issues from output
                return [line.strip() for line in output.split("\n") if line.strip()]

        return []

    async def _sequential_refactor(
        self, files: List[str], refactoring_type: str, model: Optional[str], dry_run: bool
    ) -> SkillResult:
        """Sequential fallback."""
        import time

        self.output(f"Refactoring {len(files)} files sequentially...")

        start = time.time()
        for filepath in files:
            self.output(f"  Processing: {filepath}")

        elapsed = time.time() - start

        return SkillResult(
            success=True,
            output=f"Refactored {len(files)} files (sequential mode)",
            execution_time=elapsed,
            data={"mode": "sequential", "files": files},
        )

    def _format_dry_run_results(self, plans: List[Dict[str, Any]]) -> SkillResult:
        """Format dry run results."""
        output = "Planned Refactoring Changes:\n"
        output += "=" * 60 + "\n\n"

        for plan in plans:
            output += f"File: {plan['file']}\n"
            output += "-" * 40 + "\n"
            output += plan.get("prompt", "")[:500] + "...\n\n"

        return SkillResult(
            success=True, output=output, data={"dry_run": True, "files": [p["file"] for p in plans]}
        )


class CodeModernizationSkill(RefactoringSkill):
    """Skill for modernizing legacy code."""

    name = "code-modernization"
    description = "Modernize legacy code patterns"

    async def execute(
        self, files: List[str], target_version: str = "python3.11", **kwargs
    ) -> SkillResult:
        """Modernize code to use newer language features."""

        modernization_prompts = {
            "python3.11": """
Modernize Python code to use 3.11+ features:
- Use modern type hints (| instead of Union, etc.)
- Use match/case statements where appropriate
- Use exception groups if applicable
- Update to modern asyncio patterns
- Use tomllib instead of toml
""",
            "python3.10": """
Modernize Python code to use 3.10+ features:
- Use union types with | operator
- Use structural pattern matching (match/case)
- Use better error messages
- Update type hints
""",
            "es6": """
Modernize JavaScript to ES6+:
- Use const/let instead of var
- Use arrow functions
- Use template literals
- Use destructuring
- Use async/await
- Use modules
""",
        }

        prompt = modernization_prompts.get(target_version, f"Modernize code for {target_version}")

        # Add the modernization prompt to kwargs
        kwargs["custom_prompt"] = prompt

        return await super().execute(
            files=files, refactoring_type=f"modernize-{target_version}", **kwargs
        )
