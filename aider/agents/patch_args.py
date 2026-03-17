#!/usr/bin/env python
"""
Patch for args.py to add agent-related CLI arguments.

This file contains the agent arguments that need to be added to args.py.
Instead of modifying args.py directly (which is large and frequently changes),
we provide this patch that can be applied programmatically.
"""


def add_agent_args(parser):
    """
    Add agent-related arguments to the parser.
    
    Args:
        parser: The ArgumentParser instance from args.py
    """
    group = parser.add_argument_group("Multi-agent Options")
    
    group.add_argument(
        "--enable-agents",
        action="store_true",
        help="Enable multi-agent support for parallel task execution",
        default=False,
    )
    
    group.add_argument(
        "--max-agents",
        type=int,
        default=5,
        metavar="N",
        help="Maximum number of concurrent agents (default: 5)",
    )
    
    group.add_argument(
        "--agent-timeout",
        type=float,
        default=300.0,
        metavar="SECONDS",
        help="Default timeout for agent execution in seconds (default: 300)",
    )
    
    return parser
