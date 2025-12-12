import glob
import os
import re
import typing
from typing import Optional, List, Dict, Any, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import SearchFilesTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.sys_utils import default_exclude_dirs

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class SearchFilesToolResolver(BaseToolResolver):
    def __init__(
            self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
            tool: SearchFilesTool, args: AutoCoderArgs
    ):
        super().__init__(agent, tool, args)
        self.tool: SearchFilesTool = tool
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

    def search_in_dir(
            self, base_dir: str, regex_pattern: str, file_pattern: str, source_dir: str,
            is_shadow: bool = False, compiled_regex: Optional[re.Pattern] = None
    ) -> List[Dict[str, Any]]:
        """Helper function to search in a directory"""
        search_results = []
        search_glob_pattern = os.path.join(base_dir, "**", file_pattern)

        if compiled_regex is None:
            compiled_regex = re.compile(regex_pattern)

        for filepath in glob.glob(search_glob_pattern, recursive=True):
            abs_path = os.path.abspath(filepath)
            if self.should_exclude(abs_path):
                continue
            if os.path.isfile(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                    for i, line in enumerate(lines):
                        if compiled_regex.search(line):
                            context_start = max(0, i - 2)
                            context_end = min(len(lines), i + 3)
                            context = "".join([f"{j + 1}: {lines[j]}" for j in range(context_start, context_end)])

                            relative_path = os.path.relpath(filepath, source_dir)

                            search_results.append({
                                "path": relative_path,
                                "line_number": i + 1,
                                "match_line": line.strip(),
                                "context": context.strip()
                            })
                except Exception as e:
                    # logger.warning(f"Could not read or process file {filepath}: {e}")
                    continue

        return search_results

    def search_files_normal(
            self, search_path_str: str, regex_pattern: str, file_pattern: str, source_dir: str,
            absolute_source_dir: str, absolute_search_path: str
    ) -> Union[ToolResult, List[Dict[str, Any]]]:
        """Search files directly without using shadow manager"""
        # Security check
        if not absolute_search_path.startswith(absolute_source_dir):
            return ToolResult(success=False,
                              message=f"错误: 拒绝访问, 尝试搜索项目目录之外的文件: {search_path_str}")

        # Validate that the directory exists
        if not os.path.exists(absolute_search_path):
            return ToolResult(success=False, message=f"错误: 搜索路径未找到 {search_path_str}")
        if not os.path.isdir(absolute_search_path):
            return ToolResult(success=False, message=f"错误: 搜错路径不是目录 {search_path_str}")

        try:
            compiled_regex = re.compile(regex_pattern)
            # Search in the directory
            search_results = self.search_in_dir(absolute_search_path, regex_pattern, file_pattern, source_dir,
                                                is_shadow=False, compiled_regex=compiled_regex)
            return search_results
        except re.error as e:
            return ToolResult(success=False, message=f"无效的正则表达式: {e}")
        except Exception as e:
            return ToolResult(success=False, message=f"搜索过程中出现未知错误: {str(e)}")

    def resolve(self) -> ToolResult:
        """Resolve the search files tool by calling the appropriate implementation"""
        search_path_str = self.tool.path
        regex_pattern = self.tool.regex
        file_pattern = self.tool.file_pattern or "*"
        source_dir = self.agent.args.source_dir or "."
        absolute_source_dir = os.path.abspath(source_dir)
        absolute_search_path = os.path.abspath(os.path.join(source_dir, search_path_str))

        result = self.search_files_normal(
            search_path_str, regex_pattern, file_pattern, source_dir, absolute_source_dir, absolute_search_path
        )

        if isinstance(result, list):
            total_results = len(result)
            if total_results > 200:
                truncated_results = result[:200]
                message = f"搜索完成. 总计匹配 {total_results} 条结果, 当前展示前 200 条"
                return ToolResult(success=True, message=message, content=truncated_results)
            else:
                message = f"搜索完成. 总计匹配 {total_results} 条结果."
                return ToolResult(success=True, message=message, content=result)
        else:
            return result

    def guide(self) -> str:
        doc = """
        ## search_files（搜索文件）
        描述：
        - 在指定目录的文件中执行正则表达式搜索，输出包含每个匹配项及其周围的上下文结果。
        参数：
        - path（必填）：要搜索的目录路径，相对于当前工作目录，该目录将被递归搜索。
        - regex（必填）：要搜索的正则表达式模式，使用 Rust 正则表达式语法。
        - file_pattern（可选）：用于过滤文件的 Glob 模式（例如，'.ts' 表示 TypeScript 文件），若未提供，则搜索所有文件（*）。
        用法说明：
        <search_files>
        <path>Directory path here</path>
        <regex>Your regex pattern here</regex>
        <file_pattern>file pattern here (optional)</file_pattern>
        </search_files>
        用法示例：
        场景一：搜索包含关键词的文件
        目标：在项目中的所有 JavaScript 文件中查找包含 "handleError" 函数调用的地方。
        思维过程：我们需要在当前目录（.）下，通过 "handleError(" 关键词搜索所有 JavaScript(.js) 文件，
        <search_files>
        <path>.</path>
        <regex>handleError(</regex>
        <file_pattern>.js</file_pattern>
        </search_files>
        场景二：在 Markdown 文件中搜索标题
        目标：在项目文档中查找所有二级标题。
        思维过程：这是一个只读操作。我们可以在 docs 目录下，使用正则表达式 ^##\s 搜索所有 .md 文件。
        <search_files>
        <path>docs/</path>
        <regex>^##\s</regex>
        <file_pattern>.md</file_pattern>
        </search_files>
        """
        return doc