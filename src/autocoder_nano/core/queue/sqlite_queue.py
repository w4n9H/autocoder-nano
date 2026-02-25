import sqlite3
import json
from typing import List, Dict, Any


def get_connection(queue_db_path):
    """ 获取数据库连接（设置 row_factory 为 Row 以便按列名访问）"""
    conn = sqlite3.connect(queue_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(queue_db_path):
    """初始化数据库表（若不存在则创建）"""
    with get_connection(queue_db_path) as conn:
        cursor = conn.cursor()
        # 用户消息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Agent 响应表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


# ==================== 用户消息操作 ====================

def insert_user_message(queue_db_path: str, client_id: str, message_id: str, conversation_id: str, content: str):
    """插入一条用户消息到 user_messages 表"""
    with get_connection(queue_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_messages (client_id, message_id, conversation_id, content) VALUES (?, ?, ?, ?)",
            (client_id, message_id, conversation_id, content)
        )
        conn.commit()


def fetch_pending_user_messages(queue_db_path: str) -> List[Dict[str, Any]]:
    """获取所有状态为 pending 的用户消息（按创建时间排序）"""
    with get_connection(queue_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, client_id, message_id, conversation_id, content 
            FROM user_messages WHERE status='pending' ORDER BY created_at"""
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def mark_user_message_done(queue_db_path: str, msg_id: int):
    """将指定 ID 的用户消息状态标记为 done"""
    with get_connection(queue_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_messages SET status='done' WHERE id=?", (msg_id,))
        conn.commit()


# ==================== Agent 响应操作 ====================

def insert_agent_response(queue_db_path: str, client_id: str, message_id: str, resp_type: str, content: Any):
    """
    插入一条 Agent 响应到 agent_responses 表
    content 可以是任意可 JSON 序列化的对象，内部会转换为 JSON 字符串存储
    """
    with get_connection(queue_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO agent_responses (client_id, message_id, type, content) VALUES (?, ?, ?, ?)",
            (client_id, message_id, resp_type, json.dumps(content, ensure_ascii=False))
        )
        conn.commit()


def fetch_pending_responses(queue_db_path: str) -> List[Dict[str, Any]]:
    """获取所有状态为 pending 的 Agent 响应（按创建时间排序）"""
    with get_connection(queue_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, client_id, message_id, type, content 
            FROM agent_responses WHERE status='pending' ORDER BY created_at"""
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            row_dict = dict(row)
            # content 字段是 JSON 字符串，解析回 Python 对象
            row_dict["content"] = json.loads(row_dict["content"])
            result.append(row_dict)
        return result


def mark_response_sent(queue_db_path: str, response_id: int):
    """将指定 ID 的 Agent 响应状态标记为 sent"""
    with get_connection(queue_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE agent_responses SET status='sent' WHERE id=?", (response_id,))
        conn.commit()


# 可选：清理已发送的消息（防止表无限增长）
def clean_sent_responses(queue_db_path: str, days: int = 7):
    """删除超过指定天数的已发送响应"""
    with get_connection(queue_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM agent_responses WHERE status='sent' AND created_at < datetime('now', ?)",
            (f'-{days} days',)
        )
        conn.commit()