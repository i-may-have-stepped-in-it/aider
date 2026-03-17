"""
Documentation Skill - Parallel documentation generation.

Generates documentation for multiple files simultaneously using sub-agents.
"""

import time
from typing import List, Optional

from .base import Skill, SkillContext, SkillResult
from .agent_skill import AgentSkillMixin


class DocumentationSkill(Skill, AgentSkillMixin):
    """
    Skill for generating documentation.
    
    Spawns agents to document different parts of the codebase
    in parallel.
    """
    
    name = "documentation"
    description = "Generate documentation in parallel"
    version = "1.0.0"
    supports_agents = True
    max_agents = 8
    
    def __init__(self, context: Optional[SkillContext] = None):
        Skill.__init__(self, context)
        AgentSkillMixin.__init__(self)
    
    async def execute(
        self,
        files: List[str],
        doc_format: str = "google",
        model: Optional[str] = None,
        update_readme: bool = True,
        **kwargs
    ) -> SkillResult:
        """
        Generate documentation for the specified files.
        
        Args:
            files: Source files to document
            doc_format: Documentation format (google, numpy, sphinx)
            model: Model to use
            update_readme: Whether to update README.md
            
        Returns:
            SkillResult with documentation
        """
        if not files:
            return SkillResult(
                success=False,
                error="No files specified for documentation"
            )
        
        agents_available = self.init_agents(self.context)
        
        self.output(f"📝 Generating documentation...")
        self.output(f"   Files: {len(files)}")
        self.output(f"   Format: {doc_format}")
        
        if not agents_available:
            return await self._sequential_document(
                files, doc_format, model, update_readme
            )
        
        # Create documentation tasks
        tasks = []
        for i, filepath in enumerate(files):
            prompt = self._create_doc_prompt(filepath, doc_format)
            tasks.append({
                "name": f"doc_{i}",
                "prompt": prompt,
                "model": model,
                "files": [filepath],
            })
        
        # Spawn agents
        start_time = time.monotonic()
        agent_ids = await self.spawn_agents(tasks)
        
        self.output(f"   Spawned {len(agent_ids)} documentation agents")
        
        # Wait for completion
        results = await self.wait_for_all()
        
        elapsed = time.monotonic() - start_time
        
        # Process results
        successful = sum(1 for r in results if r.get("success"))
        
        # Combine documentation
        all_docs = []
        for i, result in enumerate(results):
            filepath = files[i] if i < len(files) else "unknown"
            
            if result.get("success"):
                all_docs.append(f"\n## {filepath}\n")
                all_docs.append(result.get("output", ""))
        
        combined_docs = "\n".join(all_docs)
        
        # Optionally update README
        readme_result = None
        if update_readme:
            self.output("\n📄 Updating README...")
            readme_result = await self._update_readme(files, combined_docs, model)
        
        summary = f"""
Documentation Generation Summary
{'='*60}
Files documented: {len(files)}
Successful: {successful}/{len(files)}
Format: {doc_format}
Time elapsed: {elapsed:.2f}s
README updated: {update_readme and readme_result is not None}
"""
        
        self.output(summary)
        
        return SkillResult(
            success=successful == len(files),
            output=combined_docs,
            files_modified=["README.md"] if update_readme else [],
            data={
                "files_documented": len(files),
                "successful": successful,
                "format": doc_format,
                "elapsed_time": elapsed,
            },
            execution_time=elapsed,
            agent_results=results
        )
    
    async def _sequential_document(
        self,
        files: List[str],
        doc_format: str,
        model: Optional[str],
        update_readme: bool
    ) -> SkillResult:
        """Sequential fallback."""
        import time
        
        self.output(f"Generating documentation sequentially for {len(files)} files...")
        
        outputs = []
        start = time.time()
        
        for filepath in files:
            self.output(f"  Documenting: {filepath}")
            outputs.append(f"Documentation for {filepath} (simulated)")
        
        elapsed = time.time() - start
        
        return SkillResult(
            success=True,
            output="\n".join(outputs),
            execution_time=elapsed,
            data={"mode": "sequential"}
        )
    
    def _create_doc_prompt(self, filepath: str, doc_format: str) -> str:
        """Create documentation generation prompt."""
        
        format_examples = {
            "google": """
Use Google style docstrings:
```python
def function(arg1: int, arg2: str) -> bool:
    '''
    Short description.
    
    Longer description if needed.
    
    Args:
        arg1: Description of arg1
        arg2: Description of arg2
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When invalid input
    '''
```
""",
            "numpy": """
Use NumPy style docstrings:
```python
def function(arg1, arg2):
    '''
    Short description.
    
    Parameters
    ----------
    arg1 : int
        Description
    arg2 : str
        Description
        
    Returns
    -------
    bool
        Description
    '''
```
""",
            "sphinx": """
Use Sphinx/reStructuredText style:
```python
def function(arg1, arg2):
    '''
    Short description.
    
    :param arg1: Description
    :type arg1: int
    :param arg2: Description
    :type arg2: str
    :returns: Description
    :rtype: bool
    '''
```
""",
        }
        
        format_example = format_examples.get(doc_format, format_examples["google"])
        
        return f"""Generate comprehensive documentation for the code in '{filepath}'.

Format: {doc_format} style
{format_example}

Include:
1. Module-level docstring
2. Class docstrings with attributes
3. Function/method docstrings with args, returns, raises
4. Type hints where missing
5. Examples for complex functions

Output the fully documented code.
"""
    
    async def _update_readme(
        self,
        files: List[str],
        docs: str,
        model: Optional[str]
    ) -> Optional[SkillResult]:
        """Update README.md with API documentation."""
        prompt = f"""Update README.md with the following API documentation.

Files documented:
{chr(10).join(files)}

Documentation content:
{docs[:2000]}...

Add or update the API section in README.md with this information.
Keep the existing structure but add/update the API Reference section.
"""
        
        agent_id = await self.spawn_agent(
            name="readme_update",
            prompt=prompt,
            model=model,
            files=["README.md"] if __import__('os').path.exists("README.md") else []
        )
        
        result = await self.wait_for_agent(agent_id)
        
        return self.to_skill_result(result)


class ArchitectureDocSkill(Skill, AgentSkillMixin):
    """Generate architecture documentation."""
    
    name = "architecture-docs"
    description = "Generate architecture documentation"
    supports_agents = True
    
    def __init__(self, context: Optional[SkillContext] = None):
        Skill.__init__(self, context)
        AgentSkillMixin.__init__(self)
    
    async def execute(
        self,
        files: List[str],
        output_file: str = "ARCHITECTURE.md",
        **kwargs
    ) -> SkillResult:
        """Generate architecture documentation."""
        
        agents_available = self.init_agents(self.context)
        
        if agents_available:
            # Phase 1: Analyze each file
            analysis_tasks = [
                {
                    "name": f"arch_analyze_{i}",
                    "prompt": f"""Analyze '{filepath}' for architecture documentation.
Describe:
1. Purpose of this module/component
2. Key classes and their responsibilities
3. Dependencies on other components
4. Design patterns used
""",
                    "files": [filepath],
                }
                for i, filepath in enumerate(files)
            ]
            
            await self.spawn_agents(analysis_tasks)
            analyses = await self.wait_for_all()
            
            # Phase 2: Generate architecture doc
            combined_analysis = "\n\n".join(
                a.get("output", "") for a in analyses if a.get("success")
            )
            
            prompt = f"""Generate an ARCHITECTURE.md document based on these component analyses:

{combined_analysis}

Include:
1. High-level architecture overview
2. Component diagram description
3. Data flow
4. Key design decisions
5. Technology stack
"""
            
            agent_id = await self.spawn_agent(
                name="arch_doc",
                prompt=prompt
            )
            
            result = await self.wait_for_agent(agent_id)
            
            return self.to_skill_result(result)
        
        else:
            return SkillResult(
                success=True,
                output=f"Architecture documentation (sequential mode)",
                data={"files": files, "output": output_file}
            )
