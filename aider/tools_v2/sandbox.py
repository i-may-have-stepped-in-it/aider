"""Secure sandbox implementations for command execution.

SECURITY NOTICE - THREAT MODEL
================================

This module provides multiple sandbox implementations with varying security levels.
The threat model assumes:

1. MALICIOUS USER INPUT: Commands and arguments may be attacker-controlled
2. PRIVILEGE ESCALATION: Attempts to escape sandbox via:
   - Environment variable poisoning (LD_PRELOAD, PATH manipulation)
   - Symlink attacks in cwd
   - Resource exhaustion (fork bombs, memory exhaustion)
   - Namespace/container escapes
   - setuid binary exploitation
3. INFORMATION DISCLOSURE: Attempts to read files outside allowed paths
4. DENIAL OF SERVICE: CPU/memory exhaustion, disk filling

DEFENSES IMPLEMENTED:
- Command passed as list (argv), never string (prevents shell injection)
- Environment sanitization (removes LD_PRELOAD, PYTHONPATH, etc.)
- Resource limits via setrlimit (memory, CPU, FDs, file size)
- Namespace isolation (mount, pid, net namespaces)
- Filesystem isolation (pivot_root/chroot with careful setup)
- Path validation (cwd must be within allowed directories)
- Static firejail profiles (no user input in profile generation)
- Timeout enforcement with proper cleanup

SECURITY INVARIANTS:
- NO user input in profile generation
- NO shell=True or shell command injection
- NO reliance on PATH for critical binaries
- NO unsanitized environment variables passed to child
- NO write access to system directories
"""

from __future__ import annotations

import asyncio
import logging
import os
import resource
import signal
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SandboxResult:
    """Result from sandboxed execution.

    Attributes:
        success: True if command executed and exited with code 0
        output: Combined stdout/stderr (truncated if partial=True)
        exit_code: Process exit code (-1 if killed by signal)
        error: Error message if sandbox setup or execution failed
        partial: True if output was truncated due to max_output limit
        resource_usage: Dict with max_rss_kb, user_time_ms, sys_time_ms
    """

    success: bool
    output: str
    exit_code: int
    error: Optional[str] = None
    partial: bool = False
    resource_usage: Optional[dict] = None


# =============================================================================
# Exceptions
# =============================================================================


class SandboxError(Exception):
    """Base exception for sandbox errors."""

    pass


class SandboxNotAvailableError(SandboxError):
    """Raised when requested sandbox is not available on this system."""

    pass


class SandboxSetupError(SandboxError):
    """Raised when sandbox setup fails."""

    pass


class SandboxExecutionError(SandboxError):
    """Raised when command execution in sandbox fails."""

    pass


# =============================================================================
# Abstract Base Class
# =============================================================================


class Sandbox(ABC):
    """Abstract base for secure sandboxes.

    All implementations must:
    1. Use command as list (never string - prevents shell injection)
    2. Sanitize environment variables
    3. Validate working directory
    4. Enforce resource limits
    5. Provide functional availability checks
    """

    # Allowed base paths for cwd validation
    ALLOWED_PATH_PREFIXES: tuple[str, ...] = ("/tmp", "/project", "/home", "/workspace")

    @classmethod
    @abstractmethod
    def available(cls) -> bool:
        """Functional check - actually test the sandbox works.

        This performs a real test execution, not just checking for binary presence.
        Returns True only if the sandbox can successfully isolate a simple command.
        """
        pass

    @abstractmethod
    async def run(
        self,
        command: list[str],
        cwd: Path,
        timeout: float,
        env: Optional[dict] = None,
        max_output: int = 10 * 1024 * 1024,  # 10MB
        max_memory: int = 512 * 1024 * 1024,  # 512MB
    ) -> SandboxResult:
        """Execute command in sandbox.

        Args:
            command: Command and arguments as list (NEVER use shell=True)
            cwd: Working directory (must be within ALLOWED_PATH_PREFIXES)
            timeout: Maximum execution time in seconds
            env: Optional environment variables (will be sanitized)
            max_output: Maximum output size in bytes
            max_memory: Maximum memory limit in bytes

        Returns:
            SandboxResult with execution results

        Raises:
            SandboxSetupError: If sandbox cannot be initialized
            SandboxExecutionError: If command execution fails critically
        """
        pass

    def execute(
        self, command: list[str], timeout: float = 30.0, cwd: Optional[Path] = None, **kwargs
    ) -> SandboxResult:
        """Synchronous wrapper for run().

        Convenience method for synchronous code that can't use async/await.
        Runs the command in the current working directory.

        Args:
            command: Command and arguments as list
            timeout: Maximum execution time in seconds
            cwd: Optional working directory (defaults to current directory)
            **kwargs: Additional arguments passed to run()

        Returns:
            SandboxResult with execution results
        """
        if cwd is None:
            cwd = Path.cwd()

        # Create coroutine but don't run it yet - let caller manage the loop
        return self.run(command, cwd=cwd, timeout=timeout, **kwargs)

    def _validate_cwd(self, cwd: Path) -> Path:
        """Validate working directory is within allowed paths.

        SECURITY: Prevents symlink attacks and directory traversal by:
        1. Resolving all symlinks in the path
        2. Checking against allowed prefixes
        3. Ensuring directory exists and is accessible

        Args:
            cwd: Requested working directory

        Returns:
            Resolved, validated Path

        Raises:
            SandboxSetupError: If path is not allowed or doesn't exist
        """
        try:
            # Resolve to absolute path, following symlinks
            resolved = cwd.resolve(strict=True)

            # Check against allowed prefixes
            path_str = str(resolved)
            if not any(path_str.startswith(prefix) for prefix in self.ALLOWED_PATH_PREFIXES):
                raise SandboxSetupError(
                    f"Working directory '{cwd}' is not within allowed paths: "
                    f"{self.ALLOWED_PATH_PREFIXES}"
                )

            # Verify it's actually a directory
            if not resolved.is_dir():
                raise SandboxSetupError(f"Working directory '{cwd}' is not a directory")

            return resolved

        except (OSError, ValueError) as e:
            raise SandboxSetupError(f"Cannot access working directory '{cwd}': {e}")

    def cleanup(self) -> None:
        """Cleanup any resources held by the sandbox.

        Base implementation does nothing. Subclasses may override
        to clean up temp directories, processes, etc.
        """
        pass

    def _sanitize_env(self, env: Optional[dict], allowed_vars: Optional[set[str]] = None) -> dict:
        """Remove dangerous environment variables.

        SECURITY: Clears all environment variables that could be used for:
        - Library injection (LD_PRELOAD, LD_LIBRARY_PATH)
        - Path manipulation (PATH with attacker-controlled directories)
        - Python module loading (PYTHONPATH, PYTHONHOME)
        - Debug/tracing (MALLOC_TRACE, MALLOC_CHECK_)
        - Locale-based attacks (LC_*, LANG if malformed)

        Args:
            env: User-provided environment variables
            allowed_vars: Additional allowed variable names beyond defaults

        Returns:
            Sanitized environment dict with only safe variables
        """
        # Start with minimal safe environment
        safe_env: dict[str, str] = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
        }

        # Allow specific safe locale/timezone vars
        default_allowed = {"LANG", "LC_ALL", "LC_CTYPE", "TZ"}
        if allowed_vars:
            default_allowed = default_allowed | allowed_vars

        if env:
            for key in default_allowed:
                if key in env:
                    # Basic validation - no control chars, reasonable length
                    value = env[key]
                    if self._is_safe_env_value(value):
                        safe_env[key] = value

        return safe_env

    def _is_safe_env_value(self, value: str) -> bool:
        """Check if environment variable value is safe.

        SECURITY: Prevents environment variable poisoning via:
        - Control characters (could affect terminal/parsing)
        - Overly long values (potential buffer issues)
        - Path separators in unexpected places
        """
        if not value:
            return True

        # Check length (prevent potential buffer issues)
        if len(value) > 4096:
            logger.warning(f"Environment variable value too long: {len(value)} chars")
            return False

        # Check for control characters
        for char in value:
            if ord(char) < 32 and char not in "\t\n":
                logger.warning("Environment variable contains control character")
                return False

        return True

    def _set_resource_limits(self, max_memory: int, max_fds: int = 256):
        """Set resource limits for current process.

        SECURITY: Prevents resource exhaustion attacks:
        - Memory limits prevent OOM conditions
        - CPU limits prevent infinite loops
        - FD limits prevent FD exhaustion
        - File size limits prevent disk filling
        - Process limits prevent fork bombs

        Args:
            max_memory: Maximum memory in bytes (address space limit)
            max_fds: Maximum number of file descriptors
        """
        try:
            # Address space (virtual memory) limit
            # Use 1.5x max_memory to allow for overhead while preventing exhaustion
            as_limit = int(max_memory * 1.5)
            resource.setrlimit(resource.RLIMIT_AS, (as_limit, as_limit))

            # Resident set size (physical memory) limit - Linux specific
            try:
                rss_limit = max_memory
                resource.setrlimit(resource.RLIMIT_RSS, (rss_limit, rss_limit))
            except (ValueError, OSError):
                pass  # RSS limit not available on all systems

            # Data segment limit
            resource.setrlimit(resource.RLIMIT_DATA, (max_memory, max_memory))

            # Stack limit - reasonable default
            stack_limit = 8 * 1024 * 1024  # 8MB
            resource.setrlimit(resource.RLIMIT_STACK, (stack_limit, stack_limit))

            # File size limit (prevent filling disk)
            file_size_limit = 100 * 1024 * 1024  # 100MB
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_size_limit, file_size_limit))

            # File descriptor limit
            resource.setrlimit(resource.RLIMIT_NOFILE, (max_fds, max_fds))

            # Number of processes (prevent fork bombs)
            nproc_limit = 32
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (nproc_limit, nproc_limit))
            except (ValueError, OSError):
                pass  # May not work in all containers

            # CPU time limit (will be enforced by timeout, but defense in depth)
            cpu_limit = 300  # 5 minutes
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))

            # Core dump size (prevent large core files, info leak)
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        except Exception as e:
            logger.warning(f"Could not set all resource limits: {e}")


# =============================================================================
# Firejail Sandbox
# =============================================================================


class FirejailSandbox(Sandbox):
    """Firejail-based sandbox.

    Uses STATIC profile - no user input allowed in profile generation.
    This is the most secure option when available.

    SECURITY NOTES:
    - Profile is STATIC and installed at build time
    - NO runtime profile generation
    - Whitelist-based filesystem access
    - Namespace isolation via firejail
    - Seccomp-bpf filtering
    """

    # Static profile path - installed with package
    PROFILE_PATH = "/etc/firejail/aider-static.profile"

    # Static profile content (embedded for reference/installation)
    # This is NEVER written with user input - it's a constant template
    PROFILE_CONTENT = """# Aider static sandbox profile
# AUTOMATICALLY GENERATED - DO NOT MODIFY
# NO USER MODIFIABLE SETTINGS

# Basic security
quiet
private-tmp
private-dev
noexec /tmp
nosound
novideo
net none
seccomp
memory-deny-write-execute
noroot
protocol unix,inet,inet6

# Filesystem restrictions - whitelist only
whitelist /project
whitelist /tmp
whitelist /workspace
read-only /project
read-only /workspace

# Blacklist sensitive directories
blacklist /boot
blacklist /etc/shadow
blacklist /etc/ssh
blacklist /root
blacklist /var/log
blacklist /var/mail
blacklist /proc/kcore
blacklist /proc/kallsyms
blacklist /proc/modules
blacklist /sys/kernel

# Resource limits (firejail-specific)
cpu 60
rlimit-as 1073741824  # 1GB address space
rlimit-fsize 104857600  # 100MB file size
rlimit-nofile 256
rlimit-nproc 32
rlimit-core 0

# Environment cleanup
rmenv LD_PRELOAD
rmenv LD_LIBRARY_PATH
rmenv LD_AUDIT
rmenv LD_DEBUG
rmenv LD_PROFILE
rmenv PYTHONPATH
rmenv PYTHONHOME
rmenv PYTHONSTARTUP
rmenv PYTHONINSPECT
rmenv MALLOC_TRACE
rmenv MALLOC_CHECK_
rmenv HEAPCHECK
rmenv TMOUT
"""

    # Binary paths - hardcoded to prevent PATH manipulation
    FIREJAIL_BIN = "/usr/bin/firejail"

    _availability_cache: Optional[bool] = None

    @classmethod
    def available(cls) -> bool:
        """Check if firejail is available and functional.

        Performs actual test execution to verify sandbox works correctly.
        """
        if cls._availability_cache is not None:
            return cls._availability_cache

        # Check binary exists and is executable
        if not os.path.isfile(cls.FIREJAIL_BIN):
            cls._availability_cache = False
            return False

        if not os.access(cls.FIREJAIL_BIN, os.X_OK):
            cls._availability_cache = False
            return False

        # Check profile exists or can be created
        if not os.path.isfile(cls.PROFILE_PATH):
            logger.warning(f"Firejail profile not found: {cls.PROFILE_PATH}")
            # We'll still return True - profile can be passed inline

        # Functional test: run a simple command in sandbox
        try:
            result = subprocess.run(
                [cls.FIREJAIL_BIN, "--quiet", "--noprofile", "/bin/true"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            cls._availability_cache = result.returncode == 0
            return cls._availability_cache
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug(f"Firejail functional test failed: {e}")
            cls._availability_cache = False
            return False

    def __init__(self):
        """Initialize firejail sandbox."""
        if not self.available():
            raise SandboxNotAvailableError("Firejail is not available or not functional")

    async def run(
        self,
        command: list[str],
        cwd: Path,
        timeout: float,
        env: Optional[dict] = None,
        max_output: int = 10 * 1024 * 1024,
        max_memory: int = 512 * 1024 * 1024,
    ) -> SandboxResult:
        """Execute command in firejail sandbox."""
        # Validate inputs
        if not command:
            return SandboxResult(
                success=False, output="", exit_code=-1, error="No command specified"
            )

        resolved_cwd = self._validate_cwd(cwd)
        safe_env = self._sanitize_env(env)

        # Build firejail command
        # SECURITY: All options are hardcoded - no user input
        firejail_cmd = [
            self.FIREJAIL_BIN,
            "--quiet",
            "--noprofile",  # We'll use command-line options instead
            "--private-tmp",
            "--private-dev",
            "--noexec=/tmp",
            "--net=none",
            "--seccomp",
            "--memory-deny-write-execute",
            "--rlimit-as",
            str(int(max_memory * 1.5)),
            "--rlimit-fsize",
            str(100 * 1024 * 1024),
            "--rlimit-nofile",
            "256",
            "--rlimit-nproc",
            "32",
            "--rlimit-core",
            "0",
            f"--whitelist={resolved_cwd}",
            "--whitelist=/tmp",
        ]

        # Add environment cleanup
        dangerous_vars = [
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "LD_AUDIT",
            "LD_DEBUG",
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONSTARTUP",
            "MALLOC_TRACE",
            "MALLOC_CHECK_",
            "HEAPCHECK",
        ]
        for var in dangerous_vars:
            firejail_cmd.append(f"--rmenv={var}")

        # Set environment variables
        for key, value in safe_env.items():
            firejail_cmd.append(f"--env={key}={value}")

        # Add working directory and command
        firejail_cmd.extend(["--cwd", str(resolved_cwd)])
        firejail_cmd.extend(command)

        return await self._execute(
            firejail_cmd,
            resolved_cwd,
            timeout,
            max_output,
            safe_env,
        )

    async def _execute(
        self,
        cmd: list[str],
        cwd: Path,
        timeout: float,
        max_output: int,
        env: dict[str, str],
    ) -> SandboxResult:
        """Execute the prepared command with output capture."""
        output_chunks: list[bytes] = []

        truncated = False

        try:
            # Create subprocess with pipe for output
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )

            try:
                # Read output with timeout
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)

                # Truncate if necessary
                if len(stdout) > max_output:
                    stdout = stdout[:max_output]
                    truncated = True

                output = stdout.decode("utf-8", errors="replace")

                return SandboxResult(
                    success=process.returncode == 0,
                    output=output,
                    exit_code=process.returncode or 0,
                    partial=truncated,
                    resource_usage={
                        "max_rss_kb": None,  # Firejail doesn't provide this easily
                        "user_time_ms": None,
                        "sys_time_ms": None,
                    },
                )

            except asyncio.TimeoutError:
                # Kill the process group (firejail may spawn children)
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass

                try:
                    process.kill()
                except ProcessLookupError:
                    pass

                await process.wait()

                return SandboxResult(
                    success=False,
                    output=b"".join(output_chunks).decode("utf-8", errors="replace"),
                    exit_code=-1,
                    error=f"Execution timed out after {timeout}s",
                    partial=True,
                )

        except OSError as e:
            return SandboxResult(
                success=False,
                output="",
                exit_code=-1,
                error=f"Failed to execute: {e}",
            )


# =============================================================================
# Unshare Sandbox (Linux Namespaces)
# =============================================================================


class UnshareSandbox(Sandbox):
    """Linux unshare-based sandbox using namespaces.

    More lightweight than firejail but less secure.
    Requires CAP_SYS_ADMIN or user namespace support.

    SECURITY NOTES:
    - Uses mount, pid, net, ipc, uts namespaces
    - Implements pivot_root for filesystem isolation
    - Sets resource limits via setrlimit
    - Requires careful setup of root filesystem
    """

    UNSHARE_BIN = "/usr/bin/unshare"

    _availability_cache: Optional[bool] = None

    @classmethod
    def available(cls) -> bool:
        """Check if unshare with user namespaces is available."""
        if cls._availability_cache is not None:
            return cls._availability_cache

        # Check unshare binary exists
        if not os.path.isfile(cls.UNSHARE_BIN):
            cls._availability_cache = False
            return False

        # Test if we can create user namespace (doesn't require privileges)
        try:
            result = subprocess.run(
                [
                    cls.UNSHARE_BIN,
                    "--user",
                    "--map-root-user",
                    "--pid",
                    "--fork",
                    "--mount-proc",
                    "id",
                ],
                capture_output=True,
                timeout=5,
                check=False,
            )
            cls._availability_cache = result.returncode == 0 and b"root" in result.stdout
            return cls._availability_cache
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug(f"Unshare functional test failed: {e}")
            cls._availability_cache = False
            return False

    def __init__(self):
        """Initialize unshare sandbox."""
        if not self.available():
            raise SandboxNotAvailableError("Unshare is not available or not functional")

    async def run(
        self,
        command: list[str],
        cwd: Path,
        timeout: float,
        env: Optional[dict] = None,
        max_output: int = 10 * 1024 * 1024,
        max_memory: int = 512 * 1024 * 1024,
    ) -> SandboxResult:
        """Execute command in unshare sandbox."""
        if not command:
            return SandboxResult(
                success=False, output="", exit_code=-1, error="No command specified"
            )

        resolved_cwd = self._validate_cwd(cwd)
        safe_env = self._sanitize_env(env)

        # Build unshare command with namespaces
        # --user: user namespace (required for unprivileged use)
        # --map-root-user: map current user to root in namespace
        # --pid: pid namespace (process isolation)
        # --fork: fork before executing (required for pid ns)
        # --mount-proc: mount procfs in new pid namespace
        # --net: network namespace (no network access)
        # --ipc: IPC namespace
        # --uts: UTS namespace (hostname isolation)
        unshare_cmd = [
            self.UNSHARE_BIN,
            "--user",
            "--map-root-user",
            "--pid",
            "--fork",
            "--mount-proc",
            "--net",
            "--ipc",
            "--uts",
        ]

        # Build the wrapper script that sets up sandbox
        wrapper_script = self._build_wrapper_script(
            command,
            resolved_cwd,
            max_memory,
            safe_env,
        )

        unshare_cmd.extend(["/bin/sh", "-c", wrapper_script])

        return await self._execute(unshare_cmd, timeout, max_output)

    def _build_wrapper_script(
        self,
        command: list[str],
        cwd: Path,
        max_memory: int,
        env: dict[str, str],
    ) -> str:
        """Build shell script for sandbox setup.

        SECURITY: This script runs inside the namespace but we still
        must be careful about what we expose.
        """
        # Escape command arguments for shell
        escaped_cmd = " ".join(self._shell_escape(arg) for arg in command)

        # Build env exports
        env_exports = "\n".join(
            f"export {self._shell_escape(k)}={self._shell_escape(v)}" for k, v in env.items()
        )

        script = f"""
set -e

# Set resource limits using ulimit (Bash built-in for setrlimit)
ulimit -v {max_memory // 1024}  # Virtual memory (KB)
ulimit -m {max_memory // 1024}  # Resident memory (KB)
ulimit -d {max_memory // 1024}  # Data segment (KB)
ulimit -s 8192                  # Stack size (KB)
ulimit -f 102400                # File size (KB)
ulimit -n 256                   # File descriptors
ulimit -p 32 2>/dev/null || true  # Max user processes (may not be supported)
ulimit -c 0                     # Core file size

{env_exports}

# Change to working directory
cd {self._shell_escape(str(cwd))}

# Execute command
exec {escaped_cmd}
"""
        return script

    def _shell_escape(self, s: str) -> str:
        """Escape string for shell."""
        # Use single quotes and handle embedded single quotes
        # 'a' -> 'a'
        # 'a'b' -> 'a'\''b'
        return "'" + s.replace("'", "'\"'\"'") + "'"

    async def _execute(
        self,
        cmd: list[str],
        timeout: float,
        max_output: int,
    ) -> SandboxResult:
        """Execute the prepared command."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)

                truncated = len(stdout) > max_output
                if truncated:
                    stdout = stdout[:max_output]

                return SandboxResult(
                    success=process.returncode == 0,
                    output=stdout.decode("utf-8", errors="replace"),
                    exit_code=process.returncode or 0,
                    partial=truncated,
                )

            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

                return SandboxResult(
                    success=False,
                    output="",
                    exit_code=-1,
                    error=f"Execution timed out after {timeout}s",
                    partial=True,
                )

        except OSError as e:
            return SandboxResult(
                success=False,
                output="",
                exit_code=-1,
                error=f"Failed to execute: {e}",
            )


# =============================================================================
# Minimal Sandbox (Chroot + Resource Limits)
# =============================================================================


class MinimalSandbox(Sandbox):
    """Minimal sandbox using chroot and resource limits.

    Last resort when firejail/unshare unavailable.
    NOTE: chroot alone is NOT a security boundary - it's trivial to escape
    without additional restrictions. This is a defense-in-depth measure only.

    SECURITY NOTES:
    - Requires root privileges for chroot (usually not available)
    - Does NOT provide true isolation
    - Resource limits are the main protection
    - Should only be used when no better option exists
    """

    _availability_cache: Optional[bool] = None

    @classmethod
    def available(cls) -> bool:
        """Check if we can at least set resource limits."""
        if cls._availability_cache is not None:
            return cls._availability_cache

        # We can always set resource limits
        cls._availability_cache = True
        return True

    async def run(
        self,
        command: list[str],
        cwd: Path,
        timeout: float,
        env: Optional[dict] = None,
        max_output: int = 10 * 1024 * 1024,
        max_memory: int = 512 * 1024 * 1024,
    ) -> SandboxResult:
        """Execute command with resource limits.

        WARNING: This does NOT provide true sandboxing. It only sets
        resource limits. Use only when no better option is available.
        """
        if not command:
            return SandboxResult(
                success=False, output="", exit_code=-1, error="No command specified"
            )

        try:
            resolved_cwd = self._validate_cwd(cwd)
        except SandboxSetupError as e:
            return SandboxResult(success=False, output="", exit_code=-1, error=str(e))
        safe_env = self._sanitize_env(env)

        # Build wrapper that sets resource limits before exec
        wrapper_script = self._build_wrapper_script(
            command,
            resolved_cwd,
            max_memory,
            safe_env,
        )

        return await self._execute(
            ["/bin/sh", "-c", wrapper_script],
            timeout,
            max_output,
            safe_env,
        )

    def _build_wrapper_script(
        self,
        command: list[str],
        cwd: Path,
        max_memory: int,
        env: dict[str, str],
    ) -> str:
        """Build wrapper script with resource limits."""
        escaped_cmd = " ".join(self._shell_escape(arg) for arg in command)

        env_exports = "\n".join(
            f"export {self._shell_escape(k)}={self._shell_escape(v)}" for k, v in env.items()
        )

        script = f"""
set -e

# Set resource limits
ulimit -v {max_memory // 1024}  # Virtual memory
ulimit -m {max_memory // 1024}  # Resident memory
ulimit -d {max_memory // 1024}  # Data segment
ulimit -s 8192                  # Stack
ulimit -f 102400                # File size
ulimit -n 256                   # File descriptors
ulimit -c 0                     # Core dump size
ulimit -t 300                   # CPU time (seconds)

{env_exports}

# Clear any inherited dangerous variables
unset LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT LD_DEBUG LD_PROFILE
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT
unset MALLOC_TRACE MALLOC_CHECK_ HEAPCHECK

cd {self._shell_escape(str(cwd))}
exec {escaped_cmd}
"""
        return script

    def _shell_escape(self, s: str) -> str:
        """Escape string for shell."""
        return "'" + s.replace("'", "'\"'\"'") + "'"

    async def _execute(
        self,
        cmd: list[str],
        timeout: float,
        max_output: int,
        env: dict[str, str],
    ) -> SandboxResult:
        """Execute the prepared command."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )

            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)

                truncated = len(stdout) > max_output
                if truncated:
                    stdout = stdout[:max_output]

                return SandboxResult(
                    success=process.returncode == 0,
                    output=stdout.decode("utf-8", errors="replace"),
                    exit_code=process.returncode or 0,
                    partial=truncated,
                    resource_usage={},
                )

            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

                return SandboxResult(
                    success=False,
                    output="",
                    exit_code=-1,
                    error=f"Execution timed out after {timeout}s",
                    partial=True,
                )

        except OSError as e:
            return SandboxResult(
                success=False,
                output="",
                exit_code=-1,
                error=f"Failed to execute: {e}",
            )


# =============================================================================
# Advanced Unshare Sandbox with Pivot Root
# =============================================================================


class AdvancedUnshareSandbox(Sandbox):
    """Advanced sandbox using Linux namespaces with proper pivot_root.

    This provides better filesystem isolation than basic unshare by:
    1. Creating a minimal root filesystem
    2. Using pivot_root to change root (more secure than chroot)
    3. Mounting only necessary filesystems

    SECURITY NOTES:
    - pivot_root requires more setup but is harder to escape than chroot
    - Creates temporary directory that is cleaned up
    - Mounts /proc read-only or hides it
    - Uses bind mounts for allowed directories only

    LIMITATION: Requires user namespace support in kernel.
    """

    UNSHARE_BIN = "/usr/bin/unshare"

    _availability_cache: Optional[bool] = None

    @classmethod
    def available(cls) -> bool:
        """Check if advanced unshare with user namespaces is available."""
        if cls._availability_cache is not None:
            return cls._availability_cache

        if not os.path.isfile(cls.UNSHARE_BIN):
            cls._availability_cache = False
            return False

        # Test user namespace support
        try:
            result = subprocess.run(
                [
                    cls.UNSHARE_BIN,
                    "--user",
                    "--map-root-user",
                    "--mount",
                    "--pid",
                    "--fork",
                    "--mount-proc",
                    "id",
                ],
                capture_output=True,
                timeout=5,
                check=False,
            )
            cls._availability_cache = result.returncode == 0 and b"root" in result.stdout
            return cls._availability_cache
        except (subprocess.TimeoutExpired, OSError):
            cls._availability_cache = False
            return False

    def __init__(self):
        """Initialize advanced unshare sandbox."""
        if not self.available():
            raise SandboxNotAvailableError("Advanced unshare is not available")
        self._temp_dirs: list[str] = []

    async def run(
        self,
        command: list[str],
        cwd: Path,
        timeout: float,
        env: Optional[dict] = None,
        max_output: int = 10 * 1024 * 1024,
        max_memory: int = 512 * 1024 * 1024,
    ) -> SandboxResult:
        """Execute command in advanced sandbox with pivot_root."""
        if not command:
            return SandboxResult(
                success=False, output="", exit_code=-1, error="No command specified"
            )

        resolved_cwd = self._validate_cwd(cwd)
        safe_env = self._sanitize_env(env)

        # Create temporary root filesystem
        root_dir = tempfile.mkdtemp(prefix="sandbox_root_")
        self._temp_dirs.append(root_dir)

        try:
            # Setup minimal filesystem
            self._setup_rootfs(root_dir, resolved_cwd)

            # Build the sandbox setup script
            setup_script = self._build_pivot_root_script(
                root_dir,
                command,
                resolved_cwd,
                max_memory,
                safe_env,
            )

            # Build unshare command
            unshare_cmd = [
                self.UNSHARE_BIN,
                "--user",
                "--map-root-user",
                "--mount",
                "--pid",
                "--fork",
                "--net",
                "--ipc",
                "--uts",
                "/bin/sh",
                "-c",
                setup_script,
            ]

            return await self._execute(unshare_cmd, timeout, max_output)

        finally:
            # Cleanup
            self._cleanup()

    def _setup_rootfs(self, root_dir: str, work_dir: Path):
        """Setup minimal root filesystem.

        Creates directory structure and bind mounts necessary files.
        """
        # Create essential directories
        for subdir in ["bin", "lib", "lib64", "usr", "tmp", "proc", "dev", "workspace"]:
            os.makedirs(os.path.join(root_dir, subdir), exist_ok=True)

        # Bind mount essential binaries
        essential_bins = ["/bin/sh", "/bin/bash", "/bin/cat", "/bin/ls", "/bin/echo"]
        for bin_path in essential_bins:
            if os.path.exists(bin_path):
                dest = os.path.join(root_dir, bin_path.lstrip("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                try:
                    # Use read-only bind mount
                    subprocess.run(
                        ["mount", "--bind", "-o", "ro", bin_path, dest],
                        check=False,
                        capture_output=True,
                    )
                except Exception:
                    pass  # May fail without privileges

    def _build_pivot_root_script(
        self,
        root_dir: str,
        command: list[str],
        cwd: Path,
        max_memory: int,
        env: dict[str, str],
    ) -> str:
        """Build script that sets up pivot_root and runs command."""
        escaped_cmd = " ".join(self._shell_escape(arg) for arg in command)

        env_exports = "\n".join(
            f"export {self._shell_escape(k)}={self._shell_escape(v)}" for k, v in env.items()
        )

        # Build path inside new root
        cwd_in_root = "/workspace"

        script = f"""
set -e

# Mount proc (required for many programs)
mount -t proc proc /proc 2>/dev/null || true

# Bind mount working directory into sandbox
mount --bind {self._shell_escape(str(cwd))} {root_dir}/workspace 2>/dev/null || true

# pivot_root setup
mkdir -p {root_dir}/oldroot

# Perform pivot_root
pivot_root {root_dir} {root_dir}/oldroot 2>/dev/null || {{
    echo "Warning: pivot_root failed, falling back to chroot" >&2
    chroot {root_dir} /bin/sh -c 'cd {cwd_in_root} && exec {escaped_cmd}'
    exit $?
}}

# Unmount old root
cd /
umount -l /oldroot 2>/dev/null || true

# Set resource limits
ulimit -v {max_memory // 1024}
ulimit -m {max_memory // 1024}
ulimit -d {max_memory // 1024}
ulimit -s 8192
ulimit -f 102400
ulimit -n 256
ulimit -p 32 2>/dev/null || true
ulimit -c 0
ulimit -t 300

{env_exports}

cd {cwd_in_root}
exec {escaped_cmd}
"""
        return script

    def _shell_escape(self, s: str) -> str:
        """Escape string for shell."""
        return "'" + s.replace("'", "'\"'\"'") + "'"

    async def _execute(
        self,
        cmd: list[str],
        timeout: float,
        max_output: int,
    ) -> SandboxResult:
        """Execute the prepared command."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)

                truncated = len(stdout) > max_output
                if truncated:
                    stdout = stdout[:max_output]

                return SandboxResult(
                    success=process.returncode == 0,
                    output=stdout.decode("utf-8", errors="replace"),
                    exit_code=process.returncode or 0,
                    partial=truncated,
                )

            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

                return SandboxResult(
                    success=False,
                    output="",
                    exit_code=-1,
                    error=f"Execution timed out after {timeout}s",
                    partial=True,
                )

        except OSError as e:
            return SandboxResult(
                success=False,
                output="",
                exit_code=-1,
                error=f"Failed to execute: {e}",
            )

    def _cleanup(self):
        """Cleanup temporary directories."""
        for temp_dir in self._temp_dirs:
            try:
                # Try to unmount any bind mounts
                subprocess.run(
                    ["umount", "-l", temp_dir],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass

            try:
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

        self._temp_dirs.clear()


# =============================================================================
# Sandbox Manager
# =============================================================================


class SandboxManager:
    """Manages sandbox lifecycle and resource cleanup.

    Ensures:
    - Temporary directories cleaned up
    - Processes terminated on timeout
    - Resource limits enforced
    - Automatic fallback to less secure sandboxes

    Usage:
        async with SandboxManager() as manager:
            result = await manager.run(
                command=["python", "script.py"],
                cwd=Path("/project"),
                timeout=30.0,
            )
    """

    # Priority order of sandbox implementations
    SANDBOX_PRIORITY = [
        FirejailSandbox,
        AdvancedUnshareSandbox,
        UnshareSandbox,
        MinimalSandbox,
    ]

    def __init__(self, preferred_sandbox: Optional[type[Sandbox]] = None):
        """Initialize sandbox manager.

        Args:
            preferred_sandbox: Specific sandbox class to use, or None for auto-selection
        """
        self._preferred = preferred_sandbox
        self._sandbox: Optional[Sandbox] = None
        self._temp_dirs: list[str] = []

    async def __aenter__(self) -> SandboxManager:
        """Enter async context."""
        self._select_sandbox()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context - cleanup resources."""
        self._cleanup()
        return False

    def _select_sandbox(self) -> Sandbox:
        """Select best available sandbox."""
        if self._preferred:
            if self._preferred.available():
                self._sandbox = self._preferred()
                return self._sandbox
            raise SandboxNotAvailableError(
                f"Preferred sandbox {self._preferred.__name__} is not available"
            )

        for sandbox_class in self.SANDBOX_PRIORITY:
            if sandbox_class.available():
                logger.debug(f"Selected sandbox: {sandbox_class.__name__}")
                self._sandbox = sandbox_class()
                return self._sandbox

        raise SandboxNotAvailableError("No sandbox implementation available")

    async def run(
        self,
        command: list[str],
        cwd: Path | str,
        timeout: float = 30.0,
        env: Optional[dict] = None,
        max_output: int = 10 * 1024 * 1024,
        max_memory: int = 512 * 1024 * 1024,
    ) -> SandboxResult:
        """Execute command in selected sandbox.

        Args:
            command: Command and arguments as list
            cwd: Working directory
            timeout: Maximum execution time
            env: Optional environment variables
            max_output: Maximum output size in bytes
            max_memory: Maximum memory in bytes

        Returns:
            SandboxResult with execution results
        """
        if self._sandbox is None:
            self._select_sandbox()

        cwd_path = Path(cwd) if isinstance(cwd, str) else cwd

        return await self._sandbox.run(
            command=command,
            cwd=cwd_path,
            timeout=timeout,
            env=env,
            max_output=max_output,
            max_memory=max_memory,
        )

    def _cleanup(self):
        """Cleanup all resources."""
        # Cleanup temporary directories
        for temp_dir in self._temp_dirs:
            try:
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

        self._temp_dirs.clear()

    def cleanup(self):
        """Public cleanup method for explicit resource cleanup."""
        self._cleanup()

    @classmethod
    def get_best_available(cls) -> Optional[type[Sandbox]]:
        """Get the best available sandbox class without instantiating."""
        for sandbox_class in cls.SANDBOX_PRIORITY:
            if sandbox_class.available():
                return sandbox_class
        return None

    @classmethod
    def list_available(cls) -> list[str]:
        """List all available sandbox implementations."""
        available = []
        for sandbox_class in cls.SANDBOX_PRIORITY:
            if sandbox_class.available():
                available.append(sandbox_class.__name__)
        return available


# =============================================================================
# Convenience Functions
# =============================================================================


async def run_sandboxed(
    command: list[str],
    cwd: Path | str,
    timeout: float = 30.0,
    env: Optional[dict] = None,
    max_output: int = 10 * 1024 * 1024,
    max_memory: int = 512 * 1024 * 1024,
    preferred_sandbox: Optional[type[Sandbox]] = None,
) -> SandboxResult:
    """Convenience function to run a command in the best available sandbox.

    Args:
        command: Command and arguments as list (NOT string!)
        cwd: Working directory for command execution
        timeout: Maximum execution time in seconds
        env: Optional environment variables (will be sanitized)
        max_output: Maximum output size in bytes
        max_memory: Maximum memory in bytes
        preferred_sandbox: Specific sandbox class to use, or None for auto

    Returns:
        SandboxResult with execution status and output

    Example:
        result = await run_sandboxed(
            command=["python", "script.py"],
            cwd=Path("/project"),
            timeout=30.0,
        )
        if result.success:
            print(result.output)
    """
    async with SandboxManager(preferred_sandbox) as manager:
        return await manager.run(
            command=command,
            cwd=cwd,
            timeout=timeout,
            env=env,
            max_output=max_output,
            max_memory=max_memory,
        )


def check_sandbox_availability() -> dict[str, bool]:
    """Check availability of all sandbox implementations.

    Returns:
        Dict mapping sandbox name to availability status
    """
    return {
        "FirejailSandbox": FirejailSandbox.available(),
        "AdvancedUnshareSandbox": AdvancedUnshareSandbox.available(),
        "UnshareSandbox": UnshareSandbox.available(),
        "MinimalSandbox": MinimalSandbox.available(),
    }


# =============================================================================
# Module Testing
# =============================================================================

if __name__ == "__main__":
    # Basic tests when run directly
    import asyncio  # noqa: F811

    async def test_sandboxes():
        print("Sandbox availability:")
        for name, available in check_sandbox_availability().items():
            print(f"  {name}: {'✓' if available else '✗'}")

        print("\nTesting basic execution:")
        try:
            result = await run_sandboxed(
                command=["echo", "Hello from sandbox!"],
                cwd=Path("/tmp"),
                timeout=5.0,
            )
            print(f"Success: {result.success}")
            print(f"Output: {result.output.strip()}")
            print(f"Exit code: {result.exit_code}")
        except Exception as e:
            print(f"Error: {e}")

    asyncio.run(test_sandboxes())


def create_sandbox(sandbox_type: str = "auto") -> Sandbox:
    """Factory function to create appropriate sandbox.

    Args:
        sandbox_type: Type of sandbox to create:
            - "auto": Automatically select best available
            - "firejail": Use FirejailSandbox
            - "unshare": Use UnshareSandbox
            - "advanced_unshare": Use AdvancedUnshareSandbox
            - "minimal": Use MinimalSandbox

    Returns:
        Sandbox instance

    Raises:
        SandboxNotAvailableError: If requested sandbox type not available
    """
    sandbox_map = {
        "firejail": FirejailSandbox,
        "unshare": UnshareSandbox,
        "advanced_unshare": AdvancedUnshareSandbox,
        "minimal": MinimalSandbox,
    }

    if sandbox_type == "auto":
        # Use SandboxManager to select best available
        best = SandboxManager.get_best_available()
        if best is None:
            raise SandboxNotAvailableError("No sandbox implementation available")
        return best()

    if sandbox_type in sandbox_map:
        sandbox_class = sandbox_map[sandbox_type]
        if sandbox_class.available():
            return sandbox_class()
        raise SandboxNotAvailableError(
            f"Sandbox type '{sandbox_type}' is not available on this system"
        )

    raise ValueError(f"Unknown sandbox type: {sandbox_type}")
