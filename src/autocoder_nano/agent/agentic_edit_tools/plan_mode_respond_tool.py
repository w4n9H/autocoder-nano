import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ToolResult, AttemptCompletionTool, PlanModeRespondTool
from autocoder_nano.actypes import AutoCoderArgs

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_edit import AgenticEdit
    from autocoder_nano.agent.agentic_ask import AgenticAsk


class PlanModeRespondToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticEdit', 'AgenticAsk']], tool: PlanModeRespondTool,
                 args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: PlanModeRespondTool = tool  # For type hinting

    def resolve(self) -> ToolResult:
        """
        Packages the response and options for Plan Mode interaction.
        """
        response_text = self.tool.response
        options = self.tool.options
        # logger.info(f"Resolving PlanModeRespondTool: Response='{response_text[:100]}...', Options={options}")

        if not response_text:
            return ToolResult(success=False, message="错误：规划模式返回结果不可为空.")

        # The actual presentation happens outside the resolver.
        result_content = {
            "response": response_text,
            "options": options
        }

        # Indicate success in preparing the plan mode response data
        return ToolResult(success=True, message="规划模式响应已就绪.", content=result_content)
