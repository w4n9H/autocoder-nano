import os
import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import WriteToFileTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class WriteToFileToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
                 tool: WriteToFileTool, args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: WriteToFileTool = tool  # For type hinting
        self.args = args

    def write_file_normal(self, file_path: str, content: str, source_dir: str, abs_project_dir: str,
                          abs_file_path: str) -> ToolResult:
        """Write file directly without using shadow manager"""
        try:
            os.makedirs(os.path.dirname(abs_file_path), exist_ok=True)

            # if self.agent:
            #     rel_path = os.path.relpath(abs_file_path, abs_project_dir)
            #     self.agent.record_file_change(rel_path, "added", diff=None, content=content)

            # todo: 应该是先备份,再写入, 参考 autocoder checkpoint_manager

            with open(abs_file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # todo: 写入后执行代码质量检查

            message = f"{file_path}"
            result_content = {"content": content}

            return ToolResult(success=True, message=message, content=result_content)
        except Exception as e:
            return ToolResult(success=False, message=f"An error occurred while writing to the file: {str(e)}")

    def resolve(self) -> ToolResult:
        """Resolve the write file tool by calling the appropriate implementation"""
        file_path = self.tool.path
        content = self.tool.content
        source_dir = self.args.source_dir or "."
        abs_project_dir = os.path.abspath(source_dir)
        abs_file_path = os.path.abspath(os.path.join(source_dir, file_path))

        # Security check: ensure the path is within the source directory
        if not abs_file_path.startswith(abs_project_dir):
            return ToolResult(
                success=False,
                message=f"错误: 拒绝访问, 尝试修改项目目录之外的文件：{file_path}")

        return self.write_file_normal(file_path, content, source_dir, abs_project_dir, abs_file_path)