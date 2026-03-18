import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

@dataclass
class MissionStats:
    total_tokens: int = 0
    total_cost: float = 0.0
    total_turns: int = 0
    active_agents: int = 0
    start_time: float = field(default_factory=time.time)

class MissionGovernor:
    """
    Global safety governor for multi-agent missions.
    Prevents budget runaway and recursive agent explosion.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super(MissionGovernor, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_cost: float = 5.0, max_turns: int = 50, max_depth: int = 3):
        if self._initialized:
            return
        self.max_cost = max_cost
        self.max_turns = max_turns
        self.max_depth = max_depth
        self.stats = MissionStats()
        self.agent_depths: Dict[str, int] = {}
        self._initialized = True

    def check_safety(self, agent_id: str, depth: int) -> bool:
        """Verify if it is safe to spawn or continue an agent."""
        if self.stats.total_cost >= self.max_cost:
            logger.error(f"Mission Governor: Cost limit exceeded (${self.stats.total_cost})")
            return False
        if self.stats.total_turns >= self.max_turns:
            logger.error(f"Mission Governor: Turn limit exceeded ({self.stats.total_turns})")
            return False
        if depth > self.max_depth:
            logger.error(f"Mission Governor: Max delegation depth exceeded ({depth})")
            return False
        return True

    def record_turn(self, cost: float = 0.0, tokens: int = 0):
        self.stats.total_turns += 1
        self.stats.total_cost += cost
        self.stats.total_tokens += tokens

    def register_agent(self, agent_id: str, depth: int):
        self.stats.active_agents += 1
        self.agent_depths[agent_id] = depth

    def unregister_agent(self, agent_id: str):
        self.stats.active_agents -= 1

    def get_report(self) -> str:
        duration = time.time() - self.stats.start_time
        return (
            f"Mission Report:\n"
            f"- Runtime: {duration:.1f}s\n"
            f"- Total Turns: {self.stats.total_turns}\n"
            f"- Active Agents: {self.stats.active_agents}\n"
            f"- Total Cost: ${self.stats.total_cost:.4f}\n"
            f"- Total Tokens: {self.stats.total_tokens}"
        )

# Global singleton access
def get_governor() -> MissionGovernor:
    return MissionGovernor()
