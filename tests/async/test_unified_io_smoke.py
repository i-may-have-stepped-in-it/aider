import asyncio
import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch
from aider.io import InputOutput
from aider.ui import PromptMode

class TestUnifiedIOSmoke(IsolatedAsyncioTestCase):
    def test_init_sync(self):
        """Verify InputOutput can be initialized in sync context."""
        io = InputOutput(pretty=False, fancy_input=False)
        self.assertIsNone(io.async_running_prompt_manager)
        self.assertEqual(io.status_data["mode"], "CHAT")

    async def test_init_async(self):
        """Verify InputOutput initializes async components in async context."""
        # This will run in an async loop thanks to IsolatedAsyncioTestCase
        io = InputOutput(pretty=False, fancy_input=False)
        self.assertIsNotNone(io.async_running_prompt_manager)
        self.assertTrue(io.is_async_mode())

    def test_status_updates(self):
        """Verify status updates work and propagate to docked prompt if present."""
        io = InputOutput(pretty=False, fancy_input=False)
        io.set_model("test-model")
        self.assertEqual(io.status_data["model_name"], "test-model")
        
        io.set_git_branch("main")
        self.assertEqual(io.status_data["git_branch"], "main")
        
        io.set_mode("AUTO")
        self.assertEqual(io.status_data["mode"], "AUTO")

    @patch('aider.ui.DockedPromptSession')
    @patch('aider.ui.live_output.LiveOutputManager')
    def test_docked_prompt_init(self, mock_live, mock_docked):
        """Verify docked prompt and live output are initialized when enabled."""
        with patch.dict('os.environ', {'AIDER_DOCKED_PROMPT': '1'}):
            io = InputOutput(pretty=True, fancy_input=True)
            self.assertIsNotNone(io._docked_prompt)
            self.assertIsNotNone(io._live_output)
            from aider.ui.live_output import LiveRichConsole
            self.assertIsInstance(io.console, LiveRichConsole)

    async def test_get_input_async_signature(self):
        """Verify get_input_async accepts edit_format argument."""
        io = InputOutput(pretty=False, fancy_input=False)
        io.yes = True # Ensure it returns early
        
        # This should not raise TypeError
        result = await io.get_input_async(
            root=".",
            rel_fnames=[],
            addable_rel_fnames=[],
            commands=None,
            abs_read_only_fnames=[],
            edit_format="diff"
        )
        self.assertEqual(result, "")

    async def test_live_output_throttling(self):
        """Verify LiveOutputManager throttles refreshes."""
        from aider.ui.live_output import LiveOutputManager
        from rich.console import Console
        from unittest.mock import MagicMock
        import time
        
        console = Console(force_terminal=True)
        manager = LiveOutputManager(console)
        manager._live = MagicMock()
        manager._is_active = True
        
        # First refresh should happen
        manager.refresh()
        self.assertEqual(manager._live.update.call_count, 1)
        
        # Immediate second refresh should be throttled
        manager.refresh()
        self.assertEqual(manager._live.update.call_count, 1)
        
        # Forced refresh should happen regardless
        manager.refresh(force=True)
        self.assertEqual(manager._live.update.call_count, 2)

    async def test_confirm_ask_yes_mode(self):
        """Verify confirm_ask in --yes mode."""
        io = InputOutput(pretty=False, fancy_input=False)
        io.yes = True
        self.assertTrue(io.confirm_ask("Ready?"))

    async def test_prompt_ask_yes_mode(self):
        """Verify prompt_ask in --yes mode."""
        io = InputOutput(pretty=False, fancy_input=False)
        io.yes = True
        self.assertEqual(io.prompt_ask("Name?", default="anon"), "yes")

if __name__ == '__main__':
    unittest.main()
