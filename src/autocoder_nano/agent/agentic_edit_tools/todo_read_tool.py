import json
import os
import typing
from typing import Union, Optional, List, Dict, Any

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.agent.agentic_edit_tools import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ToolResult, TodoReadTool
from autocoder_nano.utils.printer_utils import Printer

printer = Printer()

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class TodoReadToolResolver(BaseToolResolver):
    def __init__(
            self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
            tool: TodoReadTool, args: AutoCoderArgs
    ):
        super().__init__(agent, tool, args)
        self.tool: TodoReadTool = tool
        # self.args = args

    def _get_todo_file_path(self) -> str:
        source_dir = self.agent.args.source_dir or "."
        todo_dir = os.path.join(source_dir, ".auto-coder", "todos")
        os.makedirs(todo_dir, exist_ok=True)
        return os.path.join(todo_dir, "current_session.json")

    def _load_todos(self) -> List[Dict[str, Any]]:
        """Load todos from the session file."""
        todo_file = self._get_todo_file_path()
        if not os.path.exists(todo_file):
            return []

        try:
            with open(todo_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('todos', [])
        except Exception as e:
            printer.print_text(f"打开 Todos 文件失败: {e}")
            return []

    @staticmethod
    def _format_todo_display(todos: List[Dict[str, Any]]) -> str:
        """Format todos for display."""
        if not todos:
            return "当前会话中未找到待办事项."

        output = ["## 当前会话 Todo List \n"]

        # Group by status
        pending = [t for t in todos if t.get('status') == 'pending']
        in_progress = [t for t in todos if t.get('status') == 'in_progress']
        completed = [t for t in todos if t.get('status') == 'completed']

        def render_section(title: str, icon: str, section_todos: List[Dict[str, Any]]):
            if not section_todos:
                return

            output.append(f"### {icon} {title}")
            for _todo in section_todos:
                _priority_icon = {
                    "high": "[高]", "medium": "[中]", "low": "[低]"
                }.get(_todo.get('priority', 'medium'), "[中]")

                _line = f"- {_priority_icon} **[{_todo['id']}]** {_todo['content']}"
                output.append(_line)
                if _todo.get('notes'):
                    output.append(f"  > {_todo['notes']}")
            output.append("")

        render_section("进行中", "", in_progress)
        render_section("待处理", "", pending)
        render_section("已完成", "", completed)

        # Add summary
        total = len(todos)
        pending_count = len(pending)
        in_progress_count = len(in_progress)
        completed_count = len(completed)

        output.append(
            f"**摘要**: 总计 {total} 项 | 待处理 {pending_count} | 进行中 {in_progress_count} | 已完成 {completed_count}")

        return "\n".join(output)

    def resolve(self) -> ToolResult:
        """
        Read the current todo list and return it in a formatted display.
        """
        try:
            printer.print_text(f"正在读取当前 TodoList", style="green")

            # Load todos from file
            todos = self._load_todos()

            # Format for display
            formatted_display = self._format_todo_display(todos)

            printer.print_text(f"在当前会话中找到 {len(todos)} 个 Todos", style="green")

            return ToolResult(
                success=True,
                message="成功获取 TodoList.",
                content=formatted_display
            )
        except Exception as e:
            printer.print_text(f"读取TodoList时出错: {e}", style="red")
            return ToolResult(
                success=False,
                message=f"读取TodoList时出错: {str(e)}",
                content=None
            )

    def guide(self) -> str:
        doc = """
        ## todo_read（读取待办事项）
        描述：
        - 请求读取当前会话的待办事项列表。该工具有助于跟踪进度，组织复杂任务并了解当前工作状态。
        - 请主动使用此工具以掌握任务进度，展现细致周全的工作态度。
        参数：
        - 无需参数
        用法说明：
        <todo_read>
        </todo_read>
        用法示例：
        场景一：读取当前的会话的待办事项
        目标：读取当前的会话的待办事项
        <todo_read>
        </todo_read>
        """
        return doc