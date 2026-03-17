import hashlib
import sqlite3
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple
from aider.llm import litellm


class SemanticIndexer:
    """Local vector index for Aider using SQLite and LiteLLM embeddings."""

    def __init__(self, root: str, model_name: str = "text-embedding-3-small", db_path: Optional[Path] = None):
        self.root = Path(root)
        self.model_name = model_name
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = self.root / ".aider" / "semantic.db"
        self.db_path.parent.mkdir(exist_ok=True, parents=True)
        self._init_db()

    @classmethod
    def get_global(cls, model_name: str = "text-embedding-3-small"):
        """Get the global semantic indexer."""
        global_path = Path.home() / ".aider" / "global_semantic.db"
        return cls(root=str(Path.home()), model_name=model_name, db_path=global_path)

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_cache
                (path TEXT PRIMARY KEY, hash TEXT, embedding BLOB)
            """)

    def _get_hash(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def update_index(self, files: List[str]):
        """Incrementally update embeddings for changed files."""
        with sqlite3.connect(self.db_path) as conn:
            for f_str in files:
                f_path = self.root / f_str
                if not f_path.exists() or f_path.is_dir():
                    continue

                new_hash = self._get_hash(f_path)
                curr = conn.execute("SELECT hash FROM file_cache WHERE path=?", (f_str,)).fetchone()

                if curr and curr[0] == new_hash:
                    continue

                content = f_path.read_text(errors='ignore')
                try:
                    response = litellm.embedding(model=self.model_name, input=[content])
                    embedding = np.array(response.data[0].embedding, dtype=np.float32)
                    conn.execute(
                        "INSERT OR REPLACE INTO file_cache VALUES (?, ?, ?)",
                        (f_str, new_hash, embedding.tobytes())
                    )
                except Exception as e:
                    print(f"Embedding error for {f_str}: {e}")

    def add_content(self, identifier: str, content: str):
        """Add raw content to the index (e.g. for crawled docs)."""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Check if already indexed and unchanged
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute("SELECT hash FROM file_cache WHERE path = ?", (identifier,)).fetchone()
            if res and res[0] == content_hash:
                return

        # Generate embedding
        response = litellm.embedding(model=self.model_name, input=[content])
        embedding = response.data[0].embedding
        embedding_blob = np.array(embedding, dtype=np.float32).tobytes()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO file_cache (path, hash, embedding) VALUES (?, ?, ?)",
                (identifier, content_hash, embedding_blob),
            )

    def query(self, query: str, limit: int = 5) -> List[Tuple[str, float]]:

        """Semantic search using cosine similarity."""
        try:
            response = litellm.embedding(model=self.model_name, input=[query])
            q_vec = np.array(response.data[0].embedding, dtype=np.float32)
        except Exception:
            return []

        results = []
        with sqlite3.connect(self.db_path) as conn:
            for path, _, vec_blob in conn.execute("SELECT * FROM file_cache"):
                f_vec = np.frombuffer(vec_blob, dtype=np.float32)
                score = np.dot(f_vec, q_vec) / (np.linalg.norm(f_vec) * np.linalg.norm(q_vec))
                results.append((path, score))

        return sorted(results, key=lambda x: x[1], reverse=True)[:limit]
