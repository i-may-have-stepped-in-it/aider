"""
Semantic Index Manager - Unified ownership of semantic indexing functionality.

This module provides a unified approach to semantic index ownership, resolving
the mixed ownership issues identified in the codex findings. It centralizes
all semantic index logic and provides a single canonical path for access.

The manager handles:
- Index creation and initialization
- Background indexing operations 
- Index updates and maintenance
- Context retrieval and search
- Thread safety and locking
"""

import hashlib
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from aider.llm import litellm

logger = logging.getLogger(__name__)


class SemanticIndexManager:
    """
    Unified manager for semantic indexing operations.
    
    This class provides a single point of ownership for semantic index functionality,
    resolving the mixed ownership issues that existed across the codebase.
    """
    
    _instances: Dict[str, 'SemanticIndexManager'] = {}
    _instances_lock = threading.Lock()
    
    def __init__(
        self,
        root: str,
        model_name: str = "text-embedding-3-small",
        db_path: Optional[Path] = None,
        api_base: Optional[str] = None,
        manager_id: Optional[str] = None
    ):
        """
        Initialize the semantic index manager.
        
        Args:
            root: Root directory of the project
            model_name: Name of the embedding model
            db_path: Path to the database file
            api_base: API base URL for embedding service
            manager_id: Optional ID for multiple instances in same project
        """
        self.root = Path(root).resolve()
        self.model_name = model_name
        self.api_base = api_base
        self.manager_id = manager_id or "default"
        
        # Determine database path
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = self.root / ".aider" / f"semantic_{self.manager_id}.db"
        
        self.db_path.parent.mkdir(exist_ok=True, parents=True)
        
        # Index configuration
        self.chunk_size = 4000  # ~1000 tokens
        self.chunk_overlap = 500
        
        # Thread safety
        self._db_locks = {}
        self._db_locks_guard = threading.Lock()
        self._initialized = False
        self._embedding_available = True
        
        # Initialize the database
        self._init_db()
    
    @classmethod
    def get_instance(
        cls,
        root: str,
        model_name: str = "text-embedding-3-small",
        db_path: Optional[Path] = None,
        api_base: Optional[str] = None,
        manager_id: Optional[str] = None
    ) -> 'SemanticIndexManager':
        """
        Get or create a singleton instance of the semantic index manager.
        
        Args:
            root: Root directory of the project
            model_name: Name of the embedding model
            db_path: Path to the database file
            api_base: API base URL for embedding service
            manager_id: Optional ID for multiple instances
            
        Returns:
            Singleton instance of SemanticIndexManager
        """
        root_path = str(Path(root).resolve())
        key = f"{root_path}:{model_name}:{str(db_path or '')}:{manager_id or 'default'}"
        
        with cls._instances_lock:
            if key not in cls._instances:
                cls._instances[key] = cls(
                    root=root,
                    model_name=model_name,
                    db_path=db_path,
                    api_base=api_base,
                    manager_id=manager_id
                )
            return cls._instances[key]
    
    @classmethod
    def clear_instance(cls, root: str, manager_id: Optional[str] = None):
        """
        Clear a specific instance from the singleton cache.
        
        Useful for testing or when the root directory changes.
        """
        root_path = str(Path(root).resolve())
        key = f"{root_path}:{manager_id or 'default'}"
        
        with cls._instances_lock:
            if key in cls._instances:
                cls._instances[key].cleanup()
                del cls._instances[key]
    
    @classmethod
    def clear_all_instances(cls):
        """Clear all instances from the singleton cache."""
        with cls._instances_lock:
            for instance in cls._instances.values():
                instance.cleanup()
            cls._instances.clear()
    
    def _get_db_lock(self):
        """Get a database-specific lock for thread safety."""
        db_key = str(self.db_path)
        with self._db_locks_guard:
            if db_key not in self._db_locks:
                self._db_locks[db_key] = threading.Lock()
            return self._db_locks[db_key]
    
    def _connect(self):
        """Create a database connection with proper timeouts."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def _mark_embedding_unavailable(self, error, context):
        """Mark embedding as unavailable and log warning."""
        if self._embedding_available:
            logger.warning("Semantic indexing disabled after %s: %s", context, error)
        self._embedding_available = False
    
    def _init_db(self):
        """Initialize the database schema."""
        if self._initialized:
            return
            
        with self._get_db_lock(), self._connect() as conn:
            # Create chunk-based table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_chunks
                (path TEXT, chunk_id INTEGER, hash TEXT, embedding BLOB,
                 PRIMARY KEY (path, chunk_id))
            """)
            
            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_path ON file_chunks(path)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON file_chunks(hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_path_hash ON file_chunks(path, hash)")
        
        self._initialized = True
    
    def _get_hash(self, text: str) -> str:
        """Generate a hash for text content."""
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
    
    def update_index(self, files: List[str]) -> bool:
        """
        Update the semantic index with the given files.
        
        Args:
            files: List of file paths to index
            
        Returns:
            True if update was successful, False otherwise
        """
        if not self._embedding_available:
            return False
        
        try:
            for file_path in files:
                self._index_file(file_path)
            return True
        except Exception as e:
            self._mark_embedding_unavailable(e, "index update")
            return False
    
    def _index_file(self, file_path: str):
        """Index a single file."""
        import os
        
        abs_file_path = Path(file_path)
        if not abs_file_path.exists():
            return
        
        # Skip non-text files
        if self._is_binary_file(abs_file_path):
            return
        
        # Read file content
        try:
            with open(abs_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Skip files that can't be decoded as UTF-8
            return
        
        # Create chunks
        chunks = self._create_chunks(content)
        
        # Get embeddings for each chunk
        embeddings = []
        for chunk in chunks:
            try:
                embedding = self._get_embedding(chunk)
                embeddings.append(embedding)
            except Exception as e:
                logger.warning(f"Failed to get embedding for {file_path}: {e}")
                embeddings.append(None)
        
        # Store in database
        with self._get_db_lock(), self._connect() as conn:
            # Remove old chunks for this file
            conn.execute("DELETE FROM file_chunks WHERE path = ?", (file_path,))
            
            # Insert new chunks
            for chunk_id, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                if embedding is not None:
                    hash_val = self._get_hash(chunk)
                    conn.execute(
                        "INSERT INTO file_chunks (path, chunk_id, hash, embedding) VALUES (?, ?, ?, ?)",
                        (file_path, chunk_id, hash_val, embedding.tobytes())
                    )
    
    def _is_binary_file(self, file_path: Path) -> bool:
        """Check if a file is binary."""
        import os
        
        # Check file extension
        binary_extensions = {'.exe', '.dll', '.so', '.dylib', '.bin', '.dat', '.pdf', '.jpg', '.png', '.gif'}
        if file_path.suffix.lower() in binary_extensions:
            return True
        
        # Check file size
        try:
            if file_path.stat().st_size > 10 * 1024 * 1024:  # 10MB
                return True
        except OSError:
            return True
        
        # Check file content
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(1024)
                return b'\0' in chunk
        except OSError:
            return True
    
    def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for text using the configured model."""
        try:
            response = litellm.embedding(
                model=self.model_name,
                input=text,
                api_base=self.api_base
            )
            
            if response and response.data and len(response.data) > 0:
                return np.array(response.data[0]['embedding'])
            else:
                raise ValueError("No embedding data returned")
                
        except Exception as e:
            self._mark_embedding_unavailable(e, "embedding generation")
            raise
    
    def search_similar(self, query: str, limit: int = 10) -> List[Tuple[str, float]]:
        """
        Search for content similar to the query.
        
        Args:
            query: Query text to search for
            limit: Maximum number of results to return
            
        Returns:
            List of tuples (file_path, similarity_score)
        """
        if not self._embedding_available:
            return []
        
        try:
            # Get query embedding
            query_embedding = self._get_embedding(query)
            
            # Search database
            with self._get_db_lock(), self._connect() as conn:
                cursor = conn.execute("""
                    SELECT path, chunk_id, embedding
                    FROM file_chunks
                    WHERE embedding IS NOT NULL
                """)
                
                results = []
                for path, chunk_id, embedding_bytes in cursor.fetchall():
                    stored_embedding = np.frombuffer(embedding_bytes)
                    similarity = self._cosine_similarity(query_embedding, stored_embedding)
                    results.append((path, similarity))
                
                # Sort by similarity and return top results
                results.sort(key=lambda x: x[1], reverse=True)
                return results[:limit]
                
        except Exception as e:
            self._mark_embedding_unavailable(e, "semantic search")
            return []
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def get_file_context(self, file_path: str, max_tokens: int = 2000) -> str:
        """
        Get context for a specific file from the semantic index.
        
        Args:
            file_path: Path to the file
            max_tokens: Maximum tokens of context to return
            
        Returns:
            Context string for the file
        """
        if not self._embedding_available:
            return ""
        
        try:
            # Search for related content
            similar_results = self.search_similar(f"code in {file_path}", limit=5)
            
            # Build context from similar files
            context_parts = []
            total_tokens = 0
            
            for related_file, similarity in similar_results:
                if related_file == file_path:
                    continue
                
                try:
                    with open(related_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Estimate tokens (rough approximation)
                    estimated_tokens = len(content) // 4  # Rough estimate
                    
                    if total_tokens + estimated_tokens <= max_tokens:
                        context_parts.append(f"### {related_file}\n{content}\n")
                        total_tokens += estimated_tokens
                    else:
                        break
                        
                except Exception as e:
                    logger.warning(f"Failed to read {related_file}: {e}")
                    continue
            
            return "\n".join(context_parts)
            
        except Exception as e:
            logger.warning(f"Failed to get context for {file_path}: {e}")
            return ""
    
    def cleanup_orphaned_entries(self, active_files: List[str]):
        """
        Remove database entries for files that no longer exist.
        
        Args:
            active_files: List of files that should still be in the index
        """
        with self._get_db_lock(), self._connect() as conn:
            # Get all unique file paths in the database
            db_files = [row[0] for row in conn.execute("SELECT DISTINCT path FROM file_chunks").fetchall()]
            
            # Find orphaned files
            active_set = set(active_files)
            orphaned = [f for f in db_files if f not in active_set]
            
            # Remove orphaned entries
            for file_path in orphaned:
                conn.execute("DELETE FROM file_chunks WHERE path = ?", (file_path,))
                logger.info(f"Removed orphaned entries for {file_path}")
    
    def get_stats(self) -> Dict[str, any]:
        """
        Get statistics about the semantic index.
        
        Returns:
            Dictionary with index statistics
        """
        with self._get_db_lock(), self._connect() as conn:
            stats = {}
            
            # Count total chunks
            result = conn.execute("SELECT COUNT(*) FROM file_chunks").fetchone()
            stats['total_chunks'] = result[0]
            
            # Count files
            result = conn.execute("SELECT COUNT(DISTINCT path) FROM file_chunks").fetchone()
            stats['total_files'] = result[0]
            
            # Count chunks with embeddings
            result = conn.execute("SELECT COUNT(*) FROM file_chunks WHERE embedding IS NOT NULL").fetchone()
            stats['chunks_with_embeddings'] = result[0]
            
            # Database size
            if self.db_path.exists():
                stats['db_size_bytes'] = self.db_path.stat().st_size
                stats['db_size_mb'] = stats['db_size_bytes'] / (1024 * 1024)
            
            stats['embedding_available'] = self._embedding_available
            stats['chunk_size'] = self.chunk_size
            stats['chunk_overlap'] = self.chunk_overlap
            
            return stats
    
    def cleanup(self):
        """Clean up resources."""
        with self._db_locks_guard:
            self._db_locks.clear()
    
    def __del__(self):
        """Cleanup when object is destroyed."""
        self.cleanup()


# Global convenience functions
def get_semantic_manager(
    root: str,
    model_name: str = "text-embedding-3-small",
    db_path: Optional[Path] = None,
    api_base: Optional[str] = None
) -> SemanticIndexManager:
    """
    Get the global semantic index manager instance.
    
    Args:
        root: Root directory of the project
        model_name: Name of the embedding model
        db_path: Path to the database file
        api_base: API base URL for embedding service
        
    Returns:
        SemanticIndexManager instance
    """
    return SemanticIndexManager.get_instance(
        root=root,
        model_name=model_name,
        db_path=db_path,
        api_base=api_base
    )


def clear_semantic_manager(root: str, manager_id: Optional[str] = None):
    """
    Clear the semantic index manager instance.
    
    Args:
        root: Root directory of the project
        manager_id: Optional ID for specific instance
    """
    SemanticIndexManager.clear_instance(root, manager_id)
