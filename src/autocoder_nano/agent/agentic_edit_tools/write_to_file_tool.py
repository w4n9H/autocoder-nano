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
        # self.args = args

    @staticmethod
    def write_file_normal(file_path: str, content: str, source_dir: str, abs_project_dir: str,
                          abs_file_path: str) -> ToolResult:
        """Write file directly without using shadow manager"""
        try:
            os.makedirs(os.path.dirname(abs_file_path), exist_ok=True)
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
        source_dir = self.agent.args.source_dir or "."
        abs_project_dir = os.path.abspath(source_dir)
        abs_file_path = os.path.abspath(os.path.join(source_dir, file_path))

        # Security check: ensure the path is within the source directory
        if not abs_file_path.startswith(abs_project_dir):
            return ToolResult(
                success=False,
                message=f"错误: 拒绝访问, 尝试修改项目目录之外的文件：{file_path}")

        return self.write_file_normal(file_path, content, source_dir, abs_project_dir, abs_file_path)

    def guide(self) -> str:
        doc = """
        ## write_to_file（写入文件）
        描述：将内容写入指定路径文件，文件存在则覆盖，不存在则创建，会自动创建所需目录。
        参数：
        - path（必填）：要写入的文件路径（相对于当前工作目录）。
        - content（必填）：要写入文件的内容。必须提供文件的完整预期内容，不得有任何截断或遗漏，必须包含文件的所有部分，即使它们未被修改。
        用法说明：
        <write_to_file>
        <path>文件路径在此</path>
        <content>
            你的文件内容在此
        </content>
        </write_to_file>
        用法示例：
        场景一：创建一个新的代码文件
        目标：在 src 目录下创建一个新的 Python 文件 main.py 并写入初始代码。
        思维过程：目标是创建新文件并写入内容，所以直接使用 write_to_file，指定新文件路径和要写入的代码内容。
        <write_to_file>
        <path>src/main.py</path>
        <content>
        print("Hello, world!")
        </content>
        </write_to_file>
        """
        return doc