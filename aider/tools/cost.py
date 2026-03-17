"""Cost tracking for tool execution.

This module tracks all costs associated with agent tool execution, including:
- LLM API call costs (input/output tokens)
- Tool output costs (when added to context for next iteration)

COST MODEL ASSUMPTIONS:
- Input tokens: $10 per million tokens ($0.00001 per token)
- Output tokens: $30 per million tokens ($0.00003 per token)

WHY TOOL OUTPUT MATTERS FOR COST:
When a tool executes, its output is added to the conversation context. This output
becomes INPUT tokens for the next LLM call. Many tools (search, file read, grep)
can return large amounts of text. Without tracking tool output, we underestimate
the true cost of multi-turn tool interactions by 50-80%.

Example cost flow:
  Iteration 1:
    - LLM generates tool call: 50 output tokens
    - Tool returns search results: 5000 tokens
    - Tool output cost: 5000 * $0.00001 = $0.05 (will be next iteration's input)
  
  Iteration 2:
    - LLM input: 5000 tokens (previous tool output) + 100 history = 5100 input tokens
    - LLM generates response: 200 output tokens
    - Input cost: 5100 * $0.00001 = $0.051
    - Output cost: 200 * $0.00003 = $0.006

The tool output cost is charged at INPUT rates because it becomes input to the next LLM call.
"""

from dataclasses import dataclass, field
from typing import Optional
import warnings


@dataclass
class ToolCallCost:
    """Cost breakdown for a single tool call iteration.
    
    Each iteration represents one turn in the tool execution loop:
    1. LLM decides what tool to call (or responds)
    2. Tool executes and returns output
    3. Output becomes input for next iteration
    
    Attributes:
        iteration: The iteration number (0-indexed)
        llm_input_tokens: Tokens sent to LLM API (conversation history)
        llm_output_tokens: Tokens received from LLM API (tool calls or responses)
        llm_cost: Actual cost charged by LLM API
        tool_output_tokens: Tokens produced by tool execution
        tool_output_cost: Estimated cost when these tokens become next iteration's input
    """
    iteration: int
    
    # LLM call costs (what the API charges us)
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cost: float = 0.0
    
    # Tool execution (no direct cost, but output becomes input)
    # This is crucial for accurate cost estimation because:
    # - Tool output is appended to conversation history
    # - On next iteration, it becomes LLM input tokens
    # - Large tool outputs (file reads, search results) significantly impact cost
    tool_output_tokens: int = 0
    tool_output_cost: float = 0.0  # Estimated cost when added to context
    
    # Total for this iteration
    @property
    def total_tokens(self) -> int:
        """Total tokens involved in this iteration.
        
        Includes LLM input/output and tool output tokens.
        Note: Tool output becomes input on the NEXT iteration, so we count
        it separately to avoid double-counting in session totals.
        """
        return self.llm_input_tokens + self.llm_output_tokens + self.tool_output_tokens
    
    @property
    def total_cost(self) -> float:
        """Total cost for this iteration.
        
        Combines actual LLM API cost with estimated cost of tool output
        that will be charged on the next iteration.
        """
        return self.llm_cost + self.tool_output_cost


@dataclass  
class CostTracker:
    """Track costs across agent loop iterations.
    
    Provides comprehensive cost tracking for multi-turn tool execution,
    including budget management and warnings when approaching limits.
    
    Default pricing reflects typical API costs (OpenAI GPT-4 style):
    - Input: $10 per million tokens
    - Output: $30 per million tokens
    
    Attributes:
        max_cost: Maximum allowed cost in USD (default: $5.00)
        input_cost_per_token: Cost per input token (default: $0.00001)
        output_cost_per_token: Cost per output token (default: $0.00003)
        iterations: List of completed iteration costs
        _current: Currently active iteration being tracked
    
    Example usage:
        tracker = CostTracker(max_cost=10.0)  # $10 budget
        
        for i in range(max_iterations):
            tracker.start_iteration(i)
            
            # LLM API call
            response = llm.chat(messages)
            tracker.record_llm_cost(response.usage, model_config)
            
            # Tool execution
            if response.has_tool_call:
                result = execute_tool(response.tool_call)
                tracker.record_tool_output(result)
            
            tracker.end_iteration()
            
            if tracker.is_budget_exceeded():
                warnings.warn(f"Budget exceeded: ${tracker.total_cost:.2f}")
                break
        
        print(tracker.get_summary())
    """
    
    max_cost: float = 5.0  # Default $5 limit - reasonable for most tasks
    input_cost_per_token: float = 0.00001  # $10/M tokens - standard input rate
    output_cost_per_token: float = 0.00003  # $30/M tokens - standard output rate
    
    # Completed iterations (read-only after end_iteration)
    iterations: list[ToolCallCost] = field(default_factory=list)
    
    # Current iteration being tracked
    _current: Optional[ToolCallCost] = field(default=None, repr=False)
    
    # Warning thresholds (as fractions of max_cost)
    _warning_threshold_50: float = field(default=0.5, repr=False)
    _warning_threshold_80: float = field(default=0.8, repr=False)
    _warning_threshold_90: float = field(default=0.9, repr=False)
    
    # Track which warnings have been issued to avoid duplicates
    _warned_50: bool = field(default=False, repr=False)
    _warned_80: bool = field(default=False, repr=False)
    _warned_90: bool = field(default=False, repr=False)
    
    def start_iteration(self, iteration: int) -> ToolCallCost:
        """Start tracking a new iteration.
        
        Creates a new ToolCallCost for the given iteration number.
        Must be followed by end_iteration() before starting another.
        
        Args:
            iteration: The iteration number (typically 0-indexed)
            
        Returns:
            The newly created ToolCallCost instance
            
        Raises:
            RuntimeError: If an iteration is already in progress
        """
        if self._current is not None:
            raise RuntimeError(
                f"Iteration {self._current.iteration} already in progress. "
                "Call end_iteration() before starting a new one."
            )
        
        self._current = ToolCallCost(iteration=iteration)
        return self._current
    
    def record_llm_cost(self, usage, model_cost_config: Optional[dict] = None) -> None:
        """Record LLM API call cost.
        
        Extracts token counts from the usage object and calculates cost.
        Supports both standardized usage objects and dicts with token counts.
        
        Args:
            usage: Object with prompt_tokens and completion_tokens attributes,
                   or a dict with 'prompt_tokens' and 'completion_tokens' keys,
                   or an object with a 'dict()' method returning such a dict.
            model_cost_config: Optional dict with 'input_cost_per_token' and
                              'output_cost_per_token' for model-specific pricing.
                              If None, uses the tracker's default pricing.
                              
        Raises:
            RuntimeError: If no iteration is in progress
            AttributeError: If usage object doesn't have required token attributes
        """
        if self._current is None:
            raise RuntimeError("No iteration in progress. Call start_iteration() first.")
        
        # Extract token counts from various possible formats
        if hasattr(usage, 'prompt_tokens'):
            input_tokens = usage.prompt_tokens
            output_tokens = usage.completion_tokens
        elif hasattr(usage, 'input_tokens'):
            # Alternative naming (Anthropic style)
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
        elif isinstance(usage, dict):
            input_tokens = usage.get('prompt_tokens', usage.get('input_tokens', 0))
            output_tokens = usage.get('completion_tokens', usage.get('output_tokens', 0))
        elif hasattr(usage, 'dict'):
            # Pydantic model or similar
            d = usage.dict()
            input_tokens = d.get('prompt_tokens', d.get('input_tokens', 0))
            output_tokens = d.get('completion_tokens', d.get('output_tokens', 0))
        else:
            raise AttributeError(
                f"Usage object must have prompt_tokens/completion_tokens or "
                f"input_tokens/output_tokens attributes. Got: {type(usage)}"
            )
        
        # Use model-specific pricing if provided, otherwise use defaults
        if model_cost_config:
            input_rate = model_cost_config.get('input_cost_per_token', self.input_cost_per_token)
            output_rate = model_cost_config.get('output_cost_per_token', self.output_cost_per_token)
        else:
            input_rate = self.input_cost_per_token
            output_rate = self.output_cost_per_token
        
        # Calculate costs
        input_cost = input_tokens * input_rate
        output_cost = output_tokens * output_rate
        
        # Record in current iteration
        self._current.llm_input_tokens = input_tokens
        self._current.llm_output_tokens = output_tokens
        self._current.llm_cost = input_cost + output_cost
    
    def record_llm_tokens(self, input_tokens: int, output_tokens: int,
                          model_cost_config: Optional[dict] = None) -> None:
        """Record LLM cost directly from token counts.
        
        Alternative to record_llm_cost() when you already have token counts
        rather than a usage object.
        
        Args:
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/completion tokens
            model_cost_config: Optional model-specific pricing config
        """
        if self._current is None:
            raise RuntimeError("No iteration in progress. Call start_iteration() first.")
        
        if model_cost_config:
            input_rate = model_cost_config.get('input_cost_per_token', self.input_cost_per_token)
            output_rate = model_cost_config.get('output_cost_per_token', self.output_cost_per_token)
        else:
            input_rate = self.input_cost_per_token
            output_rate = self.output_cost_per_token
        
        self._current.llm_input_tokens = input_tokens
        self._current.llm_output_tokens = output_tokens
        self._current.llm_cost = (input_tokens * input_rate) + (output_tokens * output_rate)
    
    def record_tool_output(self, output: str) -> int:
        """Record tool output size (becomes next iteration's input).
        
        Calculates token count from string output using a simple heuristic:
        approximately 4 characters per token (conservative estimate for English text).
        This estimates the cost that will be incurred when this output is sent
        as input to the next LLM call.
        
        Args:
            output: The string output from tool execution
            
        Returns:
            The estimated token count of the output
            
        Raises:
            RuntimeError: If no iteration is in progress
        """
        if self._current is None:
            raise RuntimeError("No iteration in progress. Call start_iteration() first.")
        
        # Simple token estimation: ~4 characters per token
        # This is a conservative estimate that works well for English text
        # More accurate methods would use tiktoken or similar
        estimated_tokens = len(output) // 4 if output else 0
        
        # Record the output tokens
        self._current.tool_output_tokens = estimated_tokens
        
        # Estimate the cost when this becomes input to next iteration
        self._current.tool_output_cost = estimated_tokens * self.input_cost_per_token
        
        return estimated_tokens
    
    def record_tool_output_tokens(self, token_count: int) -> None:
        """Record tool output token count directly.
        
        Use this when you have an accurate token count from a tokenizer
        rather than needing to estimate from string length.
        
        Args:
            token_count: The exact number of tokens in the tool output
        """
        if self._current is None:
            raise RuntimeError("No iteration in progress. Call start_iteration() first.")
        
        self._current.tool_output_tokens = token_count
        self._current.tool_output_cost = token_count * self.input_cost_per_token
    
    def end_iteration(self) -> ToolCallCost:
        """Finalize current iteration tracking.
        
        Moves the current iteration to the completed list and checks
        budget thresholds for warnings.
        
        Returns:
            The completed ToolCallCost instance
            
        Raises:
            RuntimeError: If no iteration is in progress
        """
        if self._current is None:
            raise RuntimeError("No iteration in progress. Call start_iteration() first.")
        
        completed = self._current
        self.iterations.append(completed)
        self._current = None
        
        # Check budget thresholds and issue warnings
        self._check_budget_warnings()
        
        return completed
    
    def _check_budget_warnings(self) -> None:
        """Check budget thresholds and issue warnings if crossed."""
        total = self.total_cost
        ratio = total / self.max_cost if self.max_cost > 0 else 0
        
        if ratio >= self._warning_threshold_90 and not self._warned_90:
            warnings.warn(
                f"Cost budget 90% exhausted: ${total:.2f} / ${self.max_cost:.2f}. "
                f"Consider completing the task soon.",
                UserWarning,
                stacklevel=3
            )
            self._warned_90 = True
        elif ratio >= self._warning_threshold_80 and not self._warned_80:
            warnings.warn(
                f"Cost budget 80% exhausted: ${total:.2f} / ${self.max_cost:.2f}",
                UserWarning,
                stacklevel=3
            )
            self._warned_80 = True
        elif ratio >= self._warning_threshold_50 and not self._warned_50:
            warnings.warn(
                f"Cost budget 50% exhausted: ${total:.2f} / ${self.max_cost:.2f}",
                UserWarning,
                stacklevel=3
            )
            self._warned_50 = True
    
    @property
    def total_cost(self) -> float:
        """Total accumulated cost across all iterations.
        
        Includes both actual LLM costs and estimated tool output costs
        that will be charged on subsequent iterations.
        """
        total = sum(it.total_cost for it in self.iterations)
        if self._current is not None:
            total += self._current.total_cost
        return total
    
    @property
    def total_tokens(self) -> int:
        """Total tokens across all iterations.
        
        Counts all tokens: LLM input, LLM output, and tool output.
        Note that tool output from iteration N becomes LLM input in iteration N+1,
        so there's some conceptual overlap in what these tokens represent.
        """
        total = sum(it.total_tokens for it in self.iterations)
        if self._current is not None:
            total += self._current.total_tokens
        return total
    
    @property
    def total_llm_cost(self) -> float:
        """Total actual LLM API costs (excluding estimated tool output costs)."""
        total = sum(it.llm_cost for it in self.iterations)
        if self._current is not None:
            total += self._current.llm_cost
        return total
    
    @property
    def total_tool_output_cost(self) -> float:
        """Total estimated cost of tool outputs that will become input."""
        total = sum(it.tool_output_cost for it in self.iterations)
        if self._current is not None:
            total += self._current.tool_output_cost
        return total
    
    @property
    def remaining_budget(self) -> float:
        """Remaining cost budget.
        
        Returns:
            Dollars remaining in budget (can be negative if exceeded)
        """
        return self.max_cost - self.total_cost
    
    def is_budget_exceeded(self) -> bool:
        """Check if we've exceeded the cost limit.
        
        Returns:
            True if total_cost >= max_cost, False otherwise
        """
        return self.total_cost >= self.max_cost
    
    def get_summary(self) -> str:
        """Get human-readable cost summary.
        
        Returns a formatted string with:
        - Total cost and budget status
        - Breakdown by iteration
        - LLM vs tool output cost breakdown
        - Token counts
        
        Returns:
            Formatted multi-line string with cost summary
        """
        lines = [
            "=" * 50,
            "COST TRACKING SUMMARY",
            "=" * 50,
            "",
            f"Budget:        ${self.max_cost:.2f}",
            f"Total Cost:    ${self.total_cost:.4f} ({self.total_cost/self.max_cost*100:.1f}% of budget)",
            f"Remaining:     ${self.remaining_budget:.4f}",
            "",
            "Cost Breakdown:",
            f"  LLM API:     ${self.total_llm_cost:.4f}",
            f"  Tool Output: ${self.total_tool_output_cost:.4f} (estimated)",
            "",
            f"Total Tokens:  {self.total_tokens:,}",
            f"Iterations:    {len(self.iterations)}",
            "",
        ]
        
        if self.iterations:
            lines.append("Per-Iteration Details:")
            lines.append("-" * 50)
            for it in self.iterations:
                status = "✓" if it.llm_output_tokens > 0 else "○"
                lines.append(
                    f"  Iteration {it.iteration}: {status} "
                    f"LLM(${it.llm_cost:.4f}) + Tool(${it.tool_output_cost:.4f}) = "
                    f"${it.total_cost:.4f}"
                )
                lines.append(
                    f"             Tokens: LLM in={it.llm_input_tokens:,} out={it.llm_output_tokens:,}, "
                    f"tool_out={it.tool_output_tokens:,}"
                )
        
        if self._current is not None:
            lines.append("-" * 50)
            lines.append(
                f"  Current (iter {self._current.iteration}): IN PROGRESS... "
                f"LLM=${self._current.llm_cost:.4f}, Tool=${self._current.tool_output_cost:.4f}"
            )
        
        lines.append("")
        lines.append("=" * 50)
        
        if self.is_budget_exceeded():
            lines.append("⚠️  BUDGET EXCEEDED")
        elif self.total_cost >= self.max_cost * 0.9:
            lines.append("⚠️  Budget nearly exhausted")
        
        return "\n".join(lines)
    
    def get_iteration_costs(self) -> list[dict]:
        """Get iteration costs as list of dicts for serialization.
        
        Returns:
            List of dicts with iteration cost details
        """
        return [
            {
                "iteration": it.iteration,
                "llm_input_tokens": it.llm_input_tokens,
                "llm_output_tokens": it.llm_output_tokens,
                "llm_cost": it.llm_cost,
                "tool_output_tokens": it.tool_output_tokens,
                "tool_output_cost": it.tool_output_cost,
                "total_cost": it.total_cost,
            }
            for it in self.iterations
        ]
    
    def reset(self) -> None:
        """Reset the tracker to initial state.
        
        Clears all iterations and warnings. Use with caution - this
        discards all accumulated cost history.
        """
        self.iterations.clear()
        self._current = None
        self._warned_50 = False
        self._warned_80 = False
        self._warned_90 = False
