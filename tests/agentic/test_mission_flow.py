import unittest
from unittest.mock import MagicMock, patch

from aider.coders.architect_coder import ArchitectCoder
from aider.io import InputOutput
from aider.models import Model


class TestArchitectMission(unittest.TestCase):
    def setUp(self):
        self.io = MagicMock(spec=InputOutput)
        self.io.confirm_ask.return_value = True
        self.io.pretty = True
        self.io.chat_history_file = "/tmp/fake_hist"
        self.io.read_text.return_value = ""

        self.model = MagicMock(spec=Model)
        self.model.name = "gpt-4o"
        self.model.max_chat_history_tokens = 1024
        self.model.info = {"max_input_tokens": 128000}
        self.model.weak_model = MagicMock(spec=Model)
        self.model.weak_model.name = "gpt-4o-mini"
        self.model.editor_model = None
        self.model.editor_edit_format = "editor-whole"

    @patch("aider.coders.base_coder.Coder.create")
    def test_full_agentic_loop(self, mock_coder_create):
        """
        Verify that Architect correctly sequences:
        Librarian -> Reviewer -> Editor -> Proactive Monitor
        """
        # Specialists
        mock_librarian = MagicMock()
        mock_librarian.run.return_value = "FILES:\ntest.py"

        mock_reviewer = MagicMock()
        mock_reviewer.run.return_value = "PASSED"

        mock_editor = MagicMock()
        mock_editor.total_cost = 0.01
        mock_editor.aider_commit_hashes = ["hash1"]

        # Route create calls to the correct mock
        def side_effect(*args, **kwargs):
            from_coder = kwargs.get("from_coder")
            prompts = getattr(from_coder, "gpt_prompts", None)
            p_str = str(type(prompts))
            if "Librarian" in p_str:
                return mock_librarian
            if "Reviewer" in p_str:
                return mock_reviewer
            return mock_editor

        mock_coder_create.side_effect = side_effect

        # Initialize Architect with patched __init__ to avoid deep repo deps
        with patch("aider.coders.architect_coder.ArchitectCoder.__init__", return_value=None):
            coder = ArchitectCoder()
            coder.io = self.io
            coder.main_model = self.model
            coder.abs_fnames = set()
            coder.research_done = False
            coder.num_critiques = 0
            coder.max_critiques = 1
            coder.auto_accept_architect = True
            coder.auto_test = False
            coder.partial_response_content = "The plan is to edit test.py"
            coder.cur_messages = [{"content": "Fix the bug"}]
            coder.a2a_bus = MagicMock()
            coder.root = "/project"
            coder._critique_count = 0

            # Attributes for ToolEnabledCoderV2.run()
            coder.tool_call_count = 0
            coder.max_tool_calls = 10
            coder.tool_router = MagicMock()
            coder.tool_router.cost_tracker.check_budget.return_value = (True, "OK")
            coder.tool_router.cost_tracker.consumed_budget = 0.01
            coder.tool_router.cost_tracker.available_budget = 4.99
            coder.tool_router.cost_tracker.estimated_total_cost = 0.01
            coder.tool_router.cost_tracker.max_budget = 5.0
            coder.llm_circuit = MagicMock()
            coder._in_tool_loop = False

            # Mock methods
            coder.abs_root_path = lambda x: f"/project/{x}"
            coder.add_rel_fname = MagicMock()
            coder.move_back_cur_messages = MagicMock()
            coder.get_inchat_relative_files = lambda: []

            # Connect the actual methods we want to test
            from aider.coders.architect_coder import ArchitectCoder as RealArchitect

            coder.perform_research = RealArchitect.perform_research.__get__(coder, RealArchitect)
            coder.critique_plan = RealArchitect.critique_plan.__get__(coder, RealArchitect)
            coder.reply_completed = RealArchitect.reply_completed.__get__(coder, RealArchitect)

            # Execute Phase 1 & 2
            coder.perform_research("Fix the bug")
            coder.reply_completed()

            # Assertions
            self.assertTrue(mock_librarian.run.called, "Librarian research turn was skipped")
            self.assertTrue(mock_reviewer.run.called, "Reviewer critique turn was skipped")
            self.assertTrue(mock_editor.run.called, "Editor action turn was skipped")
            coder.add_rel_fname.assert_called_with("test.py")


if __name__ == "__main__":
    unittest.main()
