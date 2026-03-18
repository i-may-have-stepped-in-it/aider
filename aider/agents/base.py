from abc import ABC, abstractmethod

from ..context import ProjectContext
from ..io import InputOutput
from ..models import Model


class BaseAgent(ABC):
    """
    Stateless Base Agent class.
    Operates on a ProjectContext and uses a Model to perform tasks.
    """

    def __init__(self, context: ProjectContext, main_model: Model, io: InputOutput):
        self.context = context
        self.main_model = main_model
        self.io = io

    @abstractmethod
    async def run(self, task: str) -> str:
        """Run the agent's primary loop for a given task."""
        pass

    def output(self, message: str):
        self.io.tool_output(f"[{self.__class__.__name__}] {message}")

    def error(self, message: str):
        self.io.tool_error(f"[{self.__class__.__name__}] {message}")
