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

    def guide(self) -> str:
        doc = """
        ## ask_followup_question（提出后续问题）
        描述：
        - 向用户提问获取任务所需信息。
        - 当遇到歧义，需要澄清或需要更多细节以有效推进时使用此工具。
        - 它通过与用户直接沟通实现交互式问题解决，应明智使用，以在收集必要信息和避免过多来回沟通之间取得平衡。
        参数：
        - question（必填）：清晰具体的问题。
        - options（可选）：2-5个选项的数组，每个选项应为描述可能答案的字符串，并非总是需要提供选项，少数情况下有助于避免用户手动输入。
        用法说明：
        <ask_followup_question>
        <question>Your question here</question>
        <options>
        Array of options here (optional), e.g. ["Option 1", "Option 2", "Option 3"]
        </options>
        </ask_followup_question>
        用法示例：
        场景一：澄清需求
        目标：用户只说要修改文件，但没有提供文件名。
        思维过程：需要向用户询问具体要修改哪个文件，提供选项可以提高效率。
        <ask_followup_question>
        <question>请问您要修改哪个文件？</question>
        <options>
        ["src/app.js", "src/index.js", "package.json"]
        </options>
        </ask_followup_question>
        场景二：询问用户偏好
        目标：在实现新功能时，有多种技术方案可供选择。
        思维过程：为了确保最终实现符合用户预期，需要询问用户更倾向于哪种方案。
        <ask_followup_question>
        <question>您希望使用哪个框架来实现前端界面？</question>
        <options>
        ["React", "Vue", "Angular"]
        </options>
        </ask_followup_question>
        """
        return doc