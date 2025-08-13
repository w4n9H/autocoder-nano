import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import RecallMemoryTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.context import recall_memory

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_edit import AgenticEdit
    from autocoder_nano.agent.agentic_ask import AgenticAsk


class RecallMemoryToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticEdit', 'AgenticAsk']], tool: RecallMemoryTool, args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: RecallMemoryTool = tool  # For type hinting

    @staticmethod
    def _prune_file_content(content: str) -> str:
        """
        该函数主要目的是对命令行执行后的结果内容进行剪枝处理
        因为执行的命令可能包含
        - 读取大量文件
        等操作
        todo: 该函数目前暂时未实现，直接返回全部结果
        """
        return content

    def resolve(self) -> ToolResult:
        query = self.tool.query

        try:
            note_content = recall_memory(
                project_root=self.args.source_dir,
                user_id="agentic",
                query=query
            )
            return ToolResult(success=True, message=f"笔记检索成功, 查询问题: {query}", content=note_content)
        except Exception as e:
            return ToolResult(success=False, message=f"笔记记录失败: {str(e)}", content="")