"""
Tool system - DEPRECATED modules removed.

Only RiskLevel and get_tool_risk remain here for backward compatibility.
All other tool functionality has moved to aider.tools_v2
"""

from .risk import RiskLevel, get_tool_risk

__all__ = ["RiskLevel", "get_tool_risk"]
