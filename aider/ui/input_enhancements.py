"""
Input enhancements for docked prompt.

Features:
- File mention completion (@filename)
- Syntax highlighting in input
- Command palette
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


class FileMentionCompleter(Completer):
    """
    Completer for @filename mentions.
    
    Triggers when user types @ followed by partial filename.
    Searches current directory and git repo for matches.
    """
    
    def __init__(self, root_dir: str = ".", git_repo=None):
        self._root = Path(root_dir)
        self._git_repo = git_repo
        self._file_cache: list[str] = []
        self._cache_valid = False
    
    def _refresh_cache(self) -> None:
        """Refresh the file cache."""
        self._file_cache = []
        
        # Get files from git repo if available
        if self._git_repo:
            try:
                tracked = self._git_repo.get_tracked_files()
                self._file_cache.extend(tracked)
            except Exception:
                pass
        
        # Also scan current directory
        try:
            for path in self._root.rglob("*"):
                if path.is_file():
                    rel_path = str(path.relative_to(self._root))
                    if rel_path not in self._file_cache:
                        self._file_cache.append(rel_path)
        except Exception:
            pass
        
        self._cache_valid = True
    
    def get_completions(
        self,
        document: Document,
        complete_event,
    ) -> Iterable[Completion]:
        """Get file completions for @ mentions."""
        text = document.text_before_cursor
        
        # Check if we're in an @ mention context
        # Look for @ followed by word characters at end of text
        match = re.search(r'@(\w*)$', text)
        if not match:
            return
        
        prefix = match.group(1)
        
        if not self._cache_valid:
            self._refresh_cache()
        
        # Filter and yield completions
        for filename in self._file_cache:
            if prefix.lower() in filename.lower():
                # Calculate display metadata
                display_meta = "file"
                try:
                    path = self._root / filename
                    if path.is_file():
                        size = path.stat().st_size
                        if size < 1024:
                            display_meta = f"{size}B"
                        elif size < 1024 * 1024:
                            display_meta = f"{size // 1024}KB"
                        else:
                            display_meta = f"{size // (1024 * 1024)}MB"
                except Exception:
                    pass
                
                yield Completion(
                    filename,
                    start_position=-len(prefix),
                    display=filename,
                    display_meta=display_meta,
                )


class SlashCommandCompleter(Completer):
    """
    Enhanced slash command completer.
    
    Shows command descriptions and arguments.
    """
    
    def __init__(self, commands: dict[str, str]):
        """
        Args:
            commands: Dict mapping command name to description
        """
        self._commands = commands
    
    def get_completions(
        self,
        document: Document,
        complete_event,
    ) -> Iterable[Completion]:
        """Get slash command completions."""
        text = document.text_before_cursor
        
        # Only complete at start of line with /
        if not text.startswith('/'):
            return
        
        # Get the command being typed
        cmd_part = text[1:]  # Remove leading /
        
        for name, description in self._commands.items():
            if name.startswith(cmd_part):
                yield Completion(
                    name,
                    start_position=-len(cmd_part),
                    display=f"/{name}",
                    display_meta=description[:50] if description else "",
                )


class InputHighlighter:
    """
    Syntax highlighter for input text.
    
    Highlights:
    - @file mentions
    - /commands
    - code blocks (```)
    - URLs
    """
    
    # Patterns for highlighting
    PATTERNS = {
        'mention': (r'@\w+', 'fg:#00aaff bold'),  # Blue for mentions
        'command': (r'/\w+', 'fg:#7ee787 bold'),  # Green for commands
        'code_block': (r'```[\w]*', 'fg:#ffa657'),  # Orange for code blocks
        'url': (r'https?://\S+', 'fg:#a371f7 underline'),  # Purple for URLs
    }
    
    @classmethod
    def highlight(cls, text: str) -> list[tuple[str, str]]:
        """
        Highlight text and return formatted fragments.
        
        Returns list of (style, text) tuples.
        """
        if not text:
            return [("", "")]
        
        fragments = []
        last_end = 0
        
        # Find all matches for all patterns
        matches = []
        for pattern_name, (pattern, style) in cls.PATTERNS.items():
            for match in re.finditer(pattern, text):
                matches.append((match.start(), match.end(), style, match.group()))
        
        # Sort by start position
        matches.sort(key=lambda x: x[0])
        
        # Build fragments
        for start, end, style, matched_text in matches:
            # Add text before this match
            if start > last_end:
                fragments.append(("", text[last_end:start]))
            
            # Add highlighted match
            fragments.append((style, matched_text))
            last_end = end
        
        # Add remaining text
        if last_end < len(text):
            fragments.append(("", text[last_end:]))
        
        return fragments if fragments else [("", text)]


def create_enhanced_completer(
    root_dir: str = ".",
    git_repo=None,
    commands: Optional[dict[str, str]] = None,
) -> Completer:
    """
    Create an enhanced completer that combines file mentions and commands.
    
    Args:
        root_dir: Root directory for file search
        git_repo: Git repo for tracked files
        commands: Dict of slash commands
    
    Returns:
        Combined completer
    """
    from prompt_toolkit.completion import merge_completers
    
    completers = []
    
    # Add file mention completer
    completers.append(FileMentionCompleter(root_dir, git_repo))
    
    # Add slash command completer if commands provided
    if commands:
        completers.append(SlashCommandCompleter(commands))
    
    return merge_completers(completers, deduplicate=True)
