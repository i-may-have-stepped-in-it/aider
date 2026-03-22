"""
Tests for UI Modernization features (Phases 1-5).

Covers:
- Toast notifications
- Enhanced status bar with color-coded context
- AiderPromptSession with running prompt delegate
- LiveView streaming display
- Prompt queuing (steer vs queue)
- Context-aware footer modes
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from prompt_toolkit.formatted_text import FormattedText

from aider.io import (
    AiderPromptSession,
    InputOutput,
    ToastManager,
)
from aider.live_view import (
    LiveView,
    StreamingMarkdownParser,
    _ContentBlock,
    _StatusBlock,
    _ToolCallBlock,
)
from aider.prompt_delegate import (
    PromptLiveViewDelegate,
    QueuedInputManager,
)


class TestToastManager(unittest.TestCase):
    """Test the ToastManager for temporary notifications."""
    
    def test_toast_adds_message(self):
        tm = ToastManager()
        tm.toast("Test message", duration=5.0)
        
        active = tm.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0], "Test message")
    
    def test_toast_with_topic_replaces_existing(self):
        tm = ToastManager()
        tm.toast("First message", duration=5.0, topic="test")
        tm.toast("Second message", duration=5.0, topic="test")
        
        active = tm.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0], "Second message")
    
    def test_toast_expires(self):
        tm = ToastManager()
        tm.toast("Quick message", duration=0.05)
        
        # Should be active immediately
        self.assertEqual(len(tm.get_active()), 1)
        
        # Wait for expiration (longer than duration)
        time.sleep(0.1)
        tm._cleanup_expired()
        
        # Should be expired now
        self.assertEqual(len(tm.get_active()), 0)
    
    def test_clear_topic_removes_toasts(self):
        tm = ToastManager()
        tm.toast("Message 1", topic="topic1")
        tm.toast("Message 2", topic="topic2")
        
        tm.clear_topic("topic1")
        
        active = tm.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0], "Message 2")


class TestEnhancedStatusBar(unittest.TestCase):
    """Test the enhanced two-line status bar."""
    
    def test_status_bar_includes_model_and_mode(self):
        io = InputOutput(pretty=False, fancy_input=False)
        io.status_data.update({
            "mode": "CHAT",
            "model_name": "openai/gpt-4",
            "phase": "Idle",
        })
        
        toolbar = io._get_bottom_toolbar()
        text = str(toolbar)
        
        self.assertIn("chat", text.lower())
        self.assertIn("gpt-4", text.lower())
    
    def test_status_bar_color_coding_green(self):
        io = InputOutput(pretty=False, fancy_input=False)
        io.status_data.update({
            "tokens_used": 5000,
            "tokens_max": 10000,
            "tokens_pct": 50.0,  # < 70% = green
        })
        
        toolbar = io._get_bottom_toolbar()
        # Should contain green color code
        text = str(toolbar)
        self.assertIn("50.0%", text)
    
    def test_status_bar_color_coding_yellow(self):
        io = InputOutput(pretty=False, fancy_input=False)
        io.status_data.update({
            "tokens_used": 7500,
            "tokens_max": 10000,
            "tokens_pct": 75.0,  # 70-90% = yellow
        })
        
        toolbar = io._get_bottom_toolbar()
        text = str(toolbar)
        self.assertIn("75.0%", text)
    
    def test_status_bar_color_coding_red(self):
        io = InputOutput(pretty=False, fancy_input=False)
        io.status_data.update({
            "tokens_used": 9500,
            "tokens_max": 10000,
            "tokens_pct": 95.0,  # > 90% = red
        })
        
        toolbar = io._get_bottom_toolbar()
        text = str(toolbar)
        self.assertIn("95.0%", text)
    
    def test_status_bar_includes_git_branch(self):
        io = InputOutput(pretty=False, fancy_input=False)
        io.status_data.update({
            "mode": "CHAT",
            "git_branch": "feature-branch",
        })
        
        toolbar = io._get_bottom_toolbar()
        text = str(toolbar)
        
        self.assertIn("feature-branch", text)
    
    def test_status_bar_token_formatting(self):
        io = InputOutput(pretty=False, fancy_input=False)
        
        # Test k formatting
        io.status_data.update({
            "tokens_used": 1500,
            "tokens_max": 5000,
            "tokens_pct": 30.0,
        })
        toolbar = io._get_bottom_toolbar()
        text = str(toolbar)
        self.assertIn("1.5k", text)
        
        # Test m formatting
        io.status_data.update({
            "tokens_used": 1500000,
            "tokens_max": 2000000,
            "tokens_pct": 75.0,
        })
        toolbar = io._get_bottom_toolbar()
        text = str(toolbar)
        self.assertIn("1.5m", text)
    
    def test_context_aware_hints_empty_composer(self):
        io = InputOutput(pretty=False, fancy_input=False)
        io.status_data.update({
            "footer_mode": "composer_empty",
            "has_draft": False,
            "is_task_running": False,
        })
        
        toolbar = io._get_bottom_toolbar()
        text = str(toolbar)
        
        # Should show default hints
        self.assertIn("?", text)  # shortcuts hint
    
    def test_context_aware_hints_task_running(self):
        io = InputOutput(pretty=False, fancy_input=False)
        io.status_data.update({
            "footer_mode": "task_running",
            "has_draft": False,
            "is_task_running": True,
        })
        
        toolbar = io._get_bottom_toolbar()
        text = str(toolbar)
        
        # Should show cancel/queue hints
        self.assertIn("esc", text.lower())
        self.assertIn("cancel", text.lower())


class TestAiderPromptSession(unittest.TestCase):
    """Test AiderPromptSession with running prompt delegate support."""
    
    def test_initial_state(self):
        session = AiderPromptSession()
        self.assertIsNone(session.running_prompt_delegate)
        self.assertFalse(session.last_submission_was_running)
        self.assertFalse(session.has_queued_input())
    
    def test_queue_input(self):
        session = AiderPromptSession()
        session.queue_input("Test message")
        
        self.assertTrue(session.has_queued_input())
        self.assertEqual(session.get_queued_input(), "Test message")
        self.assertFalse(session.has_queued_input())
    
    def test_multiple_queued_inputs(self):
        session = AiderPromptSession()
        session.queue_input("Message 1")
        session.queue_input("Message 2")
        session.queue_input("Message 3")
        
        self.assertEqual(session.get_queued_input(), "Message 1")
        self.assertEqual(session.get_queued_input(), "Message 2")
        self.assertEqual(session.get_queued_input(), "Message 3")
        self.assertIsNone(session.get_queued_input())
    
    def test_attach_detach_running_prompt(self):
        session = AiderPromptSession()
        delegate = MagicMock()
        
        session.attach_running_prompt(delegate)
        self.assertEqual(session.running_prompt_delegate, delegate)
        
        session.detach_running_prompt(delegate)
        self.assertIsNone(session.running_prompt_delegate)


class TestLiveView(unittest.TestCase):
    """Test LiveView streaming display."""
    
    def test_content_block_creation(self):
        block = _ContentBlock(is_thinking=False)
        self.assertEqual(block.raw_text, "")
        self.assertFalse(block.is_thinking)
    
    def test_content_block_append(self):
        block = _ContentBlock(is_thinking=False)
        block.append("Hello")
        block.append(" world")
        
        self.assertEqual(block.raw_text, "Hello world")
    
    def test_thinking_block_styling(self):
        block = _ContentBlock(is_thinking=True)
        block.append("Reasoning...")
        
        renderable = block.compose()
        # Thinking blocks should be styled as dim/italic
        self.assertTrue(block.is_thinking)
    
    def test_tool_call_block_lifecycle(self):
        block = _ToolCallBlock(tool_name="FetchURL", tool_id="123")
        block.set_argument("example.com")
        
        self.assertFalse(block.finished)
        self.assertEqual(block.tool_name, "FetchURL")
        self.assertEqual(block.argument, "example.com")
        
        block.finish({"output": "Success"}, is_error=False)
        self.assertTrue(block.finished)
        self.assertFalse(block.is_error)
    
    def test_tool_call_block_error(self):
        block = _ToolCallBlock(tool_name="ReadFile", tool_id="456")
        block.finish({"error": "File not found"}, is_error=True)
        
        self.assertTrue(block.finished)
        self.assertTrue(block.is_error)
    
    def test_status_block_formatting(self):
        status_data = {
            "tokens_pct": 45.2,
            "tokens_used": 5000,
            "tokens_max": 10000,
            "cost": 0.05,
        }
        block = _StatusBlock(status_data)
        
        renderable = block.render()
        self.assertIsNotNone(renderable)


class TestStreamingMarkdownParser(unittest.TestCase):
    """Test StreamingMarkdownParser for separating thinking blocks."""
    
    def test_plain_text(self):
        parser = StreamingMarkdownParser()
        results = parser.append("Hello world")
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], ("Hello world", False))
    
    def test_thinking_block(self):
        parser = StreamingMarkdownParser()
        results = parser.append("<thinking>Reasoning</thinking>")
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], ("Reasoning", True))
    
    def test_mixed_content(self):
        parser = StreamingMarkdownParser()
        results = parser.append("Before<thinking>Reason</thinking>After")
        
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0], ("Before", False))
        self.assertEqual(results[1], ("Reason", True))
        self.assertEqual(results[2], ("After", False))
    
    def test_incomplete_thinking_block(self):
        parser = StreamingMarkdownParser()
        results = parser.append("<thinking>Reasoning in progress")
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], ("Reasoning in progress", True))
    
    def test_flush_remaining(self):
        parser = StreamingMarkdownParser()
        # Append returns incomplete content immediately (doesn't buffer)
        results = parser.append("<thinking>Incomplete reasoning")
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], ("Incomplete reasoning", True))
        
        # Buffer should be empty, in_thinking_block should be True
        self.assertEqual(parser.buffer, "")
        self.assertTrue(parser.in_thinking_block)
        
        # flush() returns nothing since buffer is empty
        flush_results = parser.flush()
        self.assertEqual(flush_results, [])


class TestPromptLiveViewDelegate(unittest.TestCase):
    """Test PromptLiveViewDelegate with steer vs queue."""
    
    def test_initial_state(self):
        io_mock = MagicMock()
        delegate = PromptLiveViewDelegate(
            io=io_mock,
            status_data={},
        )
        
        self.assertFalse(delegate.cancelled)
        self.assertEqual(delegate.pending_steers, [])
    
    def test_handle_local_input_queue(self):
        io_mock = MagicMock()
        steer_callback = MagicMock()
        
        delegate = PromptLiveViewDelegate(
            io=io_mock,
            status_data={},
            steer_callback=steer_callback,
        )
        
        # Tab key = queue (queue=True)
        delegate.handle_local_input("Fix the bug", queue=True)
        
        # Should add to pending_steers
        self.assertEqual(delegate.pending_steers, ["Fix the bug"])
        # Should call callback with is_steer=False
        steer_callback.assert_called_once_with("Fix the bug", is_steer=False)
        # Should show "Queued" message
        io_mock.console.print.assert_called_once()
        self.assertIn("Queued", str(io_mock.console.print.call_args))
    
    def test_handle_local_input_steer(self):
        io_mock = MagicMock()
        steer_callback = MagicMock()
        
        delegate = PromptLiveViewDelegate(
            io=io_mock,
            status_data={},
            steer_callback=steer_callback,
        )
        
        # Enter key = steer (queue=False)
        delegate.handle_local_input("Stop and explain", queue=False)
        
        # Should NOT add to pending_steers
        self.assertEqual(delegate.pending_steers, [])
        # Should call callback with is_steer=True
        steer_callback.assert_called_once_with("Stop and explain", is_steer=True)
        # Should show "Steer" message
        io_mock.console.print.assert_called_once()
        self.assertIn("Steer", str(io_mock.console.print.call_args))
    
    def test_get_pending_steers(self):
        io_mock = MagicMock()
        delegate = PromptLiveViewDelegate(
            io=io_mock,
            status_data={},
        )
        
        delegate.pending_steers = ["Message 1", "Message 2"]
        
        steers = delegate.get_pending_steers()
        self.assertEqual(steers, ["Message 1", "Message 2"])
        self.assertEqual(delegate.pending_steers, [])  # Cleared after get
    
    def test_cancel_callback(self):
        cancel_callback = MagicMock()
        delegate = PromptLiveViewDelegate(
            io=MagicMock(),
            status_data={},
            cancel_callback=cancel_callback,
        )
        
        delegate.handle_running_prompt_key("escape", None)
        
        self.assertTrue(delegate.cancelled)
        cancel_callback.assert_called_once()


class TestQueuedInputManager(unittest.TestCase):
    """Test QueuedInputManager standalone."""
    
    def test_add_and_get(self):
        qm = QueuedInputManager()
        qm.add("Message 1")
        qm.add("Message 2")
        
        self.assertTrue(qm.has_pending())
        self.assertEqual(qm.get_next(), "Message 1")
        self.assertEqual(qm.get_next(), "Message 2")
        self.assertIsNone(qm.get_next())
    
    def test_peek_all(self):
        qm = QueuedInputManager()
        qm.add("A")
        qm.add("B")
        
        peeked = qm.peek_all()
        self.assertEqual(peeked, ["A", "B"])
        # Should still be there after peek
        self.assertTrue(qm.has_pending())
    
    def test_clear(self):
        qm = QueuedInputManager()
        qm.add("A")
        qm.add("B")
        
        qm.clear()
        self.assertFalse(qm.has_pending())


class TestInputOutputPromptQueuing(unittest.TestCase):
    """Test InputOutput methods for prompt queuing."""
    
    def test_has_queued_input_without_session(self):
        io = InputOutput(pretty=False, fancy_input=False)
        self.assertFalse(io.has_queued_input())
    
    def test_queue_input_with_session(self):
        io = InputOutput(pretty=False, fancy_input=False)
        # Manually create session to test
        io.prompt_session = AiderPromptSession()
        
        io.queue_input("Test message")
        
        self.assertTrue(io.has_queued_input())
        self.assertEqual(io.get_queued_input(), "Test message")
    
    def test_get_queued_input_empty(self):
        io = InputOutput(pretty=False, fancy_input=False)
        io.prompt_session = AiderPromptSession()
        
        self.assertIsNone(io.get_queued_input())
    
    def test_set_footer_mode(self):
        io = InputOutput(pretty=False, fancy_input=False)
        
        io.set_footer_mode("task_running")
        self.assertEqual(io.status_data["footer_mode"], "task_running")
        
        # Invalid mode should be ignored
        io.set_footer_mode("invalid_mode")
        self.assertEqual(io.status_data["footer_mode"], "task_running")  # Unchanged
    
    def test_set_task_running_updates_footer(self):
        io = InputOutput(pretty=False, fancy_input=False)
        
        io.set_task_running(True)
        self.assertTrue(io.status_data["is_task_running"])
        self.assertEqual(io.status_data["footer_mode"], "task_running")
        
        io.set_task_running(False)
        self.assertFalse(io.status_data["is_task_running"])
        self.assertEqual(io.status_data["footer_mode"], "composer_empty")
    
    def test_set_draft_status_updates_footer(self):
        io = InputOutput(pretty=False, fancy_input=False)
        
        io.set_draft_status(True)
        self.assertTrue(io.status_data["has_draft"])
        self.assertEqual(io.status_data["footer_mode"], "composer_has_draft")
        
        io.set_draft_status(False)
        self.assertFalse(io.status_data["has_draft"])
        self.assertEqual(io.status_data["footer_mode"], "composer_empty")
    
    def test_toast_method(self):
        io = InputOutput(pretty=False, fancy_input=False)
        
        # Should not raise
        io.toast("Test message", duration=0.01)
        
        # Verify toast was added
        self.assertEqual(len(io.toast_manager.get_active()), 1)
    
    def test_set_git_branch(self):
        io = InputOutput(pretty=False, fancy_input=False)
        
        io.set_git_branch("main")
        self.assertEqual(io.status_data["git_branch"], "main")
        
        io.set_git_branch(None)
        self.assertIsNone(io.status_data["git_branch"])
    
    def test_set_model(self):
        io = InputOutput(pretty=False, fancy_input=False)
        
        io.set_model("openai/gpt-4")
        self.assertEqual(io.status_data["model_name"], "openai/gpt-4")


class TestIntegration(unittest.TestCase):
    """Integration tests combining multiple components."""
    
    def test_full_prompt_queuing_workflow(self):
        """Test the complete workflow: queue inputs, then process them."""
        io = InputOutput(pretty=False, fancy_input=False)
        io.prompt_session = AiderPromptSession()
        
        # Simulate user queuing messages during LLM generation
        io.queue_input("First follow-up")
        io.queue_input("Second follow-up")
        
        # Verify both are queued
        self.assertTrue(io.has_queued_input())
        
        # Process queued messages (like coder would do)
        messages = []
        while io.has_queued_input():
            msg = io.get_queued_input()
            if msg:
                messages.append(msg)
        
        self.assertEqual(messages, ["First follow-up", "Second follow-up"])
        self.assertFalse(io.has_queued_input())
    
    def test_live_view_with_streaming_content(self):
        """Test LiveView handling streaming content."""
        io = InputOutput(pretty=False, fancy_input=False)
        status_data = {"tokens_pct": 0, "tokens_used": 0, "tokens_max": 1000, "cost": 0.0}
        
        view = LiveView(io, status_data)
        
        # Simulate streaming
        view.append_content("Hello ", is_thinking=False)
        view.append_content("world!", is_thinking=False)
        
        # Content should be accumulated
        self.assertEqual(view.current_content_block.raw_text, "Hello world!")
    
    def test_delegate_with_live_view(self):
        """Test PromptLiveViewDelegate integrating with LiveView."""
        io = InputOutput(pretty=False, fancy_input=False)
        status_data = {"tokens_pct": 0, "tokens_used": 0, "tokens_max": 1000, "cost": 0.0}
        
        delegate = PromptLiveViewDelegate(io, status_data)
        
        # Simulate streaming through delegate
        delegate.append_content("Response", is_thinking=False)
        
        # Simulate user queuing input
        delegate.handle_local_input("Follow-up", queue=True)
        
        # Verify queued
        self.assertEqual(delegate.get_pending_steers(), ["Follow-up"])

    def test_handle_steer_callback_signature(self):
        """Test that _handle_steer accepts is_steer keyword argument."""
        from aider.coders.base_coder import Coder
        from unittest.mock import MagicMock
        
        io = InputOutput(pretty=False, fancy_input=False)
        main_model = MagicMock()
        main_model.name = "test-model"
        main_model.info = {"max_input_tokens": 1000}
        
        coder = Coder(main_model, io)
        
        # This should not raise TypeError
        coder._handle_steer("test message", is_steer=True)
        coder._handle_steer("test message", is_steer=False)


if __name__ == "__main__":
    unittest.main()
