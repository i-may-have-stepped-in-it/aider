"""Semantic output compression for context window management.

This module provides intelligent compression of tool outputs (test results,
tracebacks, logs, diffs) that preserves semantic meaning rather than just
truncating. This ensures important context like errors and failures are
retained even when output must be shortened.

Example:
    >>> compressor = SmartCompressor()
    >>> result = compressor.compress(long_test_output, max_tokens=2000)
    >>> print(f"Compressed {result.original_lines} -> {result.compressed_lines} lines")
    >>> print(result.content)
"""

import difflib
import json
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List


class OutputType(Enum):
    """Types of output that can be compressed."""

    UNKNOWN = "unknown"
    TEST_OUTPUT = "test_output"
    TRACEBACK = "traceback"
    LOG_FILE = "log"
    BUILD_OUTPUT = "build"
    DIFF = "diff"
    JSON_OUTPUT = "json"


@dataclass
class CompressionResult:
    """Result of compression operation.

    Attributes:
        content: The compressed content
        original_lines: Number of lines in original content
        compressed_lines: Number of lines after compression
        compression_ratio: Ratio of compressed to original (0.0-1.0)
        warnings: Any warnings about what was compressed
        preserved_sections: Key sections that were kept
    """

    content: str
    original_lines: int
    compressed_lines: int
    compression_ratio: float
    warnings: List[str] = field(default_factory=list)
    preserved_sections: List[str] = field(default_factory=list)


class OutputCompressor(ABC):
    """Base class for semantic compressors.

    Each compressor specializes in a specific output type and understands
    its structure to make intelligent compression decisions.
    """

    @abstractmethod
    def detect(self, content: str) -> bool:
        """Check if this compressor handles this content type."""
        pass

    @abstractmethod
    def compress(self, content: str, max_tokens: int) -> CompressionResult:
        """Compress content to fit within token limit."""
        pass

    def estimate_tokens(self, content: str) -> int:
        """Estimate token count (rough: 3.5 chars/token for code)."""
        return int(len(content) / 3.5)


class TestOutputCompressor(OutputCompressor):
    """Compress test output intelligently.

    Strategy:
    - Deduplicate repeated warnings
    - Collapse passing tests to a summary
    - Keep full failure details with context
    - Preserve overall summary statistics

    Example:
        >>> compressor = TestOutputCompressor()
        >>> # Pytest output with many passing tests - result keeps failures,
        >>> # collapses passing tests to summary
    """

    # Patterns for different test frameworks
    PYTEST_PATTERN = re.compile(r"(collected \d+ items|PASSED|FAILED|ERROR)", re.MULTILINE)
    UNITTEST_PATTERN = re.compile(r"(Ran \d+ tests|OK|FAILED)", re.MULTILINE)

    def detect(self, content: str) -> bool:
        """Detect test output by looking for common test patterns."""
        test_indicators = [
            r"==+ test session starts ==+",
            r"collected \d+ items",
            r"PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS",
            r"Ran \d+ tests? in",
            r"\[\s*\d+%\]",  # Progress percentage
            r"pytest",
            r"unittest",
            r"^test_.*\.py",
        ]
        return any(
            re.search(pattern, content, re.MULTILINE | re.IGNORECASE) for pattern in test_indicators
        )

    def compress(self, content: str, max_tokens: int) -> CompressionResult:
        """Compress test output while preserving failures."""
        original_lines = content.count("\n") + 1
        warnings = []
        preserved_sections = []

        lines = content.split("\n")

        # Categorize lines
        failures = []
        passing = []
        summary_lines = []
        header_lines = []
        other_lines = []

        in_failure = False
        failure_buffer = []

        for i, line in enumerate(lines):
            # Detect section starts
            if re.search(r"(FAILED|ERROR).*\[", line) and not in_failure:
                in_failure = True
                failure_buffer = [line]
            elif in_failure:
                # Check if we're still in failure details
                if line.strip() and not line.startswith(" ") and not line.startswith("\t"):
                    # New section started
                    failures.extend(failure_buffer)
                    in_failure = False
                    failure_buffer = []
                else:
                    failure_buffer.append(line)
            elif re.search(r"==+ .* ==+", line):
                summary_lines.append(line)
            elif re.search(r"(collected|platform|rootdir)", line):
                header_lines.append(line)
            elif re.search(r"PASSED.*\[", line):
                passing.append(line)
            elif re.search(r"FAILED|ERROR", line):
                failures.append(line)
            else:
                other_lines.append(line)

        # Add any remaining failure buffer
        if failure_buffer:
            failures.extend(failure_buffer)

        # Build compressed output - prioritize failures
        compressed_parts = []

        # Always keep header
        if header_lines:
            compressed_parts.extend(header_lines[:5])
            preserved_sections.append("header")

        # Keep all failures with full details
        if failures:
            compressed_parts.append("\n=== FAILURES ===")
            compressed_parts.extend(failures)
            preserved_sections.append(f"{len(failures)} failure(s)")

        # Collapse passing tests to summary
        if passing:
            # Group by test file
            test_files = Counter()
            for line in passing:
                match = re.search(r"([^/]+\.py)::", line)
                if match:
                    test_files[match.group(1)] += 1

            compressed_parts.append(f"\n=== {len(passing)} passing tests (collapsed) ===")
            for f, count in sorted(test_files.items()):
                compressed_parts.append(f"  {f}: {count} passed")
            warnings.append(f"Collapsed {len(passing)} passing test lines")
            preserved_sections.append("passing test summary")

        # Keep summary
        if summary_lines:
            compressed_parts.append("")
            compressed_parts.extend(summary_lines[-3:])  # Last few summary lines
            preserved_sections.append("summary")

        compressed_content = "\n".join(compressed_parts)
        compressed_lines = compressed_content.count("\n") + 1

        # If still too long, keep only failures and summary
        if self.estimate_tokens(compressed_content) > max_tokens:
            warnings.append("Further compression applied - removed some context")
            compressed_parts = ["=== FAILURES (only) ==="]
            compressed_parts.extend(failures[:50])  # Limit failure details
            if summary_lines:
                compressed_parts.extend(summary_lines[-2:])
            compressed_content = "\n".join(compressed_parts)
            compressed_lines = compressed_content.count("\n") + 1

        ratio = compressed_lines / original_lines if original_lines > 0 else 1.0

        return CompressionResult(
            content=compressed_content,
            original_lines=original_lines,
            compressed_lines=compressed_lines,
            compression_ratio=ratio,
            warnings=warnings,
            preserved_sections=preserved_sections,
        )


class TracebackCompressor(OutputCompressor):
    """Compress Python tracebacks intelligently.

    Strategy:
    - Keep exception type and message prominently
    - Show user code frames in full with context
    - Collapse library/framework frames with count
    - Preserve line numbers for user code

    Example:
        >>> compressor = TracebackCompressor()
        >>> # Long traceback through many library frames - result shows user
        >>> # code clearly, collapses library internals
    """

    # Pattern to match traceback frame
    FRAME_PATTERN = re.compile(
        r'  File "([^"]+)", line (\d+), in (\w+)\n' r"    ([^\n]*)\n", re.MULTILINE
    )

    # Pattern for exception line
    EXCEPTION_PATTERN = re.compile(
        r"^([\w\.]+Error|Exception|[\w\.]+Exception):\s*(.*)$", re.MULTILINE
    )

    # Library patterns to collapse
    LIBRARY_PATTERNS = [
        r"/site-packages/",
        r"/lib/python\d\.\d/",
        r"/usr/lib/",
        r"lib/python",
        r"django/",
        r"flask/",
        r"requests/",
        r"urllib",
        r"http/client",
        r"asyncio/",
        r"concurrent/",
        r"multiprocessing/",
        r"threading\.py",
        r"socketserver\.py",
        r"wsgiref/",
    ]

    def detect(self, content: str) -> bool:
        """Detect Python traceback."""
        traceback_indicators = [
            r"Traceback \(most recent call last\):",
            r'  File ".*", line \d+, in \w+',
            r'File ".*"[^,]*, line \d+',
        ]
        return any(re.search(pattern, content) for pattern in traceback_indicators)

    def compress(self, content: str, max_tokens: int) -> CompressionResult:
        """Compress traceback while preserving important frames."""
        original_lines = content.count("\n") + 1
        warnings = []
        preserved_sections = []

        lines = content.split("\n")
        compressed_parts = []

        # Always keep the traceback header
        if lines and "Traceback" in lines[0]:
            compressed_parts.append(lines[0])

        # Parse frames
        user_frames = []
        library_frames = []
        current_frame = []
        exception_line = None

        for line in lines[1:]:
            if line.startswith('  File "'):
                # Start of new frame
                if current_frame:
                    # Save previous frame
                    frame_text = "\n".join(current_frame)
                    if self._is_user_code(current_frame[0]):
                        user_frames.append(frame_text)
                    else:
                        library_frames.append(frame_text)
                current_frame = [line]
            elif line.startswith("    "):
                # Code line in frame
                current_frame.append(line)
            elif re.search(r"[A-Za-z_][A-Za-z0-9_]*Error:", line) or re.search(
                r"[A-Za-z_][A-Za-z0-9_]*Exception:", line
            ):
                # Exception line - end of traceback
                exception_line = line
                if current_frame:
                    frame_text = "\n".join(current_frame)
                    if self._is_user_code(current_frame[0]):
                        user_frames.append(frame_text)
                    else:
                        library_frames.append(frame_text)
                    current_frame = []
                break
            elif line.strip():
                # Other content (like "^" pointers)
                if current_frame:
                    current_frame.append(line)

        # Add remaining frame if any
        if current_frame:
            frame_text = "\n".join(current_frame)
            if self._is_user_code(current_frame[0]):
                user_frames.append(frame_text)
            else:
                library_frames.append(frame_text)

        # Add all user frames first (most important)
        if user_frames:
            compressed_parts.append("\n=== Your Code ===")
            for frame in user_frames:
                compressed_parts.append(frame)
            preserved_sections.append(f"{len(user_frames)} user code frame(s)")

        # Add collapsed library frames notice
        if library_frames:
            warnings.append(f"Collapsed {len(library_frames)} library frames")
            compressed_parts.append(f"\n[... {len(library_frames)} library frames collapsed ...]")

        # Always add exception line
        if exception_line:
            compressed_parts.append("\n=== Exception ===")
            compressed_parts.append(exception_line)
            preserved_sections.append("exception type and message")

        compressed_content = "\n".join(compressed_parts)
        compressed_lines = compressed_content.count("\n") + 1

        ratio = compressed_lines / original_lines if original_lines > 0 else 1.0

        return CompressionResult(
            content=compressed_content,
            original_lines=original_lines,
            compressed_lines=compressed_lines,
            compression_ratio=ratio,
            warnings=warnings,
            preserved_sections=preserved_sections,
        )

    def _is_user_code(self, frame_line: str) -> bool:
        """Check if a frame is user code vs library code."""
        for pattern in self.LIBRARY_PATTERNS:
            if re.search(pattern, frame_line):
                return False
        return True


class LogCompressor(OutputCompressor):
    """Compress log files intelligently.

    Strategy:
    - Group consecutive repeated log lines with count
    - Prioritize ERROR/WARNING over INFO/DEBUG
    - Keep most recent lines (they're often most relevant)
    - Sample INFO messages if needed

    Example:
        >>> compressor = LogCompressor()
        >>> # Log with thousands of repetitive INFO lines - result shows all
        >>> # errors, samples INFO, groups repeats
    """

    # Log level patterns
    LOG_LEVELS = {
        "CRITICAL": 5,
        "ERROR": 4,
        "WARNING": 3,
        "WARN": 3,
        "INFO": 2,
        "DEBUG": 1,
        "TRACE": 0,
    }

    # Common log formats
    LOG_PATTERN = re.compile(
        r"^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2})?\s*" r"([A-Z]+)\s*:?\s*(.*)", re.MULTILINE
    )

    def detect(self, content: str) -> bool:
        """Detect log file format."""
        log_indicators = [
            r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}",
            r"(ERROR|WARNING|INFO|DEBUG)\s*:",
            r"^\[\d{4}-\d{2}-\d{2}",
            r"\[[A-Z]+\]\s+\d{4}",
        ]
        return any(re.search(pattern, content, re.MULTILINE) for pattern in log_indicators)

    def compress(self, content: str, max_tokens: int) -> CompressionResult:
        """Compress log file while preserving important messages."""
        original_lines = content.count("\n") + 1
        warnings = []
        preserved_sections = []

        lines = content.split("\n")

        # Categorize by severity
        error_lines = []
        warning_lines = []
        info_lines = []
        debug_lines = []
        other_lines = []

        for line in lines:
            level = self._get_log_level(line)
            if level >= 4:  # ERROR, CRITICAL
                error_lines.append(line)
            elif level >= 3:  # WARNING
                warning_lines.append(line)
            elif level >= 2:  # INFO
                info_lines.append(line)
            elif level >= 1:  # DEBUG
                debug_lines.append(line)
            else:
                other_lines.append(line)

        compressed_parts = []

        # Always include all errors
        if error_lines:
            compressed_parts.append(f"=== {len(error_lines)} ERROR(s) ===")
            # Deduplicate similar errors
            deduped_errors = self._deduplicate_similar(error_lines)
            compressed_parts.extend(deduped_errors)
            preserved_sections.append(f"{len(error_lines)} error(s)")

        # Include warnings
        if warning_lines:
            compressed_parts.append(f"\n=== {len(warning_lines)} WARNING(s) ===")
            deduped_warnings = self._deduplicate_similar(warning_lines[:50])
            compressed_parts.extend(deduped_warnings)
            preserved_sections.append(f"{len(warning_lines)} warning(s)")

        # Sample INFO lines - keep first few and last few
        if info_lines:
            compressed_parts.append(f"\n=== INFO (sampled from {len(info_lines)}) ===")
            sample_size = min(20, len(info_lines))
            if len(info_lines) > sample_size:
                # Keep first 5 and last 15
                info_sample = info_lines[:5] + ["[...]"] + info_lines[-(sample_size - 5) :]
                warnings.append(f"Sampled INFO: showing {sample_size}/{len(info_lines)} lines")
            else:
                info_sample = info_lines
            compressed_parts.extend(info_sample)
            preserved_sections.append("INFO samples")

        # Include count of debug/trace if any
        if debug_lines:
            compressed_parts.append(f"\n=== {len(debug_lines)} DEBUG/TRACE lines omitted ===")
            warnings.append(f"Omitted {len(debug_lines)} DEBUG/TRACE lines")

        compressed_content = "\n".join(compressed_parts)
        compressed_lines = compressed_content.count("\n") + 1

        ratio = compressed_lines / original_lines if original_lines > 0 else 1.0

        return CompressionResult(
            content=compressed_content,
            original_lines=original_lines,
            compressed_lines=compressed_lines,
            compression_ratio=ratio,
            warnings=warnings,
            preserved_sections=preserved_sections,
        )

    def _get_log_level(self, line: str) -> int:
        """Extract log level priority from line."""
        upper_line = line.upper()
        for level, priority in self.LOG_LEVELS.items():
            if level in upper_line:
                return priority
        return 2  # Default to INFO level

    def _deduplicate_similar(self, lines: List[str], threshold: float = 0.85) -> List[str]:
        """Deduplicate lines that are very similar."""
        if not lines:
            return []

        result = []
        prev_line = None
        duplicate_count = 0

        for line in lines:
            if prev_line is None:
                prev_line = line
                result.append(line)
            elif difflib.SequenceMatcher(None, prev_line, line).ratio() > threshold:
                duplicate_count += 1
            else:
                if duplicate_count > 0:
                    result.append(f"  [... {duplicate_count} similar line(s) ...]")
                    duplicate_count = 0
                result.append(line)
                prev_line = line

        if duplicate_count > 0:
            result.append(f"  [... {duplicate_count} similar line(s) ...]")

        return result


class DiffCompressor(OutputCompressor):
    """Compress git diff output intelligently.

    Strategy:
    - Keep all file headers for context
    - Show all changed (add/remove) lines
    - Collapse large unchanged sections
    - Preserve diff statistics

    Example:
        >>> compressor = DiffCompressor()
        >>> # Large diff with minimal changes - result shows only changed
        >>> # sections with context
    """

    # Patterns for diff sections
    FILE_HEADER_PATTERN = re.compile(r"^diff --git|^--- |^\+\+\+ |^@@")
    HUNK_HEADER_PATTERN = re.compile(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@")

    def detect(self, content: str) -> bool:
        """Detect git diff format."""
        diff_indicators = [
            r"^diff --git",
            r"^--- [ab]/",
            r"^\+\+\+ [ab]/",
            r"^@@ -\d+,\d+ \+\d+,\d+ @@",
            r"^index [a-f0-9]+\.\.[a-f0-9]+",
        ]
        return any(re.search(pattern, content, re.MULTILINE) for pattern in diff_indicators)

    def compress(self, content: str, max_tokens: int) -> CompressionResult:
        """Compress diff while preserving all changes."""
        original_lines = content.count("\n") + 1
        warnings = []
        preserved_sections = []

        lines = content.split("\n")
        compressed_parts = []

        current_file = None
        current_hunk = []
        file_stats = {"added": 0, "removed": 0, "files": 0}

        i = 0
        while i < len(lines):
            line = lines[i]

            # File header
            if line.startswith("diff --git"):
                if current_file and current_hunk:
                    compressed_parts.extend(current_hunk)
                    current_hunk = []
                current_file = line
                compressed_parts.append(line)
                file_stats["files"] += 1
                i += 1
                # Include file metadata lines
                while i < len(lines) and (
                    lines[i].startswith("index ")
                    or lines[i].startswith("--- ")
                    or lines[i].startswith("+++ ")
                ):
                    compressed_parts.append(lines[i])
                    i += 1
                continue

            # Hunk header
            elif self.HUNK_HEADER_PATTERN.match(line):
                if current_hunk:
                    compressed_parts.extend(current_hunk)
                    current_hunk = []
                current_hunk.append(line)
                i += 1

                # Collect hunk lines
                context_buffer = []
                while i < len(lines):
                    hunk_line = lines[i]
                    if hunk_line.startswith("@@") or hunk_line.startswith("diff "):
                        break

                    if hunk_line.startswith("+") and not hunk_line.startswith("+++"):
                        if len(context_buffer) > 3:
                            current_hunk.append(
                                f"  [... {len(context_buffer) - 3} unchanged lines ...]"
                            )
                        elif context_buffer:
                            current_hunk.extend(context_buffer)
                        context_buffer = []
                        current_hunk.append(hunk_line)
                        file_stats["added"] += 1
                    elif hunk_line.startswith("-") and not hunk_line.startswith("---"):
                        if len(context_buffer) > 3:
                            current_hunk.append(
                                f"  [... {len(context_buffer) - 3} unchanged lines ...]"
                            )
                        elif context_buffer:
                            current_hunk.extend(context_buffer)
                        context_buffer = []
                        current_hunk.append(hunk_line)
                        file_stats["removed"] += 1
                    elif hunk_line.startswith(" "):
                        context_buffer.append(hunk_line)
                        if len(context_buffer) > 6:
                            # Keep 3 before, drop middle
                            context_buffer = context_buffer[:3]
                    else:
                        break
                    i += 1

                # Add remaining context
                if len(context_buffer) > 3:
                    current_hunk.extend(context_buffer[:3])
                    current_hunk.append(f"  [... {len(context_buffer) - 3} unchanged lines ...]")
                else:
                    current_hunk.extend(context_buffer)
                continue

            else:
                i += 1

        # Add final hunk
        if current_hunk:
            compressed_parts.extend(current_hunk)

        # Add statistics
        stats_line = (
            f"\n=== Diff Summary: {file_stats['files']} files, "
            f"+{file_stats['added']}/-{file_stats['removed']} lines ==="
        )
        compressed_parts.append(stats_line)
        preserved_sections.append(f"{file_stats['files']} file changes")

        compressed_content = "\n".join(compressed_parts)
        compressed_lines = compressed_content.count("\n") + 1

        if original_lines > compressed_lines:
            warnings.append(
                f"Collapsed {original_lines - compressed_lines} unchanged context lines"
            )

        ratio = compressed_lines / original_lines if original_lines > 0 else 1.0

        return CompressionResult(
            content=compressed_content,
            original_lines=original_lines,
            compressed_lines=compressed_lines,
            compression_ratio=ratio,
            warnings=warnings,
            preserved_sections=preserved_sections,
        )


class JSONCompressor(OutputCompressor):
    """Compress JSON output intelligently.

    Strategy:
    - Keep structure intact
    - Truncate large arrays (show first/last N items)
    - Truncate long string values
    - Preserve keys

    Example:
        >>> compressor = JSONCompressor()
        >>> # Large JSON response with many items
        >>> result = compressor.compress(json_content, max_tokens=1000)
        >>> # Result keeps structure, truncates large arrays
    """

    def detect(self, content: str) -> bool:
        """Detect JSON format."""
        stripped = content.strip()
        return (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        )

    def compress(self, content: str, max_tokens: int) -> CompressionResult:
        """Compress JSON while preserving structure."""
        original_lines = content.count("\n") + 1
        warnings = []
        preserved_sections = []

        try:
            data = json.loads(content)
            compressed_data = self._compress_json_value(data, max_tokens)
            compressed_content = json.dumps(compressed_data, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            # Fallback: just truncate with ellipsis
            compressed_content = content[: int(max_tokens * 3.5)] + "\n[... truncated ...]"
            warnings.append("Invalid JSON - fell back to truncation")

        compressed_lines = compressed_content.count("\n") + 1
        ratio = compressed_lines / original_lines if original_lines > 0 else 1.0

        return CompressionResult(
            content=compressed_content,
            original_lines=original_lines,
            compressed_lines=compressed_lines,
            compression_ratio=ratio,
            warnings=warnings,
            preserved_sections=preserved_sections or ["JSON structure"],
        )

    def _compress_json_value(self, value, max_tokens: int, depth: int = 0):
        """Recursively compress JSON values."""
        if depth > 10:
            return "[... nested depth exceeded ...]"

        if isinstance(value, dict):
            result = {}
            for k, v in value.items():
                # Always keep keys, compress values
                if isinstance(v, (dict, list)) and len(json.dumps(v)) > 500:
                    result[k] = self._compress_json_value(v, max_tokens // 2, depth + 1)
                elif isinstance(v, str) and len(v) > 200:
                    result[k] = v[:100] + " [... " + str(len(v) - 100) + " chars ...]"
                else:
                    result[k] = v
            return result

        elif isinstance(value, list):
            if len(value) > 10:
                # Keep first 5 and last 2
                kept = value[:5] + [f"[... {len(value) - 7} items ...]"] + value[-2:]
                return [self._compress_json_value(item, max_tokens, depth + 1) for item in kept]
            else:
                return [self._compress_json_value(item, max_tokens, depth + 1) for item in value]

        elif isinstance(value, str) and len(value) > 200:
            return value[:100] + f" [... {len(value) - 100} chars ...]"

        return value


class GenericCompressor(OutputCompressor):
    """Fallback compressor for unknown content types.

    Strategy:
    - Keep first N lines (context)
    - Keep last N lines (often most important)
    - Extract lines containing error keywords
    """

    ERROR_KEYWORDS = [
        "error",
        "exception",
        "failed",
        "failure",
        "fatal",
        "critical",
        "traceback",
        "assertion",
        "undefined",
        "not found",
        "permission denied",
        "syntax error",
        "compilation failed",
    ]

    def detect(self, content: str) -> bool:
        """Generic compressor matches anything."""
        return True

    def compress(self, content: str, max_tokens: int) -> CompressionResult:
        """Generic compression with error extraction."""
        original_lines = content.count("\n") + 1
        warnings = ["Used generic compression - no specific format detected"]
        preserved_sections = []

        lines = content.split("\n")

        # Find lines with errors
        error_lines = []
        for i, line in enumerate(lines):
            if any(kw in line.lower() for kw in self.ERROR_KEYWORDS):
                # Get context around error
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                error_lines.extend(range(start, end))

        error_lines = sorted(set(error_lines))

        # Build output: header + errors + footer
        compressed_parts = []

        # Header (first 10 lines)
        header = lines[:10]
        compressed_parts.extend(header)
        preserved_sections.append("header context")

        # Error sections with gaps
        if error_lines:
            compressed_parts.append("\n=== Error Context ===")
            prev_end = -1
            for line_num in error_lines:
                if line_num > prev_end + 1:
                    compressed_parts.append("[...]")
                compressed_parts.append(f"{line_num + 1}: {lines[line_num]}")
                prev_end = line_num
            preserved_sections.append(f"{len(error_lines)} error context lines")

        # Footer (last 10 lines)
        compressed_parts.append("\n=== End Context ===")
        compressed_parts.extend(lines[-10:])
        preserved_sections.append("footer context")

        compressed_content = "\n".join(compressed_parts)
        compressed_lines = compressed_content.count("\n") + 1

        ratio = compressed_lines / original_lines if original_lines > 0 else 1.0

        return CompressionResult(
            content=compressed_content,
            original_lines=original_lines,
            compressed_lines=compressed_lines,
            compression_ratio=ratio,
            warnings=warnings,
            preserved_sections=preserved_sections,
        )


class SmartCompressor:
    """Automatically selects appropriate compressor based on content type.

    Detects output type and routes to specialized compressor for that format.
    Falls back to generic compression if no specific type is detected.

    Example:
        >>> compressor = SmartCompressor()
        >>>
        >>> # Automatically detects and compresses test output
        >>> result = compressor.compress(pytest_output, max_tokens=2000)
        >>>
        >>> # Automatically detects and compresses traceback
        >>> result = compressor.compress(traceback, max_tokens=1000)
        >>>
        >>> # Check what type was detected
        >>> output_type = compressor.detect_type(content)
    """

    def __init__(self):
        self.compressors = [
            TracebackCompressor(),  # Most specific - check first
            DiffCompressor(),  # Very specific format
            JSONCompressor(),  # Structural format
            LogCompressor(),  # Timestamp patterns
            TestOutputCompressor(),  # Can be broad - check last
        ]
        self.generic = GenericCompressor()

    def compress(self, content: str, max_tokens: int = 4000) -> CompressionResult:
        """Compress content intelligently.

        1. Detect content type
        2. Route to appropriate compressor
        3. Fall back to generic if needed

        Args:
            content: The output content to compress
            max_tokens: Maximum tokens to aim for (approximate)

        Returns:
            CompressionResult with compressed content and metadata
        """
        if not content or not content.strip():
            return CompressionResult(
                content="",
                original_lines=0,
                compressed_lines=0,
                compression_ratio=1.0,
                warnings=[],
                preserved_sections=[],
            )

        # Find matching compressor
        for compressor in self.compressors:
            if compressor.detect(content):
                return compressor.compress(content, max_tokens)

        # Fallback to generic
        return self.generic.compress(content, max_tokens)

    def detect_type(self, content: str) -> OutputType:
        """Detect the type of output.

        Args:
            content: The content to analyze

        Returns:
            OutputType enum value
        """
        if not content:
            return OutputType.UNKNOWN

        type_mapping = [
            (TracebackCompressor(), OutputType.TRACEBACK),
            (DiffCompressor(), OutputType.DIFF),
            (JSONCompressor(), OutputType.JSON_OUTPUT),
            (LogCompressor(), OutputType.LOG_FILE),
            (TestOutputCompressor(), OutputType.TEST_OUTPUT),
        ]

        for compressor, output_type in type_mapping:
            if compressor.detect(content):
                return output_type

        return OutputType.UNKNOWN


# Utility functions for compression operations


def deduplicate_lines(lines: List[str], similarity_threshold: float = 0.9) -> List[str]:
    """Deduplicate similar lines (e.g., repeated warnings).

    Groups consecutive similar lines and replaces them with a count indicator.
    Uses difflib.SequenceMatcher to detect near-duplicate lines.

    Args:
        lines: List of lines to deduplicate
        similarity_threshold: Ratio above which lines are considered similar (0.0-1.0)

    Returns:
        List with duplicates replaced by count indicator

    Example:
        >>> lines = [
        ...     "Warning: Connection timeout to server1",
        ...     "Warning: Connection timeout to server2",
        ...     "Warning: Connection timeout to server3",
        ...     "Error: Critical failure"
        ... ]
        >>> deduplicate_lines(lines, similarity_threshold=0.8)
        ['Warning: Connection timeout to server1',
         '[... 2 similar lines ...]',
         'Error: Critical failure']
    """
    if not lines:
        return []

    result = []
    current_group = [lines[0]]

    for line in lines[1:]:
        # Check similarity with first line in current group
        if difflib.SequenceMatcher(None, current_group[0], line).ratio() >= similarity_threshold:
            current_group.append(line)
        else:
            # Flush current group
            if len(current_group) == 1:
                result.append(current_group[0])
            else:
                result.append(current_group[0])
                result.append(f"[... {len(current_group) - 1} similar lines ...]")
            current_group = [line]

    # Flush final group
    if len(current_group) == 1:
        result.append(current_group[0])
    else:
        result.append(current_group[0])
        result.append(f"[... {len(current_group) - 1} similar lines ...]")

    return result


def extract_error_context(content: str, context_lines: int = 5) -> str:
    """Extract lines around errors/exceptions.

    Preserves error location with surrounding context for debugging.

    Args:
        content: The content to search
        context_lines: Number of lines before and after error to include

    Returns:
        Extracted context sections joined by newlines

    Example:
        >>> content = "line1\\nline2\\nError: Something failed\\nline4\\nline5"
        >>> extract_error_context(content, context_lines=1)
        'line2\\nError: Something failed\\nline4'
    """
    error_patterns = [
        r"\b[Ee]rror\b",
        r"\b[Ee]xception\b",
        r"\b[Ff]ailed\b",
        r"\b[Ff]ailure\b",
        r"Traceback",
        r"\bassert\b",
    ]

    lines = content.split("\n")
    error_line_indices = set()

    for i, line in enumerate(lines):
        for pattern in error_patterns:
            if re.search(pattern, line):
                # Add context lines
                for j in range(max(0, i - context_lines), min(len(lines), i + context_lines + 1)):
                    error_line_indices.add(j)

    # Build result with gap indicators
    result = []
    prev_idx = -1
    for idx in sorted(error_line_indices):
        if prev_idx >= 0 and idx > prev_idx + 1:
            result.append("[...]")
        result.append(lines[idx])
        prev_idx = idx

    return "\n".join(result)


def collapse_unimportant(
    content: str, importance_func: Callable[[str], float], threshold: float = 0.5
) -> str:
    """Collapse sections below importance threshold.

    Shows count of collapsed lines instead of the content.

    Args:
        content: Content to process
        importance_func: Function that returns importance score (0.0-1.0) for a line
        threshold: Importance threshold below which lines are collapsed

    Returns:
        Content with unimportant sections collapsed

    Example:
        >>> def importance(line):
        ...     return 1.0 if 'ERROR' in line else 0.1
        >>> content = "INFO: Start\\nERROR: Critical\\nINFO: End"
        >>> collapse_unimportant(content, importance, threshold=0.5)
        '[... 1 unimportant lines ...]\\nERROR: Critical\\n[... 1 unimportant lines ...]'
    """
    lines = content.split("\n")
    result = []
    collapsed_count = 0

    for line in lines:
        importance = importance_func(line)
        if importance < threshold:
            collapsed_count += 1
        else:
            if collapsed_count > 0:
                result.append(f"[... {collapsed_count} unimportant lines ...]")
                collapsed_count = 0
            result.append(line)

    if collapsed_count > 0:
        result.append(f"[... {collapsed_count} unimportant lines ...]")

    return "\n".join(result)


# Example usage and demonstrations


def create_example_test_output() -> str:
    """Create example pytest output for demonstration."""
    lines = [
        "============================= test session starts ==============================",
        "platform linux -- Python 3.11.0, pytest-7.4.0, pluggy-1.2.0",
        "rootdir: /home/user/project",
        "collected 150 items",
        "",
    ]

    # Add many passing tests
    for i in range(145):
        lines.append(
            f"tests/test_features.py::test_feature_{i:03d} PASSED"
            f"        [ {(i + 1) / 150 * 100:5.1f}%]"
        )

    # Add some failures
    lines.extend(
        [
            "tests/test_features.py::test_feature_145 FAILED          [ 96.7%]",
            "",
            "=================================== FAILURES ===================================",
            "____________________________ test_feature_145 ____________________________",
            "",
            "    def test_feature_145():",
            ">       assert calculate(145) == expected_value",
            "E       AssertionError: assert 290 == 300",
            "E        +  where 290 = calculate(145)",
            "",
            "tests/test_features.py:145: AssertionError",
            "",
            "tests/test_features.py::test_feature_146 PASSED          [ 97.3%]",
            "tests/test_features.py::test_feature_147 PASSED          [ 98.0%]",
            "tests/test_features.py::test_feature_148 PASSED          [ 98.7%]",
            "tests/test_features.py::test_feature_149 PASSED          [ 99.3%]",
            "",
            "========================= short test summary info ==========================",
            "FAILED tests/test_features.py::test_feature_145 - AssertionError: assert 290 == 300",
            "========================= 1 failed, 149 passed ==========================",
        ]
    )

    return "\n".join(lines)


def create_example_traceback() -> str:
    """Create example Python traceback for demonstration."""
    return """Traceback (most recent call last):
  File "/usr/lib/python3.11/site-packages/django/core/handlers/exception.py", line 55, in inner
    response = get_response(request)
  File "/usr/lib/python3.11/site-packages/django/core/handlers/base.py", line 197, in _get_response
    response = wrapped_callback(request, *callback_args, **callback_kwargs)
  File "/usr/lib/python3.11/site-packages/django/views/decorators/csrf.py", line 65,
    in _view_wrapper
    return view_func(request, *args, **kwargs)
  File "/home/user/project/api/views.py", line 42, in process_data
    result = calculate_values(data)
  File "/home/user/project/core/calculator.py", line 89, in calculate_values
    validate_input(item)
  File "/home/user/project/core/validators.py", line 23, in validate_input
    raise ValueError(f"Invalid input: {item['name']}")
ValueError: Invalid input: test_data"""


def create_example_log() -> str:
    """Create example log output for demonstration."""
    lines = [
        "2024-01-15 10:00:00 INFO: Application starting up",
        "2024-01-15 10:00:01 INFO: Connected to database",
        "2024-01-15 10:00:02 INFO: Loading configuration",
    ]

    # Add repetitive processing logs
    for i in range(50):
        lines.append(f"2024-01-15 10:01:{i:02d} INFO: Processing item {i}")

    # Add some warnings
    lines.extend(
        [
            "2024-01-15 10:02:00 WARNING: Slow query detected: 2.5s",
            "2024-01-15 10:02:01 WARNING: Slow query detected: 2.3s",
            "2024-01-15 10:02:02 WARNING: Slow query detected: 2.8s",
        ]
    )

    # More processing
    for i in range(50, 100):
        lines.append(f"2024-01-15 10:03:{i % 60:02d} INFO: Processing item {i}")

    # Add error
    lines.extend(
        [
            "2024-01-15 10:04:00 ERROR: Connection failed to payment gateway",
            "2024-01-15 10:04:01 ERROR: Transaction 12345 failed",
            "2024-01-15 10:04:02 INFO: Retrying connection...",
        ]
    )

    return "\n".join(lines)


def create_example_diff() -> str:
    """Create example git diff for demonstration."""
    return '''diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,7 @@ import os
 import sys

 from flask import Flask
+from flask_cors import CORS
 from routes import api

 app = Flask(__name__)
@@ -25,20 +26,25 @@ def create_app():
     app.register_blueprint(api)
     return app

+def configure_cors(app):
+    """Enable CORS for all routes."""
+    CORS(app, resources={r"/api/*": {"origins": "*"}})
+
 if __name__ == '__main__':
     app = create_app()
+    configure_cors(app)
     app.run(debug=True)

 # This is a large unchanged section
 # Line 40 - unchanged
 # Line 41 - unchanged
 # Line 42 - unchanged
 # ... (many more unchanged lines)
-# Line 100 - unchanged
+# Line 100 - changed!
 # Line 101 - unchanged
 # Line 102 - unchanged
 # ... (many more unchanged lines)
 # Line 200 - unchanged

diff --git a/config/settings.py b/config/settings.py
index 9876543..fedcba0 100644
--- a/config/settings.py
+++ b/config/settings.py
@@ -5,6 +5,7 @@ DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
 DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'
 SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-prod')
+CORS_ENABLED = os.environ.get('CORS_ENABLED', 'true').lower() == 'true'

 # API Settings
 API_VERSION = 'v1'
'''


def demonstrate_compression():
    """Demonstrate compression on various output types."""
    print("=" * 70)
    print("SEMANTIC OUTPUT COMPRESSION DEMONSTRATION")
    print("=" * 70)

    compressor = SmartCompressor()

    # Test output compression
    print("\n" + "=" * 70)
    print("TEST OUTPUT COMPRESSION")
    print("=" * 70)
    test_output = create_example_test_output()
    print(f"\nOriginal: {test_output.count(chr(10)) + 1} lines")

    result = compressor.compress(test_output, max_tokens=500)
    ratio = result.compression_ratio
    print(f"Compressed: {result.compressed_lines} lines ({ratio:.1%} of original)")
    print(f"Preserved: {', '.join(result.preserved_sections)}")
    print(f"Warnings: {result.warnings}")
    print("\n--- Compressed Output ---")
    print(result.content)

    # Traceback compression
    print("\n" + "=" * 70)
    print("TRACEBACK COMPRESSION")
    print("=" * 70)
    traceback = create_example_traceback()
    print(f"\nOriginal: {traceback.count(chr(10)) + 1} lines")

    result = compressor.compress(traceback, max_tokens=300)
    ratio = result.compression_ratio
    print(f"Compressed: {result.compressed_lines} lines ({ratio:.1%} of original)")
    print(f"Preserved: {', '.join(result.preserved_sections)}")
    print(f"Warnings: {result.warnings}")
    print("\n--- Compressed Output ---")
    print(result.content)

    # Log compression
    print("\n" + "=" * 70)
    print("LOG COMPRESSION")
    print("=" * 70)
    log_output = create_example_log()
    print(f"\nOriginal: {log_output.count(chr(10)) + 1} lines")

    result = compressor.compress(log_output, max_tokens=500)
    ratio = result.compression_ratio
    print(f"Compressed: {result.compressed_lines} lines ({ratio:.1%} of original)")
    print(f"Preserved: {', '.join(result.preserved_sections)}")
    print(f"Warnings: {result.warnings}")
    print("\n--- Compressed Output ---")
    print(result.content)

    # Diff compression
    print("\n" + "=" * 70)
    print("DIFF COMPRESSION")
    print("=" * 70)
    diff_output = create_example_diff()
    print(f"\nOriginal: {diff_output.count(chr(10)) + 1} lines")

    result = compressor.compress(diff_output, max_tokens=400)
    ratio = result.compression_ratio
    print(f"Compressed: {result.compressed_lines} lines ({ratio:.1%} of original)")
    print(f"Preserved: {', '.join(result.preserved_sections)}")
    print(f"Warnings: {result.warnings}")
    print("\n--- Compressed Output ---")
    print(result.content)

    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    demonstrate_compression()
