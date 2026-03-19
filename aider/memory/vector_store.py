"""
Lightweight Vector Store for Local RAG.

This module provides a simple, numpy-based vector store for semantic search,
enabling persistent project memory without heavy external dependencies.
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

class VectorStore:
    """
    Simple numpy-based vector store for cosine similarity search.
    """

    def __init__(self, embedding_model: str = "text-embedding-3-small"):
        self.embedding_model = embedding_model
        self.vectors: List[np.ndarray] = []
        self.metadata: List[Dict[str, Any]] = []
        self.dim: Optional[int] = None

    def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for text via litellm."""
        from litellm import embedding
        
        try:
            response = embedding(model=self.embedding_model, input=[text])
            vector = response['data'][0]['embedding']
            return np.array(vector)
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            # Fallback to zero vector if failed (not ideal but avoids crash)
            return np.zeros(self.dim) if self.dim else np.zeros(1536)

    def add(self, text: str, metadata: Dict[str, Any]):
        """Add text and metadata to the store."""
        vector = self._get_embedding(text)
        
        if self.dim is None:
            self.dim = len(vector)
        
        self.vectors.append(vector)
        self.metadata.append(metadata)

    def search(self, query: str, limit: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """Search for most similar entries."""
        if not self.vectors:
            return []

        query_vec = self._get_embedding(query)
        
        # Calculate cosine similarities
        vectors_np = np.vstack(self.vectors)
        # Normalize vectors for cosine similarity
        vectors_norm = vectors_np / np.linalg.norm(vectors_np, axis=1, keepdims=True)
        query_norm = query_vec / np.linalg.norm(query_vec)
        
        similarities = np.dot(vectors_norm, query_norm)
        
        # Get top indices
        top_indices = np.argsort(similarities)[::-1][:limit]
        
        results = []
        for idx in top_indices:
            results.append((self.metadata[idx], float(similarities[idx])))
            
        return results

    def save(self, path: Path):
        """Save store to disk."""
        data = {
            "metadata": self.metadata,
            "vectors": [v.tolist() for v in self.vectors],
            "dim": self.dim,
            "embedding_model": self.embedding_model
        }
        with open(path, "w") as f:
            json.dump(data, f)

    def load(self, path: Path):
        """Load store from disk."""
        if not path.exists():
            return

        with open(path, "r") as f:
            data = json.load(f)
            
        self.metadata = data["metadata"]
        self.vectors = [np.array(v) for v in data["vectors"]]
        self.dim = data["dim"]
        self.embedding_model = data["embedding_model"]

class ProjectMemory:
    """
    Enterprise-grade Project Memory Manager.
    Orchestrates semantic retrieval and indexing of architectural decisions.
    """

    def __init__(self, root_dir: str):
        self.root = Path(root_dir)
        self.memory_dir = self.root / ".aider" / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.store_path = self.memory_dir / "vector_store.json"
        
        self.store = VectorStore()
        self.store.load(self.store_path)

    def record_decision(self, task: str, plan: str, outcome: str = "success"):
        """Record an architectural decision/task."""
        content = f"Task: {task}\nPlan: {plan}"
        metadata = {
            "task": task,
            "plan": plan,
            "outcome": outcome,
            "timestamp": os.path.getmtime(self.store_path) if self.store_path.exists() else 0
        }
        self.store.add(content, metadata)
        self.store.save(self.store_path)

    def get_relevant_past_tasks(self, query: str, limit: int = 3) -> str:
        """Retrieve relevant past tasks as a formatted string."""
        results = self.store.search(query, limit=limit)
        if not results:
            return ""

        output = "\n### Relevant Past Decisions & Patterns:\n"
        for meta, score in results:
            if score < 0.7: continue # Threshold for relevance
            output += f"- [Relevance: {score:.2f}] Task: {meta['task']}\n"
            output += f"  Pattern: {meta['plan'][:200]}...\n"
            
        return output
