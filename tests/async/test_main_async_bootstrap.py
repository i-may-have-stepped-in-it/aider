import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import git
import asyncio

from aider.main_async import async_main

class TestMainAsyncBootstrap(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir.name)
        
        # Initialize a mock git repo
        self.repo = git.Repo.init(self.test_dir.name)
        Path("test.txt").write_text("hello")
        self.repo.index.add(["test.txt"])
        self.repo.index.commit("initial")

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.test_dir.cleanup()

    @patch('aider.bootstrap.launch.prepare_main_model')
    @patch('aider.bootstrap.launch.prepare_repo_and_runtime')
    @patch('aider.bootstrap.runtime.run_interactive_session_async')
    @patch('aider.io.InputOutput')
    def test_async_main_detects_repo(self, mock_io, mock_run, mock_prep_repo, mock_prep_model):
        """Verify async_main correctly detects repo root when starting in a git dir."""
        # Setup mocks to return success and exit early
        mock_prep_model.return_value = (False, None, MagicMock(), [])
        mock_prep_repo.return_value = (False, None, MagicMock(), MagicMock())
        mock_run.return_value = None
        
        # Run async_main with empty args
        asyncio.run(async_main(argv=[]))
        
        # Check if git_root in the call to prepare_main_model matches our test dir
        call_args = mock_prep_model.call_args[1]
        self.assertEqual(Path(call_args['git_root']).resolve(), Path(self.test_dir.name).resolve())

if __name__ == '__main__':
    unittest.main()
