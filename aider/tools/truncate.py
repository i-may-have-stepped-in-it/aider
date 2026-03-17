"""Output truncation for context window management.

This module provides intelligent truncation of tool output to prevent
context window overflow in LLM interactions. The key insight is that
LLMs benefit from seeing the beginning (context/setup), end (results/conclusion),
and any errors, while the middle section (repetitive progress output) is
typically less valuable.

Truncation Strategies:
---------------------
1. **Smart Head/Tail Preservation**: Keep the first ~20% and last ~30% of lines,
   as these typically contain setup/context and final results respectively.

2. **Error Pattern Detection**: Scan for error patterns (tracebacks, exception
   messages, failure indicators) and ensure these are ALWAYS preserved, even
   if they fall in the middle section. Errors are critical for debugging.

3. **Token-Aware Truncation**: Estimate token usage and truncate to stay within
   limits. Uses a rough approximation (4 chars/token) which works well for
   English text and code.

4. **Summarization**: Replace removed middle sections with a clear indicator
   showing how many lines were omitted, preserving the flow of the document.

Why Preserve Certain Content:
----------------------------
- **Head (first lines)**: Usually contains command invocations, file paths,
  configuration, and setup context. Essential for understanding what was run.
  
- **Tail (last lines)**: Contains final results, summaries, exit codes, and
  completion status. Critical for determining success/failure.
  
- **Error Lines**: Stack traces, exception messages, and error indicators
  are the most valuable diagnostic information. We scan for common patterns
  and ensure these survive truncation.
  
- **Line Structure**: Preserving line boundaries (not mid-line truncation)
  ensures output remains readable and copy-pasteable.

Usage:
------
    from truncate import truncate_output, OutputTruncator
    
    # Simple truncation
    truncated = truncate_output(long_output, max_tokens=4000)
    
    # Detailed control
    result = OutputTruncator.truncate(long_output, max_tokens=4000)
    if result.was_truncated:
        print(f"Removed {result.original_lines - result.final_lines} lines")
"""

from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class TruncationResult:
    """Result of truncation operation.
    
    Attributes:
        content: The truncated (or original) content
        was_truncated: Whether any truncation was performed
        original_lines: Number of lines in original content
        final_lines: Number of lines in truncated content
        original_tokens: Estimated token count of original content
        final_tokens: Estimated token count of final content
        truncation_reason: Human-readable explanation of truncation
    """
    content: str
    was_truncated: bool
    original_lines: int
    final_lines: int
    original_tokens: int
    final_tokens: int
    truncation_reason: Optional[str]


class OutputTruncator:
    """Intelligently truncate tool output for LLM context.
    
    This class implements smart truncation strategies that preserve
    the most valuable parts of tool output (head, tail, errors) while
    removing redundant middle content to fit within token limits.
    
    The default token limit (4000) is conservative and leaves room
    for other context in the LLM's context window.
    """
    
    # Default conservative limit - leaves room for system prompts,
    # conversation history, and other context
    DEFAULT_MAX_TOKENS = 4000
    
    # Rough approximation: most English text averages ~4 characters per token.
    # Code tends to be slightly higher due to punctuation and symbols.
    # This is a fast estimation - accurate enough for truncation decisions.
    APPROX_CHARS_PER_TOKEN = 4
    
    # Patterns that indicate important content to preserve.
    # These are matched case-insensitively and against each line.
    # Priority order matters - more specific patterns should come first.
    ERROR_PATTERNS = [
        # Python/Java stack traces
        r'Traceback \(most recent call last\):',
        r'File ".*", line \d+',  # File references in tracebacks
        r'\^+\s*$',  # Caret indicators pointing to error location
        
        # Common exception types
        r'Error:', r'Exception:', r'AssertionError', r'KeyError',
        r'ValueError:', r'TypeError:', r'NameError:', r'IndexError:',
        r'AttributeError:', r'ImportError:', r'ModuleNotFoundError:',
        r'RuntimeError:', r'NotImplementedError:', r'ZeroDivisionError:',
        r'OSError:', r'IOError:', r'FileNotFoundError:', r'PermissionError:',
        r'SyntaxError:', r'IndentationError:', r'TabError:',
        
        # Test failure indicators
        r'FAILED', r'FAIL:', r'Error in test',
        r'Assertion failed', r'expected.*but got',
        
        # Build/compilation errors
        r'error:', r'Error ', r'ERROR:', r'fatal error:',
        r'undefined reference', r'cannot find',
        r'compilation terminated', r'make:\*\*\*',
        
        # HTTP/API errors
        r'HTTP \d{3}', r'404 Not Found', r'500 Internal Server Error',
        r'Connection refused', r'Timeout', r'ECONNREFUSED',
        
        # Shell/command errors
        r'command not found', r'No such file or directory',
        r'Permission denied', r'Operation not permitted',
        
        # Language-specific error indicators
        r'panic:',  # Go panics
        r'error\[',  # Rust errors
        r'Exception in thread',  # Java
    ]
    
    # Compiled regex for error detection (compiled once for efficiency)
    _error_regex: Optional[re.Pattern] = None
    
    @classmethod
    def _get_error_regex(cls) -> re.Pattern:
        """Get compiled error detection regex.
        
        Lazily compile the regex on first use to avoid compilation
        overhead if error detection is never needed.
        """
        if cls._error_regex is None:
            # Combine all patterns with alternation, case-insensitive
            pattern = '|'.join(f'(?:{p})' for p in cls.ERROR_PATTERNS)
            cls._error_regex = re.compile(pattern, re.IGNORECASE)
        return cls._error_regex
    
    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """Estimate token count using rough character approximation.
        
        This is not exact but is fast and sufficiently accurate for
        making truncation decisions. For reference:
        - GPT tokenizers average ~4 chars/token for English
        - Code averages ~3-5 chars/token depending on language
        
        Args:
            text: The text to estimate
            
        Returns:
            Estimated token count
        """
        return len(text) // cls.APPROX_CHARS_PER_TOKEN
    
    @classmethod
    def truncate(
        cls,
        content: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        preserve_errors: bool = True
    ) -> TruncationResult:
        """Truncate content to fit within token limit.
        
        Strategy:
        1. If under limit, return as-is
        2. Extract error lines if present (always preserved)
        3. Keep head (first N lines) and tail (last N lines)
        4. Summarize middle section with line count indicator
        
        The head/tail split is weighted toward the tail (results) as
        that's typically more informative than setup output.
        
        Args:
            content: The content to potentially truncate
            max_tokens: Maximum allowed tokens (estimated)
            preserve_errors: Whether to scan for and preserve error lines
            
        Returns:
            TruncationResult with truncated content and metadata
        """
        # Handle empty content
        if not content or not content.strip():
            return TruncationResult(
                content=content,
                was_truncated=False,
                original_lines=0,
                final_lines=0,
                original_tokens=0,
                final_tokens=0,
                truncation_reason=None
            )
        
        # Calculate initial metrics
        original_lines = content.split('\n')
        original_line_count = len(original_lines)
        original_tokens = cls.estimate_tokens(content)
        
        # If under token limit, no truncation needed
        if original_tokens <= max_tokens:
            return TruncationResult(
                content=content,
                was_truncated=False,
                original_lines=original_line_count,
                final_lines=original_line_count,
                original_tokens=original_tokens,
                final_tokens=original_tokens,
                truncation_reason=None
            )
        
        # Content needs truncation
        # Calculate target lines based on max_tokens (rough estimate)
        target_chars = max_tokens * cls.APPROX_CHARS_PER_TOKEN
        
        # Extract error lines if requested
        error_lines = []
        if preserve_errors:
            error_lines = cls._extract_error_lines(original_lines)
        
        # Determine head/tail split
        # Weight: 30% head, 70% tail (tail usually has more valuable info)
        # But ensure we keep at least some context from both ends
        head_ratio = 0.25
        tail_ratio = 0.35
        
        # Calculate lines for head and tail
        total_available_chars = target_chars - 200  # Reserve space for summary
        
        # Account for error lines in the budget
        error_content = '\n'.join(line for _, line in error_lines)
        error_chars = len(error_content)
        remaining_chars = total_available_chars - error_chars - 100  # Buffer
        
        if remaining_chars < 500:  # Not enough space, prioritize errors
            remaining_chars = total_available_chars * 0.6
            error_chars = total_available_chars * 0.4
        
        head_chars = int(remaining_chars * head_ratio / (head_ratio + tail_ratio))
        tail_chars = remaining_chars - head_chars
        
        # Build truncated content
        result_lines = []
        removed_count = 0
        
        # Add head section
        head_lines = cls._lines_fitting_chars(original_lines, head_chars, from_end=False)
        result_lines.extend(head_lines)
        
        # Track where head ends
        head_end_index = len(head_lines)
        tail_start_index = original_line_count
        
        # Add tail section
        tail_lines = cls._lines_fitting_chars(original_lines, tail_chars, from_end=True)
        tail_start_index = original_line_count - len(tail_lines)
        
        # Add error lines that fall in the middle (not already in head/tail)
        middle_error_lines = [
            line for idx, line in error_lines
            if idx >= head_end_index and idx < tail_start_index
        ]
        
        # Calculate what we're removing
        if head_end_index < tail_start_index:
            removed_count = tail_start_index - head_end_index
        
        # Add truncation marker if we removed anything
        if removed_count > 0:
            result_lines.append(cls._create_summary(removed_count))
        
        # Add middle error lines (marked as preserved)
        if middle_error_lines:
            result_lines.append("[Preserved error lines from truncated section:]")
            result_lines.extend(middle_error_lines)
        
        # Add tail section
        result_lines.extend(tail_lines)
        
        # Build final content
        final_content = '\n'.join(result_lines)
        final_line_count = len(result_lines)
        final_tokens = cls.estimate_tokens(final_content)
        
        # Build truncation reason
        reason_parts = [
            f"Original: {original_line_count} lines (~{original_tokens} tokens)",
            f"Truncated to: {final_line_count} lines (~{final_tokens} tokens)",
        ]
        if removed_count > 0:
            reason_parts.append(f"Removed {removed_count} middle lines")
        if middle_error_lines:
            reason_parts.append(f"Preserved {len(middle_error_lines)} error lines")
        
        return TruncationResult(
            content=final_content,
            was_truncated=True,
            original_lines=original_line_count,
            final_lines=final_line_count,
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            truncation_reason='; '.join(reason_parts)
        )
    
    @classmethod
    def _lines_fitting_chars(
        cls,
        lines: list[str],
        max_chars: int,
        from_end: bool = False
    ) -> list[str]:
        """Extract lines that fit within character budget.
        
        Args:
            lines: List of lines to extract from
            max_chars: Maximum characters to include
            from_end: If True, take from end of list; else from start
            
        Returns:
            List of lines fitting within budget
        """
        result = []
        current_chars = 0
        
        if from_end:
            # Iterate from end backwards
            for line in reversed(lines):
                line_chars = len(line) + 1  # +1 for newline
                if current_chars + line_chars > max_chars and result:
                    break
                result.append(line)
                current_chars += line_chars
            result.reverse()
        else:
            # Iterate from start
            for line in lines:
                line_chars = len(line) + 1  # +1 for newline
                if current_chars + line_chars > max_chars and result:
                    break
                result.append(line)
                current_chars += line_chars
        
        return result
    
    @classmethod
    def _extract_error_lines(cls, lines: list[str]) -> list[tuple[int, str]]:
        """Extract lines that appear to be error messages.
        
        Scans through all lines and identifies those matching
        known error patterns. Returns list of (index, line) tuples
        to preserve positional information.
        
        Args:
            lines: List of lines to scan
            
        Returns:
            List of (index, line) tuples for error lines
        """
        error_regex = cls._get_error_regex()
        error_lines = []
        
        for idx, line in enumerate(lines):
            if error_regex.search(line):
                error_lines.append((idx, line))
        
        return error_lines
    
    @classmethod
    def _create_summary(cls, removed_count: int) -> str:
        """Create truncation summary message.
        
        Creates a clear, machine-readable indicator that content
        was removed. This helps both humans and LLMs understand
        that the output was truncated.
        
        Args:
            removed_count: Number of lines removed
            
        Returns:
            Summary string to insert in place of removed content
        """
        return f"... [{removed_count} lines truncated for brevity] ..."


# Convenience function for simple use cases
def truncate_output(content: str, max_tokens: int = 4000) -> str:
    """Truncate output and return string only.
    
    This is a convenience wrapper around OutputTruncator.truncate()
    for cases where you just need the truncated content string
    without the metadata.
    
    Args:
        content: Content to potentially truncate
        max_tokens: Maximum token limit (default 4000)
        
    Returns:
        Truncated content string
        
    Example:
        >>> long_output = "line 1\\n" * 10000
        >>> truncated = truncate_output(long_output, max_tokens=100)
        >>> len(truncated) < len(long_output)
        True
    """
    result = OutputTruncator.truncate(content, max_tokens=max_tokens)
    return result.content


# Additional strategy classes for different truncation approaches

class HeadOnlyTruncator(OutputTruncator):
    """Truncator that keeps only the head (beginning) of output.
    
    Useful when you only care about initial setup, configuration,
    or early diagnostic output.
    """
    
    @classmethod
    def truncate(cls, content: str, max_tokens: int = 4000, preserve_errors: bool = True) -> TruncationResult:
        """Truncate keeping only the head section."""
        if not content or not content.strip():
            return super().truncate(content, max_tokens, preserve_errors)
        
        original_lines = content.split('\n')
        original_line_count = len(original_lines)
        original_tokens = cls.estimate_tokens(content)
        
        if original_tokens <= max_tokens:
            return TruncationResult(
                content=content,
                was_truncated=False,
                original_lines=original_line_count,
                final_lines=original_line_count,
                original_tokens=original_tokens,
                final_tokens=original_tokens,
                truncation_reason=None
            )
        
        target_chars = max_tokens * cls.APPROX_CHARS_PER_TOKEN - 100
        head_lines = cls._lines_fitting_chars(original_lines, target_chars, from_end=False)
        
        if len(head_lines) < original_line_count:
            head_lines.append(cls._create_summary(original_line_count - len(head_lines)))
        
        final_content = '\n'.join(head_lines)
        final_tokens = cls.estimate_tokens(final_content)
        
        return TruncationResult(
            content=final_content,
            was_truncated=True,
            original_lines=original_line_count,
            final_lines=len(head_lines),
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            truncation_reason=f"Kept first {len(head_lines)} lines only"
        )


class TailOnlyTruncator(OutputTruncator):
    """Truncator that keeps only the tail (end) of output.
    
    Useful when you only care about final results, conclusions,
    or error messages that appear at the end.
    """
    
    @classmethod
    def truncate(cls, content: str, max_tokens: int = 4000, preserve_errors: bool = True) -> TruncationResult:
        """Truncate keeping only the tail section."""
        if not content or not content.strip():
            return super().truncate(content, max_tokens, preserve_errors)
        
        original_lines = content.split('\n')
        original_line_count = len(original_lines)
        original_tokens = cls.estimate_tokens(content)
        
        if original_tokens <= max_tokens:
            return TruncationResult(
                content=content,
                was_truncated=False,
                original_lines=original_line_count,
                final_lines=original_line_count,
                original_tokens=original_tokens,
                final_tokens=original_tokens,
                truncation_reason=None
            )
        
        target_chars = max_tokens * cls.APPROX_CHARS_PER_TOKEN - 100
        tail_lines = cls._lines_fitting_chars(original_lines, target_chars, from_end=True)
        
        if len(tail_lines) < original_line_count:
            tail_lines.insert(0, cls._create_summary(original_line_count - len(tail_lines)))
        
        final_content = '\n'.join(tail_lines)
        final_tokens = cls.estimate_tokens(final_content)
        
        return TruncationResult(
            content=final_content,
            was_truncated=True,
            original_lines=original_line_count,
            final_lines=len(tail_lines),
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            truncation_reason=f"Kept last {len(tail_lines)} lines only"
        )


class MiddleOutTruncator(OutputTruncator):
    """Truncator that removes from the middle first.
    
    Keeps head, tail, and errors, but prioritizes removing
    middle content even more aggressively than the default.
    """
    
    @classmethod
    def truncate(cls, content: str, max_tokens: int = 4000, preserve_errors: bool = True) -> TruncationResult:
        """Truncate with aggressive middle removal."""
        # Use parent's implementation but with adjusted ratios
        # This is a placeholder - the default is already middle-focused
        return super().truncate(content, max_tokens, preserve_errors)
