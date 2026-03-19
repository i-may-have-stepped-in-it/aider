from abc import ABC, abstractmethod

class TerminalUIObserver(ABC):
    """
    Interface for terminal UI components that observe system events.
    
    This follows the Observer pattern to decouple core logic from 
    terminal rendering, ensuring an enterprise-grade architecture.
    """

    @abstractmethod
    def on_phase_change(self, phase: str, status: str = "running"):
        """Called when an autonomous workflow phase changes."""
        pass

    @abstractmethod
    def on_cost_update(self, total: float, percentage: float):
        """Called when the session cost is updated."""
        pass

    @abstractmethod
    def on_agent_status(self, agent_id: str, status: str, task: str = None):
        """Called when a sub-agent's status changes."""
        pass

    @abstractmethod
    def on_tool_progress(self, tool_name: str, message: str, progress: float = None):
        """Called for granular tool execution progress."""
        pass

    @abstractmethod
    def on_policy_check(self, result: Any):
        """Called when a security policy scan result is available."""
        pass
