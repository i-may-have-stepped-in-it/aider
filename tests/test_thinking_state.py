"""
Tests for ThinkingStateManager and AsyncSendMessageAdapter.
"""
import pytest
import asyncio
from unittest.mock import Mock, MagicMock


class TestThinkingStateManager:
    """Test ThinkingStateManager functionality."""
    
    @pytest.fixture
    def manager(self):
        """Create a ThinkingStateManager for testing."""
        from aider.ui.thinking_state import ThinkingStateManager, ThinkingConfig
        
        config = ThinkingConfig(
            start_delay_ms=50,  # Fast for testing
            timeout_ms=100,
            animation_interval_ms=10,
        )
        return ThinkingStateManager(config=config)
    
    def test_initial_state(self, manager):
        """Verify initial state is IDLE."""
        from aider.ui.thinking_state import ThinkingState
        
        assert manager.state == ThinkingState.IDLE
        assert not manager.is_thinking
        assert not manager.show_thinking_indicator
    
    @pytest.mark.asyncio
    async def test_start_generation_transitions_to_starting(self, manager):
        """Verify start_generation transitions to STARTING."""
        from aider.ui.thinking_state import ThinkingState
        
        await manager.start_generation()
        assert manager.state == ThinkingState.STARTING
    
    @pytest.mark.asyncio
    async def test_token_received_transitions_to_thinking(self, manager):
        """Verify token received transitions from STARTING to THINKING."""
        from aider.ui.thinking_state import ThinkingState
        
        await manager.start_generation()
        await manager.on_token_received("test")
        
        assert manager.state == ThinkingState.THINKING
        assert manager.is_thinking
        assert manager.show_thinking_indicator
    
    @pytest.mark.asyncio
    async def test_end_generation_returns_to_idle(self, manager):
        """Verify end_generation returns to IDLE."""
        from aider.ui.thinking_state import ThinkingState
        
        await manager.start_generation()
        await manager.on_token_received("test")
        assert manager.state == ThinkingState.THINKING
        
        await manager.end_generation()
        assert manager.state == ThinkingState.IDLE
        assert not manager.is_thinking
    
    @pytest.mark.asyncio
    async def test_state_callback_fires(self):
        """Verify state change callback is called."""
        from aider.ui.thinking_state import ThinkingStateManager, ThinkingState
        
        callback_states = []
        def on_change(state):
            callback_states.append(state)
        
        manager = ThinkingStateManager(on_state_change=on_change)
        await manager.start_generation()
        await manager.end_generation()
        
        assert len(callback_states) >= 2
        assert callback_states[0] == ThinkingState.STARTING


class TestAsyncSendMessageAdapter:
    """Test AsyncSendMessageAdapter functionality."""
    
    @pytest.fixture
    def mock_send_message(self):
        """Create a mock send_message generator."""
        def _generator(message):
            yield "Chunk 1"
            yield "Chunk 2"
            yield "Chunk 3"
        return _generator
    
    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, mock_send_message):
        """Verify stream yields all chunks."""
        from aider.ui.thinking_state import AsyncSendMessageAdapter
        
        adapter = AsyncSendMessageAdapter(mock_send_message)
        chunks = []
        
        async for chunk in adapter.stream("test message"):
            chunks.append(chunk)
        
        assert len(chunks) == 3
        assert chunks[0] == "Chunk 1"
        assert chunks[1] == "Chunk 2"
        assert chunks[2] == "Chunk 3"
    
    @pytest.mark.asyncio
    async def test_stream_calls_chunk_callback(self, mock_send_message):
        """Verify stream calls on_chunk callback."""
        from aider.ui.thinking_state import AsyncSendMessageAdapter
        
        received_chunks = []
        def on_chunk(chunk):
            received_chunks.append(chunk)
        
        adapter = AsyncSendMessageAdapter(
            mock_send_message,
            on_chunk=on_chunk
        )
        
        async for _ in adapter.stream("test"):
            pass
        
        assert len(received_chunks) == 3
    
    @pytest.mark.asyncio
    async def test_stream_with_thinking_manager(self, mock_send_message):
        """Verify stream integrates with thinking manager."""
        from aider.ui.thinking_state import AsyncSendMessageAdapter, ThinkingStateManager
        
        thinking = ThinkingStateManager()
        adapter = AsyncSendMessageAdapter(
            mock_send_message,
            thinking_manager=thinking
        )
        
        assert not thinking.is_thinking
        
        async for _ in adapter.stream("test"):
            pass
        
        # Should have been thinking during generation
        assert not thinking.is_thinking  # Back to idle after


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
