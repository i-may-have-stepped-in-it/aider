"""
Gateway Tier Hook - Automatically inject tier prefixes based on message complexity.

This hook analyzes outgoing messages and injects appropriate tier prefixes
(@intel, @fast) based on message complexity and cost estimates.
"""

from typing import Any, Dict, Optional


def estimate_complexity(messages: list) -> Dict[str, Any]:
    """
    Estimate message complexity for tier selection.

    Returns a dict with:
    - total_tokens: estimated token count
    - complexity_score: 0-100 score
    - recommended_tier: @intel or @fast
    """
    total_chars = sum(len(m.get("content", "")) for m in messages if isinstance(m, dict))

    # Rough token estimate (4 chars per token)
    estimated_tokens = total_chars // 4

    # Calculate complexity score (0-100)
    # Based on: message length, code blocks, file count mentions
    complexity_score = min(100, estimated_tokens // 100)

    # Count code blocks
    code_blocks = sum(1 for m in messages if isinstance(m, dict) and "```" in m.get("content", ""))
    complexity_score += min(30, code_blocks * 5)

    # Determine recommended tier
    # @speed = highspeed pool (fast, simple tasks)
    # @intel = intelligence pool (complex reasoning, coding, debugging)
    if complexity_score < 50:
        recommended_tier = "@speed"  # Fast, cheap for simple/moderate tasks
    else:
        recommended_tier = "@intel"  # Intelligence pool for complex tasks

    return {
        "total_tokens": estimated_tokens,
        "complexity_score": complexity_score,
        "recommended_tier": recommended_tier,
        "code_blocks": code_blocks,
    }


def on_pre_send(messages: list, model: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """
    Hook to inject tier prefix before sending to LLM.

    Analyzes message complexity and prepends appropriate tier to model name.
    """
    # Only process if using gateway (model starts with @ or is "chat")
    if model and not (model.startswith("@") or model == "chat"):
        return {"model": model}  # Pass through specific models

    # Analyze complexity
    analysis = estimate_complexity(messages)
    recommended_tier = analysis["recommended_tier"]

    # Use recommended tier unless explicitly set
    if model == "chat" or not model:
        new_model = recommended_tier
    else:
        # Already has tier prefix, keep it
        new_model = model

    return {
        "model": new_model,
        "tier_analysis": analysis,
    }


def on_post_send(response: Any, tier_analysis: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
    """
    Hook to log tier usage after response.
    """
    if tier_analysis:
        # Could log metrics here
        return {
            "tier_used": tier_analysis.get("recommended_tier"),
            "complexity_score": tier_analysis.get("complexity_score"),
        }
    return {}


def register_hooks(hooks_manager):
    """
    Register gateway tier hooks.

    Usage in Aider config:
        --hooks-dir /path/to/this/file
    """
    hooks_manager.register("pre_send", on_pre_send)
    hooks_manager.register("post_send", on_post_send)

    if hooks_manager.io:
        hooks_manager.io.tool_output("Gateway tier hooks registered")


# Configuration
TIER_THRESHOLDS = {
    "@speed": {"max_complexity": 50, "description": "Fast, economical — highspeed pool"},
    "@intel": {
        "max_complexity": 100,
        "description": "Intelligence pool — complex reasoning/coding",
    },
    "@uncen": {"max_complexity": 100, "description": "Uncensored pool — NSFW/explicit content"},
}


def get_tier_info(tier: str) -> Dict[str, Any]:
    """Get information about a tier."""
    return TIER_THRESHOLDS.get(tier, {"description": "Unknown tier"})
