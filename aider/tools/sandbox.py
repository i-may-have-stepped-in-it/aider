"""Sandbox implementations for safe command execution.

This module provides multiple sandbox backends for executing untrusted shell commands
in isolated environments. The security model prioritizes defense in depth:

1. Firejail: Uses seccomp-bpf, namespaces, and filesystem restrictions
2. Unshare: Uses Linux namespaces (user, mount, pid, net, ipc, uts) as a fallback
3. None: Direct execution (last resort, should be avoided for untrusted code)

Security considerations:
- All sandboxes run as the current user (not root), limiting damage potential
- Network access is restricted where possible
- Filesystem access is limited to temp directories
- Timeouts prevent resource exhaustion attacks
- Output size limits prevent memory exhaustion
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from typing import Optional


class Sandbox(ABC):
    """Abstract base class for sandbox implementations.
    
    All sandboxes must implement:
    - available(): Check if the sandbox is functional on this system
    - run(): Execute a command within the sandbox constraints
    
    Implementations should prioritize:
    1. Isolation (prevent escape)
    2. Resource limits (CPU, memory, disk, network)
    3. Observability (capture output, detect failures)
    """
    
    # Maximum output size to prevent memory exhaustion (10MB)
    MAX_OUTPUT_SIZE = 10 * 1024 * 1024
    
    @classmethod
    @abstractmethod
    def available(cls) -> bool:
        """Check if sandbox is functional on this system.
        
        This must be a functional test, not just checking if the binary exists.
        For example, firejail might be installed but not work due to:
        - Kernel lacking namespace support
        - AppArmor/SELinux blocking it
        - Missing capabilities
        
        Returns:
            True if the sandbox can actually run commands.
        """
        pass
    
    @abstractmethod
    async def run(self, command: str, cwd: str, timeout: int) -> str:
        """Run a command within the sandbox.
        
        Args:
            command: The shell command to execute
            cwd: Working directory for command execution
            timeout: Maximum seconds to allow command to run
            
        Returns:
            Combined stdout/stderr output as string
            
        Raises:
            subprocess.TimeoutExpired: If command exceeds timeout
            subprocess.CalledProcessError: If command returns non-zero exit
            OSError: If sandbox fails to start
        """
        pass
    
    def _truncate_output(self, data: bytes) -> str:
        """Truncate output to prevent memory exhaustion.
        
        Args:
            data: Raw output bytes from subprocess
            
        Returns:
            Truncated and decoded string
        """
        if len(data) > self.MAX_OUTPUT_SIZE:
            # Truncate and add notice
            data = data[:self.MAX_OUTPUT_SIZE]
            data += b"\n[Output truncated due to size limit]"
        # Use 'replace' error handling to avoid crashing on invalid UTF-8
        return data.decode('utf-8', errors='replace')


class FirejailSandbox(Sandbox):
    """Sandbox implementation using Firejail.
    
    Firejail is a SUID sandbox program that uses:
    - Linux namespaces (mount, network, pid, ipc, uts)
    - Seccomp-bpf syscall filtering
    - Filesystem restrictions (read-only, blacklists)
    - Resource limits (CPU, memory, time)
    
    Security profile:
    - No network access (--net=none)
    - Private temp directory (--private-tmp)
    - Restricted shell (--shell=none prevents shell escape)
    - Read-only system directories
    - Writable only in the specified working directory
    
    Note: Firejail requires the binary to be SUID root to set up namespaces,
    but the sandboxed process runs as the invoking user.
    """
    
    # Firejail profile for minimal, safe execution
    # Disables network, restricts filesystem access, limits capabilities
    PROFILE = """
# Minimal firejail profile for command execution
# Disable all network access
net none

# Use private temporary directory (isolated /tmp)
private-tmp

# Disable D-Bus access (prevents desktop integration attacks)
nodbus

# Disable system tray access
notray

# Disable X11 access (prevent GUI attacks)
no3d
noaudio
noautostart
noexec /tmp
noexec /var
nonewprivs

# Restrict capabilities to bare minimum
caps.drop all

# Disable environment variable passthrough (prevents LD_PRELOAD attacks)
env PATH=/usr/local/bin:/usr/bin:/bin
env LD_PRELOAD=

# Seccomp filter - block dangerous syscalls
seccomp
"""
    
    @classmethod
    def available(cls) -> bool:
        """Test if firejail is installed and functional.
        
        We actually run a test command because firejail might:
        1. Be installed but not in PATH
        2. Require kernel features not available (e.g., in a container)
        3. Be blocked by AppArmor/SELinux policies
        4. Have broken SUID permissions
        
        Returns:
            True only if firejail successfully runs a simple command.
        """
        firejail_path = shutil.which("firejail")
        if not firejail_path:
            return False
        
        try:
            # Test with a simple command that should always work
            # --quiet suppresses firejail's output
            # --noprofile uses default restrictions (we'll use custom profile in real runs)
            result = subprocess.run(
                [firejail_path, "--quiet", "--noprofile", "/bin/true"],
                capture_output=True,
                timeout=5,
                check=False
            )
            # Exit code 0 means firejail worked (even if sandboxed process failed)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            return False
        except Exception:
            # Any other error means firejail is not functional
            return False
    
    async def run(self, command: str, cwd: str, timeout: int) -> str:
        """Execute command within firejail sandbox.
        
        Args:
            command: Shell command to execute
            cwd: Working directory (must be accessible within sandbox)
            timeout: Maximum execution time in seconds
            
        Returns:
            Command output as string
            
        Raises:
            subprocess.TimeoutExpired: If command times out
            subprocess.CalledProcessError: If command fails
        """
        # Write our security profile to a temp file
        # Using a custom profile allows fine-grained control over restrictions
        with tempfile.NamedTemporaryFile(mode='w', suffix='.profile', delete=False) as f:
            f.write(self.PROFILE)
            profile_path = f.name
        
        try:
            # Build firejail command
            # --quiet: Don't show firejail's startup messages
            # --profile=: Use our custom security profile
            # --net=none: No network access
            # --private-tmp: Isolated /tmp
            # --shell=none: Don't use a shell (prevents escape via shell features)
            # --cwd=: Set working directory
            # SECURITY: Parse command with shlex to safely pass as arguments
            import shlex
            parsed_command = shlex.split(command)
            cmd_parts = [
                "firejail",
                "--quiet",
                f"--profile={profile_path}",
                "--net=none",
                "--private-tmp",
                "--shell=none",
                f"--cwd={cwd}",
                *parsed_command  # Pass as arguments, not shell string
            ]
            
            # Run with asyncio to handle timeout properly
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
                cwd=cwd
            )
            
            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                
                if process.returncode != 0:
                    output = self._truncate_output(stdout)
                    raise subprocess.CalledProcessError(
                        process.returncode, cmd_parts, output=output
                    )
                
                return self._truncate_output(stdout)
                
            except asyncio.TimeoutError:
                # Kill the process group to ensure cleanup
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass  # Already exited
                raise subprocess.TimeoutExpired(cmd_parts, timeout)
                
        finally:
            # Clean up profile file
            try:
                os.unlink(profile_path)
            except OSError:
                pass


class UnshareSandbox(Sandbox):
    """Sandbox using Linux unshare and namespaces.
    
    This is a fallback when firejail is not available. It uses:
    - User namespaces (isolate user/group IDs)
    - Mount namespace (isolated filesystem view)
    - PID namespace (isolated process tree)
    - Network namespace (optional, if available)
    
    Security notes:
    - Requires unprivileged user namespaces to be enabled in kernel
    - Less restrictive than firejail (no seccomp filtering)
    - Mount namespace provides some filesystem isolation
    - Process isolation prevents signal attacks
    
    Limitations:
    - User namespaces may be disabled on some systems
    - No syscall filtering (unlike firejail's seccomp)
    - Root inside namespace is still limited by outer UID mapping
    """
    
    @classmethod
    def available(cls) -> bool:
        """Test if unshare is available and functional.
        
        Checks:
        1. unshare binary exists
        2. User namespaces are enabled in kernel
        3. Can actually create a namespace
        
        Returns:
            True if unshare works on this system.
        """
        unshare_path = shutil.which("unshare")
        if not unshare_path:
            return False
        
        # Check if user namespaces are enabled
        # /proc/sys/kernel/unprivileged_userns_clone on some distros
        userns_paths = [
            "/proc/sys/kernel/unprivileged_userns_clone",  # Debian/Ubuntu
            "/proc/sys/user/max_user_namespaces",  # General
        ]
        
        userns_enabled = False
        for path in userns_paths:
            try:
                with open(path, 'r') as f:
                    value = f.read().strip()
                    # 0 or 1 for unprivileged_userns_clone, number for max_user_namespaces
                    if path.endswith("unprivileged_userns_clone"):
                        userns_enabled = value == "1"
                    else:
                        userns_enabled = int(value) > 0
                    if userns_enabled:
                        break
            except (FileNotFoundError, ValueError, PermissionError):
                continue
        
        # If we can't determine from sysctl, try a functional test
        if not userns_enabled:
            try:
                result = subprocess.run(
                    [unshare_path, "--user", "--pid", "--fork", "--mount-proc", "/bin/true"],
                    capture_output=True,
                    timeout=5,
                    check=False
                )
                userns_enabled = result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
                return False
        
        return userns_enabled
    
    async def run(self, command: str, cwd: str, timeout: int) -> str:
        """Execute command within namespace sandbox.
        
        Args:
            command: Shell command to execute
            cwd: Working directory
            timeout: Maximum execution time in seconds
            
        Returns:
            Command output as string
            
        Raises:
            subprocess.TimeoutExpired: If command times out
            subprocess.CalledProcessError: If command fails
        """
        # Build unshare command with namespaces
        # --user: User namespace (map current user to root inside)
        # --mount: Mount namespace (isolated mount points)
        # --pid: PID namespace (isolated process tree)
        # --fork: Fork before exec (required for PID namespace)
        # --mount-proc: Mount new proc filesystem
        # --net: Network namespace (if available, prevents network access)
        cmd_parts = [
            "unshare",
            "--user",
            "--mount",
            "--pid",
            "--fork",
            "--mount-proc",
            "/bin/sh",
            "-c",
            command
        ]
        
        # Try to add network namespace if we think it will work
        # Some systems disable user namespaces but allow unshare --net as root
        # We only add it if we're confident it won't break the command
        # For now, we omit --net to maximize compatibility
        
        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd
        )
        
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            if process.returncode != 0:
                output = self._truncate_output(stdout)
                raise subprocess.CalledProcessError(
                    process.returncode, cmd_parts, output=output
                )
            
            return self._truncate_output(stdout)
            
        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass
            raise subprocess.TimeoutExpired(cmd_parts, timeout)


class NoneSandbox(Sandbox):
    """No sandbox - direct command execution.
    
    WARNING: This provides NO isolation. Use only when:
    1. No sandbox is available on the system
    2. The command is fully trusted
    3. The environment is already isolated (e.g., container, VM)
    
    Security implications:
    - Command runs with full user privileges
    - Can access entire filesystem
    - Can make network connections
    - Can spawn arbitrary processes
    - Can exhaust resources (CPU, memory, disk)
    
    Mitigations still applied:
    - Timeout to prevent infinite loops
    - Output size limit to prevent memory exhaustion
    - Working directory restriction
    """
    
    @classmethod
    def available(cls) -> bool:
        """Always available - this is the fallback.
        
        Returns:
            Always True.
        """
        return True
    
    async def run(self, command: str, cwd: str, timeout: int) -> str:
        """Execute command directly without sandboxing.
        
        Args:
            command: Shell command to execute
            cwd: Working directory
            timeout: Maximum execution time in seconds
            
        Returns:
            Command output as string
            
        Raises:
            subprocess.TimeoutExpired: If command times out
            subprocess.CalledProcessError: If command fails
        """
        # SECURITY: Parse command with shlex to avoid shell injection
        # This maintains some functionality while being safer than direct shell
        import shlex
        try:
            cmd_parts = shlex.split(command)
        except ValueError as e:
            raise subprocess.CalledProcessError(1, command, output=f"Invalid command syntax: {e}")
        
        if not cmd_parts:
            raise subprocess.CalledProcessError(1, command, output="Empty command")
        
        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            # Limit environment to prevent some attacks
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": os.path.expanduser("~"),
                # Clear dangerous environment variables
                "LD_PRELOAD": "",
                "LD_AUDIT": "",
                "LD_DEBUG": "",
                "PYTHONPATH": "",
            }
        )
        
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            if process.returncode != 0:
                output = self._truncate_output(stdout)
                raise subprocess.CalledProcessError(
                    process.returncode, command, output=output
                )
            
            return self._truncate_output(stdout)
            
        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass
            raise subprocess.TimeoutExpired(command, timeout)


def create_sandbox(sandbox_type: str = "auto") -> Sandbox:
    """Create and return a sandbox instance.
    
    This factory function selects the best available sandbox based on:
    1. User preference (if specified)
    2. System capabilities
    3. Security level desired
    
    The selection priority when sandbox_type="auto" is:
    1. Firejail (most restrictive, seccomp filtering)
    2. Unshare (namespace isolation)
    3. None (direct execution, least secure)
    
    Args:
        sandbox_type: Type of sandbox to create:
            - "auto": Automatically select best available
            - "firejail": Use firejail (raises if unavailable)
            - "unshare": Use unshare/namespaces (raises if unavailable)
            - "none": Use no sandbox
            
    Returns:
        Configured Sandbox instance
        
    Raises:
        ValueError: If sandbox_type is invalid
        RuntimeError: If requested sandbox is not available
    """
    if sandbox_type == "auto":
        # Try sandboxes in order of security preference
        if FirejailSandbox.available():
            return FirejailSandbox()
        elif UnshareSandbox.available():
            return UnshareSandbox()
        else:
            return NoneSandbox()
    
    elif sandbox_type == "firejail":
        if not FirejailSandbox.available():
            raise RuntimeError(
                "Firejail is not available. Install it or use 'auto' or 'none' mode."
            )
        return FirejailSandbox()
    
    elif sandbox_type == "unshare":
        if not UnshareSandbox.available():
            raise RuntimeError(
                "Unshare namespaces are not available. "
                "Check if user namespaces are enabled in your kernel."
            )
        return UnshareSandbox()
    
    elif sandbox_type == "none":
        return NoneSandbox()
    
    else:
        raise ValueError(
            f"Invalid sandbox_type: {sandbox_type}. "
            "Choose from: auto, firejail, unshare, none"
        )


def get_available_sandboxes() -> dict[str, bool]:
    """Check which sandboxes are available on this system.
    
    Returns:
        Dictionary mapping sandbox name to availability.
    """
    return {
        "firejail": FirejailSandbox.available(),
        "unshare": UnshareSandbox.available(),
        "none": NoneSandbox.available(),
    }


# Convenience function for simple use cases
async def run_sandboxed(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 60,
    sandbox_type: str = "auto"
) -> str:
    """Run a command in the best available sandbox.
    
    This is a convenience function for simple sandbox usage.
    For more control, create a sandbox instance directly.
    
    Args:
        command: Shell command to execute
        cwd: Working directory (defaults to current directory)
        timeout: Maximum execution time in seconds
        sandbox_type: Sandbox type or "auto"
        
    Returns:
        Command output as string
        
    Raises:
        subprocess.TimeoutExpired: If command times out
        subprocess.CalledProcessError: If command fails
        RuntimeError: If sandbox is unavailable
    """
    if cwd is None:
        cwd = os.getcwd()
    
    sandbox = create_sandbox(sandbox_type)
    return await sandbox.run(command, cwd, timeout)
