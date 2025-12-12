import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ACModSearchTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.context import recall_memory

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class ACModSearchToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
                 tool: ACModSearchTool, args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: ACModSearchTool = tool

    @staticmethod
    def _prune_file_content(content: str) -> str:
        """
        该函数主要目的是对命令行执行后的结果内容进行剪枝处理
        因为执行的命令可能包含
        - 读取大量文件
        """
        return content

    def resolve(self) -> ToolResult:
        query = self.tool.query

        try:
            note_content = recall_memory(
                project_root=self.agent.args.source_dir,
                user_id="agentic_ac_mod",
                query=query
            )
            return ToolResult(success=True, message=f"ACMod 检索成功, 查询问题: {query}", content=note_content)
        except Exception as e:
            return ToolResult(success=False, message=f"ACMod 检索失败: {str(e)}", content="")

    def guide(self) -> str:
        doc = """
        ## ac_mod_search (检索AC模块)
        描述：
        - 从存储中检索已经生成的 AC Module
        参数：
        - query（必填）：检索 AC Module 的提问，可以使用多个关键词（关键词可以根据任务需求自由发散），且必须使用空格分割关键词
        用法说明：
        <ac_mod_search>
        <query>Search AC Module Key Word</query>
        </ac_mod_search>
        用法示例：
        场景一：修改 agentic_runtime.py 前，查询的相关用法
        思维过程：检索 agentic_runtime.py 相关, 拆分为 agent agentic_runtime 两个关键词
        <ac_mod_search>
        <query>agent agentic_runtime</query>
        </ac_mod_search>
        """
        return doc