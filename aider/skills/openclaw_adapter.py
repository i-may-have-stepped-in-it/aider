"""
Adapter skills that expose OpenClaw bridge skills through the shared Skill API.
"""

from __future__ import annotations

from typing import Any, Dict

from aider.openclaw_bridge import OpenClawBridge

from .base import Skill, SkillResult


def create_openclaw_skill_class(skill_name: str, metadata, bridge: OpenClawBridge | None = None):
    """Create a shared-skill adapter class for an OpenClaw bridge skill."""
    bridge = bridge or OpenClawBridge()

    class OpenClawBridgeSkill(Skill):
        name = skill_name
        description = metadata.description or f"OpenClaw skill: {skill_name}"
        version = "openclaw"
        supports_agents = False
        max_agents = 0
        source = "openclaw"
        homepage = getattr(metadata, "homepage", None)
        requires = getattr(metadata, "requires", {})
        install = getattr(metadata, "install", [])
        emoji = getattr(metadata, "emoji", "🔧")
        _bridge = bridge
        _openclaw_metadata = metadata

        def get_parameters(self) -> Dict[str, Any]:
            return {
                "action": {
                    "type": "string",
                    "description": "OpenClaw action/script name to execute",
                    "default": "run",
                },
                "args": {
                    "type": "array",
                    "description": "Arguments forwarded to the OpenClaw skill script",
                    "default": [],
                },
                "timeout": {
                    "type": "number",
                    "description": "Execution timeout in seconds",
                    "default": 300,
                },
            }

        async def _execute_impl(self, **kwargs) -> SkillResult:
            action = kwargs.get("action", "run")
            args = kwargs.get("args", [])
            timeout = kwargs.get("timeout", 300)

            if isinstance(args, str):
                args = [args]
            elif args is None:
                args = []

            result = self._bridge.execute_skill(
                skill_name=self.name,
                action=action,
                args=list(args),
                timeout=int(timeout),
            )

            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout.strip())
            if result.stderr:
                output_parts.append(result.stderr.strip())

            return SkillResult(
                success=result.success,
                output="\n".join(part for part in output_parts if part),
                error=result.error_message if not result.success else None,
                data={
                    "exit_code": result.exit_code,
                    "duration_ms": result.duration_ms,
                    "skill_name": result.skill_name,
                    "action": result.action,
                    "source": "openclaw",
                    "homepage": self.homepage,
                    "requires": self.requires,
                    "install": self.install,
                },
            )

    OpenClawBridgeSkill.__name__ = f"OpenClaw_{skill_name.replace('-', '_')}_Skill"
    return OpenClawBridgeSkill
