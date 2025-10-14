import json
import os
import typing
import uuid
from typing import Union, Optional, List, Dict, Any
from datetime import datetime

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.agent.agentic_edit_tools import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ToolResult, TodoWriteTool
from autocoder_nano.utils.printer_utils import Printer

printer = Printer()

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class TodoWriteToolResolver(BaseToolResolver):
    def __init__(
            self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
            tool: TodoWriteTool, args: AutoCoderArgs
    ):
        super().__init__(agent, tool, args)
        self.tool: TodoWriteTool = tool
        self.args = args

    def _get_todo_file_path(self) -> str:
        """Get the path to the todo file for this session."""
        source_dir = self.args.source_dir or "."
        todo_dir = os.path.join(source_dir, ".auto-coder", "todos")
        os.makedirs(todo_dir, exist_ok=True)
        return os.path.join(todo_dir, "current_session.json")

    def _load_todos(self) -> Dict[str, Any]:
        """Load todos from the session file."""
        todo_file = self._get_todo_file_path()
        if not os.path.exists(todo_file):
            return {
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "todos": []
            }

        try:
            with open(todo_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            printer.print_text(f"加载 TodoList 失败: {e}", style="yellow")
            return {
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "todos": []
            }

    def _save_todos(self, data: Dict[str, Any]) -> bool:
        """Save todos to the session file."""
        try:
            todo_file = self._get_todo_file_path()
            data["updated_at"] = datetime.now().isoformat()

            with open(todo_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            printer.print_text(f"保存 TodoList 失败: {e}", style="red")
            return False

    @staticmethod
    def _generate_todo_id() -> str:
        """Generate a unique ID for a todo item."""
        return str(uuid.uuid4())[:8]

    @staticmethod
    def _find_todo_by_id(todos: List[Dict[str, Any]], task_id: str) -> Optional[Dict[str, Any]]:
        """Find a todo item by ID."""
        for todo in todos:
            if todo.get('id') == task_id:
                return todo
        return None

    def _create_todo_list(self, content: str) -> List[Dict[str, Any]]:
        """Create a new todo list from content."""
        import re

        todos = []

        # First, try to parse <task> tags
        task_pattern = r'<task>(.*?)</task>'
        task_matches = re.findall(task_pattern, content, re.DOTALL)

        if task_matches:
            # Found <task> tags, use them
            for task_content in task_matches:
                task_content = task_content.strip()
                if task_content:
                    todo = {
                        "id": self._generate_todo_id(),
                        "content": task_content,
                        "status": "pending",
                        "priority": self.tool.priority or "medium",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat()
                    }

                    if self.tool.notes:
                        todo["notes"] = self.tool.notes

                    todos.append(todo)
        else:
            # Fallback to original line-by-line parsing
            lines = content.strip().split('\n')

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Remove common prefixes like "1.", "- ", "* ", etc.
                line = line.lstrip('0123456789.- *\t')

                if line:
                    todo = {
                        "id": self._generate_todo_id(),
                        "content": line,
                        "status": "pending",
                        "priority": self.tool.priority or "medium",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat()
                    }

                    if self.tool.notes:
                        todo["notes"] = self.tool.notes

                    todos.append(todo)

        return todos

    def _add_single_task(self, todos: List[Dict[str, Any]], content: str) -> Dict[str, Any]:
        """Add a single task to the existing todo list."""
        import re

        # Check if content contains <task> tags
        task_pattern = r'<task>(.*?)</task>'
        task_matches = re.findall(task_pattern, content, re.DOTALL)

        if task_matches:
            # If <task> tags found, use the first one
            task_content = task_matches[0].strip()
        else:
            # Use the content as-is
            task_content = content.strip()

        todo = {
            "id": self._generate_todo_id(),
            "content": task_content,
            "status": self.tool.status or "pending",
            "priority": self.tool.priority or "medium",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        if self.tool.notes:
            todo["notes"] = self.tool.notes

        todos.append(todo)
        return todo

    def _update_task(self, todo: Dict[str, Any]) -> None:
        """Update an existing task."""
        if self.tool.content:
            todo["content"] = self.tool.content
        if self.tool.status:
            todo["status"] = self.tool.status
        if self.tool.priority:
            todo["priority"] = self.tool.priority
        if self.tool.notes:
            todo["notes"] = self.tool.notes

        todo["updated_at"] = datetime.now().isoformat()

    @staticmethod
    def _format_todo_response(todos: List[Dict[str, Any]], action_performed: str) -> str:
        """Format the response message after todo operations."""
        if not todos:
            return f"操作完成: {action_performed}"

        # Show the latest todos
        recent_todos = todos[-10:] if len(todos) > 10 else todos

        output = [f"✅ 操作完成: {action_performed}\n"]

        if action_performed.startswith("Created"):
            output.append("📝 新创建的 Todo List:")
            for todo in recent_todos:
                priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(todo.get('priority', 'medium'), "⚪")
                status_icon = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}.get(todo.get('status', 'pending'),
                                                                                         "⏳")
                output.append(f"  {priority_icon} {status_icon} [{todo['id']}] {todo['content']}")

        elif action_performed.startswith("Updated") or action_performed.startswith("Marked"):
            output.append("📝 已更新的 Todo List:")
            for todo in recent_todos:
                priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(todo.get('priority', 'medium'), "⚪")
                status_icon = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}.get(todo.get('status', 'pending'),
                                                                                         "⏳")
                output.append(f"  {priority_icon} {status_icon} [{todo['id']}] {todo['content']}")

        total_todos = len(todos)
        pending_count = len([t for t in todos if t.get('status') == 'pending'])
        in_progress_count = len([t for t in todos if t.get('status') == 'in_progress'])
        completed_count = len([t for t in todos if t.get('status') == 'completed'])

        output.append(
            f"\n📊 当前摘要: 总计 {total_todos} 项 | 待处理 {pending_count} | 进行中 {in_progress_count} | 已完成 {completed_count}")

        return "\n".join(output)

    def resolve(self) -> ToolResult:
        """
        Create and manage a structured task list based on the action specified.
        """
        try:
            action = self.tool.action.lower()
            printer.print_text(f"执行待办事项操作: {action}", style="green")

            # Load existing todos
            data = self._load_todos()
            todos = data["todos"]

            if action == "create":
                if not self.tool.content:
                    return ToolResult(
                        success=False,
                        message="错误: 创建 Todo List 需要内容.",
                        content=None
                    )

                # Clear existing todos and create new ones
                new_todos = self._create_todo_list(self.tool.content)
                data["todos"] = new_todos

                if self._save_todos(data):
                    response = self._format_todo_response(new_todos, f"Created {len(new_todos)} new todo items")
                    return ToolResult(
                        success=True,
                        message="Todo List 创建成功.",
                        content=response
                    )
                else:
                    return ToolResult(
                        success=False,
                        message="保存 Todo List 失败.",
                        content=None
                    )

            elif action == "add_task":
                if not self.tool.content:
                    return ToolResult(
                        success=False,
                        message="错误: 添加任务需要内容.",
                        content=None
                    )

                new_todo = self._add_single_task(todos, self.tool.content)

                if self._save_todos(data):
                    response = self._format_todo_response([new_todo], f"Added new task: {new_todo['content']}")
                    return ToolResult(
                        success=True,
                        message="任务添加成功.",
                        content=response
                    )
                else:
                    return ToolResult(
                        success=False,
                        message="保存新任务失败.",
                        content=None
                    )

            elif action in ["update", "mark_progress", "mark_completed"]:
                if not self.tool.task_id:
                    return ToolResult(
                        success=False,
                        message=f"错误: 更新操作需要任务ID.",
                        content=None
                    )

                todo = self._find_todo_by_id(todos, self.tool.task_id)
                if not todo:
                    return ToolResult(
                        success=False,
                        message=f"错误: 未找到ID为 '{self.tool.task_id}' 的任务.",
                        content=None
                    )

                # Apply specific action
                if action == "mark_progress":
                    todo["status"] = "in_progress"
                    todo["updated_at"] = datetime.now().isoformat()
                    action_msg = f"标记任务为进行中: {todo['content']}"
                elif action == "mark_completed":
                    todo["status"] = "completed"
                    todo["updated_at"] = datetime.now().isoformat()
                    action_msg = f"标记任务为已完成: {todo['content']}"
                else:  # update
                    self._update_task(todo)
                    action_msg = f"更新了任务: {todo['content']}"

                if self._save_todos(data):
                    response = self._format_todo_response([todo], action_msg)
                    return ToolResult(
                        success=True,
                        message="任务更新成功.",
                        content=response
                    )
                else:
                    return ToolResult(
                        success=False,
                        message="保存任务更新失败.",
                        content=None
                    )

            else:
                return ToolResult(
                    success=False,
                    message=f"错误: 未知操作 '{action}'. 支持的操作: create, add_task, update, "
                            f"mark_progress, mark_completed.",
                    content=None
                )

        except Exception as e:
            printer.print_text(f"执行待办事项操作失败: {e}", style="red")
            return ToolResult(
                success=False,
                message=f"执行待办事项操作失败: {str(e)}",
                content=None
            )