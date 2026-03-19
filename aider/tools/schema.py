"""Tool schema generation for LLM function calling.

This module generates OpenAI-compatible tool schemas from aider's existing Commands class.
The schemas follow the OpenAI function calling format and are compatible with litellm.
"""

from typing import Any, Optional


class ToolSchemaGenerator:
    """Generates OpenAI-compatible tool schemas from aider Commands.

    This class provides schemas for aider commands that can be used with
    LLM function calling APIs. Each schema defines the command's parameters,
    types, and descriptions in the OpenAI function format.

    Example:
        >>> schemas = ToolSchemaGenerator.generate_all()
        >>> print(schemas[0]["function"]["name"])
        'run'
    """

    # Command schemas in OpenAI-compatible format
    COMMAND_SCHEMAS: dict[str, dict[str, Any]] = {
        "run": {
            "type": "function",
            "function": {
                "name": "run",
                "description": (
                    "Run a short-lived shell command and wait for its completion. "
                    "For long-running processes (dev servers, build watchers), "
                    "use terminal_watch_start instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "The shell command to execute. "
                                "Example: 'ls -la', 'python test.py', 'git status'"
                            ),
                        },
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
        },
        "terminal_watch_start": {
            "type": "function",
            "function": {
                "name": "terminal_watch_start",
                "description": (
                    "Start a long-running background process and monitor its output. "
                    "Use this for dev servers, background tests, or anything that "
                    "produces a continuous stream of logs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "A unique name for this process.",
                        },
                        "command": {
                            "type": "string",
                            "description": "The command to run in the background.",
                        },
                    },
                    "required": ["name", "command"],
                    "additionalProperties": False,
                },
            },
        },
        "terminal_watch_read": {
            "type": "function",
            "function": {
                "name": "terminal_watch_read",
                "description": "Read the recent log output from a monitored background process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The name of the process to read logs from.",
                        },
                        "lines": {
                            "type": "integer",
                            "description": "Number of recent lines to retrieve.",
                            "default": 50,
                        },
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
        "terminal_watch_input": {
            "type": "function",
            "function": {
                "name": "terminal_watch_input",
                "description": "Send keyboard input (stdin) to a monitored background process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The name of the process."},
                        "text": {"type": "string", "description": "The text to send (e.g. 'y\n')."},
                    },
                    "required": ["name", "text"],
                    "additionalProperties": False,
                },
            },
        },
        "add": {
            "type": "function",
            "function": {
                "name": "add",
                "description": (
                    "Add files to the chat so aider can edit them or review them in detail. "
                    "Files can be specified by path, glob pattern, or directory. "
                    "New files can be created if they don't exist."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of file paths, glob patterns, or directories to add. "
                                "Examples: ['src/main.py'], ['*.py'], ['src/'], "
                                "['file1.py', 'file2.py']"
                            ),
                        },
                    },
                    "required": ["files"],
                    "additionalProperties": False,
                },
            },
        },
        "read_file": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": (
                    "Read the contents of a file and add it to the chat as read-only. "
                    "Use this to examine files without editing them. "
                    "The file content will be included in the context for reference."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "Path to the file to read. Can be absolute or relative "
                                "to the project root. Example: 'src/utils.py'"
                            ),
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
        "search": {
            "type": "function",
            "function": {
                "name": "search",
                "description": (
                    "Search for text patterns in the codebase using git grep or similar. "
                    "Use this to find code occurrences, references, or patterns across files. "
                    "Returns matching files and line numbers."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": (
                                "The search pattern or regular expression to find. "
                                "Example: 'def foo', 'class.*Manager', 'TODO'"
                            ),
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "Optional path or directory to limit the search scope. "
                                "If not provided, searches the entire repository. "
                                "Example: 'src/', '*.py'"
                            ),
                        },
                    },
                    "required": ["pattern"],
                    "additionalProperties": False,
                },
            },
        },
        "git": {
            "type": "function",
            "function": {
                "name": "git",
                "description": (
                    "Run a git command (output excluded from chat by default). "
                    "Use this for git operations like checking status, branching, "
                    "or viewing history. The command output is displayed but not "
                    "automatically added to the chat context."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "The git subcommand and arguments to execute. "
                                "Do not include 'git' prefix. "
                                "Examples: 'status', 'log --oneline -10', 'diff HEAD~1'"
                            ),
                        },
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
        },
        "ls": {
            "type": "function",
            "function": {
                "name": "ls",
                "description": (
                    "List all known files and indicate which are included in the chat session. "
                    "Shows three categories: files in the chat (editable), read-only files, "
                    "and repository files not in the chat. Use this to understand "
                    "the current context and available files."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
        "drop": {
            "type": "function",
            "function": {
                "name": "drop",
                "description": (
                    "Remove files from the chat session to free up context space. "
                    "Use this when files are no longer needed in the conversation "
                    "to make room for other files or reduce token usage. "
                    "If no files are specified, drops all files from the chat."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional list of file paths or patterns to remove from chat. "
                                "If empty or not provided, all files are dropped. "
                                "Examples: ['src/old_file.py'], ['*.tmp'], []"
                            ),
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            },
        },
        "commit": {
            "type": "function",
            "function": {
                "name": "commit",
                "description": (
                    "Commit edits to the repo made outside the chat. "
                    "Use this to save changes with an optional commit message. "
                    "If no message is provided, aider may generate one automatically "
                    "based on the changes made."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": (
                                "Optional commit message describing the changes. "
                                "If not provided, aider may auto-generate a message. "
                                "Example: 'Fix authentication bug in login flow'"
                            ),
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            },
        },
        "search_web": {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": (
                    "Search the web for information via OpenClaw Gateway. "
                    "Use this to find documentation, latest library versions, "
                    "or answers to technical questions not in your knowledge base."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "The search query to execute. Example: 'latest react-router v7"
                                " docs'"
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": (
                                "Maximum number of search results to return (default 5)."
                            ),
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        "scrape_web": {
            "type": "function",
            "function": {
                "name": "scrape_web",
                "description": (
                    "Scrape a webpage via OpenClaw Gateway and convert it to readable markdown. "
                    "Use this to read documentation or articles from a specific URL."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL of the webpage to scrape.",
                        },
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
        },
        "index_search": {
            "type": "function",
            "function": {
                "name": "index_search",
                "description": (
                    "Search the global semantic index for information across all indexed projects. "
                    "Use this to find how features are implemented in other repositories or "
                    "to search for organizational standards and shared components."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "The semantic search query. Example: 'auth-middleware"
                                " implementation'"
                            ),
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 5).",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        "delegate": {
            "type": "function",
            "function": {
                "name": "delegate",
                "description": (
                    "Spawn a specialized sub-agent to handle a specific sub-mission. Use this for"
                    " complex tasks that can be partitioned into independent pieces, or when you"
                    " need a specialist to focus on a particular area (e.g. testing, docs, a"
                    " specific directory)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": (
                                "A descriptive name for the specialist (e.g. 'tester',"
                                " 'migration-expert')."
                            ),
                        },
                        "mission": {
                            "type": "string",
                            "description": (
                                "The specific mission for the sub-agent. Be detailed and"
                                " unambiguous."
                            ),
                        },
                        "decompose": {
                            "type": "boolean",
                            "description": (
                                "If True, automatically break the mission into multiple parallel"
                                " sub-tasks. Use this for very large or complex requests."
                            ),
                            "default": False,
                        },
                    },
                    "required": ["agent_name", "mission"],
                    "additionalProperties": False,
                },
            },
        },
        "browser_action": {
            "type": "function",
            "function": {
                "name": "browser_action",
                "description": (
                    "Perform interactive browser actions (click, type, screenshot) via OpenClaw"
                    " Gateway. Use this for visual verification, testing, or multi-step navigation."
                    " The browser state (cookies, session) is preserved between calls."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["navigate", "click", "type", "screenshot", "scroll"],
                            "description": "The action to perform.",
                        },
                        "url": {
                            "type": "string",
                            "description": "URL for 'navigate' action.",
                        },
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for 'click' or 'type' actions.",
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to type for 'type' action.",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
            },
        },
        "mcp_list_resources": {
            "type": "function",
            "function": {
                "name": "mcp_list_resources",
                "description": (
                    "List all available resources from connected MCP servers (Model Context"
                    " Protocol)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        },
        "mcp_read_resource": {
            "type": "function",
            "function": {
                "name": "mcp_read_resource",
                "description": (
                    "Read the content of an MCP resource (e.g. database schema, remote file, log)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "uri": {
                            "type": "string",
                            "description": (
                                "The URI of the resource to read (get this from"
                                " mcp_list_resources)."
                            ),
                        },
                    },
                    "required": ["uri"],
                    "additionalProperties": False,
                },
            },
        },
        "terminal_watch_start": {
            "type": "function",
            "function": {
                "name": "terminal_watch_start",
                "description": (
                    "Start a command in the background and monitor its output. "
                    "Use this for long-running processes like dev servers or watchers."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Unique name for this process."},
                        "command": {"type": "string", "description": "The command to run."},
                    },
                    "required": ["name", "command"],
                    "additionalProperties": False,
                },
            },
        },
        "terminal_watch_read": {
            "type": "function",
            "function": {
                "name": "terminal_watch_read",
                "description": "Read the latest output buffer from a background process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The process name."},
                        "lines": {
                            "type": "integer",
                            "description": "Number of recent lines to read (default 50).",
                        },
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
        "terminal_watch_input": {
            "type": "function",
            "function": {
                "name": "terminal_watch_input",
                "description": (
                    "Send interactive input (text/keys) to a background process's stdin."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The process name."},
                        "text": {
                            "type": "string",
                            "description": "The text to send. Include \\n for Enter.",
                        },
                    },
                    "required": ["name", "text"],
                    "additionalProperties": False,
                },
            },
        },
        "terminal_watch_signal": {
            "type": "function",
            "function": {
                "name": "terminal_watch_signal",
                "description": "Send a Unix signal to a background process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The process name."},
                        "signal": {
                            "type": "integer",
                            "description": "Signal number (e.g. 2 for SIGINT, 15 for SIGTERM).",
                        },
                    },
                    "required": ["name", "signal"],
                    "additionalProperties": False,
                },
            },
        },
        "terminal_watch_stop": {
            "type": "function",
            "function": {
                "name": "terminal_watch_stop",
                "description": "Stop a monitored background process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The process name."},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
    }

    # Mapping of command names to their descriptions
    COMMAND_DESCRIPTIONS: dict[str, str] = {
        name: schema["function"]["description"] for name, schema in COMMAND_SCHEMAS.items()
    }

    @classmethod
    def generate_all(cls, coder: Optional[Any] = None) -> list[dict[str, Any]]:
        """Generate complete tool definitions for litellm.

        If coder is provided, it will also include dynamic tools from MCP servers.

        Returns a list of all tool schemas in OpenAI-compatible format.
        This can be passed directly to litellm or other OpenAI-compatible APIs.

        Returns:
            List of tool schema dictionaries, each containing 'type' and 'function' keys.
        """
        schemas = list(cls.COMMAND_SCHEMAS.values())

        # Add MCP tools if available
        if coder and hasattr(coder, "tool_router") and hasattr(coder.tool_router, "mcp_manager"):
            for mcp_tool in coder.tool_router.mcp_manager.get_all_tools():
                schemas.append(
                    {
                        "type": "function",
                        "function": {
                            "name": mcp_tool.name,
                            "description": mcp_tool.description,
                            "parameters": mcp_tool.input_schema,
                        },
                    }
                )

        return schemas

    @classmethod
    def get_command_schemas(cls) -> dict[str, dict[str, Any]]:
        """Get schemas as dict for command routing.

        Returns a dictionary mapping command names to their schemas.
        Useful for looking up schemas by command name.

        Returns:
            Dictionary with command names as keys and schema dicts as values.

        Example:
            >>> schemas = ToolSchemaGenerator.get_command_schemas()
            >>> "run" in schemas
            True
            >>> schemas["commit"]["function"]["name"]
            'commit'
        """
        return cls.COMMAND_SCHEMAS.copy()

    @classmethod
    def get_tool_description(cls, name: str) -> Optional[str]:
        """Get description for a specific tool.

        Args:
            name: The name of the tool/command.

        Returns:
            The description string if the tool exists, None otherwise.

        Example:
            >>> desc = ToolSchemaGenerator.get_tool_description("run")
            >>> "shell" in desc.lower()
            True
            >>> ToolSchemaGenerator.get_tool_description("nonexistent")
            None
        """
        return cls.COMMAND_DESCRIPTIONS.get(name)

    @classmethod
    def get_tool_schema(cls, name: str) -> Optional[dict[str, Any]]:
        """Get the full schema for a specific tool.

        Args:
            name: The name of the tool/command.

        Returns:
            The full schema dict if the tool exists, None otherwise.

        Example:
            >>> schema = ToolSchemaGenerator.get_tool_schema("add")
            >>> schema["function"]["parameters"]["required"]
            ['files']
        """
        return cls.COMMAND_SCHEMAS.get(name)

    @classmethod
    def get_required_params(cls, name: str) -> list[str]:
        """Get the required parameter names for a tool.

        Args:
            name: The name of the tool/command.

        Returns:
            List of required parameter names. Empty list if tool not found.

        Example:
            >>> ToolSchemaGenerator.get_required_params("run")
            ['command']
            >>> ToolSchemaGenerator.get_required_params("ls")
            []
        """
        schema = cls.COMMAND_SCHEMAS.get(name)
        if schema is None:
            return []
        return schema["function"]["parameters"].get("required", [])

    @classmethod
    def validate_tool_call(cls, name: str, arguments: dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate tool call arguments against the schema.

        Args:
            name: The name of the tool/command.
            arguments: Dictionary of arguments to validate.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.

        Example:
            >>> valid, error = ToolSchemaGenerator.validate_tool_call("run", {"command": "ls"})
            >>> valid
            True
            >>> valid, error = ToolSchemaGenerator.validate_tool_call("run", {})
            >>> valid
            False
            >>> "required" in error
            True
        """
        schema = cls.COMMAND_SCHEMAS.get(name)
        if schema is None:
            return False, f"Unknown tool: {name}"

        params = schema["function"]["parameters"]
        required = params.get("required", [])
        properties = params.get("properties", {})

        # Check required parameters
        for param in required:
            if param not in arguments:
                return False, f"Missing required parameter: {param}"

        # Check for unknown parameters
        if not params.get("additionalProperties", True):
            for key in arguments:
                if key not in properties:
                    return False, f"Unknown parameter: {key}"

        return True, None

    @classmethod
    def get_tool_names(cls) -> list[str]:
        """Get a list of all available tool names.

        Returns:
            Sorted list of tool/command names.

        Example:
            >>> names = ToolSchemaGenerator.get_tool_names()
            >>> "run" in names
            True
            >>> "add" in names
            True
        """
        return sorted(cls.COMMAND_SCHEMAS.keys())

    @classmethod
    def fetch_upstream_tools(cls) -> list[dict[str, Any]]:
        """
        Fetch tools from the upstream gateway (OpenClaw/OpenRouter/etc).
        Enables 'upstream skill awareness'.
        """
        import logging
        import os

        import httpx

        logger = logging.getLogger(__name__)
        gateway_url = os.environ.get("OPENAI_API_BASE")
        if not gateway_url:
            return []

        # Try to fetch from /tools or /skills endpoint
        # The gateway often exposes its available skills/tools here
        tools_url = gateway_url.rstrip("/") + "/tools"

        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(tools_url)
                if response.status_code == 200:
                    data = response.json()
                    # Expecting OpenAI tool format: [{"type": "function", "function": {...}}]
                    upstream_tools = data.get("tools", [])
                    if upstream_tools:
                        logger.info(f"Fetched {len(upstream_tools)} tools from upstream gateway")
                        return upstream_tools
        except Exception as e:
            logger.debug(f"Failed to fetch upstream tools from {tools_url}: {e}")

        return []


# Convenience functions for direct use


def get_tool_schemas() -> list[dict[str, Any]]:
    """Get all tool schemas as a list for litellm.

    This is a convenience function that calls ToolSchemaGenerator.generate_all().

    Returns:
        List of all tool schemas in OpenAI-compatible format.
    """
    return ToolSchemaGenerator.generate_all()


def get_tool_schema(name: str) -> Optional[dict[str, Any]]:
    """Get schema for a specific tool.

    This is a convenience function that calls ToolSchemaGenerator.get_tool_schema().

    Args:
        name: The name of the tool/command.

    Returns:
        The schema dict if found, None otherwise.
    """
    return ToolSchemaGenerator.get_tool_schema(name)


def get_tool_descriptions() -> dict[str, str]:
    """Get descriptions for all tools.

    Returns:
        Dictionary mapping tool names to their descriptions.
    """
    return ToolSchemaGenerator.COMMAND_DESCRIPTIONS.copy()
