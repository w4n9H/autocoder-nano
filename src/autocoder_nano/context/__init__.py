from autocoder_nano.context.notebook import NoteBook
from autocoder_nano.context.context_prune import ConversationsPruner, ContentPruner
from autocoder_nano.context.context_manager import (
    get_context_manager, get_context_manager_config, reset_context_manager, ContextManagerConfig
)


def record_memory(project_root: str, user_id: str, content: str, context: str = None) -> int:
    """
    记录重要记忆到笔记系统
    Args:
        project_root
        user_id: 身份标识，诸如
        content: 需要记录的核心信息
        context: 记忆上下文(可选)
    Returns:
        新建笔记的ID
    """
    note = NoteBook(project_root=project_root)
    return note.add_note(user_id=user_id, text=content, context=context)


def recall_memory(project_root: str, user_id: str, query: str, limit: int = 5) -> str:
    """
    从记忆中检索相关信息
    Args:
        project_root:
        user_id: Agent身份标识
        query: 你的问题
        limit: 返回结果数量
    Returns:
        相关笔记的DataFrame(id, content, created_at)
    """
    note = NoteBook(project_root=project_root)
    df = note.search_by_query(user_id=user_id, query=query, limit=limit)
    results = []
    if not df.empty:
        results = []
        for _, row in df.iterrows():
            # 格式化时间戳
            created_at = row['created_at'].strftime("%Y-%m-%d %H:%M:%S")
            results.append(f"{created_at}:\n{row['content']}\n{'-' * 40}")
    return "\n".join(results)


__all__ = ["record_memory", "recall_memory", "ConversationsPruner", "ContentPruner", "ContextManagerConfig",
           "get_context_manager", "get_context_manager_config",
           "reset_context_manager"]