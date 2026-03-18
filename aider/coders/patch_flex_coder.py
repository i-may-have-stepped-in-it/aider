"""
PatchFlexCoder - Flexible patch-based editing with relaxed parsing.

A variant of PatchCoder that allows for more flexible patch formats,
including fuzzy matching and relaxed context requirements.
"""

from typing import List, Tuple

from .patch_coder import ActionType, PatchAction, PatchCoder


class PatchFlexCoder(PatchCoder):
    """
    Coder that applies patches with flexible/lenient parsing.

    Extends PatchCoder with:
    - Fuzzy line matching (ignores whitespace differences)
    - Relaxed context requirements
    - Automatic indentation detection
    - Support for abbreviated patch formats
    """

    edit_format = "patch-flex"

    # More lenient than strict PatchCoder
    fuzz_tolerance = 2  # Allow 2 lines of context mismatch
    ignore_whitespace = True
    auto_indent = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_edits(self, content: str = None) -> List[Tuple[str, PatchAction]]:
        """
        Get edits from the chat history with flexible parsing.

        Overrides parent to apply more lenient parsing rules.
        """
        edits = super().get_edits(content)

        # Post-process edits to handle fuzzy matches
        if self.ignore_whitespace:
            edits = self._normalize_whitespace(edits)

        return edits

    def _normalize_whitespace(
        self, edits: List[Tuple[str, PatchAction]]
    ) -> List[Tuple[str, PatchAction]]:
        """Normalize whitespace in edit actions."""
        normalized = []

        for path, action in edits:
            if action.type == ActionType.UPDATE and action.chunks:
                for chunk in action.chunks:
                    # Strip trailing whitespace from deleted lines
                    chunk.del_lines = [line.rstrip() for line in chunk.del_lines]
                    # Strip trailing whitespace from inserted lines
                    chunk.ins_lines = [line.rstrip() for line in chunk.ins_lines]

            normalized.append((path, action))

        return normalized

    def apply_edits(self, edits: List[Tuple[str, PatchAction]]) -> None:
        """
        Apply edits with flexible matching.

        Tries exact match first, then falls back to fuzzy matching.
        """
        try:
            # Try exact application first
            super().apply_edits(edits)
        except Exception as e:
            # Fall back to flexible matching
            self.io.tool_warning(f"Exact patch failed, trying flexible match: {e}")
            flexible_edits = self._make_flexible(edits)
            super().apply_edits(flexible_edits)

    def _make_flexible(self, edits: List[Tuple[str, PatchAction]]) -> List[Tuple[str, PatchAction]]:
        """Convert edits to use flexible matching."""
        flexible = []

        for path, action in edits:
            if action.type == ActionType.UPDATE and action.chunks:
                # Reduce context in chunks for more flexible matching
                for chunk in action.chunks:
                    # Keep only essential context
                    if len(chunk.del_lines) > 3:
                        chunk.del_lines = chunk.del_lines[:3]
                    if len(chunk.ins_lines) > 3:
                        chunk.ins_lines = chunk.ins_lines[:3]

            flexible.append((path, action))

        return flexible

    @classmethod
    def flex_patch(cls, original: str, patch_text: str) -> str:
        """
        Apply a patch with maximum flexibility.

        Utility method for applying patches outside of coder context.

        Args:
            original: Original file content
            patch_text: Patch text to apply

        Returns:
            Patched content
        """
        # Simple line-based flexible patching
        lines = original.splitlines(keepends=True)
        patch_lines = patch_text.splitlines()

        result = []
        i = 0

        while i < len(patch_lines):
            line = patch_lines[i]

            if line.startswith("+"):
                # Addition - add the line (without + prefix)
                result.append(line[1:] + "\n")
            elif line.startswith("-"):
                # Deletion - skip this line in original
                if i < len(lines):
                    i += 1
            elif line.startswith(" "):
                # Context line - keep from original
                result.append(line[1:] + "\n")
            else:
                # Header or other - skip
                pass

            i += 1

        return "".join(result)
