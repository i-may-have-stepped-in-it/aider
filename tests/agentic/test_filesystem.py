import shutil
import tempfile
import unittest
from pathlib import Path

from aider.filesystem import TransactionalFilesystem


class TestTransactionalFilesystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        (self.test_dir / "existing.txt").write_text("original content")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_stage_and_commit(self):
        tfs = TransactionalFilesystem(str(self.test_dir))

        # Modify existing file in shadow
        tfs.write_content("existing.txt", "new content")

        # Create new file in shadow
        tfs.write_content("new.txt", "created content")

        # Verify primary root is UNCHANGED before commit
        self.assertEqual((self.test_dir / "existing.txt").read_text(), "original content")
        self.assertFalse((self.test_dir / "new.txt").exists())

        # Commit
        tfs.commit()

        # Verify primary root is UPDATED after commit
        self.assertEqual((self.test_dir / "existing.txt").read_text(), "new content")
        self.assertEqual((self.test_dir / "new.txt").read_text(), "created content")

    def test_rollback(self):
        tfs = TransactionalFilesystem(str(self.test_dir))
        tfs.write_content("existing.txt", "garbage")

        # Rollback
        tfs.rollback()

        # Verify primary root is UNCHANGED
        self.assertEqual((self.test_dir / "existing.txt").read_text(), "original content")


if __name__ == "__main__":
    unittest.main()
