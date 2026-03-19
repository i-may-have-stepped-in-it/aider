"""
Semantic index service for runtime-managed indexing.

This module unifies semantic index ownership by moving index lifecycle
management from individual Coders to the SessionRuntime.
"""

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from aider.indexers.semantic import SemanticIndexer

logger = logging.getLogger(__name__)


class SemanticIndexService:
    """
    Runtime-owned service for semantic indexing.
    
    This service manages the lifecycle of the SemanticIndexer, ensuring
    that:
    - Only one indexer exists per session
    - Background indexing is properly coordinated
    - Resources are cleaned up appropriately
    
    The service is designed to be owned by SessionRuntime and shared
    across all Coders in a session.
    """

    def __init__(
        self,
        root: str,
        model_name: str = "text-embedding-3-small",
        api_base: Optional[str] = None,
        enabled: bool = True,
    ):
        self.root = Path(root) if root else Path.cwd()
        self.model_name = model_name
        self.api_base = api_base
        self.enabled = enabled and not os.environ.get("AIDER_DISABLE_SEMANTIC_INDEX")
        
        # Lazy-initialized components
        self._indexer: Optional["SemanticIndexer"] = None
        self._indexer_lock = threading.Lock()
        self._background_thread: Optional[threading.Thread] = None
        self._background_enabled = False

    @classmethod
    def create_for_coder(cls, coder) -> "SemanticIndexService":
        """
        Factory method to create service from coder configuration.
        
        This allows easy migration from the old pattern where Coder
        configured its own indexer.
        """
        root = getattr(coder, "root", None) or Path.cwd()
        
        # Extract model settings from coder's main_model if available
        model_name = "text-embedding-3-small"
        api_base = None
        
        main_model = getattr(coder, "main_model", None)
        if main_model:
            if hasattr(main_model, "embedding_model_name"):
                model_name = main_model.embedding_model_name or model_name
            if hasattr(main_model, "embedding_api_base"):
                api_base = main_model.embedding_api_base
        
        enabled = getattr(coder, "use_semantic_index", False)
        
        return cls(
            root=str(root),
            model_name=model_name,
            api_base=api_base,
            enabled=enabled,
        )

    def _get_indexer(self) -> Optional["SemanticIndexer"]:
        """Lazy initialization of the SemanticIndexer."""
        if not self.enabled:
            return None
            
        if self._indexer is None:
            with self._indexer_lock:
                if self._indexer is None:  # Double-check pattern
                    try:
                        from aider.indexers.semantic import SemanticIndexer
                        self._indexer = SemanticIndexer(
                            root=str(self.root),
                            model_name=self.model_name,
                            api_base=self.api_base,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to initialize semantic indexer: {e}")
                        self.enabled = False
                        return None
        return self._indexer

    def query(self, query: str, limit: int = 5) -> List[Tuple[str, float]]:
        """
        Query the semantic index.
        
        Args:
            query: Search query string
            limit: Maximum number of results
            
        Returns:
            List of (path, score) tuples
        """
        indexer = self._get_indexer()
        if indexer is None:
            return []
        return indexer.query(query, limit=limit)

    def update_index(self, files: List[str]) -> bool:
        """
        Update the index with the given files.
        
        Args:
            files: List of file paths to index
            
        Returns:
            True if update succeeded
        """
        indexer = self._get_indexer()
        if indexer is None:
            return False
        try:
            indexer.update_index(files)
            return True
        except Exception as e:
            logger.warning(f"Failed to update semantic index: {e}")
            return False

    def start_background_indexing(self, files: List[str]) -> bool:
        """
        Start background indexing of files.
        
        Args:
            files: List of file paths to index in background
            
        Returns:
            True if background indexing was started
        """
        if not self.enabled or self._background_enabled:
            return False
            
        self._background_enabled = True
        
        def run_index():
            try:
                self.update_index(files)
            except Exception as e:
                logger.error(f"Background indexing failed: {e}")
            finally:
                self._background_enabled = False
        
        self._background_thread = threading.Thread(target=run_index, daemon=True)
        self._background_thread.start()
        return True

    def wait_for_background(self, timeout: float = 30.0) -> bool:
        """
        Wait for background indexing to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if background thread completed
        """
        if self._background_thread and self._background_thread.is_alive():
            self._background_thread.join(timeout=timeout)
            return not self._background_thread.is_alive()
        return True

    def add_content(self, identifier: str, content: str) -> bool:
        """
        Add raw content to the index.
        
        Args:
            identifier: Unique identifier for this content
            content: Text content to index
            
        Returns:
            True if content was added
        """
        indexer = self._get_indexer()
        if indexer is None:
            return False
        try:
            indexer.add_content(identifier, content)
            return True
        except Exception as e:
            logger.warning(f"Failed to add content to semantic index: {e}")
            return False

    def cleanup(self):
        """Clean up resources."""
        self.wait_for_background(timeout=5.0)
        with self._indexer_lock:
            self._indexer = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False


class RuntimeBoundSemanticIndexer:
    """
    Wrapper that binds a SemanticIndexService to a Coder.
    
    This provides the same interface as the old Coder.get_semantic_indexer()
    method but delegates to the runtime-owned service.
    """

    def __init__(self, coder, service: Optional[SemanticIndexService] = None):
        self.coder = coder
        self._service = service
        self._background_started = False

    def _get_service(self) -> Optional[SemanticIndexService]:
        """Get the service from runtime or the explicitly set one."""
        if self._service is not None:
            return self._service
            
        runtime = getattr(self.coder, "runtime", None)
        if runtime:
            # Try to get from runtime
            service = getattr(runtime, "semantic_index_service", None)
            if service is not None:
                return service
                
        # Fall back to creating a service for this coder
        if getattr(self.coder, "use_semantic_index", False):
            self._service = SemanticIndexService.create_for_coder(self.coder)
            # Store on runtime if available for sharing
            runtime = getattr(self.coder, "runtime", None)
            if runtime:
                runtime.semantic_index_service = self._service
            return self._service
            
        return None

    def get_indexer(self, start_background: bool = False):
        """
        Get the underlying indexer, optionally starting background indexing.
        
        This mirrors the old Coder.get_semantic_indexer() API.
        """
        service = self._get_service()
        if service is None:
            return None
            
        if start_background and not self._background_started:
            files = getattr(self.coder, "get_all_relative_files", lambda: [])()
            if files:
                service.start_background_indexing(files)
                self._background_started = True
                
        return service._get_indexer()

    def query(self, query: str, limit: int = 5):
        """Query the semantic index."""
        service = self._get_service()
        if service is None:
            return []
        return service.query(query, limit)
