"""
Base classes for Aider skills with multi-agent support.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Callable

if TYPE_CHECKING:
    from aider.coders.base_coder import Coder
    from aider.io import InputOutput


@dataclass
class ProgressUpdate:
    """Progress update record with timestamp."""
    message: str
    progress: Optional[float] = None  # 0.0 to 1.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class SkillResult:
    """Result from skill execution with comprehensive error tracking."""
    success: bool
    output: str = ""
    error: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    files_modified: List[str] = field(default_factory=list)
    agent_results: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)  # Issue 4: Track warnings


@dataclass
class SkillContext:
    """Context passed to skills during execution."""
    coder: Optional[Coder] = None
    io: Optional[InputOutput] = None
    args: Dict[str, Any] = field(default_factory=dict)
    verbose: bool = False
    
    # Agent support
    enable_agents: bool = False
    max_agents: int = 5
    agent_timeout: float = 300.0
    
    def output(self, message: str):
        """Output a message."""
        if self.io:
            self.io.tool_output(message)
        else:
            print(message)
    
    def error(self, message: str):
        """Output an error message."""
        if self.io:
            self.io.tool_error(message)
        else:
            print(f"Error: {message}", file=__import__('sys').stderr)
    
    def confirm(self, message: str, default: bool = False) -> bool:
        """Ask for confirmation."""
        if self.io and hasattr(self.io, 'confirm_ask'):
            return self.io.confirm_ask(message, default=default)
        return default


class Skill(ABC):
    """
    Base class for Aider skills.
    
    Skills are reusable capabilities that can be invoked via the /skill command
    or programmatically. They can optionally use the multi-agent system for
    parallel task execution.
    """
    
    # Skill metadata
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    
    # Capabilities
    supports_agents: bool = False
    max_agents: int = 5
    
    def __init__(self, context: Optional[SkillContext] = None):
        self.context = context or SkillContext()
        self._start_time = time.time()
        self._progress: List[ProgressUpdate] = []
        self._errors: List[str] = []
        self._warnings: List[str] = []
    
    async def execute(self, **kwargs) -> SkillResult:
        """
        Execute the skill with parameter validation and timeout handling.
        
        Addresses:
        - Issue 1: Parameter validation
        - Issue 2: Progress tracking
        - Issue 3: Timeout handling
        - Issue 4: Error handling
        
        Args:
            **kwargs: Skill-specific arguments
            
        Returns:
            SkillResult with execution results
        """
        try:
            # Check for cancellation
            if self.context.is_cancelled():
                return SkillResult(
                    success=False,
                    error="Skill execution cancelled",
                    execution_time=time.time() - self._start_time
                )

            # Issue 1: Validate required parameters
            required_params = self._get_required_params()
            missing_params = [p for p in required_params if p not in kwargs]

            if missing_params:
                error_msg = f"Missing required parameters: {', '.join(missing_params)}"
                self._errors.append(error_msg)
                return SkillResult(
                    success=False,
                    error=error_msg,
                    execution_time=time.time() - self._start_time,
                    warnings=self._warnings
                )

            # Validate parameter types/values
            validation_errors = self._validate_parameters(kwargs)
            if validation_errors:
                error_msg = "Parameter validation failed:\n" + "\n".join(validation_errors)
                self._errors.append(error_msg)
                return SkillResult(
                    success=False,
                    error=error_msg,
                    execution_time=time.time() - self._start_time,
                    warnings=self._warnings
                )

            # Issue 3: Execute with timeout
            if self.context.timeout > 0:
                try:
                    result = await asyncio.wait_for(
                        self._execute_impl(**kwargs),
                        timeout=self.context.timeout
                    )
                    result.warnings = self._warnings
                    return result
                except asyncio.TimeoutError:
                    error_msg = f"Skill execution timed out after {self.context.timeout}s"
                    self._errors.append(error_msg)
                    return SkillResult(
                        success=False,
                        error=error_msg,
                        execution_time=time.time() - self._start_time,
                        warnings=self._warnings
                    )
            else:
                result = await self._execute_impl(**kwargs)
                result.warnings = self._warnings
                return result

        except Exception as e:
            # Issue 4: Capture all errors with traceback
            error_msg = f"Skill execution failed: {str(e)}"
            self._errors.append(error_msg)

            import traceback
            tb = traceback.format_exc()
            if self.context.verbose:
                self.context.error(f"Exception in skill {self.name}:\n{tb}")

            return SkillResult(
                success=False,
                error=error_msg,
                data={"traceback": tb},
                execution_time=time.time() - self._start_time,
                warnings=self._warnings
            )
    
    @abstractmethod
    async def _execute_impl(self, **kwargs) -> SkillResult:
        """
        Internal execution method (must be implemented by subclasses).
        
        This method should contain the actual skill logic.
        It is called after parameter validation and with timeout protection.
        """
        pass
    
    def _get_required_params(self) -> List[str]:
        """
        Return list of required parameter names.
        
        Override this method to specify required parameters for your skill.
        
        Returns:
            List of parameter names that must be provided
        """
        return []
    
    def _validate_parameters(self, params: Dict[str, Any]) -> List[str]:
        """
        Validate parameters and return list of error messages.
        
        Override this method to add custom parameter validation.
        
        Args:
            params: Dictionary of parameters to validate
            
        Returns:
            List of error messages (empty list if all valid)
        """
        return []
    
    # Issue 2: Progress tracking
    def update_progress(self, message: str, progress: Optional[float] = None):
        """
        Update progress with a message and optional percentage.
        
        Args:
            message: Progress message to display
            progress: Optional progress value (0.0 to 1.0)
        """
        self._progress.append(ProgressUpdate(
            message=message,
            progress=progress,
            timestamp=time.time()
        ))

        if self.context.verbose:
            if progress is not None:
                self.context.output(f"  [{progress:.0%}] {message}")
            else:
                self.context.output(f"  {message}")
    
    def get_progress(self) -> List[ProgressUpdate]:
        """Get all progress updates."""
        return self._progress.copy()
    
    def clear_progress(self):
        """Clear progress history."""
        self._progress.clear()
    
    def add_warning(self, message: str):
        """Add a warning message."""
        self._warnings.append(message)
        if self.context.verbose:
            self.context.output(f"  ⚠️  {message}")
    
    def run(self, **kwargs) -> SkillResult:
        """Run the skill synchronously."""
        return asyncio.run(self.execute(**kwargs))
    
    def output(self, message: str):
        """Output a message through the context."""
        self.context.output(message)
    
    def error(self, message: str):
        """Output an error message through the context."""
        self.context.error(message)
    
    def get_agent_registry(self):
        """Get the agent registry if agents are enabled."""
        if not self.context.enable_agents:
            return None
        
        # Lazy import to avoid circular dependencies
        from ..agents.registry import AgentRegistry
        return AgentRegistry(max_concurrent=self.context.max_agents)
    
    def get_agent_executor(self, registry):
        """Get an agent executor for the given registry."""
        if not self.context.coder:
            raise RuntimeError("Cannot create agent executor without a coder")
        
        from ..agents.executor import AgentExecutor
        return AgentExecutor(registry, self.context.coder.io if self.context.coder else None)


class ParallelSkill(Skill):
    """
    Skill that executes tasks in parallel using sub-agents.
    
    This is a convenience base class for skills that need to spawn
    multiple agents to work on different parts of a problem.
    """
    
    supports_agents = True
    
    async def execute_parallel(
        self,
        tasks: List[Dict[str, Any]],
        on_progress: Optional[Callable[[str, Any], None]] = None
    ) -> List[SkillResult]:
        """
        Execute multiple tasks in parallel using sub-agents.
        
        Args:
            tasks: List of task configurations, each with:
                - name: Task name
                - prompt: Task prompt/prompt
                - model: Optional model override
                - files: Optional list of files
            on_progress: Optional callback for progress updates
            
        Returns:
            List of SkillResult objects
        """
        if not self.context.enable_agents:
            # Fallback to sequential execution
            results = []
            for task in tasks:
                result = await self._execute_single(task)
                results.append(result)
            return results
        
        # Use agents for parallel execution
        registry = self.get_agent_registry()
        executor = self.get_agent_executor(registry)

        if not self.context.coder:
            return [SkillResult(success=False, error="ParallelSkill requires a coder in context")]

        # Spawn all agents
        agents = []
        for task in tasks:
            agent = await executor.spawn(
                parent_coder=self.context.coder,
                task=task.get("prompt", task.get("name", "unnamed")),
                name=task.get("name", "unnamed"),
                model=task.get("model"),
                files=task.get("files", []),
            )
            agents.append((agent, task))

        # Wait for all to complete via registry
        await registry.wait_for_all()
        
        # Collect results
        results = []
        for agent, task in agents:
            if agent.result:
                results.append(SkillResult(
                    success=agent.result.success,
                    output=agent.result.output,
                    error=agent.result.error,
                    files_modified=agent.result.files_modified,
                ))
            else:
                results.append(SkillResult(
                    success=False,
                    error=agent.error or "No result"
                ))
        
        return results
    
    async def _execute_single(self, task: Dict[str, Any]) -> SkillResult:
        """Execute a single task without agents."""
        # Subclasses can override this for sequential fallback
        start = time.time()
        try:
            # Default implementation just returns success
            # Subclasses should override
            return SkillResult(
                success=True,
                output=f"Executed: {task.get('name', 'unnamed')}",
                execution_time=time.time() - start
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start
            )
