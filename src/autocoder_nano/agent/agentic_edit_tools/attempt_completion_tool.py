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

    def guide(self) -> str:
        doc = """
        ## attempt_completion（尝试完成任务并输出结果）
        描述：
        - 每次工具使用后，用户会回复该工具使用的结果，即是否成功以及失败原因（如有）。
        - 一旦收到工具使用结果并确认任务完成，使用此工具向用户展示工作成果。
        - 可选地，你可以提供一个 CLI 命令来展示工作成果。用户可能会提供反馈，你可据此进行改进并再次尝试。
        重要提示：
        - 在确认用户已确认之前的工具使用成功之前，不得使用此工具。否则将导致代码损坏和系统故障。
        - 在使用此工具之前，必须在<thinking></thinking>标签中自问是否已从用户处确认之前的工具使用成功。如果没有，则不要使用此工具。
        参数：
        - result（必填）：任务的结果，应以最终形式表述，无需用户进一步输入，不得在结果结尾提出问题或提供进一步帮助。
        - command（可选）：用于向用户演示结果的 CLI 命令。
        用法说明：
        <attempt_completion>
        <result>
        成果交付，包括交付物（代码/文档）路径及相关说明
        </result>
        <command>Command to demonstrate result (optional)</command>
        </attempt_completion>
        用法示例：
        场景一：功能开发完成
        目标：已成功添加了一个新功能。
        思维过程：所有开发和测试工作都已完成，现在向用户展示新功能并提供一个命令来验证。
        <attempt_completion>
        <result>
        xxxxx 功能已成功集成到项目中。
        修改文件包括：
        1.src/path/main.py 新增xxx函数完成xxx功能
        2.src/path/run.py 新增xxx函数完成xxx功能
        3.src/README.md  更新文档
        现在您可以使用 python main.py 命令来运行测试，确认新功能的行为。
        </result>
        <command>python main.py</command>
        </attempt_completion>
        """
        return doc
