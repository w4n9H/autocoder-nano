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
        self.args = args

    def _get_todo_file_path(self) -> str:
        """Get the path to the todo file for this session."""
        source_dir = self.args.source_dir or "."
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

        output = ["=== 当前会话 Todo List ===\n"]

        # Group by status
        pending = [t for t in todos if t.get('status') == 'pending']
        in_progress = [t for t in todos if t.get('status') == 'in_progress']
        completed = [t for t in todos if t.get('status') == 'completed']

        if in_progress:
            output.append("🔄 进行中:")
            for todo in in_progress:
                priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(todo.get('priority', 'medium'), "⚪")
                output.append(f"  {priority_icon} [{todo['id']}] {todo['content']}")
                if todo.get('notes'):
                    output.append(f"     📝 {todo['notes']}")
            output.append("")

        if pending:
            output.append("⏳ 待处理:")
            for todo in pending:
                priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(todo.get('priority', 'medium'), "⚪")
                output.append(f"  {priority_icon} [{todo['id']}] {todo['content']}")
                if todo.get('notes'):
                    output.append(f"     📝 {todo['notes']}")
            output.append("")

        if completed:
            output.append("✅ 已完成:")
            for todo in completed:
                priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(todo.get('priority', 'medium'), "⚪")
                output.append(f"  {priority_icon} [{todo['id']}] {todo['content']}")
                if todo.get('notes'):
                    output.append(f"     📝 {todo['notes']}")
            output.append("")

        # Add summary
        total = len(todos)
        pending_count = len(pending)
        in_progress_count = len(in_progress)
        completed_count = len(completed)

        output.append(
            f"📊 摘要: 总计 {total} 项 | 待处理 {pending_count} | 进行中 {in_progress_count} | 已完成 {completed_count}")

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