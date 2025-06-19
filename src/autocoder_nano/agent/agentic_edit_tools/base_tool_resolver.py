import typing
from abc import ABC, abstractmethod

from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.llm_types import AutoCoderArgs

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_edit import AgenticEdit


class BaseToolResolver(ABC):
    def __init__(self, agent: Optional['AgenticEdit'], tool: BaseTool, args: AutoCoderArgs):
        """
        Initializes the resolver.
        Args:
            agent: The AutoCoder agent instance.
            tool: The Pydantic model instance representing the tool call.
            args: Additional arguments needed for execution (e.g., source_dir).
        """
        self.agent = agent
        self.tool = tool
        self.args = args

    @abstractmethod
    def resolve(self) -> ToolResult:
        """
        Executes the tool's logic.
        Returns:
            A ToolResult object indicating success or failure and a message.
        """
        pass