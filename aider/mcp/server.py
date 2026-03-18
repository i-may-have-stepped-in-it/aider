import json
import logging
import sys
from typing import Any, Dict, Optional

from aider.coders import Coder

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
                    "capabilities": {},
                    "serverInfo": {"name": "aider-mcp", "version": "0.1.0"},
                },
            }

        # 2. Discovery
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "tools": [
                        {
                            "name": "apply_edit",
                            "description": (
                                "Apply a code change to a file using Aider's SEARCH/REPLACE engine."
                            ),
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
                            "description": (
                                "Search the project's code and documentation semantically."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                            },
                        },
                    ]
                },
            }

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

                    indexer = SemanticIndexer.get_global()
                    results = indexer.query(query)
                    for path, score in results:
                        print(f"- {path} ({score:.2f})")
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
