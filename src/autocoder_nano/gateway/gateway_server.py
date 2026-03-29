""" 主要的 gateway 服务器实现 """
import os
import time
import asyncio
import json
import logging
import threading
import hashlib
import hmac
import secrets
import subprocess
from pathlib import Path
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from loguru import logger

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi.responses import RedirectResponse, JSONResponse
import uvicorn

import autocoder_nano
from autocoder_nano.core.queue import sqlite_queue


# ============== Configuration ==============

project_root = os.getcwd()
queue_db_path = os.path.join(project_root, ".auto-coder", "chat-bot.db")
auth_cookie = "agent_auth"


class ConnectRequest(BaseModel):
    """连接请求模型"""
    token: Optional[str] = None
    password: Optional[str] = None
    client: str = "unknown"
    mode: str = "node"
    version: str = "1.0.0"
    device_token: Optional[str] = None
    bootstrap_token: Optional[str] = None
    session_key: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)


@dataclass
class HelloOk:
    """连接成功响应"""
    session_id: str
    protocol_version: str = "1.0"
    server_version: str = "1.0.0"
    capabilities: List[str] = field(default_factory=list)


class RPCRequest(BaseModel):
    """RPC请求模型"""
    id: str
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


class RPCResponse(BaseModel):
    """RPC响应模型"""
    id: str
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


class MessageEncoder:
    """消息编码器"""

    @staticmethod
    def encode(obj: Any) -> str:
        """编码对象为JSON字符串"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, '__dataclass_fields__'):
            return json.dumps(obj.__dict__, default=MessageEncoder.encode)
        return json.dumps(obj, default=MessageEncoder.encode)

    @staticmethod
    def decode(data: str) -> Any:
        """解码JSON字符串"""
        return json.loads(data)


class EventMessage(BaseModel):
    """事件消息模型"""
    event: str
    data: Dict[str, Any] = Field(default_factory=dict)


@dataclass
class EventFrame:
    """事件帧"""
    event: str
    data: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None


@dataclass
class GatewayConfig:
    """ gateway 配置"""
    host: str = "0.0.0.0"
    port: int = 8321
    auth_config: Dict[str, Any] = field(default_factory=dict)
    max_connections: int = 10
    ping_interval: int = 30
    # SSL配置
    ssl_cert: Optional[str] = None
    ssl_key: Optional[str] = None


@dataclass
class GatewayStats:
    """Gateway统计信息"""
    started_at: Optional[datetime] = None
    total_connections: int = 0
    active_connections: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    errors: int = 0


class GatewayErrorCode(Enum):
    """ gateway 错误代码"""
    AUTH_FAILED = "auth_failed"
    AUTH_EXPIRED = "auth_expired"
    RATE_LIMITED = "rate_limited"
    INVALID_MESSAGE = "invalid_message"
    SESSION_NOT_FOUND = "session_not_found"
    METHOD_NOT_FOUND = "method_not_found"
    INTERNAL_ERROR = "internal_error"
    NOT_AUTHORIZED = "not_authorized"


class GatewayEvents:
    """ gateway 事件类型"""
    # 会话事件
    SESSION_CREATED = "session.created"
    SESSION_UPDATED = "session.updated"
    SESSION_DELETED = "session.deleted"
    SESSION_MESSAGE = "session.message"
    # Agent事件
    AGENT_STARTED = "agent.started"
    AGENT_STOPPED = "agent.stopped"
    AGENT_EVENT = "agent.event"
    # 系统事件
    SERVER_SHUTDOWN = "server.shutdown"
    CONFIG_RELOADED = "config.reloaded"
    # 连接事件
    CLIENT_CONNECTED = "client.connected"
    CLIENT_DISCONNECTED = "client.disconnected"


class GatewayClientMode(Enum):
    """ gateway 客户端模式"""
    NODE = "node"
    BROWSER = "browser"
    MOBILE = "mobile"
    CLI = "cli"
    CONTROL_UI = "control-ui"


@dataclass
class GatewayClientInfo:
    """客户端信息"""
    id: str
    mode: GatewayClientMode
    name: str
    version: str
    connected_at: datetime
    last_activity: datetime
    authenticated: bool = False
    user: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ClientState(Enum):
    """客户端状态"""
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class ClientConnection:
    """客户端连接 - FastAPI WebSocket适配"""
    id: str
    websocket: WebSocket  # FastAPI WebSocket对象
    info: GatewayClientInfo
    state: ClientState = ClientState.CONNECTING
    subscriptions: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    pending_requests: Dict[str, asyncio.Future] = field(default_factory=dict)

    async def send(self, message: Any):
        """发送消息"""
        if self.state != ClientState.CLOSED:
            try:
                if hasattr(message, '__dataclass_fields__'):
                    message = json.loads(MessageEncoder.encode(message))
                await self.websocket.send_json(message)
            except Exception as e:
                logger.error(f"向客户端发送消息失败({self.id}): {e}")

    async def send_text(self, text: str):
        """发送文本消息"""
        if self.state != ClientState.CLOSED:
            try:
                await self.websocket.send_text(text)
            except Exception as e:
                logger.error(f"向客户端发送text消息失败({self.id}): {e}")

    async def send_json(self, data: Dict):
        """发送JSON消息"""
        if self.state != ClientState.CLOSED:
            try:
                await self.websocket.send_json(data)
            except Exception as e:
                logger.error(f"向客户端发送json消息失败({self.id}): {e}")

    async def close(self, code: int = 1000, reason: str = ""):
        """关闭连接"""
        if self.state != ClientState.CLOSED:
            self.state = ClientState.CLOSING
            try:
                await self.websocket.close(code=code, reason=reason)
            except Exception as e:
                logger.error(f"关闭客户端时出错({self.id}): {e}")
            finally:
                self.state = ClientState.CLOSED


# ============== Method Registry ==============

class MethodRegistry:
    """方法注册表"""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}

    def register(self, method: str, handler: Callable):
        """注册方法处理器"""
        self._handlers[method] = handler
        logger.info(f"已注册的 Method Handler: {method}")

    def unregister(self, method: str):
        """注销方法处理器"""
        self._handlers.pop(method, None)

    def get_handler(self, method: str) -> Optional[Callable]:
        """获取方法处理器"""
        return self._handlers.get(method)

    def list_methods(self) -> List[str]:
        """列出所有注册的方法"""
        return list(self._handlers.keys())


# ============== Auth ==============


class AuthMode(Enum):
    """认证模式"""
    NONE = "none"
    TOKEN = "token"
    PASSWORD = "password"
    TRUSTED_PROXY = "trusted_proxy"
    TAILSCALE = "tailscale"
    DEVICE_TOKEN = "device_token"
    BOOTSTRAP_TOKEN = "bootstrap_token"


@dataclass
class AuthConfig:
    """认证配置"""
    mode: AuthMode = AuthMode.NONE
    token: Optional[str] = None
    password: Optional[str] = None
    allow_tailscale: bool = False
    trusted_proxies: List[str] = field(default_factory=list)
    allow_real_ip_fallback: bool = False
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window_ms: int = 60000  # 1 minute


@dataclass
class AuthResult:
    """认证结果"""
    ok: bool
    method: Optional[str] = None
    user: Optional[str] = None
    reason: Optional[str] = None
    rate_limited: bool = False
    retry_after_ms: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuthStrategy(ABC):
    """认证策略基类"""

    @abstractmethod
    def authenticate(self, credentials: Dict[str, Any], client_info: Dict[str, Any]) -> AuthResult:
        """执行认证"""
        pass

    @abstractmethod
    def get_mode(self) -> AuthMode:
        """获取认证模式"""
        pass


@dataclass
class RateLimitEntry:
    """速率限制条目"""
    count: int
    window_start: float


class RateLimiter:
    """速率限制器"""

    def __init__(self, max_requests: int = 100, window_ms: int = 60000):
        self.max_requests = max_requests
        self.window_ms = window_ms
        self._entries: Dict[str, RateLimitEntry] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, Optional[int]]:
        """
        检查是否超过速率限制
        返回: (是否允许, 重试等待时间ms)
        """
        now = time.time() * 1000

        with self._lock:
            entry = self._entries.get(key)
            if entry is None or now - entry.window_start > self.window_ms:
                # 新窗口
                self._entries[key] = RateLimitEntry(count=1, window_start=now)
                return True, None
            if entry.count < self.max_requests:
                # 在限制内
                entry.count += 1
                return True, None
            # 超过限制
            retry_after = int(self.window_ms - (now - entry.window_start))
            return False, retry_after

    def reset(self, key: str):
        """重置速率限制"""
        with self._lock:
            self._entries.pop(key, None)


class GatewayAuthenticator:
    """Gateway认证器 - 管理多种认证策略"""

    def __init__(self, config: AuthConfig):
        self.config = config
        self._strategies: Dict[AuthMode, AuthStrategy] = {}
        self._rate_limiter = RateLimiter(
            max_requests=config.rate_limit_requests,
            window_ms=config.rate_limit_window_ms
        ) if config.rate_limit_enabled else None
        self._lock = threading.Lock()

    def register_strategy(self, strategy: AuthStrategy):
        """注册认证策略"""
        with self._lock:
            self._strategies[strategy.get_mode()] = strategy

    def authenticate(self, credentials: Dict[str, Any], client_info: Dict[str, Any]) -> AuthResult:
        """
        执行认证，按照配置的优先级尝试不同的认证方式
        """
        client_ip = client_info.get("client_ip", "unknown")

        # 检查速率限制
        if self._rate_limiter:
            allowed, retry_after = self._rate_limiter.check(client_ip)
            if not allowed:
                return AuthResult(
                    ok=False,
                    method=None,
                    reason="Rate limit exceeded",
                    rate_limited=True,
                    retry_after_ms=retry_after
                )

        # 根据配置选择认证策略
        strategies_to_try = self._get_strategies_to_try()

        for mode in strategies_to_try:
            strategy = self._strategies.get(mode)
            if not strategy:
                continue

            result = strategy.authenticate(credentials, client_info)
            if result.ok:
                return result

            # 如果认证失败但不是因为缺少凭证，记录失败原因
            if result.reason and "required" not in result.reason.lower():
                return result

        # 所有认证方式都失败
        return AuthResult(
            ok=False,
            method=None,
            reason="Authentication failed"
        )

    def _get_strategies_to_try(self) -> List[AuthMode]:
        """获取要尝试的认证策略列表"""
        # 优先级顺序
        priority_order = [
            AuthMode.TOKEN,
            AuthMode.DEVICE_TOKEN,
            AuthMode.BOOTSTRAP_TOKEN,
            AuthMode.PASSWORD,
            AuthMode.TAILSCALE,
            AuthMode.TRUSTED_PROXY,
            AuthMode.NONE,
        ]

        # 如果配置了特定模式，优先使用
        if self.config.mode != AuthMode.NONE:
            # 将配置的模式移到最前面
            priority_order.remove(self.config.mode)
            priority_order.insert(0, self.config.mode)

        return priority_order

    def is_authentication_required(self) -> bool:
        """检查是否需要认证"""
        return self.config.mode != AuthMode.NONE

    def get_auth_mode(self) -> AuthMode:
        """获取当前认证模式"""
        return self.config.mode


class TokenAuthStrategy(AuthStrategy):
    """Token认证策略"""

    def __init__(self, valid_tokens: List[str]):
        self.valid_tokens = set(valid_tokens)

    def authenticate(self, credentials: Dict[str, Any], client_info: Dict[str, Any]) -> AuthResult:
        token = credentials.get("token")

        if not token:
            return AuthResult(
                ok=False,
                method="token",
                reason="Token is required"
            )

        # 使用constant-time比较防止时序攻击
        for valid_token in self.valid_tokens:
            if hmac.compare_digest(token, valid_token):
                return AuthResult(
                    ok=True,
                    method="token",
                    user="token_user",
                    metadata={"token_prefix": token[:8] + "..."}
                )
        return AuthResult(
            ok=False,
            method="token",
            reason="Invalid token"
        )

    def get_mode(self) -> AuthMode:
        return AuthMode.TOKEN

    def add_token(self, token: str):
        """添加有效token"""
        self.valid_tokens.add(token)

    def remove_token(self, token: str):
        """移除有效token"""
        self.valid_tokens.discard(token)


class PasswordAuthStrategy(AuthStrategy):
    """密码认证策略"""

    def __init__(self, password_hash: Optional[str] = None, password: Optional[str] = None):
        if password_hash:
            self.password_hash = password_hash
        elif password:
            self.password_hash = self._hash_password(password)
        else:
            raise ValueError("Either password_hash or password must be provided")

    @staticmethod
    def _hash_password(password: str) -> str:
        """哈希密码"""
        salt = secrets.token_hex(16)
        hash_value = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return f"{salt}${hash_value.hex()}"

    @staticmethod
    def _verify_password(password: str, password_hash: str) -> bool:
        """验证密码"""
        try:
            salt, hash_value = password_hash.split("$")
            computed_hash = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt.encode('utf-8'),
                100000
            )
            return hmac.compare_digest(hash_value, computed_hash.hex())
        except ValueError:
            return False

    def authenticate(self, credentials: Dict[str, Any], client_info: Dict[str, Any]) -> AuthResult:
        password = credentials.get("password")
        if not password:
            return AuthResult(
                ok=False,
                method="password",
                reason="Password is required"
            )
        if self._verify_password(password, self.password_hash):
            return AuthResult(
                ok=True,
                method="password",
                user="admin"
            )
        return AuthResult(
            ok=False,
            method="password",
            reason="Invalid password"
        )

    def get_mode(self) -> AuthMode:
        return AuthMode.PASSWORD


def create_authenticator_from_config(config_dict: Dict[str, Any]) -> GatewayAuthenticator:
    """从配置字典创建认证器"""
    auth_config = AuthConfig(
        mode=AuthMode(config_dict.get("mode", "none")),
        token=config_dict.get("token"),
        password=config_dict.get("password"),
        allow_tailscale=config_dict.get("allow_tailscale", False),
        trusted_proxies=config_dict.get("trusted_proxies", []),
        allow_real_ip_fallback=config_dict.get("allow_real_ip_fallback", False),
        rate_limit_enabled=config_dict.get("rate_limit_enabled", True),
        rate_limit_requests=config_dict.get("rate_limit_requests", 100),
        rate_limit_window_ms=config_dict.get("rate_limit_window_ms", 60000)
    )
    authenticator = GatewayAuthenticator(auth_config)

    # 注册认证策略
    if auth_config.token:
        authenticator.register_strategy(TokenAuthStrategy([auth_config.token]))

    if auth_config.password:
        authenticator.register_strategy(PasswordAuthStrategy(password=auth_config.password))

    # 始终注册设备token和bootstrap策略
    # authenticator.register_strategy(DeviceTokenAuthStrategy())
    return authenticator


# ============== ClientManager ==============


class ClientManager:
    """客户端管理器"""

    def __init__(self):
        self._clients: Dict[str, ClientConnection] = {}
        self._clients_by_user: Dict[str, Set[str]] = {}
        self._clients_by_mode: Dict[GatewayClientMode, Set[str]] = {}
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动客户端管理器"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Client Manager 已启动")

    async def stop(self):
        """停止客户端管理器"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # 关闭所有客户端连接
        async with self._lock:
            clients = list(self._clients.values())

        for client in clients:
            await client.close(1001, "Server shutting down")

        logger.info("Client Manager 已关闭")

    async def register_client(
            self, websocket: WebSocket, mode: GatewayClientMode, name: str, version: str,
            capabilities: Optional[List[str]] = None, metadata: Optional[Dict[str, Any]] = None
    ) -> ClientConnection:
        """注册新客户端"""
        import uuid
        client_id = str(uuid.uuid4())
        now = datetime.now()

        info = GatewayClientInfo(
            id=client_id,
            mode=mode,
            name=name,
            version=version,
            connected_at=now,
            last_activity=now,
            capabilities=capabilities or [],
            metadata=metadata or {}
        )

        client = ClientConnection(
            id=client_id,
            websocket=websocket,
            info=info
        )

        async with self._lock:
            self._clients[client_id] = client

            if mode not in self._clients_by_mode:
                self._clients_by_mode[mode] = set()
            self._clients_by_mode[mode].add(client_id)

        logger.info(f"Client 已注册: {client_id} ({mode.value})")

        # 触发事件
        await self._emit_event(GatewayEvents.CLIENT_CONNECTED, {
            "client_id": client_id,
            "mode": mode.value,
            "name": name,
            "version": version
        })

        return client

    async def unregister_client(self, client_id: str, reason: str = ""):
        """注销客户端"""
        async with self._lock:
            client = self._clients.pop(client_id, None)
            if not client:
                return

            # 从索引中移除
            if client.info.user and client.info.user in self._clients_by_user:
                self._clients_by_user[client.info.user].discard(client_id)

            self._clients_by_mode.get(client.info.mode, set()).discard(client_id)

        # 取消所有待处理的请求
        for future in client.pending_requests.values():
            if not future.done():
                future.cancel()

        logger.info(f"Client unregistered: {client_id} ({reason})")

        # 触发事件
        await self._emit_event(GatewayEvents.CLIENT_DISCONNECTED, {
            "client_id": client_id,
            "reason": reason
        })

    async def authenticate_client(self, client_id: str, user: str, auth_method: str):
        """认证客户端"""
        async with self._lock:
            client = self._clients.get(client_id)
            if not client:
                return False

            client.info.authenticated = True
            client.info.user = user
            client.state = ClientState.ACTIVE

            # 添加到用户索引
            if user not in self._clients_by_user:
                self._clients_by_user[user] = set()
            self._clients_by_user[user].add(client_id)

        logger.info(f"Client authenticated: {client_id} as {user} ({auth_method})")
        return True

    async def _cleanup_loop(self):
        """清理循环 - 移除不活跃的连接"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次

                now = datetime.now()
                inactive_threshold = timedelta(minutes=5)
                clients_to_check = list(self._clients.values())

                for client in clients_to_check:
                    if now - client.info.last_activity > inactive_threshold:
                        if client.state == ClientState.ACTIVE:
                            logger.warning(f"Client inactive for too long: {client.id}")
                            await client.close(1001, "Inactive for too long")
                            await self.unregister_client(client.id, "inactive")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")

    async def _emit_event(self, event: str, data: Dict[str, Any]):
        """触发事件"""
        handlers = self._event_handlers.get(event, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"Event handler error for {event}: {e}")

    def get_client(self, client_id: str) -> Optional[ClientConnection]:
        """获取客户端"""
        return self._clients.get(client_id, None)

    def get_client_count(self) -> int:
        """获取客户端数量"""
        return len(self._clients)

    def get_all_clients(self) -> List[ClientConnection]:
        """获取所有客户端"""
        return list(self._clients.values())

    def update_activity(self, client_id: str):
        """更新客户端活动时间"""
        client = self._clients.get(client_id)
        if client:
            client.info.last_activity = datetime.now()


# ============== Subscription Manager ==============


class SubscriptionManager:
    """订阅管理器 - 管理客户端对事件的订阅"""

    def __init__(self, client_manager: ClientManager):
        self.client_manager = client_manager
        self._subscriptions: Dict[str, Set[str]] = {}  # event -> set of client_ids
        self._lock = asyncio.Lock()

    async def subscribe(self, client_id: str, event: str):
        """订阅事件"""
        async with self._lock:
            if event not in self._subscriptions:
                self._subscriptions[event] = set()
            self._subscriptions[event].add(client_id)

        client = self.client_manager.get_client(client_id)
        if client:
            client.subscriptions.add(event)

    async def unsubscribe(self, client_id: str, event: str):
        """取消订阅"""
        async with self._lock:
            self._subscriptions.get(event, set()).discard(client_id)

        client = self.client_manager.get_client(client_id)
        if client:
            client.subscriptions.discard(event)

    async def unsubscribe_all(self, client_id: str):
        """取消所有订阅"""
        async with self._lock:
            for event, clients in self._subscriptions.items():
                clients.discard(client_id)

    def get_subscribers(self, event: str) -> List[str]:
        """获取事件的所有订阅者"""
        return list(self._subscriptions.get(event, set()))

    async def publish(self, event: str, data: Dict[str, Any]):
        """发布事件到订阅者"""
        subscriber_ids = self.get_subscribers(event)

        tasks = []
        for client_id in subscriber_ids:
            client = self.client_manager.get_client(client_id)
            if client:
                event_frame = EventFrame(
                    event=event,
                    data=data,
                    session_id=client.info.user
                )
                tasks.append(client.send(event_frame))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# ============== Agent Service ==============


class AgentService:
    def __init__(self, db_path: str, gateway: Optional['GatewayServer']):
        self.db_path = db_path
        self.gateway = gateway
        self._consumer_task = None

    async def start(self):
        logger.info(f"正在开启 AgentService 服务...")
        sqlite_queue.init_db(self.db_path)
        logger.info(f"AgentService 数据库初始化完成...")
        self._consumer_task = asyncio.create_task(self._response_consumer())
        logger.info(f"AgentService 响应消费者已启动...")

    async def stop(self):
        logger.info(f"开始关闭 AgentService 服务...")
        if self._consumer_task:
            self._consumer_task.cancel()
            logger.info(f"AgentService 响应消费者已关闭...")
        for ws in self.gateway.client_manager.get_all_clients():
            await ws.close()
        logger.info(f"关闭所有 AgentService ClientConnection.....")
        # todo: kill 所有运行中的 agent

    async def run_agent(self, client, content, conversation_id, message_id):
        loop = asyncio.get_running_loop()

        # 写入用户消息
        await loop.run_in_executor(
            None, sqlite_queue.insert_user_message,
            self.db_path, client.id, message_id, conversation_id, content
        )
        # 判断是否 new session
        today_size = await loop.run_in_executor(
            None, sqlite_queue.fetch_user_messages_size_bytime,
            self.db_path, datetime.now().strftime("%Y-%m-%d")
        )

        cmd = ['auto-coder.nano', '--agent-model', '--agent-query', content]
        if today_size == 1:
            cmd.append('--agent-new-session')

        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        run_id = str(uuid4())
        await loop.run_in_executor(
            None, sqlite_queue.insert_agent_run,
            self.db_path, run_id, client.id, conversation_id, message_id, content, process.pid
        )
        asyncio.create_task(self._watch_process(process, run_id))
        return {"run_id": run_id}

    async def _watch_process(self, process, run_id):
        try:
            exit_code = await asyncio.to_thread(process.wait)
            status = "finished" if exit_code == 0 else "failed"
            sqlite_queue.finish_agent_run(self.db_path, run_id, status)
        except Exception as e:
            sqlite_queue.finish_agent_run(self.db_path, run_id, "failed", str(e))

    async def _response_consumer(self):
        """ 后台任务：消费 agent_responses 并推送给前端 """
        loop = asyncio.get_running_loop()

        while True:
            messages = await loop.run_in_executor(None, sqlite_queue.fetch_pending_responses, self.db_path)
            for msg in messages:
                client_id = msg["client_id"]
                client = self.gateway.client_manager.get_client(client_id)
                if client:
                    try:
                        await client.send_json({
                            "type": msg["type"],
                            "messageId": msg["message_id"],
                            "content": msg["content"]  # 已经是 Python 对象
                        })
                        # 标记为已发送
                        await loop.run_in_executor(None, sqlite_queue.mark_response_sent,
                                                   self.db_path, msg["id"])
                    except Exception as e:
                        print(f"发送消息失败: {e}")
                        # 发送失败，暂不标记，下次循环重试
                else:
                    # 客户端已断开，直接标记为已发送（避免堆积）
                    await loop.run_in_executor(None, sqlite_queue.mark_response_sent, queue_db_path, msg["id"])
                # await self.gateway.subscription_manager.publish(
                #     "agent.message",
                #     {
                #         "client_id": msg["client_id"],
                #         "type": msg["type"],
                #         "messageId": msg["message_id"],
                #         "content": msg["content"],
                #         "conversationId": msg["conversation_id"]
                #     }
                # )
                # await loop.run_in_executor(None, sqlite_queue.mark_response_sent, self.db_path, msg["id"])
            await asyncio.sleep(0.5)


# ============== FastAPI Application ==============


class GatewayServer:
    """ gateway 服务器 """

    def __init__(self, config: GatewayConfig):
        self.config = config
        self.authenticator = create_authenticator_from_config(config.auth_config)
        self.client_manager = ClientManager()
        # self.subscription_manager = SubscriptionManager(self.client_manager)
        self.method_registry = MethodRegistry()
        self.stats = GatewayStats()
        self.agent_service = AgentService(queue_db_path, self)
        self._app: Optional[FastAPI] = None
        self._shutdown_event = asyncio.Event()

        # 注册内置方法
        self._register_builtin_methods()

        # 创建FastAPI应用
        self._create_app()

    def _create_app(self):
        """ 创建FastAPI应用 """

        @asynccontextmanager
        async def lifespan(app: FastAPI):  # 应用生命周期管理
            await self._startup()  # 启动
            yield
            await self._shutdown()  # 关闭

        self._app = FastAPI(
            title="Supa Nano Gateway",
            description="Supa Nano Gateway Server",
            version="1.0.0",
            lifespan=lifespan
        )

        self._app.mount(
            "/static", StaticFiles(directory=Path(autocoder_nano.__file__).parent / "app/static"), name="static")
        self.templates = Jinja2Templates(directory=Path(autocoder_nano.__file__).parent / "app/templates")

        # 注册路由
        self._register_routes()

    def _register_routes(self):
        """注册路由"""
        app = self._app

        # 健康检查
        @app.get("/health")
        async def health():
            """健康检查端点"""
            return {
                "status": "healthy",
                "connections": self.client_manager.get_client_count(),
                "uptime": (datetime.now() - self.stats.started_at).total_seconds() if self.stats.started_at else 0,
                "timestamp": datetime.now().isoformat()
            }

        # 版本信息
        @app.get("/version")
        async def version():
            """版本信息端点"""
            return {"server_version": "1.0.0", "api_version": "1.0"}

        # API路由 - 需要认证
        @app.get("/api/v1/ping")
        async def api_ping():
            """API Ping端点"""
            return {"pong": True, "timestamp": datetime.now().isoformat()}

        @app.get("/api/v1/stats")
        async def api_stats():
            """统计信息端点"""
            return {
                "connections": self.client_manager.get_client_count(),
                "total_connections": self.stats.total_connections,
                "messages_sent": self.stats.messages_sent,
                "messages_received": self.stats.messages_received
            }

        @app.get("/api/v1/clients")
        async def api_clients():
            """客户端列表端点"""
            clients = self.client_manager.get_all_clients()
            return {
                "clients": [
                    {
                        "id": c.id,
                        "mode": c.info.mode.value,
                        "name": c.info.name,
                        "authenticated": c.info.authenticated,
                        "connected_at": c.info.connected_at.isoformat()
                    }
                    for c in clients
                ]
            }

        @app.get("/api/v1/methods")
        async def api_methods():
            """方法列表端点"""
            return {"methods": self.method_registry.list_methods()}

        # WebSocket端点
        @app.websocket("/gateway")
        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket端点"""
            await self._handle_websocket(websocket)

        @app.get("/")
        async def index(request: Request):
            if request.cookies.get(auth_cookie) != "ok":
                return RedirectResponse("/login")
            return self.templates.TemplateResponse("index.html", {"request": request})

        @app.get("/login")
        async def login_page(request: Request):
            return self.templates.TemplateResponse("login.html", {"request": request})

        @app.post("/login")
        async def login(request: Request):
            data = await request.json()
            username = data.get("username")
            password = data.get("password")

            if username == "admin" and password == self.config.auth_config.get("password"):
                resp = RedirectResponse("/", status_code=302)
                resp.set_cookie("agent_auth", "ok", httponly=True)
                return resp

            return {"success": False}

        @app.post("/logout")
        async def logout():
            resp = JSONResponse({"success": True})
            resp.delete_cookie("agent_auth")
            return resp

    def _register_builtin_methods(self):
        """注册内置方法"""
        self.method_registry.register("health", self._handle_health)
        self.method_registry.register("agent.run", self._agent_run)

    async def _agent_run(self, client, params):
        content = params.get("content")
        conversation_id = params.get("conversation_id", "")
        message_id = params.get("message_id")

        return await self.agent_service.run_agent(
            client,
            content,
            conversation_id,
            message_id
        )

    async def _handle_health(self) -> Dict:
        """处理health方法"""
        return {
            "status": "healthy",
            "connections": self.client_manager.get_client_count(),
            "uptime": (datetime.now() - self.stats.started_at).total_seconds() if self.stats.started_at else 0
        }

    async def _startup(self):
        """启动服务"""
        logger.info("正在启动 GatewayServer 服务...")
        self.stats.started_at = datetime.now()
        await self.client_manager.start()
        await self.agent_service.start()
        logger.info(f"Gateway server started on http://{self.config.host}:{self.config.port}")
        logger.info(f"WebSocket endpoint-1: ws://{self.config.host}:{self.config.port}/gateway")
        logger.info(f"WebSocket endpoint-2: ws://{self.config.host}:{self.config.port}/ws")

    async def _shutdown(self):
        """关闭服务"""
        logger.info("正在关闭 GatewayServer 服务...")
        await self.client_manager.stop()
        await self.agent_service.stop()
        logger.info("GatewayServer 已关闭")

    async def _handle_websocket(self, websocket: WebSocket):
        """处理WebSocket连接"""
        client_ip = websocket.client.host if websocket.client else "unknown"
        # 检查最大连接数
        if self.client_manager.get_client_count() >= self.config.max_connections:
            await websocket.close(code=1013, reason="Server at capacity")
            return
        self.stats.total_connections += 1

        # 接受连接
        await websocket.accept(subprotocol="supa-nano-gateway")

        client: Optional[ClientConnection] = None

        try:
            # 处理握手
            client = await self._handle_handshake(websocket, client_ip)
            if not client:
                return

            # 消息循环
            await self._message_loop(client, websocket)

        except WebSocketDisconnect:
            logger.info(f"Client 已断开连接: {client_ip}")
        except Exception as e:
            logger.error(f"WebSocket 错误: {e}")
            self.stats.errors += 1
        finally:
            if client:
                await self.client_manager.unregister_client(client.id, "connection_closed")
            self.stats.active_connections = self.client_manager.get_client_count()

    async def _handle_handshake(self, websocket: WebSocket, client_ip: str) -> Optional[ClientConnection]:
        """处理连接握手"""
        try:
            # 等待连接消息
            message = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            data = json.loads(message)
            print(data)

            # 验证连接参数
            connect_request = ConnectRequest(**data)

            # 确定客户端模式
            mode = GatewayClientMode(connect_request.mode)

            # 创建客户端连接
            client = await self.client_manager.register_client(
                websocket=websocket,
                mode=mode,
                name=connect_request.client,
                version=connect_request.version,
                capabilities=connect_request.capabilities,
                metadata={"client_ip": client_ip}
            )

            if connect_request.mode == "browser":  # 本地 web ui 无需执行认证
                return client

            # 执行认证
            credentials = {
                "token": connect_request.token,
                "password": connect_request.password,
                "device_token": connect_request.device_token,
                "bootstrap_token": connect_request.bootstrap_token,
                "session_key": connect_request.session_key
            }

            client_info = {
                "client_ip": client_ip,
                "forwarded_for": None
            }

            auth_result = self.authenticator.authenticate(credentials, client_info)

            if not auth_result.ok and self.authenticator.is_authentication_required():
                # 认证失败
                await websocket.send_json({
                    "type": "hello_error",
                    "error": {
                        "code": GatewayErrorCode.AUTH_FAILED.value,
                        "message": auth_result.reason or "Authentication failed"
                    }
                })
                await websocket.close(code=1008, reason="Authentication failed")
                await self.client_manager.unregister_client(client.id, "auth_failed")
                return None

            # 认证成功或不需要认证
            if auth_result.ok:
                await self.client_manager.authenticate_client(
                    client.id,
                    auth_result.user or "anonymous",
                    auth_result.method or "none"
                )

            # 发送hello响应
            hello_ok = HelloOk(
                session_id=client.id,
                protocol_version="1.0",    # ProtocolValidator.PROTOCOL_VERSION,
                server_version="1.0.0",
                capabilities=["sessions", "agents", "models", "skills"]
            )

            await websocket.send_json({
                "type": "hello_ok",
                **json.loads(MessageEncoder.encode(hello_ok))
            })

            self.stats.active_connections = self.client_manager.get_client_count()

            return client

        except asyncio.TimeoutError:
            logger.warning("握手超时")
            await websocket.close(code=1008, reason="Handshake timeout")
            return None
        except json.JSONDecodeError:
            logger.warning("握手时包含无效的 JSON")
            await websocket.close(code=1008, reason="Invalid JSON")
            return None
        except Exception as e:
            logger.error(f"握手错误: {e}")
            await websocket.close(code=1011, reason="Internal error")
            return None

    async def _message_loop(self, client: ClientConnection, websocket: WebSocket):
        """消息处理循环"""
        while not self._shutdown_event.is_set():
            try:
                message = await websocket.receive_text()
                self.stats.messages_received += 1

                # 更新活动时间
                self.client_manager.update_activity(client.id)
                # 解析消息
                data = json.loads(message)
                # 处理消息
                if "method" in data:
                    # 请求帧
                    # {
                    #     id: assistantMessageId,
                    #     method: "agent.run",
                    #     params: {
                    #         content: content,
                    #         conversation_id: currentConversationId,
                    #         message_id: assistantMessageId
                    #     }
                    # }
                    await self._handle_request(client, websocket, data)
                else:
                    # 未知消息类型
                    logger.warning(f"未知 Message 类型: {data}")

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                logger.warning("收到无效的 JSON")
            except Exception as e:
                logger.error(f"Message 处理错误: {e}")
                self.stats.errors += 1

    async def _handle_request(self, client: ClientConnection, websocket: WebSocket, data: Dict):
        """处理请求"""
        try:
            request = RPCRequest(**data)
            # 获取方法处理器
            handler = self.method_registry.get_handler(request.method)
            if not handler:
                return

            # 执行方法
            try:
                await handler(client, request.params)
                self.stats.messages_sent += 1
            except Exception as e:
                logger.error(f"Method execution error: {e}")
        except Exception as e:
            logger.error(f"Method execution error: {e}")

    def register_method(self, method: str, handler: Callable):
        """注册自定义方法"""
        self.method_registry.register(method, handler)

    def get_app(self) -> FastAPI:
        """获取FastAPI应用实例"""
        return self._app

    def get_stats(self) -> GatewayStats:
        """获取统计信息"""
        return self.stats

    async def start(self):
        """启动服务器（使用uvicorn）"""
        config = uvicorn.Config(
            self._app,
            host=self.config.host,
            port=self.config.port,
            ssl_certfile=self.config.ssl_cert,
            ssl_keyfile=self.config.ssl_key,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def stop(self):
        """停止服务器"""
        self._shutdown_event.set()
        await self._shutdown()
