"""
Running Prompt Manager for Aider.

Implements kimi-cli style persistent prompt with background generation.
The prompt stays active during LLM generation, enabling:
- Chat-style output (responses appear above prompt)
- Typing ahead (queuing messages for next turn)
- Steering (interrupting/influencing current generation)
"""

import threading
import time
from enum import Enum, auto
from typing import Callable


class GenerationState(Enum):
    """State of the LLM generation."""
    IDLE = auto()
    GENERATING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


class RunningPromptManager:
    """
    Manages background generation and UI synchronization.
    
    This is the core of Option B: keeping the prompt active while
    the LLM works in a background thread.
    """
    
    def __init__(self, io):
        self.io = io
        self.console = io.console
        self.state = GenerationState.IDLE
        self._thread = None
        self._error = None
        self._result = None
        
    def start_generation(self, func: Callable, *args, **kwargs) -> None:
        """Start a generation task in a background thread."""
        if self.state == GenerationState.GENERATING:
            return
            
        self.state = GenerationState.GENERATING
        self._error = None
        self._result = None
        
        # Notify IO that task is running
        self.io.set_task_running(True)
        
        self._thread = threading.Thread(
            target=self._generation_worker,
            args=(func, args, kwargs),
            daemon=True
        )
        self._thread.start()
        
    def _generation_worker(self, func, args, kwargs) -> None:
        """Background worker thread for generation."""
        try:
            # Execute the function (usually coder.run_one or send_message)
            # We wrap it to catch any output and pipe it through patch_stdout
            self._result = func(*args, **kwargs)
            self.state = GenerationState.COMPLETED
        except Exception as e:
            self._error = e
            self.state = GenerationState.FAILED
        finally:
            # Notify IO that task is finished
            self.io.set_task_running(False)
            
    def is_generating(self) -> bool:
        """Check if generation is currently in progress."""
        return self.state == GenerationState.GENERATING
        
    def wait_for_completion(self):
        """Block until generation completes (if needed)."""
        if self._thread:
            self._thread.join()
        return self._result, self._error

    def process_output(self, content: str):
        """Process streaming output chunks from the background."""
        # This is usually handled by the callback in the coder,
        # but the manager can provide synchronization if needed.
        pass


def create_running_prompt_ui(io) -> RunningPromptManager:
    """Factory function to create the running prompt UI."""
    return RunningPromptManager(io)
