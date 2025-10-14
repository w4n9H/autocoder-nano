import typing
from typing import Optional, Union

from prompt_toolkit import PromptSession

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ToolResult, AskFollowupQuestionTool
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents

printer = Printer()


class AskFollowupQuestionToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
                 tool: AskFollowupQuestionTool,
                 args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: AskFollowupQuestionTool = tool

    def resolve(self) -> ToolResult:
        """
        Packages the question and options to be handled by the main loop/UI.
        This resolver doesn't directly ask the user but prepares the data for it.
        """
        question = self.tool.question
        options = self.tool.options or []
        options_text = "\n".join([f"{i + 1}. {option}" for i, option in enumerate(options)])

        # 创建一个醒目的问题面板
        printer.print_panel(
            content=question,
            title="[bold yellow]AutoCoder Nano 的提问[/bold yellow]",
            border_style="blue",
            center=True
        )

        session = PromptSession(message="> 您的回复是: ")
        try:
            answer = session.prompt()
        except KeyboardInterrupt:
            answer = ""

        # The actual asking logic resides outside the resolver, typically in the agent's main loop
        # or UI interaction layer. The resolver's job is to validate and package the request.
        if not answer:
            return ToolResult(success=False, message="错误: 问题未得到回答.")

        # Indicate success in preparing the question data
        return ToolResult(success=True, message="已生成后续追问问题.", content=answer)