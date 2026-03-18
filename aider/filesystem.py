import shutil
import tempfile
from pathlib import Path
from typing import Set


class TransactionalFilesystem:
    """
    Manages atomic file operations using a shadow workspace.
    Ensures that changes are only committed to the primary root after validation.
    """

    def __init__(self, root: str):
        self.root = Path(root)
        self.shadow_root = Path(tempfile.mkdtemp(prefix="aider_shadow_"))
        self.modified_files: Set[str] = set()

    def stage_file(self, rel_path: str):
        """Copy a file from root to shadow workspace for editing."""
        src = self.root / rel_path
        dst = self.shadow_root / rel_path

        if not src.exists():
            # If creating a new file, just ensure parent dir exists
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.touch()
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        self.modified_files.add(rel_path)

    def write_content(self, rel_path: str, content: str):
        """Write content to the shadow version of a file."""
        if rel_path not in self.modified_files:
            self.stage_file(rel_path)

        (self.shadow_root / rel_path).write_text(content)

    def commit(self):
        """Move all files from shadow workspace back to the primary root."""
        for rel_path in self.modified_files:
            src = self.shadow_root / rel_path
            dst = self.root / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    def rollback(self):
        """Discard all shadow changes."""
        shutil.rmtree(self.shadow_root)
        self.modified_files.clear()

    def __del__(self):
        if self.shadow_root.exists():
            shutil.rmtree(self.shadow_root)
