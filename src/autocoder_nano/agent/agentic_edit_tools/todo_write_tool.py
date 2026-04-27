import json
import os
import typing
import uuid
from typing import Union, Optional, List, Dict, Any
from datetime import datetime

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.agent.agentic_edit_tools import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ToolResult, TodoWriteTool

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
        # self.args = args

    def _get_todo_file_path(self) -> str:
        source_dir = self.agent.args.source_dir or "."
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
            raise Exception(f"打开 Todos 文件失败: {e}")

    def _save_todos(self, data: Dict[str, Any]) -> bool:
        """Save todos to the session file."""
        try:
            todo_file = self._get_todo_file_path()
            data["updated_at"] = datetime.now().isoformat()

            with open(todo_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            raise Exception(f"保存 TodoList 失败: {e}")

    @staticmethod
    def _generate_todo_id() -> str:
        """Generate a unique ID for a todo item."""
        return str(uuid.uuid4())[:8]

    @staticmethod
    def _find_todo_by_id(todos: List[Dict[str, Any]], task_id: str) -> Optional[int]:
        """Find a todo item by ID."""
        for index, todo in enumerate(todos):
            if todo.get('id') == task_id:
                return index
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

    def _add_single_task(self, todos: List[Dict[str, Any]], content: str) -> List[Dict[str, Any]]:
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
        return todos

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

        output = [f"### 操作完成: {action_performed}\n"]
        if action_performed.startswith("Created"):
            output.append("#### 新创建的 Todo List")
        elif action_performed.startswith("Added"):
            output.append("#### 新添加的任务")
        elif action_performed.startswith("Updated") or action_performed.startswith("Marked"):
            output.append("#### 已更新的 Todo List")
        else:
            output.append("#### Todo List")

        output.append("")  # Empty line for spacing

        for todo in recent_todos:
            priority_icon = {"high": "[高]", "medium": "[中]", "low": "[低]"}.get(todo.get('priority', 'medium'), "[中]")
            status_icon = {
                "pending": "[待处理]", "in_progress": "[进行中]", "completed": "[已完成]"
            }.get(todo.get('status', 'pending'), "[待处理]")

            content_line = f"- {priority_icon} {status_icon} **[{todo['id']}]** {todo['content']}"
            output.append(content_line)
            if todo.get('notes'):
                output.append(f"  > {todo['notes']}")

        output.append("")
        output.append("---")

        total_todos = len(todos)
        pending_count = len([t for t in todos if t.get('status') == 'pending'])
        in_progress_count = len([t for t in todos if t.get('status') == 'in_progress'])
        completed_count = len([t for t in todos if t.get('status') == 'completed'])

        summary_line = (
            f"**📊 当前摘要**: 总计 **{total_todos}** 项 | "
            f"待处理 **{pending_count}** | "
            f"进行中 **{in_progress_count}** | "
            f"已完成 **{completed_count}**"
        )
        output.append(summary_line)
        return "\n".join(output)

    def resolve(self) -> ToolResult:
        """
        Create and manage a structured task list based on the action specified.
        """
        try:
            action = self.tool.action.lower()
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

                new_todos = self._add_single_task(todos, self.tool.content)
                data["todos"] = new_todos

                if self._save_todos(data):
                    response = self._format_todo_response(new_todos, f"Added new task: {self.tool.content}")
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

                todo_index = self._find_todo_by_id(todos, self.tool.task_id)
                if todo_index is None:
                    return ToolResult(
                        success=False,
                        message=f"错误: 未找到ID为 '{self.tool.task_id}' 的任务.",
                        content=None
                    )

                # Apply specific action
                old_todo = todos[todo_index]
                if action == "mark_progress":
                    old_todo["status"] = "in_progress"
                    old_todo["updated_at"] = datetime.now().isoformat()
                    action_msg = f"标记任务为进行中: {old_todo['content']}"
                elif action == "mark_completed":
                    old_todo["status"] = "completed"
                    old_todo["updated_at"] = datetime.now().isoformat()
                    action_msg = f"标记任务为已完成: {old_todo['content']}"
                else:  # update
                    self._update_task(old_todo)
                    action_msg = f"更新了任务: {old_todo['content']}"

                todos[todo_index] = old_todo
                data["todos"] = todos
                if self._save_todos(data):
                    response = self._format_todo_response(todos, action_msg)
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
            return ToolResult(
                success=False,
                message=f"执行待办事项操作失败: {str(e)}",
                content=None
            )

    def guide(self) -> str:
        doc = """
        ## todo_write（写入/更新待办事项）
        描述：
        - 请求为当前编码会话创建和管理结构化的任务列表。
        - 这有助于您跟踪进度，组织复杂任务，并向用户展现工作的细致程度。
        - 同时也能帮助用户了解任务进展及其需求的整体完成情况。
        - 请在处理复杂多步骤任务，用户明确要求时，或需要组织多项操作时主动使用此工具。
        参数：
        - action：（必填）要执行的操作：
            - create：创建新的待办事项列表
            - add_task：添加单个任务
            - update：更新现有任务
            - mark_progress：将任务标记为进行中
            - mark_completed：将任务标记为已完成
        - task_id：（可选）要更新的任务ID（update，mark_progress，mark_completed 操作时需要）
        - content：（可选）任务内容或描述（create、add_task 操作时需要）
        - priority：（可选）任务优先级：'high'（高）、'medium'（中）、'low'（低）（默认：'medium'）
        - status：（可选）任务状态：'pending'（待处理）、'in_progress'（进行中）、'completed'（已完成）（默认：'pending'）
        - notes：（可选）关于任务的附加说明或详细信息
        用法说明：
        <todo_write>
        <action>create</action>
        <content>
        <task>读取配置文件</task>
        <task>更新数据库设置</task>
        <task>测试连接</task>
        <task>部署更改</task>
        </content>
        <priority>high</priority>
        </todo_write>
        用法示例：
        场景一：为一个新的复杂任务创建待办事项列表
        目标：为复杂任务创建新的待办事项列表
        思维过程：用户提出了一个复杂的开发任务，这涉及到多个步骤和组件。我需要创建一个结构化的待办事项列表来跟踪这个多步骤任务的进度
        <todo_write>
        <action>create</action>
        <content>
        <task>分析现有代码库结构</task>
        <task>设计新功能架构</task>
        <task>实现核心功能</task>
        <task>添加全面测试</task>
        <task>更新文档</task>
        <task>审查和重构代码</task>
        </content>
        <priority>high</priority>
        </todo_write>
        场景二：标记任务为已完成
        目标：将特定任务标记为已完成
        思维过程：用户指示要标记一个特定任务为已完成。我需要使用mark_completed操作，这需要提供任务的ID。
        <todo_write>
        <action>mark_completed</action>
        <task_id>task_123</task_id>
        <notes>成功实现，测试覆盖率达到95%</notes>
        </todo_write>
        """
        return doc