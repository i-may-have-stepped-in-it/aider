from typing import Optional, Set, Dict, Any
from pathlib import Path
from .repo import GitRepo
from .repomap import RepoMap
from .coders.chat_history import ChatHistory
from .indexers.semantic import SemanticIndexer

class ProjectContext:
    """
    Unified state container for an Aider project.
    Encapsulates repository state, chat history, and context maps.
    """
    def __init__(
        self,
        root: str,
        repo: Optional[GitRepo] = None,
        chat_history: Optional[ChatHistory] = None,
        semantic_indexer: Optional[SemanticIndexer] = None,
        repo_map: Optional[RepoMap] = None,
    ):
        self.root = Path(root)
        self.repo = repo
        self.chat_history = chat_history
        self.semantic_indexer = semantic_indexer
        self.repo_map = repo_map
        
        # Files currently in the chat context (absolute paths)
        self.abs_fnames: Set[str] = set()
        self.abs_read_only_fnames: Set[str] = set()
        
        # Shared metadata/variables
        self.metadata: Dict[str, Any] = {}

    def add_file(self, rel_path: str, read_only: bool = False):
        """Add a file to the context."""
        abs_path = str((self.root / rel_path).resolve())
        if read_only:
            self.abs_read_only_fnames.add(abs_path)
        else:
            self.abs_fnames.add(abs_path)

    def get_relative_path(self, abs_path: str) -> str:
        """Convert an absolute path back to a project-relative path."""
        try:
            return str(Path(abs_path).relative_to(self.root))
        except ValueError:
            return abs_path
