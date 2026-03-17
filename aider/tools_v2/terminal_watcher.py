
import subprocess
import threading
import collections
import time
import os
import signal
from typing import Dict, List, Optional, Deque

class BackgroundProcess:
    """A monitored background process with a rolling log buffer."""
    def __init__(self, name: str, command: List[str], cwd: str, max_buffer: int = 1000):
        self.name = name
        self.command = command
        self.cwd = cwd
        self.buffer: Deque[str] = collections.deque(maxlen=max_buffer)
        self._buffer_lock = threading.Lock()
        self.process: Optional[subprocess.Popen] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.start_time = 0.0

    def start(self):
        self.start_time = time.time()
        try:
            # Platform dependent preexec_fn
            preexec = os.setsid if hasattr(os, "setsid") else None
            
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=self.cwd,
                bufsize=1,
                preexec_fn=preexec
            )
            self.running = True
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            with self._buffer_lock:
                self.buffer.append(f"ERROR: Failed to start: {e}")
            return False

    def send_input(self, text: str):
        """Send text to the process's stdin and log it."""
        if self.process and self.process.stdin:
            try:
                # Log the input so it appears in /watch read
                with self._buffer_lock:
                    self.buffer.append(f">> INPUT: {text.rstrip()}")
                
                self.process.stdin.write(text)
                self.process.stdin.flush()
                return True
            except Exception as e:
                with self._buffer_lock:
                    self.buffer.append(f"ERROR: Failed to send input: {e}")
        return False

    def send_signal(self, sig: int):
        """Send a signal to the process group."""
        if self.process:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(self.process.pid), sig)
                else:
                    self.process.send_signal(sig)
                return True
            except Exception as e:
                with self._buffer_lock:
                    self.buffer.append(f"ERROR: Failed to send signal {sig}: {e}")
        return False

    def _read_loop(self):
        for line in iter(self.process.stdout.readline, ''):
            if not line: break
            with self._buffer_lock:
                self.buffer.append(line.rstrip())
        self.running = False
        if self.process and self.process.stdout:
            self.process.stdout.close()

    def get_logs(self, lines: int = 50) -> List[str]:
        with self._buffer_lock:
            return list(self.buffer)[-lines:]

    def stop(self):
        self.running = False
        if self.process:
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except:
                    pass
            try:
                # Kill the entire process group
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=2)
            except:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except:
                    pass
        self.process = None

class TerminalWatcher:
    """Manages multiple background processes for Aider."""
    def __init__(self):
        self.processes: Dict[str, BackgroundProcess] = {}

    def start_process(self, name: str, command: str, cwd: str) -> bool:
        if name in self.processes:
            self.stop_process(name)
        
        # Simple shell split or use shlex
        import shlex
        cmd_args = shlex.split(command)
        
        proc = BackgroundProcess(name, cmd_args, cwd)
        if proc.start():
            self.processes[name] = proc
            return True
        return False

    def get_logs(self, name: str, lines: int = 50) -> List[str]:
        if name not in self.processes:
            return [f"ERROR: Process '{name}' not found."]
        return self.processes[name].get_logs(lines)

    def send_input(self, name: str, text: str) -> bool:
        if name not in self.processes:
            return False
        return self.processes[name].send_input(text)

    def send_signal(self, name: str, sig: int) -> bool:
        if name not in self.processes:
            return False
        return self.processes[name].send_signal(sig)

    def stop_process(self, name: str):
        if name in self.processes:
            self.processes[name].stop()
            del self.processes[name]

    def shutdown(self):
        for name in list(self.processes.keys()):
            self.stop_process(name)
