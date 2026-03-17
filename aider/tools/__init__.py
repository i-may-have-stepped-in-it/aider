"""Aider tools package for LLM function calling.

This package provides tool schemas and execution capabilities for aider commands
when used with LLM function calling APIs.
"""

from aider.tools.schema import (
    ToolSchemaGenerator,
    get_tool_schemas,
    get_tool_schema,
    get_tool_descriptions,
)

__all__ = [
    "ToolSchemaGenerator",
    "get_tool_schemas",
    "get_tool_schema",
    "get_tool_descriptions",
]
