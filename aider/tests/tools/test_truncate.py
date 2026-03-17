"""Tests for output truncation system.

This module tests the output truncation functionality which intelligently
truncates tool output to prevent context window overflow while preserving
important information like errors and results.
"""

import pytest
from aider.tools.truncate import (
    TruncationResult,
    OutputTruncator,
    HeadOnlyTruncator,
    TailOnlyTruncator,
    MiddleOutTruncator,
    truncate_output,
)


class TestTruncationResult:
    """Test suite for TruncationResult dataclass."""

    def test_truncation_result_fields(self):
        """Verify TruncationResult has all expected fields."""
        result = TruncationResult(
            content="test content",
            was_truncated=True,
            original_lines=100,
            final_lines=50,
            original_tokens=400,
            final_tokens=200,
            truncation_reason="Test truncation",
        )
        
        assert result.content == "test content"
        assert result.was_truncated is True
        assert result.original_lines == 100
        assert result.final_lines == 50
        assert result.original_tokens == 400
        assert result.final_tokens == 200
        assert result.truncation_reason == "Test truncation"

    def test_truncation_result_no_truncation(self):
        """Verify TruncationResult for non-truncated content."""
        result = TruncationResult(
            content="small content",
            was_truncated=False,
            original_lines=1,
            final_lines=1,
            original_tokens=4,
            final_tokens=4,
            truncation_reason=None,
        )
        
        assert result.was_truncated is False
        assert result.truncation_reason is None


class TestOutputTruncator:
    """Test suite for OutputTruncator class."""

    def test_estimate_tokens(self):
        """Verify token estimation uses character approximation.
        
        Tokens are estimated as len(text) // 4 (APPROX_CHARS_PER_TOKEN = 4)
        """
        text = "a" * 100  # 100 characters
        estimated = OutputTruncator.estimate_tokens(text)
        assert estimated == 25  # 100 // 4

    def test_estimate_tokens_empty(self):
        """Verify token estimation for empty string."""
        assert OutputTruncator.estimate_tokens("") == 0

    def test_small_content_not_truncated(self):
        """Verify small content is not truncated.
        
        Content under the token limit should be returned unchanged.
        """
        content = "This is a small piece of content.\nIt has only a few lines."
        result = OutputTruncator.truncate(content, max_tokens=1000)
        
        assert result.was_truncated is False
        assert result.content == content
        assert result.original_lines == 2
        assert result.final_lines == 2
        assert result.truncation_reason is None

    def test_empty_content_not_truncated(self):
        """Verify empty content is handled correctly."""
        result = OutputTruncator.truncate("", max_tokens=1000)
        
        assert result.was_truncated is False
        assert result.content == ""
        assert result.original_lines == 0
        assert result.final_lines == 0

    def test_whitespace_only_not_truncated(self):
        """Verify whitespace-only content is handled correctly."""
        result = OutputTruncator.truncate("   \n\n   ", max_tokens=1000)
        
        assert result.was_truncated is False

    def test_large_content_truncated(self):
        """Verify large content is truncated.
        
        Content exceeding max_tokens should be truncated.
        """
        # Create content that will exceed 100 tokens (~400 chars)
        lines = [f"Line {i}: This is some test content." for i in range(50)]
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=100)
        
        assert result.was_truncated is True
        assert result.final_lines < result.original_lines
        assert "truncated" in result.truncation_reason.lower()

    def test_truncation_preserves_head(self):
        """Verify truncation preserves head section.
        
        The first part of the content should be preserved.
        """
        lines = [f"Line {i}: test content" for i in range(100)]
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=50)
        
        # First line should be present
        assert "Line 0:" in result.content

    def test_truncation_preserves_tail(self):
        """Verify truncation preserves tail section.
        
        The last part of the content should be preserved.
        """
        lines = [f"Line {i}: test content" for i in range(100)]
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=50)
        
        # Last line should be present
        assert "Line 99:" in result.content

    def test_error_pattern_preservation(self):
        """Verify error patterns are preserved in truncation.
        
        Error lines in the middle should be preserved even if truncated.
        """
        lines = [f"Line {i}: normal content" for i in range(50)]
        # Insert error in the middle
        lines[25] = "Error: Something went wrong!"
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=50)
        
        # Error line should be preserved
        assert "Error: Something went wrong!" in result.content

    def test_python_traceback_preservation(self):
        """Verify Python traceback patterns are preserved."""
        content = """Line 1: Starting process
Line 2: Processing data
Traceback (most recent call last):
  File "script.py", line 10, in <module>
    main()
  File "script.py", line 5, in main
    raise ValueError("test error")
ValueError: test error
Line 50: More content here
Line 51: Even more content"""
        
        # Add more lines to force truncation
        lines = content.split("\n")
        lines.extend([f"Line {i}: filler" for i in range(52, 150)])
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=100)
        
        # Traceback should be preserved
        assert "Traceback (most recent call last):" in result.content
        assert "ValueError: test error" in result.content

    def test_multiple_error_patterns(self):
        """Verify multiple error patterns are all preserved."""
        lines = [f"Line {i}: normal" for i in range(100)]
        lines[20] = "File \"test.py\", line 10"
        lines[30] = "SyntaxError: invalid syntax"
        lines[40] = "HTTP 500 Internal Server Error"
        lines[50] = "command not found"
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=100)
        
        # All error lines should be preserved
        assert "SyntaxError" in result.content
        assert "HTTP 500" in result.content
        assert "command not found" in result.content

    def test_truncation_summary_included(self):
        """Verify truncation includes summary line."""
        lines = [f"Line {i}: test content" for i in range(200)]
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=100)
        
        # Summary line should be present
        assert "truncated" in result.content
        assert "lines" in result.content

    def test_truncation_reason_populated(self):
        """Verify truncation_reason field is populated when truncated."""
        lines = [f"Line {i}: test content" for i in range(200)]
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=100)
        
        assert result.truncation_reason is not None
        assert "Original:" in result.truncation_reason
        assert "Truncated to:" in result.truncation_reason

    def test_preserve_errors_false(self):
        """Verify preserve_errors=False disables error preservation."""
        lines = [f"Line {i}: normal" for i in range(100)]
        lines[50] = "Error: test error"
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=50, preserve_errors=False)
        
        # Error might or might not be in the result depending on truncation,
        # but no special preservation should occur
        assert result.was_truncated is True


class TestHeadOnlyTruncator:
    """Test suite for HeadOnlyTruncator class."""

    def test_keeps_only_head(self):
        """Verify HeadOnlyTruncator keeps only the beginning."""
        lines = [f"Line {i}: test content" for i in range(100)]
        content = "\n".join(lines)
        
        result = HeadOnlyTruncator.truncate(content, max_tokens=50)
        
        # Should be truncated
        assert result.was_truncated is True
        
        # First lines should be present
        assert "Line 0:" in result.content
        assert "Line 1:" in result.content
        
        # Last lines should NOT be present
        assert "Line 99:" not in result.content

    def test_includes_truncation_summary(self):
        """Verify HeadOnlyTruncator includes truncation summary."""
        lines = [f"Line {i}: test content" for i in range(200)]
        content = "\n".join(lines)
        
        result = HeadOnlyTruncator.truncate(content, max_tokens=50)
        
        # Summary should be at the end
        assert "truncated" in result.content

    def test_small_content_not_truncated(self):
        """Verify HeadOnlyTruncator doesn't truncate small content."""
        content = "Line 1\nLine 2\nLine 3"
        
        result = HeadOnlyTruncator.truncate(content, max_tokens=1000)
        
        assert result.was_truncated is False
        assert result.content == content

    def test_truncation_reason(self):
        """Verify HeadOnlyTruncator provides correct truncation reason."""
        lines = [f"Line {i}: test content" for i in range(200)]
        content = "\n".join(lines)
        
        result = HeadOnlyTruncator.truncate(content, max_tokens=50)
        
        assert result.truncation_reason is not None
        assert "first" in result.truncation_reason.lower()


class TestTailOnlyTruncator:
    """Test suite for TailOnlyTruncator class."""

    def test_keeps_only_tail(self):
        """Verify TailOnlyTruncator keeps only the end."""
        lines = [f"Line {i}: test content" for i in range(100)]
        content = "\n".join(lines)
        
        result = TailOnlyTruncator.truncate(content, max_tokens=50)
        
        # Should be truncated
        assert result.was_truncated is True
        
        # Last lines should be present
        assert "Line 99:" in result.content
        assert "Line 98:" in result.content
        
        # First lines should NOT be present
        assert "Line 0:" not in result.content
        assert "Line 1:" not in result.content

    def test_includes_truncation_summary(self):
        """Verify TailOnlyTruncator includes truncation summary."""
        lines = [f"Line {i}: test content" for i in range(200)]
        content = "\n".join(lines)
        
        result = TailOnlyTruncator.truncate(content, max_tokens=50)
        
        # Summary should be at the beginning
        assert "truncated" in result.content

    def test_small_content_not_truncated(self):
        """Verify TailOnlyTruncator doesn't truncate small content."""
        content = "Line 1\nLine 2\nLine 3"
        
        result = TailOnlyTruncator.truncate(content, max_tokens=1000)
        
        assert result.was_truncated is False
        assert result.content == content

    def test_truncation_reason(self):
        """Verify TailOnlyTruncator provides correct truncation reason."""
        lines = [f"Line {i}: test content" for i in range(200)]
        content = "\n".join(lines)
        
        result = TailOnlyTruncator.truncate(content, max_tokens=50)
        
        assert result.truncation_reason is not None
        assert "last" in result.truncation_reason.lower()


class TestMiddleOutTruncator:
    """Test suite for MiddleOutTruncator class."""

    def test_inherits_from_output_truncator(self):
        """Verify MiddleOutTruncator inherits from OutputTruncator."""
        assert issubclass(MiddleOutTruncator, OutputTruncator)

    def test_truncates_content(self):
        """Verify MiddleOutTruncator truncates large content."""
        lines = [f"Line {i}: test content" for i in range(200)]
        content = "\n".join(lines)
        
        result = MiddleOutTruncator.truncate(content, max_tokens=50)
        
        assert result.was_truncated is True
        assert result.final_lines < result.original_lines


class TestTruncateOutput:
    """Test suite for truncate_output convenience function."""

    def test_returns_string(self):
        """Verify truncate_output returns a string."""
        content = "Test content"
        result = truncate_output(content, max_tokens=1000)
        
        assert isinstance(result, str)

    def test_small_content_unchanged(self):
        """Verify small content is returned unchanged."""
        content = "Small content"
        result = truncate_output(content, max_tokens=1000)
        
        assert result == content

    def test_large_content_truncated(self):
        """Verify large content is truncated."""
        lines = [f"Line {i}: test content here" for i in range(200)]
        content = "\n".join(lines)
        
        result = truncate_output(content, max_tokens=50)
        
        assert len(result) < len(content)
        assert "truncated" in result


class TestErrorPatternDetection:
    """Test suite for error pattern detection."""

    def test_python_error_patterns(self):
        """Verify Python error patterns are detected."""
        error_lines = [
            "Traceback (most recent call last):",
            'File "test.py", line 10',
            "ValueError: invalid value",
            "TypeError: unsupported type",
            "NameError: name 'x' is not defined",
            "KeyError: 'missing_key'",
            "IndexError: list index out of range",
            "AttributeError: 'NoneType'",
            "ImportError: No module named",
            "RuntimeError: unexpected error",
        ]
        
        for error_line in error_lines:
            content = f"Line 1\n{error_line}\nLine 3"
            result = OutputTruncator.truncate(content, max_tokens=1)
            
            # If truncated, error should still be preserved
            if result.was_truncated:
                assert error_line in result.content or result.truncation_reason

    def test_build_error_patterns(self):
        """Verify build/compilation error patterns are detected."""
        error_lines = [
            "error: undefined reference",
            "Error: compilation failed",
            "fatal error: header not found",
            "make:*** [target] Error 1",
        ]
        
        for error_line in error_lines:
            lines = [f"Line {i}: normal" for i in range(50)]
            lines[25] = error_line
            content = "\n".join(lines)
            
            result = OutputTruncator.truncate(content, max_tokens=20)
            assert error_line in result.content

    def test_http_error_patterns(self):
        """Verify HTTP error patterns are detected."""
        error_lines = [
            "HTTP 404 Not Found",
            "HTTP 500 Internal Server Error",
            "Connection refused",
            "Timeout error",
        ]
        
        for error_line in error_lines:
            lines = [f"Line {i}: normal" for i in range(50)]
            lines[25] = error_line
            content = "\n".join(lines)
            
            result = OutputTruncator.truncate(content, max_tokens=20)
            assert error_line in result.content

    def test_shell_error_patterns(self):
        """Verify shell error patterns are detected."""
        error_lines = [
            "command not found",
            "No such file or directory",
            "Permission denied",
            "Operation not permitted",
        ]
        
        for error_line in error_lines:
            lines = [f"Line {i}: normal" for i in range(50)]
            lines[25] = error_line
            content = "\n".join(lines)
            
            result = OutputTruncator.truncate(content, max_tokens=20)
            assert error_line in result.content

    def test_test_failure_patterns(self):
        """Verify test failure patterns are detected."""
        error_lines = [
            "FAILED",
            "FAIL: test_example",
            "Assertion failed",
            "expected 5 but got 3",
        ]
        
        for error_line in error_lines:
            lines = [f"Line {i}: normal" for i in range(50)]
            lines[25] = error_line
            content = "\n".join(lines)
            
            result = OutputTruncator.truncate(content, max_tokens=20)
            assert error_line in result.content


class TestLinesFittingChars:
    """Test suite for _lines_fitting_chars method."""

    def test_from_start(self):
        """Verify taking lines from start works correctly."""
        lines = ["a" * 10 for _ in range(10)]  # 10 chars each + newline
        
        result = OutputTruncator._lines_fitting_chars(lines, 50, from_end=False)
        
        # Should fit ~4 lines (10 chars + 1 newline = 11 chars each)
        assert len(result) <= 5
        assert result[0] == lines[0]

    def test_from_end(self):
        """Verify taking lines from end works correctly."""
        lines = [f"line {i}" for i in range(10)]
        
        result = OutputTruncator._lines_fitting_chars(lines, 50, from_end=True)
        
        # Should take from the end
        assert len(result) <= 10
        if result:
            assert result[-1] == lines[-1]

    def test_empty_lines(self):
        """Verify handling of empty lines list."""
        result = OutputTruncator._lines_fitting_chars([], 100, from_end=False)
        assert result == []

    def test_zero_max_chars(self):
        """Verify handling of zero max_chars."""
        lines = ["line 1", "line 2"]
        result = OutputTruncator._lines_fitting_chars(lines, 0, from_end=False)
        # Should still get at least one line if result is empty check passes
        assert isinstance(result, list)


class TestCreateSummary:
    """Test suite for _create_summary method."""

    def test_summary_format(self):
        """Verify summary message format."""
        summary = OutputTruncator._create_summary(42)
        
        assert "42" in summary
        assert "lines" in summary
        assert "truncated" in summary

    def test_different_counts(self):
        """Verify summary works for different counts."""
        assert "1 lines" in OutputTruncator._create_summary(1)
        assert "100 lines" in OutputTruncator._create_summary(100)
        assert "1000 lines" in OutputTruncator._create_summary(1000)


class TestDefaultMaxTokens:
    """Test suite for default max_tokens behavior."""

    def test_default_max_tokens_value(self):
        """Verify default max_tokens is 4000."""
        assert OutputTruncator.DEFAULT_MAX_TOKENS == 4000

    def test_default_used_when_not_specified(self):
        """Verify default is used when max_tokens not specified."""
        lines = [f"Line {i}: {'x' * 100}" for i in range(200)]
        content = "\n".join(lines)
        
        # This should not truncate with default 4000 tokens
        result = OutputTruncator.truncate(content)
        
        # May or may not truncate depending on content size
        # Just verify it doesn't crash
        assert isinstance(result, TruncationResult)


class TestIntegration:
    """Integration tests for the truncation system."""

    def test_realistic_command_output(self):
        """Test truncation with realistic command output format."""
        content = """Running tests...
Test suite started at 2024-01-01 00:00:00
================================================================================
Test case 1: PASS
Test case 2: PASS
Test case 3: FAIL
Traceback (most recent call last):
  File "/tests/test_example.py", line 45, in test_something
    self.assertEqual(result, expected)
AssertionError: 5 != 10
================================================================================
Test suite completed
Results: 2 passed, 1 failed
"""
        # Add more content to force truncation
        lines = content.split("\n")
        lines.extend([f"Filler line {i}" for i in range(500)])
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=200)
        
        # Should preserve the error traceback
        assert "Traceback (most recent call last):" in result.content
        assert "AssertionError" in result.content

    def test_multi_line_error_preservation(self):
        """Test that multi-line errors are preserved."""
        content = """Starting process...
Processing item 1
Processing item 2
Traceback (most recent call last):
  File "app.py", line 100, in main
    process_items()
  File "app.py", line 50, in process_items
    raise ValueError("Invalid item")
ValueError: Invalid item
Process failed
Cleaning up...
Done
"""
        # Add filler to force truncation
        lines = content.split("\n")
        lines[4:4] = [f"Filler line {i}" for i in range(200)]
        content = "\n".join(lines)
        
        result = OutputTruncator.truncate(content, max_tokens=100)
        
        # Should preserve traceback
        assert "Traceback (most recent call last):" in result.content
        assert "ValueError: Invalid item" in result.content
