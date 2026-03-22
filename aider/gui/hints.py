from typing import Optional
import random

class HintManager:
    """
    Enterprise-grade Hint Manager for Aider.
    Provides proactive suggestions based on system events.
    """
    
    TIPS = [
        "Try '/auto fix tests' if your tests are failing.",
        "Use '/agent spawn' to parallelize complex tasks.",
        "You can add read-only files with '/add --read-only'.",
        "Type '/help <command>' for detailed information.",
        "Use '/tokens' to check your current session budget.",
        "The 'Librarian' persona helps find relevant context in large repos.",
    ]

    def __init__(self, io: object):
        self.io = io
        self._last_hint_time = 0
        self._hint_cooldown = 300  # 5 minutes

    def get_contextual_hint(self, event_type: str, data: dict = None) -> Optional[str]:
        """Generate a hint based on the current context."""
        if event_type == "test_failure":
            return "Tests failed. Try '/auto fix tests' to have Aider self-correct."
        elif event_type == "lint_failure":
            return "Lint errors detected. '/auto fix lint' can help."
        elif event_type == "budget_warning":
            return "Budget usage is high. Use '/tokens' to see the breakdown."
        elif event_type == "idle":
            return random.choice(self.TIPS)
        
        return None

    def show_hint(self, hint: str):
        """Show a hint in the terminal."""
        self.io.tool_output(f"💡 Hint: {hint}")
