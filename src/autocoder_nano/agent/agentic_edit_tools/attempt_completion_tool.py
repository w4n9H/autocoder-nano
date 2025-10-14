import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ToolResult, AttemptCompletionTool
from autocoder_nano.actypes import AutoCoderArgs

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class AttemptCompletionToolResolver(BaseToolResolver):
    def __init__(
            self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
            tool: AttemptCompletionTool, args: AutoCoderArgs
    ):
        super().__init__(agent, tool, args)
        self.tool: AttemptCompletionTool = tool

    def resolve(self) -> ToolResult:
        """
        Packages the completion result and optional command to signal task completion.
        """
        result_text = self.tool.result
        command = self.tool.command

        # logger.info(f"Resolving AttemptCompletionTool: Result='{result_text[:100]}...', Command='{command}'")

        if not result_text:
            return ToolResult(success=False, message="错误：生成结果不能为空.")

        # The actual presentation of the result happens outside the resolver.
        result_content = {
            "result": result_text,
            "command": command
        }

        # Indicate success in preparing the completion data
        return ToolResult(success=True, message="尝试完成任务.", content=result_content)
