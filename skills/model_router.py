"""
Model Routing & Selection - Makes Aider more Claude/Kimi-like

This skill provides intelligent model routing based on task complexity:
- Auto-select model based on task characteristics
- Tiered model routing (fast vs. smart)
- Cost optimization with model fallback
- Usage tracking per project
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


@dataclass
class ModelRoute:
    """Represents a model routing decision."""

    model: str
    complexity: str  # "fast", "balanced", "smart"
    confidence: float  # 0.0 to 1.0
    reasoning: str
    estimated_cost: float
    estimated_tokens: int


@dataclass
class UsageStats:
    """Track model usage statistics."""

    model: str
    total_requests: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    success_count: int = 0
    failure_count: int = 0


class ModelRoutingSkill(Skill):
    """
    Intelligent model routing based on task complexity.

    Similar to Claude's model selection and Kimi's tiered routing.
    """

    name = "model-router"
    description = "Intelligent model routing based on task complexity"

    def __init__(self, context: Optional[SkillContext] = None):
        super().__init__(context)
        self._model_routes: List[ModelRoute] = []
        self._usage_stats: Dict[str, UsageStats] = {}

        # Define model tiers
        self._fast_models = ["gemini-flash", "kimi-fast"]
        self._balanced_models = ["gemini-pro", "kimi-medium"]
        self._smart_models = ["gemini-pro-preview", "claude-sonnet", "kimi-smart"]

        # Cost per 1K tokens
        self._cost_per_1k_tokens = {
            "gemini-flash": 0.0001,
            "kimi-fast": 0.00015,
            "gemini-pro": 0.003,
            "kimi-medium": 0.004,
            "gemini-pro-preview": 0.01,
            "claude-sonnet": 0.008,
            "kimi-smart": 0.015,
        }

    def _get_required_params(self) -> List[str]:
        return ["task_description", "task_type"]

    def _validate_parameters(self, params: Dict[str, Any]) -> List[str]:
        errors = []

        if "task_description" not in params or not params["task_description"]:
            errors.append("Parameter 'task_description' is required")

        if "task_type" not in params or not params["task_type"]:
            errors.append("Parameter 'task_type' is required")

        return errors

    async def _execute_impl(self, **kwargs) -> SkillResult:
        task_description = kwargs["task_description"]
        task_type = kwargs["task_type"]

        # Analyze task complexity
        route = self._analyze_task(task_description, task_type)

        # Update usage statistics
        self._update_usage(route.model, estimated_tokens=route.estimated_tokens)

        return SkillResult(
            success=True,
            output=f"Routing to {route.model} ({route.complexity})",
            data={
                "model": route.model,
                "complexity": route.complexity,
                "confidence": route.confidence,
                "reasoning": route.reasoning,
                "estimated_cost": route.estimated_cost,
                "estimated_tokens": route.estimated_tokens,
            },
        )

    def _analyze_task(self, description: str, task_type: str) -> ModelRoute:
        """Analyze task and determine appropriate model."""
        description_lower = description.lower()

        # Heuristic analysis
        complexity_score = 0.0
        reasoning = []

        # Check for complexity indicators
        complexity_indicators = {
            "fast": ["simple", "quick", "short", "basic", "quick fix", "formatting"],
            "balanced": ["modify", "change", "update", "refactor", "improve", "optimize"],
            "smart": [
                "complex",
                "difficult",
                "analyze",
                "design",
                "architect",
                "explain",
                "review",
            ],
        }

        for level, indicators in complexity_indicators.items():
            for indicator in indicators:
                if indicator in description_lower:
                    complexity_score += 1
                    reasoning.append(f"Contains '{indicator}'")

        # Determine complexity level
        if complexity_score <= 1:
            complexity = "fast"
            models = self._fast_models
            confidence = 0.8
        elif complexity_score <= 3:
            complexity = "balanced"
            models = self._balanced_models
            confidence = 0.7
        else:
            complexity = "smart"
            models = self._smart_models
            confidence = 0.9

        # Select model based on complexity
        selected_model = models[0]  # Default to first in tier

        # Check usage stats for fallback
        if self._usage_stats:
            # Prefer models with lower cost
            min_cost = float("inf")
            for model in models:
                if model in self._usage_stats:
                    cost_per_1k = self._cost_per_1k_tokens.get(model, 0.005)
                    if cost_per_1k < min_cost:
                        min_cost = cost_per_1k
                        selected_model = model

        # Calculate estimated cost and tokens
        estimated_tokens = len(description.split()) * 10  # Rough estimate
        cost_per_1k = self._cost_per_1k_tokens.get(selected_model, 0.005)
        estimated_cost = (estimated_tokens / 1000) * cost_per_1k

        return ModelRoute(
            model=selected_model,
            complexity=complexity,
            confidence=confidence,
            reasoning=" ".join(reasoning) if reasoning else "Default routing",
            estimated_cost=estimated_cost,
            estimated_tokens=estimated_tokens,
        )

    def _update_usage(self, model: str, estimated_tokens: int):
        """Update usage statistics for a model."""
        if model not in self._usage_stats:
            self._usage_stats[model] = UsageStats(model=model)

        stats = self._usage_stats[model]
        stats.total_requests += 1
        stats.total_tokens += estimated_tokens
        stats.total_cost += (estimated_tokens / 1000) * self._cost_per_1k_tokens.get(model, 0.005)
        stats.success_count += 1

    def get_route(self, task_description: str, task_type: str) -> ModelRoute:
        """Get routing decision without executing."""
        return self._analyze_task(task_description, task_type)

    def get_model_tiers(self) -> Dict[str, List[str]]:
        """Get configured model tiers."""
        return {
            "fast": self._fast_models,
            "balanced": self._balanced_models,
            "smart": self._smart_models,
        }

    def get_usage_stats(self) -> List[Dict[str, Any]]:
        """Get usage statistics for all models."""
        return [
            {
                "model": stats.model,
                "total_requests": stats.total_requests,
                "total_tokens": stats.total_tokens,
                "total_cost": round(stats.total_cost, 4),
                "success_rate": (
                    round(stats.success_count / stats.total_requests * 100, 2)
                    if stats.total_requests > 0
                    else 0
                ),
            }
            for stats in self._usage_stats.values()
        ]

    def get_cost_estimate(self, task_description: str) -> Dict[str, Any]:
        """Get cost estimate for a task."""
        route = self._analyze_task(task_description, "general")

        return {
            "model": route.model,
            "complexity": route.complexity,
            "estimated_tokens": route.estimated_tokens,
            "estimated_cost": route.estimated_cost,
            "cost_per_1k_tokens": self._cost_per_1k_tokens.get(route.model, 0.005),
        }

    def get_optimal_model(self) -> str:
        """Get the optimal model based on current usage."""
        if not self._usage_stats:
            return self._fast_models[0]

        # Find model with best success rate and lowest cost
        best_model = None
        best_score = -1

        for model, stats in self._usage_stats.items():
            if stats.total_requests == 0:
                continue

            cost_per_1k = self._cost_per_1k_tokens.get(model, 0.005)
            success_rate = stats.success_count / stats.total_requests

            # Score: 40% success rate, 60% inverse cost
            score = (success_rate * 40) + ((1 / cost_per_1k) * 60)

            if score > best_score:
                best_score = score
                best_model = model

        return best_model if best_model else self._fast_models[0]

    def reset_usage_stats(self):
        """Reset all usage statistics."""
        self._usage_stats = {}

    async def get_recommendation(self, task_description: str) -> SkillResult:
        """Get a comprehensive recommendation for a task."""
        route = self._analyze_task(task_description, "general")
        stats = self.get_usage_stats()

        return SkillResult(
            success=True,
            output=f"Recommendation: Use {route.model} ({route.complexity})",
            data={
                "model": route.model,
                "complexity": route.complexity,
                "confidence": route.confidence,
                "reasoning": route.reasoning,
                "estimated_cost": route.estimated_cost,
                "estimated_tokens": route.estimated_tokens,
                "usage_stats": stats,
                "optimal_model": self.get_optimal_model(),
            },
        )
