import json
import logging
import sys
from typing import Any, Dict, Optional

from aider.async_utils import run_async_safely
from aider.coders import Coder
from aider.skills.base import SkillContext

logger = logging.getLogger(__name__)


class AiderMCPServer:
    """
    Exposes Aider as an MCP Server (Model Context Protocol).
    Allows other agents/IDEs to use Aider's high-fidelity editing and tools.
    """

    def __init__(self, coder: Coder):
        self.coder = coder
        self.running = False

    def start(self):
        """Run the JSON-RPC loop over stdio."""
        self.running = True
        logger.info("Aider MCP Server starting...")

        while self.running:
            line = sys.stdin.readline()
            if not line:
                break

            try:
                request = json.loads(line)
                response = self.handle_request(request)
                if response:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                logger.error(f"MCP Server error: {e}")

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rid = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        # 1. Handshake
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                        "resources": {},
                    },
                    "serverInfo": {"name": "aider-mcp", "version": "0.1.0"},
                },
            }

        # 2. Discovery
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "tools": self._build_core_tools() + self._build_skill_tools(),
                },
            }

        if method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "resources": self._build_resources(),
                },
            }

        if method == "resources/read":
            uri = params.get("uri")
            if not uri:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32602, "message": "Missing resource URI"},
                }

            try:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "application/json",
                                "text": self._read_resource(uri),
                            }
                        ]
                    },
                }
            except Exception as e:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(e)}}

        # 3. Execution
        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})

            try:
                result = self.execute_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {"content": [{"type": "text", "text": result}]},
                }
            except Exception as e:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(e)}}

        return None

    def execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        # Redirect Aider's output to a buffer to avoid corrupting the MCP stdio stream
        import io
        from contextlib import redirect_stderr, redirect_stdout

        output_buffer = io.StringIO()

        try:
            with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                if name == "apply_edit":
                    path = args.get("path")
                    edit = args.get("edit_block")
                    prompt = f"Apply this change to {path}:\n\n{edit}"
                    self.coder.run(with_message=prompt)

                elif name == "run_command":
                    cmd = args.get("command")
                    from aider.run_cmd import run_cmd

                    # run_cmd prints to stdout, which is now captured
                    run_cmd(cmd, self.coder.root)

                elif name == "semantic_search":
                    query = args.get("query")
                    from aider.indexers.semantic import SemanticIndexer

                    if hasattr(self.coder, "get_semantic_indexer"):
                        indexer = self.coder.get_semantic_indexer(start_background=True)
                    else:
                        indexer = getattr(self.coder, "semantic_indexer", None)

                    if indexer is None:
                        indexer = SemanticIndexer.get_global(getattr(self.coder, "root", None))

                    results = indexer.query(query)
                    for path, score in results:
                        print(f"- {path} ({score:.2f})")
                elif name.startswith("skill/"):
                    print(self._execute_skill_tool(name, args), end="")
                else:
                    raise ValueError(f"Unknown tool: {name}")

            return output_buffer.getvalue()
        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            raise
        finally:
            output_buffer.close()

    def stop(self):
        self.running = False

    def _get_skill_registry(self):
        runtime = getattr(self.coder, "runtime", None)
        registry = getattr(runtime, "skill_registry", None)
        if registry is not None:
            return registry
        registry = getattr(self.coder, "skills_registry", None)
        if registry is not None:
            return registry

        from aider.skills.registry import get_registry

        return get_registry()

    def _get_agent_registry(self):
        runtime = getattr(self.coder, "runtime", None)
        registry = getattr(runtime, "agent_registry", None)
        if registry is not None:
            return registry
        agent_service = getattr(runtime, "agent_service", None)
        if agent_service is not None:
            return agent_service.registry
        return getattr(self.coder, "agent_registry", None)

    def _get_a2a_bus(self):
        runtime = getattr(self.coder, "runtime", None)
        bus = getattr(runtime, "a2a_bus", None)
        if bus is not None:
            return bus
        bus = getattr(self.coder, "a2a_bus", None)
        if bus is not None:
            return bus
        registry = self._get_agent_registry()
        return getattr(registry, "a2a_bus", None)

    def _build_core_tools(self):
        return [
            {
                "name": "apply_edit",
                "description": "Apply a code change to a file using Aider's SEARCH/REPLACE engine.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "edit_block": {
                            "type": "string",
                            "description": "SEARCH/REPLACE block content",
                        },
                    },
                    "required": ["path", "edit_block"],
                },
            },
            {
                "name": "run_command",
                "description": "Run a shell command in the project environment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
            {
                "name": "semantic_search",
                "description": "Search the project's code and documentation semantically.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        ]

    def _build_skill_tools(self):
        registry = self._get_skill_registry()
        tools = []
        for skill in registry.list_skills():
            metadata = registry.get_metadata(skill["name"]) or skill
            tools.append(self._build_skill_tool(metadata))
        return tools

    def _build_skill_tool(self, metadata):
        properties = {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional files to pass to the skill.",
            },
            "model": {"type": "string", "description": "Optional model override."},
            "enable_agents": {
                "type": "boolean",
                "description": "Enable sub-agents for agent-capable skills.",
            },
            "max_agents": {"type": "integer", "description": "Maximum concurrent agents."},
            "agent_timeout": {"type": "number", "description": "Sub-agent timeout in seconds."},
            "timeout": {"type": "number", "description": "Skill execution timeout in seconds."},
        }
        required = []

        for name, spec in (metadata.get("parameters") or {}).items():
            properties[name] = self._skill_param_to_json_schema(spec)
            if "default" not in spec:
                required.append(name)

        return {
            "name": f"skill/{metadata['name']}",
            "description": metadata.get("description") or f"Run the {metadata['name']} skill.",
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def _skill_param_to_json_schema(self, spec):
        type_map = {
            "string": "string",
            "boolean": "boolean",
            "integer": "integer",
            "number": "number",
            "array": "array",
            "object": "object",
        }

        schema = {
            "type": type_map.get(spec.get("type"), "string"),
            "description": spec.get("description", ""),
        }
        if spec.get("enum"):
            schema["enum"] = spec["enum"]
        if "default" in spec:
            schema["default"] = spec["default"]
        if schema["type"] == "array" and "items" not in schema:
            schema["items"] = {"type": "string"}
        return schema

    def _build_resources(self):
        return [
            {
                "uri": "aider://skills",
                "name": "skills",
                "description": "Shared aider skill descriptors for this session.",
                "mimeType": "application/json",
            },
            {
                "uri": "aider://agents",
                "name": "agents",
                "description": "Active aider sub-agents for this session.",
                "mimeType": "application/json",
            },
            {
                "uri": "aider://a2a/history",
                "name": "a2a-history",
                "description": "Recent A2A message history for this session.",
                "mimeType": "application/json",
            },
        ]

    def _read_resource(self, uri: str) -> str:
        if uri == "aider://skills":
            registry = self._get_skill_registry()
            payload = []
            for skill in registry.list_skills():
                metadata = registry.get_metadata(skill["name"]) or skill
                payload.append(metadata)
            return json.dumps(payload, indent=2, sort_keys=True)

        if uri == "aider://agents":
            registry = self._get_agent_registry()
            if registry is None:
                return "[]"
            agents = run_async_safely(registry.list_agents())
            payload = [
                {
                    "id": agent.id,
                    "name": agent.name,
                    "status": getattr(getattr(agent, "status", None), "name", None),
                    "task": agent.task,
                    "model": getattr(agent, "model", None),
                }
                for agent in agents
            ]
            return json.dumps(payload, indent=2, sort_keys=True)

        if uri == "aider://a2a/history":
            bus = self._get_a2a_bus()
            if bus is None:
                return "[]"
            payload = [
                {
                    "id": message.id,
                    "type": message.type.value,
                    "sender_id": message.sender_id,
                    "recipient_id": message.recipient_id,
                    "content_type": message.content_type.value,
                    "content": str(message.content),
                    "timestamp": message.timestamp,
                }
                for message in bus.get_history()
            ]
            return json.dumps(payload, indent=2, sort_keys=True)

        raise ValueError(f"Unknown resource: {uri}")

    def _execute_skill_tool(self, name: str, args: Dict[str, Any]) -> str:
        skill_name = name.split("/", 1)[1]
        registry = self._get_skill_registry()
        timeout = args.pop("timeout", 0.0)
        context = SkillContext(
            coder=self.coder,
            io=getattr(self.coder, "io", None),
            verbose=getattr(self.coder, "verbose", False),
            enable_agents=args.pop("enable_agents", False),
            max_agents=args.pop("max_agents", 5),
            agent_timeout=args.pop("agent_timeout", 300.0),
            timeout=timeout or 0.0,
        )
        skill = registry.create(skill_name, context)
        if not skill:
            raise ValueError(f"Skill '{skill_name}' not found")

        result = skill.execute(
            files=args.pop("files", []) or [],
            model=args.pop("model", None),
            **args,
        )
        if hasattr(result, "__await__"):
            result = run_async_safely(result, timeout=(timeout or 300.0))

        if result.success:
            return result.output or json.dumps(result.data or {"success": True})

        detail = result.error or "Skill failed"
        raise ValueError(detail)
