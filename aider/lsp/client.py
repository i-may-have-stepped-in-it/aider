"""
Lightweight Language Server Protocol (LSP) Client for Aider.

This module provides an enterprise-grade, asynchronous LSP client that can 
interact with any standard language server (e.g., pyright, gopls, rust-analyzer).
It enables true semantic understanding of the codebase.
"""

import asyncio
import json
import logging
import os
import subprocess
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class LSPClient:
    """
    Asynchronous LSP Client implementation using JSON-RPC.
    """

    def __init__(self, command: List[str], root_dir: str):
        self.command = command
        self.root_dir = os.path.abspath(root_dir)
        self.process: Optional[asyncio.subprocess.Process] = None
        self._id_counter = 0
        self._responses: Dict[int, asyncio.Future] = {}
        self._capabilities: Dict[str, Any] = {}

    async def start(self):
        """Start the language server process."""
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=self.root_dir
            )
            # Start background reader
            asyncio.create_task(self._read_loop())
            
            # Initialize
            await self.initialize()
            return True
        except Exception as e:
            logger.error(f"Failed to start LSP server ({self.command}): {e}")
            return False

    async def stop(self):
        """Stop the language server process."""
        if self.process:
            self.process.terminate()
            await self.process.wait()

    async def _read_loop(self):
        """Background loop to read LSP responses."""
        while self.process and not self.process.stdout.at_eof():
            try:
                line = await self.process.stdout.readline()
                if not line: break
                
                if line.startswith(b"Content-Length:"):
                    length = int(line.split(b":")[1].strip())
                    await self.process.stdout.readline() # Skip empty line
                    
                    data = await self.process.stdout.readexactly(length)
                    message = json.loads(data.decode("utf-8"))
                    
                    msg_id = message.get("id")
                    if msg_id is not None and msg_id in self._responses:
                        self._responses[msg_id].set_result(message)
            except Exception as e:
                logger.error(f"LSP read error: {e}")
                break

    async def _send_request(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request to the server."""
        self._id_counter += 1
        msg_id = self._id_counter
        
        request = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params
        }
        
        body = json.dumps(request).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        
        future = asyncio.Future()
        self._responses[msg_id] = future
        
        self.process.stdin.write(header + body)
        await self.process.stdin.drain()
        
        response = await future
        del self._responses[msg_id]
        
        if "error" in response:
            raise RuntimeError(f"LSP Error: {response['error']}")
            
        return response.get("result")

    async def initialize(self):
        """Initialize the LSP server."""
        params = {
            "processId": os.getpid(),
            "rootUri": f"file://{self.root_dir}",
            "capabilities": {},
            "initializationOptions": {}
        }
        self._capabilities = await self._send_request("initialize", params)
        await self._send_request("initialized", {})

    async def get_definition(self, file_path: str, line: int, column: int) -> List[Dict[str, Any]]:
        """Get definitions for a symbol."""
        abs_path = os.path.abspath(file_path)
        params = {
            "textDocument": {"uri": f"file://{abs_path}"},
            "position": {"line": line, "character": column}
        }
        return await self._send_request("textDocument/definition", params)

    async def get_references(self, file_path: str, line: int, column: int) -> List[Dict[str, Any]]:
        """Get references for a symbol."""
        abs_path = os.path.abspath(file_path)
        params = {
            "textDocument": {"uri": f"file://{abs_path}"},
            "position": {"line": line, "character": column},
            "context": {"includeDeclaration": True}
        }
        return await self._send_request("textDocument/references", params)

class PythonLSPClient(LSPClient):
    """Specialized LSP client for Python using pyright or jedi."""
    
    @classmethod
    def find_server(cls) -> Optional[List[str]]:
        """Find an available Python LSP server on the system."""
        for cmd in [["pyright-langserver", "--stdio"], ["jedi-language-server"]]:
            try:
                subprocess.run(["which", cmd[0]], capture_output=True, check=True)
                return cmd
            except:
                continue
        return None
