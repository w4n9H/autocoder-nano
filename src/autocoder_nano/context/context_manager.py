import contextlib
import json
import os
import threading
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Union, Generator

from autocoder_nano.context.exceptions import (
    ContextManagerError, ConversationNotFoundError, MessageNotFoundError, ConcurrencyError
)
from autocoder_nano.context.models import Conversation, ConversationMessage
from autocoder_nano.context.file_locker import FileLocker
from autocoder_nano.context.cache import MemoryCache, CacheManager
from autocoder_nano.context.search import TextSearcher, FilterManager
from autocoder_nano.context.storage import FileStorage, IndexManager
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


class ContextManagerConfig:
    """对话管理器配置类"""

    storage_path: str = "./.auto-coder/context"
    max_cache_size: int = 100
    cache_ttl: float = 300.0
    lock_timeout: float = 10.0
    backup_enabled: bool = True
    backup_interval: float = 3600.0
    max_backups: int = 10
    enable_compression: bool = False
    log_level: str = "INFO"

    def __post_init__(self):
        """配置验证"""
        self._validate()

    def _validate(self):
        """验证配置数据"""
        # 验证存储路径
        if not self.storage_path or not isinstance(self.storage_path, str):
            raise ValueError("存储路径不能为空")

        # 验证缓存大小
        if not isinstance(self.max_cache_size, int) or self.max_cache_size <= 0:
            raise ValueError("缓存大小必须是正整数")

        # 验证缓存TTL
        if not isinstance(self.cache_ttl, (int, float)) or self.cache_ttl <= 0:
            raise ValueError("缓存TTL必须是正数")

        # 验证锁超时
        if not isinstance(self.lock_timeout, (int, float)) or self.lock_timeout <= 0:
            raise ValueError("锁超时时间必须是正数")

        # 验证备份间隔
        if not isinstance(self.backup_interval, (int, float)) or self.backup_interval <= 0:
            raise ValueError("备份间隔必须是正数")

        # 验证最大备份数
        if not isinstance(self.max_backups, int) or self.max_backups <= 0:
            raise ValueError("最大备份数必须是正整数")

        # 验证日志级别
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level not in valid_levels:
            raise ValueError(f"无效的日志级别: {self.log_level}，有效级别: {valid_levels}")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "storage_path": self.storage_path,
            "max_cache_size": self.max_cache_size,
            "cache_ttl": self.cache_ttl,
            "lock_timeout": self.lock_timeout,
            "backup_enabled": self.backup_enabled,
            "backup_interval": self.backup_interval,
            "max_backups": self.max_backups,
            "enable_compression": self.enable_compression,
            "log_level": self.log_level
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextManagerConfig":
        """从字典创建配置"""
        # 创建默认配置
        config = cls()
        # 更新配置字段
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        # 重新验证
        config._validate()
        return config

    def save_to_file(self, file_path: str):
        """保存配置到文件"""
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_from_file(cls, file_path: str) -> "ContextManagerConfig":
        """从文件加载配置"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"配置文件不存在: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {e}")

    def copy(self) -> "ContextManagerConfig":
        """创建配置的深拷贝"""
        return ContextManagerConfig.from_dict(self.to_dict())

    def update(self, **kwargs):
        """更新配置字段"""
        # 先备份当前配置
        backup_values = {}
        for key in kwargs.keys():
            if hasattr(self, key):
                backup_values[key] = getattr(self, key)
            else:
                raise AttributeError(f"配置类没有属性: {key}")

        # 尝试更新
        try:
            for key, value in kwargs.items():
                setattr(self, key, value)
            # 重新验证
            self._validate()
        except Exception:
            # 如果验证失败，恢复原值
            for key, value in backup_values.items():
                setattr(self, key, value)
            raise

    def __repr__(self) -> str:
        """字符串表示"""
        return (f"ConversationManagerConfig("
                f"storage_path='{self.storage_path}', "
                f"max_cache_size={self.max_cache_size}, "
                f"cache_ttl={self.cache_ttl}, "
                f"lock_timeout={self.lock_timeout}, "
                f"backup_enabled={self.backup_enabled}, "
                f"log_level='{self.log_level}')")

    def __eq__(self, other) -> bool:
        """相等性比较"""
        if not isinstance(other, ContextManagerConfig):
            return False
        return self.to_dict() == other.to_dict()


class ContextManager:
    def __init__(self, config: Optional[ContextManagerConfig] = None):
        self.config = config or ContextManagerConfig()

        # 初始化组件
        self._init_storage()
        self._init_cache()
        self._init_search()
        self._init_locks()

        # 统计信息跟踪
        self._stats = {
            'conversations_created': 0,
            'conversations_loaded': 0,
            'messages_added': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }

    def _init_storage(self):
        """初始化存储组件"""
        # 确保存储目录存在
        storage_path = Path(self.config.storage_path)
        storage_path.mkdir(parents=True, exist_ok=True)

        # 初始化存储后端
        self.storage = FileStorage(str(storage_path / "conversations"))

        # 初始化索引管理器
        self.index_manager = IndexManager(str(storage_path / "index"))

    def _init_cache(self):
        """初始化缓存系统"""
        # 为对话和消息使用基于字典的简单缓存
        self.conversation_cache = MemoryCache(
            max_size=self.config.max_cache_size,
            default_ttl=self.config.cache_ttl
        )
        self.message_cache = MemoryCache(
            max_size=self.config.max_cache_size * 10,  # 消息数量通常比对话多
            default_ttl=self.config.cache_ttl
        )

    def _init_search(self):
        """Initialize search and filtering systems."""
        self.text_searcher = TextSearcher()
        self.filter_manager = FilterManager()

    def _init_locks(self):
        """初始化 locks"""
        lock_dir = Path(self.config.storage_path) / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        self._lock_dir = str(lock_dir)

    def _get_conversation_lock_file(self, conversation_id: str) -> str:
        """获取对话的锁文件路径"""
        return os.path.join(self._lock_dir, f"{conversation_id}.lock")

    @contextlib.contextmanager
    def _conversation_lock(self, conversation_id: str, exclusive: bool = True) -> Generator[None, None, None]:
        """
        为对话操作获取锁
        Args:
            conversation_id: 需要加锁的对话ID
            exclusive: 是否获取独占（写）锁
        """
        lock_file = self._get_conversation_lock_file(conversation_id)
        locker = FileLocker(lock_file, timeout=self.config.lock_timeout)
        try:
            if exclusive:
                with locker.acquire_write_lock():
                    yield
            else:
                with locker.acquire_read_lock():
                    yield
        except (ConversationNotFoundError, MessageNotFoundError):
            # Re-raise these exceptions as-is (don't wrap in ConcurrencyError)
            raise
        except Exception as e:
            raise ConcurrencyError(f"Failed to acquire lock for conversation {conversation_id}: {e}")

    def create_conversation(
            self, name: str, description: Optional[str] = None, initial_messages: Optional[List[Dict[str, Any]]] = None,
            metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        创建新对话
        Args:
            name: 对话名称
            description: 可选描述信息
            initial_messages: 初始消息列表（可选）
            metadata: 元数据字典（可选）
        Returns:
            所创建对话的ID
        Raises:
            ConversationManagerError: 当对话创建失败时抛出此异常
        """
        try:
            conversation = Conversation(name=name, description=description, metadata=metadata or {})
            if initial_messages:
                for msg_data in initial_messages:
                    message = ConversationMessage(
                        role=msg_data['role'],
                        content=msg_data['content'],
                        metadata=msg_data.get('metadata', {})
                    )
                    conversation.add_message(message)
            # Save conversation with locking
            with self._conversation_lock(conversation.conversation_id):
                # Save to storage
                self.storage.save_conversation(conversation.to_dict())
                # Update index
                self.index_manager.add_conversation(conversation.to_dict())
                # Cache the conversation
                self.conversation_cache.set(conversation.conversation_id, conversation.to_dict())
            # Update statistics
            self._stats['conversations_created'] += 1
            return conversation.conversation_id
        except Exception as e:
            raise ContextManagerError(f"创建会话失败: {e}")

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        通过ID获取对话
        Args:
            conversation_id: 对话的ID
        Returns:
            对话数据，如果未找到则返回None
        """
        try:
            # Try cache first
            cached_conversation = self.conversation_cache.get(conversation_id)
            if cached_conversation:
                self._stats['cache_hits'] += 1
                return cached_conversation

            self._stats['cache_misses'] += 1

            # Load from storage with read lock
            with self._conversation_lock(conversation_id, exclusive=False):
                conversation_data = self.storage.load_conversation(conversation_id)

                if conversation_data:
                    # Cache the loaded conversation
                    self.conversation_cache.set(conversation_id, conversation_data)
                    self._stats['conversations_loaded'] += 1
                    return conversation_data

                return None

        except Exception as e:
            raise ContextManagerError(f"Failed to get conversation {conversation_id}: {e}")

    def update_conversation(self, conversation_id: str, name: Optional[str] = None, description: Optional[str] = None,
                            metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Update conversation metadata.
        Args:
            conversation_id: ID of the conversation to update
            name: New name (optional)
            description: New description (optional)
            metadata: New metadata (optional)
        Returns:
            True if update was successful
        Raises:
            ConversationNotFoundError: If conversation doesn't exist
        """
        try:
            with self._conversation_lock(conversation_id):
                # Load current conversation
                conversation_data = self.storage.load_conversation(conversation_id)
                if not conversation_data:
                    raise ConversationNotFoundError(conversation_id)

                # Create conversation object and update fields
                conversation = Conversation.from_dict(conversation_data)

                if name is not None:
                    conversation.name = name
                if description is not None:
                    conversation.description = description
                if metadata is not None:
                    conversation.metadata.update(metadata)

                conversation.updated_at = time.time()

                # Save updated conversation
                updated_data = conversation.to_dict()
                self.storage.save_conversation(updated_data)
                # Update index
                self.index_manager.update_conversation(updated_data)
                # Update cache
                self.conversation_cache.set(conversation_id, updated_data)

                return True

        except ConversationNotFoundError:
            raise
        except Exception as e:
            raise ContextManagerError(f"Failed to update conversation {conversation_id}: {e}")

    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation.
        Args:
            conversation_id: ID of the conversation to delete
        Returns:
            True if deletion was successful
        """
        try:
            with self._conversation_lock(conversation_id):
                # Check if conversation exists
                if not self.storage.conversation_exists(conversation_id):
                    return False
                # Delete from storage
                self.storage.delete_conversation(conversation_id)
                # Remove from index
                self.index_manager.remove_conversation(conversation_id)
                # Remove from cache
                self.conversation_cache.delete(conversation_id)
                return True

        except Exception as e:
            raise ContextManagerError(f"删除会话 {conversation_id} 失败: {e}")

    def search_conversations(
            self, query: str, search_in_messages: bool = True, filters: Optional[Dict[str, Any]] = None,
            max_results: Optional[int] = None, min_score: float = 0.0) -> List[Dict[str, Any]]:
        """
        Search conversations.
        Args:
            query: Search query
            search_in_messages: Whether to search in message content
            filters: Optional filter criteria
            max_results: Maximum number of results
            min_score: Minimum relevance score
        Returns:
            List of matching conversations with scores
        """
        try:
            # Get all conversations
            conversations = self.index_manager.list_conversations()

            # Apply filters first if provided
            if filters:
                conversations = self.filter_manager.apply_filters(conversations, filters)

            # If search_in_messages is True, load full conversation data
            if search_in_messages:
                full_conversations = []
                for conv in conversations:
                    conv_id = conv.get('conversation_id')
                    if conv_id:
                        full_conv = self.get_conversation(conv_id)
                        if full_conv:
                            full_conversations.append(full_conv)
                conversations = full_conversations

            # Perform text search
            results = self.text_searcher.search_conversations(
                query, conversations, max_results, min_score
            )

            return [{'conversation': conv, 'score': score} for conv, score in results]

        except Exception as e:
            raise ContextManagerError(f"Failed to search conversations: {e}")

    def search_messages(
            self, conversation_id: str, query: str, filters: Optional[Dict[str, Any]] = None,
            max_results: Optional[int] = None, min_score: float = 0.0) -> List[Dict[str, Any]]:
        """
        Search messages in a conversation.
        Args:
            conversation_id: ID of the conversation
            query: Search query
            filters: Optional filter criteria
            max_results: Maximum number of results
            min_score: Minimum relevance score
        Returns:
            List of matching messages with scores
        filters 示例:
        filters = {
            "filters": [
                {
                    "field": "role",
                    "operator": "in",
                    "value": ["assistant"]  # 角色在指定列表中
                },
                {
                    "field": "timestamp",
                    "operator": "gte",  # 大于等于
                    "value": 1717000000  # 时间戳（Unix时间，秒级）
                }
            ],
            "operator": "and"  # 逻辑运算符："and"（与）或 "or"（或）
        }
        支持的运算符（operator）:
        eq 等于(适用所有类型)
        ne 不等于(适用所有类型)
        gt/gte 大于/大于等于(适用数字、时间戳)
        lt/lte 小于/小于等于(数字、时间戳)
        contains 包含子串(字符串)
        in 在列表中(所有类型)
        regex 正则匹配(字符串)
        """
        try:
            # Get conversation messages
            messages = self.get_messages(conversation_id)

            # Apply filters if provided
            if filters:
                messages = self.filter_manager.apply_filters(messages, filters)

            # Perform text search
            results = self.text_searcher.search_messages(
                query, messages, max_results, min_score
            )

            return [{'message': msg, 'score': score} for msg, score in results]

        except Exception as e:
            raise ContextManagerError(f"Failed to search messages: {e}")

    def list_conversations(self, limit: Optional[int] = None, offset: int = 0, filters: Optional[Dict[str, Any]] = None,
                           sort_by: str = 'updated_at', sort_desc: bool = True) -> List[Dict[str, Any]]:
        """
        List conversations with optional filtering and sorting.
        Args:
            limit: Maximum number of conversations to return
            offset: Number of conversations to skip
            filters: Optional filter criteria
            sort_by: Field to sort by
            sort_desc: Whether to sort in descending order
        Returns:
            List of conversation data
        """
        try:
            # Convert sort_desc boolean to sort_order string
            sort_order = 'desc' if sort_desc else 'asc'
            # Get conversations from index with sorting and pagination
            conversations = self.index_manager.list_conversations(
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                sort_order=sort_order
            )
            # Apply filters if provided
            if filters:
                conversations = self.filter_manager.apply_filters(conversations, filters)

            return conversations

        except Exception as e:
            raise ContextManagerError(f"Failed to list conversations: {e}")

    def append_message(self, conversation_id: str, role: str, content: Union[str, Dict[str, Any], List[Any]],
                       metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Append a message to a conversation.
        Args:
            conversation_id: ID of the conversation
            role: Role of the message sender
            content: Message content
            metadata: Optional message metadata
        Returns:
            ID of the added message
        Raises:
            ConversationNotFoundError: If conversation doesn't exist
        """
        try:
            # Create message object
            message = ConversationMessage(
                role=role,
                content=content,
                metadata=metadata or {}
            )

            with self._conversation_lock(conversation_id):
                # Load conversation
                conversation_data = self.storage.load_conversation(conversation_id)
                if not conversation_data:
                    raise ConversationNotFoundError(conversation_id)

                # Add message to conversation
                conversation = Conversation.from_dict(conversation_data)
                conversation.add_message(message)

                # Save updated conversation
                updated_data = conversation.to_dict()
                self.storage.save_conversation(updated_data)

                # Update index
                self.index_manager.update_conversation(updated_data)

                # Update cache
                self.conversation_cache.set(conversation_id, updated_data)
                self.message_cache.set(f"{conversation_id}:{message.message_id}", message.to_dict())

            # Update statistics
            self._stats['messages_added'] += 1

            return message.message_id

        except ConversationNotFoundError:
            raise
        except Exception as e:
            raise ContextManagerError(f"Failed to append message to conversation {conversation_id}: {e}")

    def append_messages(self, conversation_id: str, messages: List[Dict[str, Any]]) -> List[str]:
        """
        Append multiple messages to a conversation.
        Args:
            conversation_id: ID of the conversation
            messages: List of message data dictionaries
        Returns:
            List of message IDs
        """
        message_ids = []
        for msg_data in messages:
            message_id = self.append_message(
                conversation_id,
                msg_data['role'],
                msg_data['content'],
                msg_data.get('metadata')
            )
            message_ids.append(message_id)
        return message_ids

    def get_messages(self, conversation_id: str, limit: Optional[int] = None, offset: int = 0,
                     message_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Get messages from a conversation.
        Args:
            conversation_id: ID of the conversation
            limit: Maximum number of messages to return
            offset: Number of messages to skip
            message_ids: Optional list of specific message IDs
        Returns:
            List of message data
        """
        try:
            # Get conversation
            conversation_data = self.get_conversation(conversation_id)
            if not conversation_data:
                raise ConversationNotFoundError(conversation_id)
            messages = conversation_data.get('messages', [])
            # Filter by message IDs if provided
            if message_ids:
                id_set = set(message_ids)
                messages = [msg for msg in messages if msg.get('message_id') in id_set]
            # Apply pagination
            end_idx = offset + limit if limit else None
            return messages[offset:end_idx]

        except ConversationNotFoundError:
            raise
        except Exception as e:
            raise ContextManagerError(f"Failed to get messages from conversation {conversation_id}: {e}")

    def get_message(self, conversation_id: str, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific message.
        Args:
            conversation_id: ID of the conversation
            message_id: ID of the message
        Returns:
            Message data or None if not found
        """
        try:
            # Try cache first
            cached_message = self.message_cache.get(f"{conversation_id}:{message_id}")
            if cached_message:
                return cached_message
            # Get from conversation
            conversation_data = self.get_conversation(conversation_id)
            if not conversation_data:
                return None
            # Find message
            for message in conversation_data.get('messages', []):
                if message.get('message_id') == message_id:
                    # Cache the message
                    self.message_cache.set(f"{conversation_id}:{message_id}", message)
                    return message
            return None
        except Exception as e:
            raise ContextManagerError(f"Failed to get message {message_id}: {e}")

    def update_message(self, conversation_id: str, message_id: str,
                       content: Optional[Union[str, Dict[str, Any], List[Any]]] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Update a message.
        Args:
            conversation_id: ID of the conversation
            message_id: ID of the message to update
            content: New content (optional)
            metadata: New metadata (optional)
        Returns:
            True if update was successful
        """
        try:
            with self._conversation_lock(conversation_id):
                # Load conversation
                conversation_data = self.storage.load_conversation(conversation_id)
                if not conversation_data:
                    raise ConversationNotFoundError(conversation_id)
                conversation = Conversation.from_dict(conversation_data)

                # Find and update message
                for i, message_data in enumerate(conversation.messages):
                    msg = ConversationMessage.from_dict(message_data)
                    if msg.message_id == message_id:
                        # Update message fields
                        if content is not None:
                            msg.content = content
                        if metadata is not None:
                            msg.metadata.update(metadata)

                        # Update timestamp
                        msg.timestamp = time.time()

                        # Replace in conversation
                        conversation.messages[i] = msg.to_dict()
                        conversation.updated_at = time.time()

                        # Save updated conversation
                        updated_data = conversation.to_dict()
                        self.storage.save_conversation(updated_data)

                        # Update index
                        self.index_manager.update_conversation(updated_data)

                        # Update caches
                        self.conversation_cache.set(conversation_id, updated_data)
                        self.message_cache.set(f"{conversation_id}:{message_id}", msg.to_dict())

                        return True

                raise MessageNotFoundError(message_id)

        except (ConversationNotFoundError, MessageNotFoundError):
            raise
        except Exception as e:
            raise ContextManagerError(f"更新会话消息失败 {message_id}: {e}")

    def delete_message(self, conversation_id: str, message_id: str) -> bool:
        """
        Delete a message from a conversation.
        Args:
            conversation_id: ID of the conversation
            message_id: ID of the message to delete
        Returns:
            True if deletion was successful
        """
        try:
            with self._conversation_lock(conversation_id):
                # Load conversation
                conversation_data = self.storage.load_conversation(conversation_id)
                if not conversation_data:
                    raise ConversationNotFoundError(conversation_id)

                conversation = Conversation.from_dict(conversation_data)

                # Find and remove message
                original_count = len(conversation.messages)
                conversation.messages = [
                    msg for msg in conversation.messages
                    if msg.get('message_id') != message_id
                ]

                if len(conversation.messages) == original_count:
                    raise MessageNotFoundError(message_id)

                conversation.updated_at = time.time()

                # Save updated conversation
                updated_data = conversation.to_dict()
                self.storage.save_conversation(updated_data)

                # Update index
                self.index_manager.update_conversation(updated_data)

                # Update caches
                self.conversation_cache.set(conversation_id, updated_data)
                self.message_cache.delete(f"{conversation_id}:{message_id}")

                return True

        except (ConversationNotFoundError, MessageNotFoundError):
            raise
        except Exception as e:
            raise ContextManagerError(f"从会话中删除消息失败 {message_id}: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get manager statistics.
        Returns:
            Dictionary with statistics
        """
        cache_stats = {
            'conversation_cache_size': self.conversation_cache.size(),
            'message_cache_size': self.message_cache.size()
        }

        return {
            **self._stats,
            'cache_stats': cache_stats,
            'total_conversations': len(self.index_manager.list_conversations()),
            'current_conversation_id': self.get_current_conversation_id(),
            'storage_path': self.config.storage_path
        }

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check of all components.
        Returns:
            Health status dictionary
        """
        health_status = {
            'status': 'healthy',
            'storage': True,
            'cache': True,
            'index': True,
            'search': True,
            'issues': []
        }

        try:
            # Check storage
            if not os.path.exists(self.config.storage_path):
                health_status['storage'] = False
                health_status['issues'].append('Storage directory not accessible')

            # Check cache
            conv_cache_size = self.conversation_cache.size()
            if conv_cache_size > self.config.max_cache_size:
                health_status['issues'].append('Conversation cache size exceeds limit')

            # Check index consistency
            try:
                conversations = self.index_manager.list_conversations()
                health_status['total_conversations'] = len(conversations)
            except Exception as e:
                health_status['index'] = False
                health_status['issues'].append(f'Index error: {e}')

            # Determine overall status
            if not all([health_status['storage'], health_status['cache'],
                        health_status['index'], health_status['search']]):
                health_status['status'] = 'degraded'

            if health_status['issues']:
                health_status['status'] = 'warning' if health_status['status'] == 'healthy' else health_status['status']

        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['issues'].append(f'Health check failed: {e}')

        return health_status

    @contextlib.contextmanager
    def transaction(self, conversation_id: str) -> Generator[None, None, None]:
        """
        Transaction context manager for atomic operations.
        Args:
            conversation_id: ID of the conversation for the transaction
        """
        with self._conversation_lock(conversation_id):
            try:
                yield
            except Exception:
                # In a full implementation, we would rollback changes here
                # For now, we just re-raise the exception
                raise

    def clear_cache(self):
        """Clear all caches."""
        self.conversation_cache.clear()
        self.message_cache.clear()

    def rebuild_index(self):
        """Rebuild the conversation index from storage."""
        try:
            # Clear existing index
            # self.index_manager._index.clear()

            # Load all conversations from storage and rebuild index
            conversation_ids = self.storage.list_conversations()

            for conv_id in conversation_ids:
                conversation_data = self.storage.load_conversation(conv_id)
                if conversation_data:
                    self.index_manager.add_conversation(conversation_data)

        except Exception as e:
            raise ContextManagerError(f"Failed to rebuild index: {e}")

    def close(self):
        """Clean up resources."""
        # Clear caches
        self.clear_cache()

        # Save any pending index changes
        try:
            self.index_manager._save_index()
        except Exception:
            pass  # Ignore errors during cleanup

    def set_current_conversation(self, conversation_id: str) -> bool:
        """
        设置当前对话。
        Args:
            conversation_id: 要设置为当前对话的ID
        Returns:
            True if setting was successful
        Raises:
            ConversationNotFoundError: 如果对话不存在
        """
        try:
            # 验证对话是否存在
            conversation_data = self.get_conversation(conversation_id)
            if not conversation_data:
                raise ConversationNotFoundError(conversation_id)

            # 设置当前对话
            success = self.index_manager.set_current_conversation(conversation_id)
            if not success:
                raise ContextManagerError(f"Failed to set current conversation: {conversation_id}")

            return True

        except ConversationNotFoundError:
            raise
        except Exception as e:
            raise ContextManagerError(f"Failed to set current conversation {conversation_id}: {e}")

    def get_current_conversation_id(self) -> Optional[str]:
        """
        获取当前对话ID。
        Returns:
            当前对话ID，如果未设置返回None
        """
        try:
            return self.index_manager.get_current_conversation_id()
        except Exception as e:
            raise ContextManagerError(f"Failed to get current conversation ID: {e}")

    def get_current_conversation(self) -> Optional[Dict[str, Any]]:
        """
        获取当前对话的完整数据。
        Returns:
            当前对话的数据字典，如果未设置或对话不存在返回None
        """
        try:
            current_id = self.get_current_conversation_id()
            if not current_id:
                return None
            return self.get_conversation(current_id)

        except Exception as e:
            raise ContextManagerError(f"Failed to get current conversation: {e}")

    def clear_current_conversation(self) -> bool:
        """
        清除当前对话设置。
        Returns:
            True if clearing was successful
        """
        try:
            success = self.index_manager.clear_current_conversation()
            if not success:
                raise ContextManagerError("Failed to clear current conversation")
            return True
        except Exception as e:
            raise ContextManagerError(f"Failed to clear current conversation: {e}")

    def append_message_to_current(
            self, role: str, content: Union[str, Dict[str, Any], List[Any]], metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        向当前对话添加消息。
        Args:
            role: 消息角色
            content: 消息内容
            metadata: 可选的消息元数据
        Returns:
            消息ID
        Raises:
            ConversationManagerError: 如果没有设置当前对话或添加失败
        """
        try:
            current_id = self.get_current_conversation_id()
            if not current_id:
                raise ContextManagerError("未设置当前会话")

            return self.append_message(current_id, role, content, metadata)

        except Exception as e:
            raise ContextManagerError(f"向当前会话新增消息失败: {e}")


class ContextManagerSingleton:
    """对话管理器的单例类，确保全局只有一个实例"""
    _instance: Optional[ContextManager] = None
    _lock = threading.Lock()
    _config: Optional[ContextManagerConfig] = None

    @classmethod
    def get_instance(cls, config: Optional[ContextManagerConfig] = None) -> ContextManager:
        """
        获取对话管理器实例
        Args:
            config: 配置对象，如果为None则使用默认配置
        Returns:
            PersistConversationManager实例
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    if config is None:
                        config = cls._get_default_config()
                    cls._config = config
                    cls._instance = ContextManager(config)
        return cls._instance

    @classmethod
    def reset_instance(cls, config: Optional[ContextManagerConfig] = None):
        """
        重置实例，用于测试或配置更改时
        Args:
            config: 新的配置对象
        """
        with cls._lock:
            cls._instance = None
            cls._config = None
            if config is not None:
                cls._instance = ContextManager(config)
                cls._config = config

    @classmethod
    def _get_default_config(cls) -> ContextManagerConfig:
        """获取默认配置"""
        # 默认存储路径为当前工作目录下的 .auto-coder/context
        default_storage_path = os.path.join(os.getcwd(), ".auto-coder", "context")
        return ContextManagerConfig()

    @classmethod
    def get_config(cls) -> Optional[ContextManagerConfig]:
        """获取当前使用的配置"""
        return cls._config


def get_context_manager(config: Optional[ContextManagerConfig] = None) -> ContextManager:
    """
    获取全局对话管理器实例
    这是一个便捷函数，内部使用单例模式确保全局只有一个实例。
    首次调用时会创建实例，后续调用会返回同一个实例。
    Args:
        config: 可选的配置对象。如果为None，将使用默认配置。
               注意：只有在首次调用时，config参数才会生效。
    Returns:
        PersistConversationManager: 对话管理器实例
    Example:
        ```python
        # 使用默认配置
        manager = get_conversation_manager()

        # 使用自定义配置（仅在首次调用时生效）
        config = ConversationManagerConfig(
            storage_path="./my_conversations",
            max_cache_size=200
        )
        manager = get_conversation_manager(config)

        # 创建对话
        conv_id = manager.create_conversation(
            name="测试对话",
            description="这是一个测试对话"
        )
        ```
    """
    return ContextManagerSingleton.get_instance(config)


def reset_context_manager(config: Optional[ContextManagerConfig] = None):
    """
    重置全局对话管理器实例
    用于测试或需要更改配置时重置实例。
    Args:
        config: 新的配置对象，如果为None则在下次调用get_conversation_manager时使用默认配置
    Example:
        ```python
        # 重置为默认配置
        reset_conversation_manager()
        # 重置为新配置
        new_config = ConversationManagerConfig(storage_path="./new_path")
        reset_conversation_manager(new_config)
        ```
    """
    ContextManagerSingleton.reset_instance(config)


def get_context_manager_config() -> Optional[ContextManagerConfig]:
    """
    获取当前对话管理器使用的配置
    Returns:
        当前配置对象，如果还未初始化则返回None
    """
    return ContextManagerSingleton.get_config()