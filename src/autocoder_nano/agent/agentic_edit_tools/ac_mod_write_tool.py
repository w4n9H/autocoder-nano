import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ACModWriteTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.context import record_memory

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class ACModWriteToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
                 tool: ACModWriteTool, args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: ACModWriteTool = tool

    @staticmethod
    def _prune_file_content(content: str) -> str:
        """
        该函数主要目的是对命令行执行后的结果内容进行剪枝处理
        因为执行的命令可能包含
        - 读取大量文件
        """
        return content

    def resolve(self) -> ToolResult:
        content = self.tool.content

        try:
            note_id = record_memory(
                project_root=self.args.source_dir,
                user_id="agentic_ac_mod",
                content=content
            )
            return ToolResult(success=True, message=f"ACMod 记录成功, ID: {note_id}", content="")
        except Exception as e:
            return ToolResult(success=False, message=f"ACMod 记录失败: {str(e)}", content="")