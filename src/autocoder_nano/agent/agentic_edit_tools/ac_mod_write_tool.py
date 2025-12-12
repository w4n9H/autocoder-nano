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
                project_root=self.agent.args.source_dir,
                user_id="agentic_ac_mod",
                content=content
            )
            return ToolResult(success=True, message=f"ACMod 记录成功, ID: {note_id}", content="")
        except Exception as e:
            return ToolResult(success=False, message=f"ACMod 记录失败: {str(e)}", content="")

    def guide(self) -> str:
        doc = """
        ## ac_mod_write（写入AC模块）
        描述：
        - 用于记录代码文件或模块的AC Module，
        - AC Module 包含使用示例，核心组件，组件依赖关系，对其他AC模块的引用以及测试信息。
        参数：
        - content（必填）：你的 AC Module 正文
        用法说明：
        <ac_mod_write>
        <content>AC Module 正文</content>
        </ac_mod_write>
        用法示例：
        场景一：分析记录 src/autocoder_nano/agent 模块的 AC Module
        思维过程：使用 read_file 顺序读取 src/autocoder_nano/agent 目录内的所有文件内容后，生成对应的 AC Module
        <ac_mod_write>
        <content>
        AC Module 正文(包含使用示例，核心组件，组件依赖关系，对其他AC模块的引用以及测试信息)
        </content>
        </ac_mod_write>
        """
        return doc