import os
import typing
from typing import Optional, Union

from autocoder_nano.rag.token_counter import count_tokens

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ReadFileTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs, SourceCode
from autocoder_nano.context import ContentPruner

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime


class ReadFileToolResolver(BaseToolResolver):
    def __init__(
            self, agent: Optional[Union['AgenticRuntime']],
            tool: ReadFileTool, args: AutoCoderArgs
    ):
        super().__init__(agent, tool, args)
        self.tool: ReadFileTool = tool  # For type hinting
        self.shadow_manager = self.agent.shadow_manager if self.agent else None
        self.context_pruner = ContentPruner(
            max_tokens=self.args.context_prune_safe_zone_tokens,
            args=self.args,
            llm=self.agent.llm
        )

    def _prune_file_content(self, content: str, file_path: str) -> str:
        """
        该函数主要目的是对命令行执行后的结果内容进行剪枝处理
        因为执行的命令可能包含
        - 读取大量文件
        等操作
        todo: 该函数目前暂时未实现，直接返回全部结果
        """
        if not self.context_pruner:
            return content

        # 计算 token 数量
        tokens = count_tokens(content)
        if tokens <= self.args.context_prune_safe_zone_tokens:
            return content

        # 创建 SourceCode 对象
        source_code = SourceCode(
            module_name=file_path,
            source_code=content,
            tokens=tokens
        )

        # 使用 context_pruner 进行剪枝
        pruned_sources = self.context_pruner.prune(
            file_sources=[source_code],
            conversations=self.agent.current_conversations if self.agent else [],
            strategy=self.args.context_prune_strategy
        )

        if not pruned_sources:
            return content

        return pruned_sources[0].source_code

    def _read_file_content(self, file_path_to_read: str) -> str:
        content = ""
        ext = os.path.splitext(file_path_to_read)[1].lower()

        if ext == '.pdf':
            # content = extract_text_from_pdf(file_path_to_read)
            # todo: 解析pdf文件
            pass
        elif ext == '.docx':
            # content = extract_text_from_docx(file_path_to_read)
            # todo: 解析doc文件
            pass
        elif ext in ('.pptx', '.ppt'):
            pass  # todo: 解析ppt文件
        else:
            with open(file_path_to_read, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

        # 对内容进行剪枝处理
        return self._prune_file_content(content, file_path_to_read)

    def read_file_normal(self, file_path: str, source_dir: str, abs_project_dir: str, abs_file_path: str) -> ToolResult:
        """Read file directly without using shadow manager"""
        try:
            if not os.path.exists(abs_file_path):
                return ToolResult(success=False, message=f"错误：未找到文件路径：{file_path}")
            if not os.path.isfile(abs_file_path):
                return ToolResult(success=False, message=f"错误：该路径不是文件：{file_path}")

            content = self._read_file_content(abs_file_path)
            return ToolResult(success=True, message=f"{file_path}", content=content)

        except Exception as e:
            return ToolResult(success=False,
                              message=f"An error occurred while processing the file '{file_path}': {str(e)}")

    def resolve(self) -> ToolResult:
        """Resolve the read file tool by calling the appropriate implementation"""
        file_path = self.tool.path
        source_dir = self.args.source_dir or "."
        abs_project_dir = os.path.abspath(source_dir)
        abs_file_path = os.path.abspath(os.path.join(source_dir, file_path))

        return self.read_file_normal(file_path, source_dir, abs_project_dir, abs_file_path)