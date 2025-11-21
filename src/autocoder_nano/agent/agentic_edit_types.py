from typing import List, Optional, Dict, Type, Any

from pydantic import BaseModel, SkipValidation


class FileChangeEntry(BaseModel):
    """ 文件变更条目，用于记录文件的变更信息 """
    type: str  # 'added' 或 'modified'
    diffs: List[str] = []  # 使用 replace_in_file 时，记录 diff 内容
    content: Optional[str] = None  # 使用 write_to_file 时，记录文件内容


class AgenticEditRequest(BaseModel):
    user_input: str


# 工具的基本Pydantic模型
class BaseTool(BaseModel):
    """ 代理工具的基类，所有工具类都应继承此类 """
    pass


class ExecuteCommandTool(BaseTool):
    command: str
    requires_approval: bool


class RecordMemoryTool(BaseTool):
    content: str


class RecallMemoryTool(BaseTool):
    query: str


class ACModWriteTool(BaseTool):
    content: str


class ACModSearchTool(BaseTool):
    query: str


class ReadFileTool(BaseTool):
    path: str


class WriteToFileTool(BaseTool):
    path: str
    content: str


class ReplaceInFileTool(BaseTool):
    path: str
    diff: str


class SearchFilesTool(BaseTool):
    path: str
    regex: str
    file_pattern: Optional[str] = None


class ListFilesTool(BaseTool):
    path: str
    recursive: Optional[bool] = False


class WebSearchTool(BaseTool):
    query: str


class TodoReadTool(BaseTool):
    """
    Tool for reading the current todolist.
    Takes no parameters.
    """
    pass  # No parameters needed


class TodoWriteTool(BaseTool):
    """
    Tool for creating and managing a structured task list.
    """
    action: str  # 'create', 'update', 'mark_progress', 'mark_completed', 'add_task'
    task_id: Optional[str] = None  # Task ID for update/mark operations
    content: Optional[str] = None  # Task content for create/add operations
    priority: Optional[str] = None  # 'high', 'medium', 'low'
    status: Optional[str] = None  # 'pending', 'in_progress', 'completed'
    notes: Optional[str] = None  # Additional notes for the task


class ListCodeDefinitionNamesTool(BaseTool):
    path: str


class AskFollowupQuestionTool(BaseTool):
    question: str
    options: Optional[List[str]] = None


class AttemptCompletionTool(BaseTool):
    result: str
    command: Optional[str] = None


class PlanModeRespondTool(BaseTool):
    response: str
    options: Optional[List[str]] = None


class UseRAGTool(BaseTool):
    query: str


class ListPackageInfoTool(BaseTool):
    path: str  # 源码包目录，相对路径或绝对路径


class CallSubAgentTool(BaseTool):
    """调用子代理处理专项任务"""
    agent_type: str    # 子代理类型 (coding/research)
    task: str    # 子代理处理的具体任务
    context: Optional[str] = None    # 传递给子代理的上下文信息


class CallCusAgentTool(BaseTool):
    """调用自定义代理处理专项任务"""
    task: str  # 子代理处理的具体任务
    prompt: str  # 系统提示词
    tools: Optional[List[str]] = None


class LLMOutputEvent(BaseModel):
    """Represents plain text output from the LLM."""
    text: str


class LLMThinkingEvent(BaseModel):
    """Represents text within <thinking> tags from the LLM."""
    text: str


class ToolCallEvent(BaseModel):
    """Represents the LLM deciding to call a tool."""
    tool: SkipValidation[BaseTool]  # Use SkipValidation as BaseTool itself is complex
    tool_xml: str


# Result class used by Tool Resolvers
class ToolResult(BaseModel):
    success: bool
    message: str
    content: Any = None  # Can store file content, command output, etc.


class ToolResultEvent(BaseModel):
    """Represents the result of executing a tool."""
    tool_name: str
    result: ToolResult


class TokenUsageEvent(BaseModel):
    """Represents the result of executing a tool."""
    usage: Any


class PlanModeRespondEvent(BaseModel):
    """Represents the LLM attempting to complete the task."""
    completion: SkipValidation[PlanModeRespondTool]  # Skip validation
    completion_xml: str


class CompletionEvent(BaseModel):
    """Represents the LLM attempting to complete the task."""
    completion: SkipValidation[AttemptCompletionTool]  # Skip validation
    completion_xml: str


class ErrorEvent(BaseModel):
    """Represents an error during the process."""
    message: str


class WindowLengthChangeEvent(BaseModel):
    """Represents the token usage in the conversation window."""
    tokens_used: int


class AgenticEditConversationConfig(BaseModel):
    conversation_name: Optional[str] = "current"
    conversation_id: Optional[str] = None
    action: Optional[str] = None
    query: Optional[str] = None
    pull_request: bool = False


# Mapping from tool tag names to Pydantic models
TOOL_MODEL_MAP: Dict[str, Type[BaseTool]] = {
    "execute_command": ExecuteCommandTool,
    "read_file": ReadFileTool,
    "write_to_file": WriteToFileTool,
    "replace_in_file": ReplaceInFileTool,
    "search_files": SearchFilesTool,
    "list_files": ListFilesTool,
    "ask_followup_question": AskFollowupQuestionTool,
    "attempt_completion": AttemptCompletionTool,
    "web_search": WebSearchTool,
    "todo_read": TodoReadTool,
    "todo_write": TodoWriteTool,
    "ac_mod_write": ACModWriteTool,
    "ac_mod_search": ACModSearchTool,
    "call_subagent": CallSubAgentTool,
    "use_rag_tool": UseRAGTool
}