import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from aider.indexers.semantic import SemanticIndexer


class TestSemanticIndexer(TestCase):
    def test_update_index_disables_after_first_embedding_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "one.txt").write_text("one")
            (root / "two.txt").write_text("two")

            indexer = SemanticIndexer(str(root))

            with patch(
                "aider.indexers.semantic.litellm.embedding",
                side_effect=RuntimeError("boom"),
            ) as mock_embedding:
                indexer.update_index(["one.txt", "two.txt"])

            self.assertFalse(indexer._embedding_available)
            self.assertEqual(mock_embedding.call_count, 1)

    def test_query_short_circuits_when_embedding_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            indexer = SemanticIndexer(tmpdir)
            indexer._embedding_available = False

            with patch("aider.indexers.semantic.litellm.embedding") as mock_embedding:
                result = indexer.query("hello")

            self.assertEqual(result, [])
            mock_embedding.assert_not_called()
