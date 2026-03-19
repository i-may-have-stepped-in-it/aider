#!/usr/bin/env python3
"""
Compatibility shim for the legacy OpenClaw-specific /skill command module.
"""

import logging

from aider.skills.command import SkillsCommand

logger = logging.getLogger(__name__)


class SkillCommand(SkillsCommand):
    """
    Backwards-compatible alias over the shared skills command implementation.

    The OpenClaw bridge skills are now exposed through the shared registry, so
    this class preserves older imports without maintaining a second command
    surface.
    """

    def __init__(self, io, coder=None, bridge=None, verbose: bool = False):
        super().__init__(io=io, coder=coder, verbose=verbose)
        self.bridge = bridge


def install_skill_command(commands_instance):
    """Install the shared /skill command on a Commands instance."""
    skill_cmd = SkillCommand(
        io=commands_instance.io,
        coder=getattr(commands_instance, "coder", None),
        verbose=getattr(commands_instance, "verbose", False),
    )
    commands_instance.cmd_skill = skill_cmd.cmd_skill
    commands_instance.completions_skill = skill_cmd.completions_skill
    logger.debug("Shared skill command installed via compatibility shim")


SKILL_COMMAND_HELP = """
/skill - Manage and execute shared aider skills

Subcommands:
  list [--verbose]           List available skills
  run <skill> [params]       Run a skill with key=value parameters
  info <skill>               Show skill information
  search <query>             Search for skills
"""
