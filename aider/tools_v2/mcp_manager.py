
import json
import logging
import subprocess
import threading
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str

@dataclass
class MCPResource:
    uri: str
    name: str
    description: str
    mime_type: Optional[str]
    server_name: str

@dataclass
class MCPPrompt:
    name: str
    description: str
    arguments: List[Dict[str, Any]]
    server_name: str

class MCPServer:
    """Handles communication with an MCP server via stdio."""
    
    def __init__(self, name: str, command: List[str]):
        self.name = name
        self.command = command
        self.process: Optional[subprocess.Popen] = None
        self.tools: List[MCPTool] = []
        self.resources: List[MCPResource] = []
        self.prompts: List[MCPPrompt] = []
        self._request_id = 1
        self._pending_requests: Dict[int, threading.Event] = {}
        self._responses: Dict[int, Any] = {}
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the MCP server process and initialize."""
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            self._running = True
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()
            
            # 1. Initialize
            init_res = self._call("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "aider", "version": "0.1.0"}
            })
            
            # 2. List Tools
            tools_res = self._call("tools/list", {})
            for t in tools_res.get("tools", []):
                self.tools.append(MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_name=self.name
                ))
            
            # 3. List Resources
            try:
                res_list = self._call("resources/list", {})
                for r in res_list.get("resources", []):
                    self.resources.append(MCPResource(
                        uri=r["uri"],
                        name=r["name"],
                        description=r.get("description", ""),
                        mime_type=r.get("mimeType"),
                        server_name=self.name
                    ))
            except Exception:
                logger.debug(f"Server {self.name} does not support resources/list")

            # 4. List Prompts
            try:
                prompts_list = self._call("prompts/list", {})
                for p in prompts_list.get("prompts", []):
                    self.prompts.append(MCPPrompt(
                        name=p["name"],
                        description=p.get("description", ""),
                        arguments=p.get("arguments", []),
                        server_name=self.name
                    ))
            except Exception:
                logger.debug(f"Server {self.name} does not support prompts/list")

            # 5. Initialized notification
            self._notify("notifications/initialized", {})
            
            logger.info(f"MCP Server '{self.name}' started: {len(self.tools)} tools, {len(self.resources)} resources, {len(self.prompts)} prompts")
            return True
        except Exception as e:
            logger.error(f"Failed to start MCP server {self.name}: {e}")
            self.stop()
            return False

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool on the MCP server."""
        return self._call("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

    def _call(self, method: str, params: Dict[str, Any], timeout: float = 30.0) -> Any:
        # Reduced default timeout for discovery calls
        if method in ["initialize", "tools/list", "resources/list", "prompts/list"]:
            timeout = 5.0

        rid = self._request_id
        self._request_id += 1
        
        event = threading.Event()
        self._pending_requests[rid] = event
        
        request = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params
        }
        
        try:
            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.flush()
        except Exception as e:
            logger.error(f"Failed to write to MCP server {self.name}: {e}")
            raise

        if not event.wait(timeout):
            del self._pending_requests[rid]
            raise TimeoutError(f"MCP request {rid} timed out")
            
        res = self._responses.pop(rid)
        if "error" in res:
            raise Exception(f"MCP Error: {res['error']}")
        return res.get("result")

    def _notify(self, method: str, params: Dict[str, Any]):
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        self.process.stdin.write(json.dumps(notification) + "\n")
        self.process.stdin.flush()

    def _read_loop(self):
        while self._running and self.process and self.process.stdout:
            line = self.process.stdout.readline()
            if not line:
                break
            try:
                data = json.loads(line)
                if "id" in data:
                    rid = data["id"]
                    if rid in self._pending_requests:
                        self._responses[rid] = data
                        self._pending_requests.pop(rid).set()
                elif "method" in data:
                    # Handle notifications/requests from server (ignored for now)
                    pass
            except Exception as e:
                logger.error(f"Error reading from MCP server {self.name}: {e}")

    def stop(self):
        self._running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except:
                self.process.kill()
        self.process = None

class MCPManager:
    """Manages multiple MCP servers and their combined toolset."""
    
    def __init__(self):
        self.servers: Dict[str, MCPServer] = {}

    def add_server(self, name: str, command: List[str]) -> bool:
        if name in self.servers:
            self.servers[name].stop()
        
        server = MCPServer(name, command)
        if server.start():
            self.servers[name] = server
            return True
        return False

    def get_all_tools(self) -> List[MCPTool]:
        all_tools = []
        for s in self.servers.values():
            all_tools.extend(s.tools)
        return all_tools

    def get_all_resources(self) -> List[MCPResource]:
        all_res = []
        for s in self.servers.values():
            all_res.extend(s.resources)
        return all_res

    def get_all_prompts(self) -> List[MCPPrompt]:
        all_prompts = []
        for s in self.servers.values():
            all_prompts.extend(s.prompts)
        return all_prompts

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource from whichever server owns the URI."""
        for s in self.servers.values():
            for r in s.resources:
                if r.uri == uri:
                    return s._call("resources/read", {"uri": uri})
        raise ValueError(f"Resource not found: {uri}")

    def get_prompt(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get a prompt template from whichever server owns the name."""
        for s in self.servers.values():
            for p in s.prompts:
                if p.name == name:
                    return s._call("prompts/get", {"name": name, "arguments": arguments})
        raise ValueError(f"Prompt not found: {name}")

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if server_name not in self.servers:
            raise ValueError(f"Unknown MCP server: {server_name}")
        return self.servers[server_name].call_tool(tool_name, arguments)

    def shutdown(self):
        for s in self.servers.values():
            s.stop()
        self.servers.clear()
