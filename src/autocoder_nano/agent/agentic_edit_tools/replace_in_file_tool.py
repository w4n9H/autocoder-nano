import os
import typing
from typing import Tuple, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.actypes import AutoCoderArgs

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class ReplaceInFileToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
                 tool: ReplaceInFileTool, args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: ReplaceInFileTool = tool  # For type hinting
        self.args = args

    @staticmethod
    def parse_diff(diff_content: str) -> List[Tuple[str, str]]:
        """
        Parses the diff content into a list of (search_block, replace_block) tuples.
        """
        blocks = []
        lines = diff_content.splitlines(keepends=True)
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]
            if line.strip() == "<<<<<<< SEARCH":
                i += 1
                search_lines = []
                # Accumulate search block
                while i < n and lines[i].strip() != "=======":
                    search_lines.append(lines[i])
                    i += 1
                if i >= n:
                    # warning: Unterminated SEARCH block found in diff content.
                    break
                i += 1  # skip '======='
                replace_lines = []
                # Accumulate replace block
                while i < n and lines[i].strip() != ">>>>>>> REPLACE":
                    replace_lines.append(lines[i])
                    i += 1
                if i >= n:
                    # warning: Unterminated REPLACE block found in diff content.
                    break
                i += 1  # skip '>>>>>>> REPLACE'

                search_block = ''.join(search_lines)
                replace_block = ''.join(replace_lines)
                blocks.append((search_block, replace_block))
            else:
                i += 1

        if not blocks and diff_content.strip():
            pass
            # warning: Could not parse any SEARCH/REPLACE blocks from diff: {diff_content}
        return blocks

    def replace_in_file_normal(
            self, file_path: str, diff_content: str, source_dir: str, abs_project_dir: str, abs_file_path: str
    ) -> ToolResult:
        """Replace content in file directly without using shadow manager"""
        try:
            if not os.path.exists(abs_file_path):
                return ToolResult(success=False, message=f"错误：未找到文件路径：{file_path}")
            if not os.path.isfile(abs_file_path):
                return ToolResult(success=False, message=f"错误：该路径不是文件：{file_path}")

            with open(abs_file_path, 'r', encoding='utf-8', errors='replace') as f:
                original_content = f.read()

            parsed_blocks = self.parse_diff(diff_content)
            if not parsed_blocks:
                return ToolResult(success=False, message="错误：在提供的diff中未找到有效的SEARCH/REPLACE代码块. ")

            current_content = original_content
            applied_count = 0
            errors = []

            # Apply blocks sequentially
            for i, (search_block, replace_block) in enumerate(parsed_blocks):
                start_index = current_content.find(search_block)

                if start_index != -1:
                    current_content = current_content[:start_index] + replace_block + current_content[
                                                                                      start_index + len(search_block):]
                    applied_count += 1
                    # f"Applied SEARCH/REPLACE block {i + 1} in file {file_path}"
                else:
                    error_message = (f"SEARCH block {i+1} not found in the current file content. Content to "
                                     f"search:\n---\n{search_block}\n---")
                    # logger.warning(error_message)
                    context_start = max(0, original_content.find(search_block[:20]) - 100)
                    context_end = min(len(original_content), context_start + 200 + len(search_block[:20]))
                    # warning: f"Approximate context in file:\n---\n{original_content[context_start:context_end]}\n---"
                    errors.append(error_message)

            return_errors = "\n".join(errors)
            if applied_count == 0 and errors:
                return ToolResult(success=False, message=f"未能应用任何更改, 错误信息: {return_errors}")

            # todo: 应该是先备份,再写入, 参考 autocoder checkpoint_manager

            with open(abs_file_path, 'w', encoding='utf-8') as f:
                f.write(current_content)

            # info: f"已成功将 {applied_count}/{len(parsed_blocks)} 个更改应用到文件：{file_path}"

            # todo: 写入后执行代码质量检查

            # 构建包含 lint 结果的返回消息
            if errors:
                message = f"成功应用了 {applied_count}/{len(parsed_blocks)} 个更改到文件：{file_path}. \n警告信息: \n{return_errors}"
            else:
                message = f"成功应用了 {applied_count}/{len(parsed_blocks)} 个更改到文件：{file_path}"

            # 变更跟踪，回调AgenticEdit
            # if self.agent:
            #     rel_path = os.path.relpath(abs_file_path, abs_project_dir)
            #     self.agent.record_file_change(
            #         rel_path, "modified", diff=diff_content, content=current_content)

            result_content = {"content": current_content}

            return ToolResult(success=True, message=message, content=result_content)
        except Exception as e:
            return ToolResult(success=False,
                              message=f"An error occurred while processing the file '{file_path}': {str(e)}")

    def resolve(self) -> ToolResult:
        """Resolve the replacement in file tool by calling the appropriate implementation"""
        file_path = self.tool.path
        diff_content = self.tool.diff
        source_dir = self.args.source_dir or "."
        abs_project_dir = os.path.abspath(source_dir)
        abs_file_path = os.path.abspath(os.path.join(source_dir, file_path))

        # 安全检查
        if not abs_file_path.startswith(abs_project_dir):
            return ToolResult(
                success=False,
                message=f"错误: 拒绝访问, 尝试修改项目目录之外的文件：{file_path}")

        return self.replace_in_file_normal(file_path, diff_content, source_dir, abs_project_dir, abs_file_path)