import os
import typing
from typing import Optional

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ToolResult, ListCodeDefinitionNamesTool
from autocoder_nano.index.index_manager import IndexManager
from autocoder_nano.index.symbols_utils import extract_symbols
from autocoder_nano.llm_types import AutoCoderArgs

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_edit import AgenticEdit


class ListCodeDefinitionNamesToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional['AgenticEdit'], tool: ListCodeDefinitionNamesTool, args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: ListCodeDefinitionNamesTool = tool
        self.llm = self.agent.llm

    def _get_index(self):
        index_manager = IndexManager(
            args=self.args,
            source_codes=[],
            llm=self.llm)
        return index_manager

    def resolve(self) -> ToolResult:
        index_items = self._get_index().read_index()  # 仅读取索引
        index_data = {item.module_name: item for item in index_items}

        target_path_str = self.tool.path
        source_dir = self.args.source_dir or "."
        absolute_target_path = os.path.abspath(os.path.join(source_dir, target_path_str))

        # Security check
        if not absolute_target_path.startswith(os.path.abspath(source_dir)):
            return ToolResult(success=False,
                              message=f"错误: 拒绝访问, 尝试分析项目目录之外的代码 {target_path_str}")

        if not os.path.exists(absolute_target_path):
            return ToolResult(success=False, message=f"错误: 路径不存在 {target_path_str}")

        try:
            # Use RepoParser or a similar mechanism to extract definitions
            # RepoParser might need adjustments or a specific method for this tool's purpose.
            # This is a placeholder implementation. A real implementation needs robust code parsing.
            # logger.info(f"Analyzing definitions in: {absolute_target_path}")
            all_symbols = []

            if os.path.isfile(absolute_target_path):
                file_paths = [absolute_target_path]
            else:
                return ToolResult(success=False,
                                  message=f"错误：路径既不是文件也不是目录 {target_path_str}")

            for file_path in file_paths:
                try:
                    item = index_data[file_path]
                    symbols_str = item.symbols
                    symbols = extract_symbols(symbols_str)
                    if symbols:
                        all_symbols.append({
                            "path": file_path,
                            "definitions": [{"name": s, "type": "function"} for s in symbols.functions] + [
                                {"name": s, "type": "variable"} for s in symbols.variables] + [
                                {"name": s, "type": "class"} for s in symbols.classes]
                        })
                except Exception as e:
                    # logger.warning(f"Could not parse symbols from {file_path}: {e}")
                    pass
            total_symbols = sum(len(s['definitions']) for s in all_symbols)
            message = f"成功从目标路径 '{target_path_str}' 的 {len(all_symbols)} 个文件中提取了 {total_symbols} 个定义."
            return ToolResult(success=True, message=message, content=all_symbols)

        except Exception as e:
            return ToolResult(success=False,
                              message=f"提取 Code Definitions 时发生错误: {str(e)}")