import time
import signal
import shutil
import threading
from typing import Optional
from prompt_toolkit.application.current import get_app_or_none

class TerminalWidthCache:
    """
    Thread-safe terminal width cache with SIGWINCH support.
    
    Reduces Device Status Report (DSR) escape sequences by caching
    terminal size queries.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance
    
    def _init(self):
        self._width: int = 80
        try:
            self._width = shutil.get_terminal_size().columns
        except (OSError, ValueError):
            pass
            
        self._last_update: float = 0
        self._ttl: float = 0.5
        self._setup_signal_handler()
    
    def _setup_signal_handler(self):
        try:
            # Only register signal handler in main thread
            # SIGWINCH doesn't exist on Windows; the TTL still keeps the width fresh there.
            sigwinch = getattr(signal, "SIGWINCH", None)
            if sigwinch and threading.current_thread() is threading.main_thread():
                signal.signal(sigwinch, self._on_resize)
        except (ValueError, OSError):
            pass  # Signal not available or not in main thread
    
    def _on_resize(self, signum, frame):
        self._last_update = 0  # Invalidate cache on next access
    
    def get_width(self, fallback: int = 80) -> int:
        """Get terminal width with caching."""
        now = time.time()
        if now - self._last_update < self._ttl:
            return self._width
        
        app = get_app_or_none()
        if app and app.output:
            try:
                self._width = app.output.get_size().columns
                self._last_update = now
                return self._width
            except Exception:
                pass
        
        # Fallback to shutil if no app or app output fails
        try:
            self._width = shutil.get_terminal_size().columns
            self._last_update = now
            return self._width
        except (OSError, ValueError):
            pass
            
        return self._width or fallback

# Global singleton
terminal_width = TerminalWidthCache()
