import hashlib
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from aider.llm import litellm


class SemanticIndexer:
    """Local vector index for Aider using SQLite and LiteLLM embeddings with Chunking."""

    def __init__(
        self,
        root: str,
        model_name: str = "text-embedding-3-small",
        db_path: Optional[Path] = None,
        api_base: Optional[str] = None,
    ):
        self.root = Path(root)
        self.model_name = model_name
        self.api_base = api_base
        self.chunk_size = 4000  # ~1000 tokens
        self.chunk_overlap = 500

        if db_path:
            self.db_path = db_path
        else:
            self.db_path = self.root / ".aider" / "semantic.db"
        self.db_path.parent.mkdir(exist_ok=True, parents=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Migration: Use a chunk-based table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_chunks
                (path TEXT, chunk_id INTEGER, hash TEXT, embedding BLOB,
                 PRIMARY KEY (path, chunk_id))
            """)
            # Index for faster lookups
            conn.execute("CREATE INDEX IF NOT EXISTS idx_path ON file_chunks(path)")

    def _get_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _create_chunks(self, text: str) -> List[str]:
        """Split text into overlapping chunks."""
        if len(text) <= self.chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end])
            start += self.chunk_size - self.chunk_overlap
            # Safety break to avoid tiny trailing chunks
            if len(text) - start < self.chunk_overlap:
                break
        return chunks

    def cleanup_orphaned_entries(self, active_files: List[str]):
        """Remove database entries for files that no longer exist in the project."""
        with sqlite3.connect(self.db_path) as conn:
            # Get all unique file paths in the database
            db_files = [
                row[0] for row in conn.execute("SELECT DISTINCT path FROM file_chunks").fetchall()
            ]

            # Find files in DB but not in the active file list
            active_set = set(active_files)
            orphaned = [
                f
                for f in db_files
                if f not in active_set and not f.startswith("http")  # Keep remote docs
            ]

            if orphaned:
                print(f"Cleaning up {len(orphaned)} orphaned entries from semantic index...")
                for f in orphaned:
                    conn.execute("DELETE FROM file_chunks WHERE path=?", (f,))

    def update_index(self, files: List[str]):
        """Incrementally update overlapping chunks for changed files."""
        # PARITY+: Maintain database integrity
        self.cleanup_orphaned_entries(files)

        with sqlite3.connect(self.db_path) as conn:
            for f_str in files:
                f_path = self.root / f_str
                if not f_path.exists() or f_path.is_dir():
                    continue

                full_content = f_path.read_text(errors="ignore")
                file_hash = hashlib.sha256(full_content.encode("utf-8")).hexdigest()

                # Check if file has changed
                curr = conn.execute(
                    "SELECT hash FROM file_chunks WHERE path=? LIMIT 1", (f_str,)
                ).fetchone()
                if curr and curr[0] == file_hash:
                    continue

                # File changed: Remove old chunks
                conn.execute("DELETE FROM file_chunks WHERE path=?", (f_str,))

                chunks = self._create_chunks(full_content)
                # Safety limit: max 20 chunks per file to prevent runaway indexing
                chunks = chunks[:20]

                for i, chunk_text in enumerate(chunks):
                    try:
                        response = litellm.embedding(
                            model=self.model_name, input=[chunk_text], api_base=self.api_base
                        )

                        data = response.data[0]
                        raw_embedding = (
                            data["embedding"] if isinstance(data, dict) else data.embedding
                        )
                        embedding_blob = np.array(raw_embedding, dtype=np.float32).tobytes()

                        conn.execute(
                            "INSERT INTO file_chunks VALUES (?, ?, ?, ?)",
                            (f_str, i, file_hash, embedding_blob),
                        )
                    except Exception as e:
                        print(f"Embedding error for {f_str} chunk {i}: {e}")
                        # Stop indexing this file if model fails
                        # (e.g. context limit still hit)
                        break

    def query(self, query: str, limit: int = 5) -> List[Tuple[str, float]]:
        """Semantic search returning best matching files via chunk deduplication."""
        try:
            response = litellm.embedding(
                model=self.model_name, input=[query], api_base=self.api_base
            )
            data = response.data[0]
            raw_embedding = data["embedding"] if isinstance(data, dict) else data.embedding
            q_vec = np.array(raw_embedding, dtype=np.float32)
        except Exception:
            return []

        # Store best score per file
        file_scores: Dict[str, float] = {}

        with sqlite3.connect(self.db_path) as conn:
            for path, _, _, vec_blob in conn.execute("SELECT * FROM file_chunks"):
                f_vec = np.frombuffer(vec_blob, dtype=np.float32)
                # Cosine Similarity
                score = np.dot(f_vec, q_vec) / (np.linalg.norm(f_vec) * np.linalg.norm(q_vec))

                if path not in file_scores or score > file_scores[path]:
                    file_scores[path] = float(score)

        # Sort and limit
        sorted_results = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:limit]

    def add_content(self, identifier: str, content: str):
        """Add overlapping chunks of raw content."""
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunks = self._create_chunks(content)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM file_chunks WHERE path=?", (identifier,))
            for i, chunk_text in enumerate(chunks[:20]):
                try:
                    response = litellm.embedding(
                        model=self.model_name, input=[chunk_text], api_base=self.api_base
                    )
                    data = response.data[0]
                    raw_embedding = data["embedding"] if isinstance(data, dict) else data.embedding
                    embedding_blob = np.array(raw_embedding, dtype=np.float32).tobytes()
                    conn.execute(
                        "INSERT INTO file_chunks VALUES (?, ?, ?, ?)",
                        (identifier, i, file_hash, embedding_blob),
                    )
                except Exception:
                    break
