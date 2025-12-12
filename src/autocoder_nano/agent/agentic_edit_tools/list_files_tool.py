import os
import re
import typing
from typing import Optional, List, Union, Set

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ListFilesTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.sys_utils import default_exclude_dirs

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class ListFilesToolResolver(BaseToolResolver):
    def __init__(
            self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
            tool: ListFilesTool, args: AutoCoderArgs
    ):
        super().__init__(agent, tool, args)
        self.tool: ListFilesTool = tool
        self.exclude_files = args.exclude_files + default_exclude_dirs
        self.exclude_patterns = self.parse_exclude_files(self.exclude_files)

    @staticmethod
    def parse_exclude_files(exclude_files):
        if not exclude_files:
            return []

        if isinstance(exclude_files, str):
            exclude_files = [exclude_files]

        exclude_patterns = []
        for pattern in exclude_files:
            if pattern.startswith("regex://"):
                pattern = pattern[8:]
                exclude_patterns.append(re.compile(pattern))
            else:
                exclude_patterns.append(re.compile(pattern))
        return exclude_patterns

    def should_exclude(self, file_path):
        for pattern in self.exclude_patterns:
            if pattern.search(file_path):
                return True
        return False

    def list_files_in_dir(self, base_dir: str, recursive: bool, source_dir: str, is_outside_source: bool) -> Set[str]:
        """Helper function to list files in a directory"""
        result = set()
        try:
            if recursive:
                for root, dirs, files in os.walk(base_dir):
                    # Modify dirs in-place to skip ignored dirs early
                    dirs[:] = [d for d in dirs if not self.should_exclude(os.path.join(root, d))]
                    for name in files:
                        full_path = os.path.join(root, name)
                        if self.should_exclude(full_path):
                            continue
                        display_path = os.path.relpath(full_path, source_dir) if not is_outside_source else full_path
                        result.add(display_path)
                    for d in dirs:
                        full_path = os.path.join(root, d)
                        display_path = os.path.relpath(full_path, source_dir) if not is_outside_source else full_path
                        result.add(display_path + "/")
            else:
                for item in os.listdir(base_dir):
                    full_path = os.path.join(base_dir, item)
                    if self.should_exclude(full_path):
                        continue
                    display_path = os.path.relpath(full_path, source_dir) if not is_outside_source else full_path
                    if os.path.isdir(full_path):
                        result.add(display_path + "/")
                    else:
                        result.add(display_path)
        except Exception as e:
            pass
            # logger.warning(f"Error listing files in {base_dir}: {e}")
        return result

    def list_files_normal(
            self, list_path_str: str, recursive: bool, source_dir: str, absolute_source_dir: str,
            absolute_list_path: str) -> Union[ToolResult, List[str]]:
        """List files directly without using shadow manager"""
        # Security check: Allow listing outside source_dir IF the original path is outside?
        is_outside_source = not absolute_list_path.startswith(absolute_source_dir)
        if is_outside_source:
            return ToolResult(success=False,
                              message=f"错误: 拒绝访问, 尝试列出项目目录之外的文件: {list_path_str}")

        if not os.path.exists(absolute_list_path):
            return ToolResult(success=False, message=f"错误: 路径未找到 {list_path_str}")
        if not os.path.isdir(absolute_list_path):
            return ToolResult(success=False, message=f"错误: 路径不是目录 {list_path_str}")

        # Collect files from the directory
        files_set = self.list_files_in_dir(absolute_list_path, recursive, source_dir, is_outside_source)

        try:
            # Successfully listed contents of '{list_path_str}' (Recursive: {recursive}). Found {len(files_set)} items.
            return sorted(files_set)
        except Exception as e:
            return ToolResult(success=False, message=f"列出文件时发生意外错误: {str(e)}")

    def resolve(self) -> ToolResult:
        """Resolve the list files tool by calling the appropriate implementation"""
        list_path_str = self.tool.path
        recursive = self.tool.recursive or False
        source_dir = self.agent.args.source_dir or "."
        absolute_source_dir = os.path.abspath(source_dir)
        absolute_list_path = os.path.abspath(os.path.join(source_dir, list_path_str))

        result = self.list_files_normal(list_path_str, recursive, source_dir, absolute_source_dir, absolute_list_path)

        if isinstance(result, list):
            total_items = len(result)
            # Limit results to 200 if needed
            if total_items > 200:
                truncated_result = result[:200]
                message = f"成功获取目录内容: {list_path_str} (递归:{recursive}), 总计 {total_items} 项, 当前截取前 200 条."
                return ToolResult(success=True, message=message, content=truncated_result)
            else:
                message = f"成功获取目录内容: {list_path_str} (递归:{recursive}), 总计 {total_items} 项."
                return ToolResult(success=True, message=message, content=result)
        else:
            return result

    def guide(self) -> str:
        doc = """
        ## list_files（列出文件）
        描述：
        - 列出指定目录中的文件和目录，支持递归列出。
        参数：
        - path（必填）：要列出内容的目录路径，相对于当前工作目录。
        - recursive（可选）：是否递归列出文件，true 表示递归列出，false 或省略表示仅列出顶级内容。
        用法说明：
        <list_files>
        <path>Directory path here</path>
        <recursive>true or false (optional)</recursive>
        </list_files>
        用法示例：
        场景一：列出当前目录下的文件
        目标：查看当前项目目录下的所有文件和子目录。
        思维过程：这是一个只读操作，直接使用 . 作为路径。
        <list_files>
        <path>.</path>
        </list_files>
        场景二：递归列出指定目录下的所有文件
        目标：查看 src 目录下所有文件和子目录的嵌套结构。
        思维过程：这是一个只读操作，使用 src 作为路径，并设置 recursive 为 true。
        <list_files>
        <path>src/</path>
        <recursive>true</recursive>
        </list_files>
        """
        return doc