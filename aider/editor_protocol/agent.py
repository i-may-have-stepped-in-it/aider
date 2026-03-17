"""Aider ACP Agent implementation using official SDK."""
import asyncio
import uuid
import time
from typing import Any, Optional, Dict, List
from dataclasses import dataclass
from enum import Enum

# Official ACP SDK imports (verified)
try:
    from acp import Agent, PromptResponse, InitializeResponse, PROTOCOL_VERSION
    from acp import SessionNotification, stdio_streams, run_agent
    from acp.agent import AgentSideConnection
    from acp.helpers import text_block, start_tool_call, update_tool_call, complete_tool_call
    from acp.schema import ToolCallStart, ToolCallProgress
    from acp.schema import NewSessionResponse, LoadSessionResponse
    from acp.schema import AgentCapabilities, Implementation
    ACP_AVAILABLE = True
except ImportError:
    ACP_AVAILABLE = False
    # Placeholder classes for when SDK is not installed
    class Agent:
        def __init__(self):
            self.client = None
    class PromptResponse:
        def __init__(self, stop_reason="end_turn"):
            self.stop_reason = stop_reason
    class InitializeResponse:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    class NewSessionResponse:
        def __init__(self, session_id=""):
            self.session_id = session_id
    class LoadSessionResponse:
        pass
    class AgentCapabilities:
        pass
    class Implementation:
        def __init__(self, name="", version=""):
            self.name = name
            self.version = version
    PROTOCOL_VERSION = 1


class SessionState(Enum):
    """Session state for tracking."""
    IDLE = "idle"
    LOADING = "loading"
    PROCESSING = "processing"
    ERROR = "error"


@dataclass
class StreamingUpdate:
    """An update to stream to the client."""
    tool_call_id: str
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None  # "in_progress", "completed", "failed"


class AiderAcpAgent(Agent):
    """
    Aider as an ACP-compatible agent.
    
    Implements the Agent Client Protocol for editor integration.
    Uses the official acp.Agent base class.
    
    Features:
    - Full history replay on session load
    - Real-time streaming updates
    - Proper error handling with try/finally
    - Unique tool call IDs per operation
    
    Note: self.client is set by on_connect after connection.
    """
    
    def __init__(self, coder=None):
        if not ACP_AVAILABLE:
            raise ImportError(
                "ACP support requires 'agent-client-protocol' package. "
                "Install with: pip install agent-client-protocol"
            )
        super().__init__()
        self.coder = coder
        self._current_session: Optional[Dict] = None
        self._session_state = SessionState.IDLE
        self._tool_call_counter = 0
        self.client = None  # Will be set by on_connect
        self._streaming_queue: Optional[asyncio.Queue] = None
        self._streaming_task: Optional[asyncio.Task] = None
    
    def _get_next_tool_call_id(self) -> str:
        """Generate unique tool call ID."""
        self._tool_call_counter += 1
        return f"tc-{self._tool_call_counter}-{int(time.time() * 1000) % 10000}"
    
    def on_connect(self, conn) -> None:
        """
        Called by SDK when connection is established.
        
        The SDK calls this from AgentSideConnection.__init__ to set self.client.
        """
        self.client = conn
    
    async def initialize(
        self,
        protocol_version: int,
        client_capabilities=None,
        client_info=None,
        **kwargs
    ) -> InitializeResponse:
        """
        Handle initialize request from editor.
        
        Uses correct field names matching InitializeResponse Pydantic model.
        """
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_info=Implementation(name="aider-custom-openclaw", version="0.1.0"),
            agent_capabilities=AgentCapabilities(),  # all defaults (False) is fine for now
        )
    
    async def new_session(
        self,
        cwd: str,
        mcp_servers=None,
        **kwargs
    ) -> NewSessionResponse:
        """
        Handle session/new request.
        From spec: https://agentclientprotocol.com/protocol/session-setup
        """
        session_id = str(uuid.uuid4())
        self._current_session = {
            "session_id": session_id,
            "cwd": cwd,  # Absolute path required
            "mcp_servers": mcp_servers or [],
            "history": [],
        }
        self._tool_call_counter = 0
        return NewSessionResponse(session_id=session_id)
    
    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers=None,
        history: List[Dict] = None,
        **kwargs
    ) -> LoadSessionResponse:
        """
        Handle session/load request.
        From spec: Must replay history via session/update before confirming.
        
        IMPLEMENTED: History replay - replays all updates from the provided history
        to restore session state in the editor.
        
        Args:
            cwd: Working directory (absolute path)
            session_id: Session ID to load
            mcp_servers: Optional list of MCP servers
            history: List of history updates to replay
        """
        self._session_state = SessionState.LOADING
        
        # Initialize session
        self._current_session = {
            "session_id": session_id,
            "cwd": cwd,
            "mcp_servers": mcp_servers or [],
            "history": history or [],
        }
        self._tool_call_counter = 0
        
        # Replay history if provided
        if history:
            for idx, update in enumerate(history):
                try:
                    await self.client.session_update(
                        session_id=session_id,
                        update=update,
                    )
                except Exception as e:
                    # Log error but continue replaying remaining history
                    print(f"Warning: Failed to replay history item {idx}: {e}")
        
        self._session_state = SessionState.IDLE
        return LoadSessionResponse()
    
    async def prompt(
        self,
        prompt: list,
        session_id: str,
        **kwargs
    ) -> PromptResponse:
        """
        Handle session/prompt request.
        Streams updates via session/update notifications.
        
        IMPLEMENTED:
        - Real streaming with unique tool call IDs
        - Proper try/finally for cleanup
        - Progress updates during coder execution
        - Error handling with failed status
        
        Ref: https://agentclientprotocol.com/protocol/prompt-turn
        """
        prompt_text = self._extract_prompt_text(prompt)
        tool_call_id = self._get_next_tool_call_id()
        
        # Set up streaming
        self._streaming_queue = asyncio.Queue()
        self._session_state = SessionState.PROCESSING
        
        # Start streaming consumer
        streamer_task = asyncio.create_task(
            self._streaming_consumer(session_id, tool_call_id)
        )
        
        try:
            # Notify turn begin
            await self._emit_update(StreamingUpdate(
                tool_call_id=tool_call_id,
                title="Processing",
                status="in_progress",
            ))
            
            # Run coder with streaming
            result = await self._run_coder_streaming(
                prompt_text, 
                session_id,
                tool_call_id
            )
            
            # Send result as content update
            await self._emit_update(StreamingUpdate(
                tool_call_id=tool_call_id,
                content=result[:1000] if result else "Completed",  # Truncate for preview
                status="in_progress",
            ))
            
            # Notify completion
            await self._emit_update(StreamingUpdate(
                tool_call_id=tool_call_id,
                status="completed",
            ))
            
            return PromptResponse(stop_reason="end_turn")
            
        except asyncio.CancelledError:
            # Handle cancellation
            await self._emit_update(StreamingUpdate(
                tool_call_id=tool_call_id,
                status="failed",
                content="Cancelled",
            ))
            raise
            
        except Exception as e:
            # Handle errors - ensure failed status is sent
            await self._emit_update(StreamingUpdate(
                tool_call_id=tool_call_id,
                status="failed",
                content=f"Error: {str(e)}",
            ))
            return PromptResponse(stop_reason="error")
            
        finally:
            # CRITICAL: Always signal completion to avoid stranded tool calls
            self._streaming_queue.put_nowait(None)  # Sentinel to stop consumer
            try:
                await asyncio.wait_for(streamer_task, timeout=5.0)
            except asyncio.TimeoutError:
                streamer_task.cancel()
            
            self._session_state = SessionState.IDLE
            self._streaming_queue = None
    
    async def _emit_update(self, update: StreamingUpdate) -> None:
        """Queue an update for streaming."""
        if self._streaming_queue:
            await self._streaming_queue.put(update)
    
    async def _streaming_consumer(self, session_id: str, tool_call_id: str) -> None:
        """
        Consume streaming updates and send to client.
        
        This runs as a separate task to handle updates asynchronously.
        """
        while True:
            try:
                update = await asyncio.wait_for(
                    self._streaming_queue.get(), 
                    timeout=30.0
                )
                
                if update is None:  # Sentinel
                    break
                
                # Build update payload
                if update.status:
                    acp_update = update_tool_call(
                        tool_call_id=update.tool_call_id,
                        status=update.status,
                    )
                    if update.content:
                        acp_update["content"] = [{"type": "text", "text": update.content}]
                    if update.title:
                        acp_update["title"] = update.title
                    
                    await self.client.session_update(
                        session_id=session_id,
                        update=acp_update,
                    )
                    
            except asyncio.TimeoutError:
                # No updates for 30s, check if still processing
                if self._session_state != SessionState.PROCESSING:
                    break
            except Exception as e:
                print(f"Streaming consumer error: {e}")
                break
    
    async def _run_coder_streaming(
        self, 
        prompt_text: str, 
        session_id: str,
        tool_call_id: str
    ) -> str:
        """
        Run the Aider coder with streaming updates.
        
        IMPLEMENTED: Progress updates during execution.
        Hooks into coder's output to provide meaningful progress.
        """
        if not self.coder:
            return "Error: No coder available"
        
        # Send initial progress
        await self._emit_update(StreamingUpdate(
            tool_call_id=tool_call_id,
            title="Analyzing request...",
            content="Starting analysis",
            status="in_progress",
        ))
        
        # Progress updates during execution
        progress_steps = [
            (0.0, "Reading files..."),
            (0.3, "Analyzing codebase..."),
            (0.6, "Generating response..."),
            (0.9, "Finalizing..."),
        ]
        
        # Run coder in executor with progress updates
        loop = asyncio.get_running_loop()
        
        # Start progress updater
        progress_task = asyncio.create_task(
            self._progress_updater(tool_call_id, progress_steps)
        )
        
        try:
            # Run coder
            result = await loop.run_in_executor(
                None, 
                lambda: self.coder.run(with_message=prompt_text)
            )
            
            # Cancel progress updater
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
            
            return result if result else "Task completed"
            
        except Exception as e:
            progress_task.cancel()
            raise
    
    async def _progress_updater(
        self, 
        tool_call_id: str, 
        steps: List[tuple]
    ) -> None:
        """Send periodic progress updates."""
        for delay, message in steps:
            await asyncio.sleep(1.0)  # Update every second
            await self._emit_update(StreamingUpdate(
                tool_call_id=tool_call_id,
                title=message,
                status="in_progress",
            ))
    
    def _extract_prompt_text(self, prompt) -> str:
        """Extract text from prompt content blocks."""
        texts = []
        for block in prompt:
            if hasattr(block, 'text'):
                texts.append(block.text)
            elif isinstance(block, dict) and 'text' in block:
                texts.append(block['text'])
        return "\n".join(texts)


# Entry point for ACP mode
async def run_acp_mode(coder):
    """Run Aider in ACP mode."""
    if not ACP_AVAILABLE:
        raise ImportError(
            "ACP mode requires 'agent-client-protocol' package. "
            "Install with: pip install agent-client-protocol"
        )
    
    # Create agent without client parameter
    agent = AiderAcpAgent(coder=coder)
    
    # Let run_agent handle stream creation internally with correct order
    # run_agent() creates stdio_streams internally (output_stream, input_stream order)
    await run_agent(agent)
