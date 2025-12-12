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
        # self.args = args

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
        source_dir = self.agent.args.source_dir or "."
        abs_project_dir = os.path.abspath(source_dir)
        abs_file_path = os.path.abspath(os.path.join(source_dir, file_path))

        # 安全检查
        if not abs_file_path.startswith(abs_project_dir):
            return ToolResult(
                success=False,
                message=f"错误: 拒绝访问, 尝试修改项目目录之外的文件：{file_path}")

        return self.replace_in_file_normal(file_path, diff_content, source_dir, abs_project_dir, abs_file_path)

    def guide(self) -> str:
        doc = """
        ## replace_in_file（替换文件内容）
        描述：
        - 请求使用定义对文件特定部分进行精确更改的 SEARCH/REPLACE 块来替换现有文件中的部分内容。
        - 此工具应用于需要对文件特定部分进行有针对性更改的情况。
        参数：
        - path（必填）：要修改的文件路径，相对于当前工作目录。
        - diff（必填）：一个或多个遵循以下精确格式的 SEARCH/REPLACE 块：
        用法说明：
        <replace_in_file>
        <path>File path here</path>
        <diff>
        <<<<<<< SEARCH
        [exact content to find]
        =======
        [new content to replace with]
        >>>>>>> REPLACE
        </diff>
        </replace_in_file>
        用法示例：
        场景一：对一个代码文件进行部分更改
        目标：对 src/components/App.tsx 文件进行特定部分的精确更改
        思维过程：目标是对代码的指定位置进行更改，所以直接使用 replace_in_file，指定文件路径和 SEARCH/REPLACE 块。
        <replace_in_file>
        <path>src/components/App.tsx</path>
        <diff>
        <<<<<<< SEARCH
        import React from 'react';
        =======
        import React, { useState } from 'react';
        >>>>>>> REPLACE
        
        <<<<<<< SEARCH
        function handleSubmit() {
        saveData();
        setLoading(false);
        }
        
        =======
        >>>>>>> REPLACE
        
        <<<<<<< SEARCH
        return (
        <div>
        =======
        function handleSubmit() {
        saveData();
        setLoading(false);
        }
        
        return (
        <div>
        >>>>>>> REPLACE
        </diff>
        </replace_in_file>
        
        关键规则：
        1. SEARCH 内容必须与关联的文件部分完全匹配：
            * 逐字符匹配，包括空格、缩进、行尾符。
            * 包含所有注释、文档字符串等。
        2. SEARCH/REPLACE 块仅替换第一个匹配项：
            * 如果需要进行多次更改，需包含多个唯一的 SEARCH/REPLACE 块。
            * 每个块的 SEARCH 部分应包含足够的行，以唯一匹配需要更改的每组行。
            * 使用多个 SEARCH/REPLACE 块时，按它们在文件中出现的顺序列出。
        3. 保持 SEARCH/REPLACE 块简洁：
            * 将大型 SEARCH/REPLACE 块分解为一系列较小的块，每个块更改文件的一小部分。
            * 仅包含更改的行，必要时包含一些周围的行以确保唯一性。
            * 不要在 SEARCH/REPLACE 块中包含长段未更改的行。
            * 每行必须完整，切勿在中途截断行，否则可能导致匹配失败。
        4. 特殊操作：
            * 移动代码：使用两个 SEARCH/REPLACE 块（一个从原始位置删除，一个插入到新位置）。
            * 删除代码：使用空的 REPLACE 部分。
        """
        return doc