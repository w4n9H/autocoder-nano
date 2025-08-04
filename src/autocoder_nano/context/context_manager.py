import threading
import time
from dataclasses import dataclass, asdict
from importlib import resources
from typing import List, Dict, Any, Optional, Callable

from tokenizers import Tokenizer

from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


@dataclass
class Message:
    role: str
    content: str
    ts: float = 0.0
    id: Optional[str] = None
    tk: int = 0

    def __post_init__(self):
        if self.ts == 0.0:
            self.ts = time.time()
        if self.id is None:
            self.id = str(hash((self.role, self.content, self.ts)))


class EventBus:
    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = {}

    def on(self, event: str, func: Callable):
        self._hooks.setdefault(event, []).append(func)

    def emit(self, event: str, *args, **kwargs):
        for f in self._hooks.get(event, []):
            try:
                f(*args, **kwargs)
            except Exception as e:
                printer.print_text(f"Hook error: {e}", style="red")


class ContextManager:
    def __init__(self, max_context_tokens: int = 4096, token_cost_config: dict = None):
        self.max_context_tokens = max_context_tokens  # 添加上下文长度限制
        self.token_cost_config = token_cost_config  # 每token成本 {"input": 0.001, "output": 0.002}

        self.event = EventBus()
        try:
            tokenizer_path = resources.files("autocoder_nano").joinpath("data/tokenizer.json").__str__()
        except FileNotFoundError:
            tokenizer_path = None
        self.enc = Tokenizer.from_file(tokenizer_path)

        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._cur_session: Optional[str] = None
        self._lock = threading.RLock()

    # ---------- 会话管理 ----------
    def create_session(self, session_id: str):
        """ 创建会话 """
        with self._lock:
            if session_id in self._sessions:
                raise ValueError(f"Session {session_id} already exists")
            self._sessions[session_id] = {
                "history": [],
                "current": [],
                "tokens": {"input": 0, "output": 0}
            }
            self._cur_session = session_id
            self.event.emit("session_created", session_id)

    def switch_session(self, session_id: str) -> bool:
        """ 切换会话 """
        with self._lock:
            if session_id not in self._sessions:
                printer.print_text(f"Session {session_id} not found", style="yellow")
                return False
            self._cur_session = session_id
            self.event.emit("session_switched", session_id)
            return True

    # def archive_session(self, session_id: str):
    #     """ 会话归档 """
    #     with self._lock:
    #         data = self._sessions.pop(session_id, None)
    #         if data:
    #             # 归档
    #             # self.storage.save(session_id, self._serialize(data))
    #             self.event.emit("session_archived", session_id)

    # def load_session(self, session_id: str):
    #     with self._lock:
    #         raw = self.storage.load(session_id)
    #         if not raw:
    #             raise FileNotFoundError(session_id)
    #         self._sessions[session_id] = self._deserialize(raw)
    #         self._cur_session = session_id
    #         self.event.emit("session_loaded", session_id)

    # ---------- 消息操作 ----------
    def add_conversation(self, role: str, content: str):
        with self._lock:
            msg = Message(role, content, tk=self._count_tokens(content))
            sess = self._ensure_session()
            sess["current"].append(msg)
            # self._update_index(sess, msg)
            # self._auto_compress_if_needed(sess)

    def get_conversation(self, limit: Optional[int] = None) -> List[Message]:
        with self._lock:
            sess = self._ensure_session()
            msgs = sess["current"]
            if limit:
                msgs = msgs[-limit:]
            return msgs

    # ---------- 压缩与摘要 ----------
    # def compress(self, budget: int) -> int:
    #     """
    #     简单策略：保留最后 budget tokens，其余用 LLM 摘要
    #     返回节省的 token 数
    #     """
    #     with self._lock:
    #         sess = self._ensure_session()
    #         msgs = sess["messages"]
    #         if not msgs:
    #             return 0
    #         total = sum(self._count_tokens(m.content) for m in msgs)
    #         if total <= budget:
    #             return 0
    #
    #         keep, drop = [], []
    #         acc = 0
    #         for m in reversed(msgs):
    #             tk = self._count_tokens(m.content)
    #             if acc + tk <= budget:
    #                 keep.append(m)
    #                 acc += tk
    #             else:
    #                 drop.append(m)
    #
    #         summary_content = self._llm_summarize([m.content for m in reversed(drop)])
    #         summary_msg = Message("system", f"[Summary] {summary_content}")
    #         sess["messages"] = [summary_msg] + list(reversed(keep))
    #         self._rebuild_index(sess)
    #         saved = total - self._count_tokens(summary_content) - acc
    #         self.event.emit("context_compressed", saved)
    #         return saved

    # ---------- 内部工具 ----------
    def _ensure_session(self) -> Dict[str, Any]:
        if self._cur_session is None or self._cur_session not in self._sessions:
            raise RuntimeError("No active session")
        return self._sessions[self._cur_session]

    def _count_tokens(self, text: str) -> int:
        return len(self.enc.encode(text).ids)

    def _calculate_cost(self, tok_in, tok_out):
        """ 计算当前会话成本 """
        input_cost = tok_in * self.token_cost_config["input"]
        output_cost = tok_out * self.token_cost_config["output"]
        return round(input_cost + output_cost, 2)

    # def _update_index(self, sess: Dict[str, Any], msg: Message):
    #     emb = self.embed.encode([msg.content]).astype(np.float32)
    #     sess["index"].add(emb)
    #     sess["embeddings"] = np.vstack([sess["embeddings"], emb])
    #
    # def _rebuild_index(self, sess: Dict[str, Any]):
    #     dim = self.embed.get_sentence_embedding_dimension()
    #     sess["index"] = faiss.IndexFlatL2(dim)
    #     embs = self.embed.encode([m.content for m in sess["messages"]]).astype(np.float32)
    #     sess["index"].add(embs)
    #     sess["embeddings"] = embs

    # def _auto_compress_if_needed(self, sess: Dict[str, Any]):
    #     total = sum(self._count_tokens(m.content) for m in sess["messages"])
    #     if total > 0.9 * self.max_context_tokens:
    #         budget = int(0.5 * self.max_context_tokens)
    #         self.compress(budget)

    # def _llm_summarize(self, texts: List[str]) -> str:
    #     # 这里简化：直接拼接后截断，真实场景可调用 OpenAI
    #     concat = " ".join(texts)[:500]
    #     return f"Summary of {len(texts)} messages: {concat}..."
    #
    # def _serialize(self, sess: Dict[str, Any]) -> Dict[str, Any]:
    #     return {"messages": [asdict(m) for m in sess["messages"]]}

    # ---------- 调试 ----------
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            sess = self._ensure_session()
            tok_in = sum(m.tk for m in sess["current"] if m.role in ['user', 'system'])
            tok_out = sum(m.tk for m in sess["current"] if m.role in ['assistant'])
            # total = sum(m.tk for m in sess["current"])
            return {
                "session": self._cur_session,
                "tok_in": tok_in,
                "tok_out": tok_out,
                "tok_total": tok_in + tok_out,
                "max_tokens": self.max_context_tokens,
                "cost": self._calculate_cost(tok_in, tok_out),
                "current_conversations_total": len(sess["current"]),
                "history_conversations_total": len(sess["history"])
            }


# ---------- 使用示例 ----------
if __name__ == "__main__":
    cm = ContextManager(max_context_tokens=1200, token_cost_config={"input": 0.001, "output": 0.002})
    cm.create_session("user-42")
    for i in range(20):
        cm.add_conversation("user", f"Hello {i}")
        cm.add_conversation("assistant", f"Reply {i}")
    import pprint
    pprint.pprint(cm.stats())




# class ContextManager:
#     def __init__(self, max_context_tokens, token_cost_config):
#         self.max_context_tokens = max_context_tokens  # 添加上下文长度限制
#         self.token_cost_config = token_cost_config  # 每token成本 {"input": 0.001, "output": 0.002}
#
#         self.history_conversation = []
#         self.current_conversations = []
#
#         self.sessions = {}
#         self.current_session = None
#         self.archives = {}
#
#         self.context_status = {
#             "input_tokens": 0,
#             "output_tokens": 0
#         }
#
#     def is_context_full(self, v: float = 0.9):  # 90%阈值警告
#         """检查是否接近上下文长度上限"""
#         used_tokens = self.context_status["input_tokens"] + self.context_status["output_tokens"]
#         return used_tokens > self.max_context_tokens * v
#
#     def compress_context(self, compression_ratio=0.5):
#         """压缩历史对话"""
#         # 实现逻辑：保留最近对话，摘要早期对话
#         # 返回被移除的对话数量和节省的token数
#
#     def create_new_session(self, session_id):
#         """创建新会话"""
#         self.sessions[session_id] = {
#             "history": [],
#             "current": [],
#             "tokens": {"input": 0, "output": 0}
#         }
#         self.current_session = session_id
#
#     def switch_session(self, session_id):
#         """切换会话"""
#         if session_id in self.sessions:
#             self.current_session = session_id
#
#     def archive_session(self, session_id):
#         """归档会话"""
#         archived = self.sessions.pop(session_id, None)
#         if archived:
#             self.archives[session_id] = archived
#
#     def calculate_cost(self):
#         """计算当前会话成本"""
#         input_cost = self.context_status["input_tokens"] * self.token_cost_config["input"]
#         output_cost = self.context_status["output_tokens"] * self.token_cost_config["output"]
#         return round(input_cost + output_cost, 2)
#
#     def generate_summary(self, model="gpt-3.5-turbo"):
#         """生成对话摘要"""
#         # 实现逻辑：将历史对话发送给摘要模型
#         # 返回摘要内容和消耗的token数
#         return ""
#
#     def auto_summarize(self, threshold=1024):
#         """自动摘要当历史对话过长时"""
#         if len(self.history_conversation) > threshold:
#             summary = self.generate_summary()
#             self.history_conversation = [summary]  # 用摘要替换详细历史
#
#     def optimize_context(self):
#         """优化上下文结构"""
#         # 1. 移除空消息
#         # 2. 合并连续同角色消息
#         # 3. 移除冗余信息
#         # 返回优化后节省的token数
#
#     def add_current_conversations(self, role, content):
#         self.current_conversations.append({"role": role, "content": content})
#
#     def accumulate_input_token_usage(self, input_tokens: int):
#         self.context_status["input_tokens"] += input_tokens
#
#     def accumulate_output_token_usage(self, output_tokens: int):
#         self.context_status["output_tokens"] += output_tokens
#
#     def get_status(self):
#         return {
#             "history_conversation_total": len(self.history_conversation),
#             "current_conversations_total": len(self.current_conversations)
#         } | self.context_status
#
#     def save_to_file(self, file_path):
#         """保存上下文到文件"""
#         with open(file_path, 'w') as f:
#             json.dump({
#                 "history": self.history_conversation,
#                 "current": self.current_conversations,
#                 "status": self.context_status
#             }, f)
#
#     def load_from_file(self, file_path):
#         """从文件加载上下文"""
#         with open(file_path, 'r') as f:
#             data = json.load(f)
#             self.history_conversation = data["history"]
#             self.current_conversations = data["current"]
#             self.context_status = data["status"]