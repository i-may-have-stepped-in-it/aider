"""A2A-enabled agent mixin."""
import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional, Callable
from ..agents.agent import SubAgent
from .types import (
    A2AMessage, A2AMessageType, A2AContentType,
    A2ACapability, A2ARequest, A2AResponse
)
from .bus import A2AMessageBus

logger = logging.getLogger(__name__)


class A2AEnabledAgent(SubAgent):
    """
    SubAgent with agent-to-agent communication capabilities.
    Always enabled - no flag needed.
    """
    
    def __init__(self, *args, a2a_bus: Optional[A2AMessageBus] = None, **kwargs):
        super().__init__(*args, **kwargs)
        
        self._a2a_bus = a2a_bus
        self._capabilities: Dict[str, A2ACapability] = {}
        self._handlers: Dict[A2AMessageType, List[Callable]] = {}
        self._pending_requests: Dict[str, asyncio.Future] = {}
        
        if self._a2a_bus:
            self._a2a_bus.register(self.id, self._on_a2a_message)
    
    async def start(self):
        """
        Start the A2A agent.
        
        Called by executor's _run_agent() after agent is confirmed running.
        Handshake is done here to ensure event loop is running.
        """
        if self._a2a_bus:
            await self._send_handshake()
    
    async def stop(self):
        """
        Stop the A2A agent and cleanup.
        
        Called by executor's finally block after agent completes.
        Cancels pending futures to prevent leaks.
        """
        if self._a2a_bus:
            self._a2a_bus.unregister(self.id)
        
        # Cancel pending futures to prevent them from waiting until timeout
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()
    
    def register_capability(self, capability: A2ACapability):
        """Register a capability this agent provides."""
        self._capabilities[capability.name] = capability
    
    def on(self, msg_type: A2AMessageType, handler: Callable):
        """Register a message handler."""
        if msg_type not in self._handlers:
            self._handlers[msg_type] = []
        self._handlers[msg_type].append(handler)
    
    async def send(self, 
                   recipient_id: Optional[str],
                   content: Any,
                   msg_type: A2AMessageType = A2AMessageType.NOTIFICATION,
                   content_type: A2AContentType = A2AContentType.TEXT,
                   context: Optional[Dict] = None,
                   reply_to: Optional[str] = None,
                   message_id: Optional[str] = None) -> A2AMessage:
        """
        Send a message to another agent.
        
        Args:
            recipient_id: Target agent ID (None for broadcast)
            content: Message content
            msg_type: Message type
            content_type: Content type
            context: Shared context
            reply_to: ID of message being replied to (for request/response matching)
            message_id: Optional pre-generated message ID
        """
        if not self._a2a_bus:
            raise RuntimeError("Agent not connected to A2A bus")
        
        message = A2AMessage(
            id=message_id or str(uuid.uuid4()),
            type=msg_type,
            sender_id=self.id,
            content=content,
            content_type=content_type,
            recipient_id=recipient_id,
            reply_to=reply_to,
            shared_context=context or {}
        )
        
        await self._a2a_bus.send(message)
        return message
    
    async def request(self,
                     recipient_id: str,
                     capability: str,
                     parameters: Dict[str, Any],
                     timeout: float = 30.0) -> A2AResponse:
        """
        Request capability from another agent.
        
        Pre-generates message ID and registers future BEFORE sending
        because the bus dispatches messages inline/synchronously. The response
        could arrive inside await self.send() before it returns.
        
        Returns:
            A2AResponse object. Check .success before reading .result:
            
            resp = await agent_a.request('agent-b', 'echo', {'text': 'hi'})
            # resp is A2AResponse(success=True, result='hi', error=None)
            if resp.success:
                use(resp.result)
            else:
                handle_error(resp.error)
        """
        if not self._a2a_bus:
            raise RuntimeError("Agent not connected to A2A bus")
        
        # Use get_running_loop() (not deprecated get_event_loop())
        future = asyncio.get_running_loop().create_future()
        
        # Pre-generate ID and register future BEFORE sending
        # because bus dispatches messages inline - response could arrive
        # inside await self.send() before it returns
        msg_id = str(uuid.uuid4())
        self._pending_requests[msg_id] = future
        
        request_obj = A2ARequest(capability=capability, parameters=parameters)
        
        try:
            await self.send(
                recipient_id=recipient_id,
                content=request_obj,
                msg_type=A2AMessageType.REQUEST,
                content_type=A2AContentType.TOOL_CALL,
                message_id=msg_id,
            )
        except Exception:
            self._pending_requests.pop(msg_id, None)
            raise
        
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response.content
        except asyncio.TimeoutError:
            raise TimeoutError(f"Request to {recipient_id} timed out")
        finally:
            self._pending_requests.pop(msg_id, None)
    
    async def broadcast(self, content: Any, content_type: A2AContentType = A2AContentType.TEXT):
        """Broadcast to all agents."""
        return await self.send(
            recipient_id=None,
            content=content,
            msg_type=A2AMessageType.BROADCAST,
            content_type=content_type
        )
    
    async def delegate(self, recipient_id: str, task: str, context: Optional[Dict] = None):
        """Delegate a task to another agent."""
        return await self.send(
            recipient_id=recipient_id,
            content={"task": task, "context": context},
            msg_type=A2AMessageType.DELEGATE,
            content_type=A2AContentType.CONTEXT
        )
    
    async def _on_a2a_message(self, message: A2AMessage):
        """Handle incoming A2A message."""
        # Handle response to pending request
        if message.type == A2AMessageType.RESPONSE and message.reply_to:
            future = self._pending_requests.get(message.reply_to)
            if future and not future.done():
                future.set_result(message)
                return
        
        # Handle requests
        if message.type == A2AMessageType.REQUEST:
            await self._handle_request(message)
        
        # Handle delegation
        if message.type == A2AMessageType.DELEGATE:
            await self._handle_delegate(message)
        
        # Call registered handlers
        handlers = self._handlers.get(message.type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.error(f"A2A handler error: {e}")
    
    async def _handle_request(self, message: A2AMessage):
        """
        Handle incoming request.
        
        Guards content type to ensure it's an A2ARequest before accessing attributes.
        """
        # Guard against non-A2ARequest content
        if not isinstance(message.content, A2ARequest):
            await self._send_error(message, "Invalid request format: expected A2ARequest")
            return
        
        # A2ARequest is a dataclass - access attributes directly
        request = message.content
        capability_name = request.capability
        parameters = request.parameters
        
        capability = self._capabilities.get(capability_name)
        if not capability:
            await self._send_error(message, f"Capability '{capability_name}' not available")
            return
        
        try:
            if capability.handler:
                if asyncio.iscoroutinefunction(capability.handler):
                    result = await capability.handler(**parameters)
                else:
                    result = capability.handler(**parameters)
            else:
                result = {"status": "executed", "capability": capability_name}
            
            await self._send_success(message, result)
        except Exception as e:
            await self._send_error(message, str(e))
    
    async def _handle_delegate(self, message: A2AMessage):
        """
        Handle task delegation.
        
        Checks if handler is coroutine before awaiting, matching pattern in _on_a2a_message.
        """
        content = message.content
        if isinstance(content, dict):
            task = content.get("task")
            context = content.get("context", {})
        else:
            task = str(content)
            context = {}
        
        # Update own task with delegated work
        self.task = f"[Delegated] {task}"
        
        # Notify handlers
        handlers = self._handlers.get(A2AMessageType.DELEGATE, [])
        for handler in handlers:
            try:
                # Check if handler is coroutine before awaiting
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                logger.error(f"Delegate handler error: {e}")
    
    async def _send_success(self, request: A2AMessage, result: Any):
        """
        Send successful response.
        
        Uses reply_to=request.id so the requester can match the response.
        """
        response = A2AResponse(success=True, result=result)
        await self.send(
            recipient_id=request.sender_id,
            content=response,
            msg_type=A2AMessageType.RESPONSE,
            content_type=A2AContentType.TOOL_RESULT,
            reply_to=request.id,
        )
    
    async def _send_error(self, request: A2AMessage, error: str):
        """
        Send error response.
        
        Uses reply_to=request.id so the requester can match the response.
        """
        response = A2AResponse(success=False, error=error)
        await self.send(
            recipient_id=request.sender_id,
            content=response,
            msg_type=A2AMessageType.RESPONSE,
            content_type=A2AContentType.ERROR,
            reply_to=request.id,
        )
    
    async def _send_handshake(self):
        """Announce presence and capabilities."""
        await asyncio.sleep(0.1)
        await self.send(
            recipient_id=None,
            content={
                "name": self.name,
                "capabilities": list(self._capabilities.keys())
            },
            msg_type=A2AMessageType.HANDSHAKE,
            content_type=A2AContentType.CONTEXT
        )

    async def discuss(self, task: str, peer_ids: List[str], max_rounds: int = 3):
        """Collaboratively discuss a task with peers on the bus."""
        logger.info(f"Agent {self.name} starting discussion with {', '.join(peer_ids)}")
        
        for round in range(max_rounds):
            # 1. Gather context from previous round
            history = self.get_discussion_context()
            
            # 2. Formulate thought/response
            prompt = f"We are collaboratively solving this task: {task}\n\n"
            if history:
                prompt += f"Discussion so far:\n{history}\n\n"
            prompt += "Provide your expert opinion, critique, or next step. Be concise."
            
            response = self.coder.run(with_message=prompt)
            
            # 3. Share with peers
            await self.broadcast(content=response, content_type=A2AContentType.TEXT)
            
            # Small delay for bus synchronization
            await asyncio.sleep(0.5)

    def get_discussion_context(self) -> str:
        """Get formatted string of recent A2A discussion history."""
        if not self._a2a_bus:
            return ""
        
        messages = self._a2a_bus.get_history()
        # Filter for recent meaningful messages
        discussion = []
        for m in messages[-20:]: # Last 20 messages
            if m.type in [A2AMessageType.BROADCAST, A2AMessageType.NOTIFICATION]:
                discussion.append(f"[{m.sender_id}]: {m.content}")
        
        return "\n".join(discussion)
