import os
import asyncio
import json
import uuid
import subprocess
from typing import Dict
from pathlib import Path
import autocoder_nano

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from autocoder_nano.core.queue import sqlite_queue


project_root = os.getcwd()
queue_db_path = os.path.join(project_root, ".auto-coder", "chat-bot.db")


# ===== 任务队列和连接管理 =====
active_connections: Dict[str, WebSocket] = {}  # 客户端ID -> WebSocket


# ===== 后台任务：消费 agent_responses 并推送给前端 =====
async def response_consumer():
    """轮询 agent_responses 表，将新消息通过 WebSocket 推送"""
    loop = asyncio.get_running_loop()
    while True:
        # 获取待发送的响应
        messages = await loop.run_in_executor(None, sqlite_queue.fetch_pending_responses, queue_db_path)
        for msg in messages:
            client_id = msg["client_id"]
            if client_id in active_connections:
                websocket = active_connections[client_id]
                try:
                    # 发送给前端
                    await websocket.send_json({
                        "type": msg["type"],
                        "messageId": msg["message_id"],
                        "content": msg["content"]  # 已经是 Python 对象
                    })
                    # 标记为已发送
                    await loop.run_in_executor(None, sqlite_queue.mark_response_sent, queue_db_path, msg["id"])
                except Exception as e:
                    print(f"发送消息失败: {e}")
                    # 发送失败，暂不标记，下次循环重试
            else:
                # 客户端已断开，直接标记为已发送（避免堆积）
                await loop.run_in_executor(None, sqlite_queue.mark_response_sent, queue_db_path, msg["id"])
        await asyncio.sleep(0.5)


# ===== Lifespan 管理器 =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：初始化数据库，启动消费者任务
    sqlite_queue.init_db(queue_db_path)
    print("数据库初始化完成")
    consumer_task = asyncio.create_task(response_consumer())
    print("响应消费者已启动")
    yield
    # 关闭时：清理任务和连接
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        print("消费者已取消")
    for ws in active_connections.values():
        await ws.close()
    active_connections.clear()

app = FastAPI(title="AI Agent", lifespan=lifespan)


# # 挂载静态文件和模板
# app.mount("/static", StaticFiles(directory="app/static"), name="static")
# templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory=Path(autocoder_nano.__file__).parent / "app/static"), name="static")
templates = Jinja2Templates(directory=Path(autocoder_nano.__file__).parent / "app/templates")


# ===== WebSocket 端点（提取 messageId） =====
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_id = str(uuid.uuid4())
    active_connections[client_id] = websocket
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            # {'type': 'user_message', 'conversationId': '1', 'messageId': 'assistant-1771917973252', 'content': '101'}
            if msg.get("type") == "user_message":
                conversation_id = msg.get("conversationId", "")
                message_id = msg["messageId"]
                content = msg["content"]
                # 异步插入用户消息
                await asyncio.get_running_loop().run_in_executor(
                    None, sqlite_queue.insert_user_message,
                    queue_db_path, client_id, message_id, conversation_id, content
                )
                process = subprocess.Popen(
                    ['auto-coder.nano', '--web-model', '--agent-query', f'{content}'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("子进程已启动，PID:", process.pid)
    except WebSocketDisconnect:
        active_connections.pop(client_id, None)
        print(f"客户端 {client_id} 断开连接")


# ===== HTTP 页面入口 =====
@app.get("/")
async def get_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


def main():
    uvicorn.run(app, host="0.0.0.0", port=8321)


if __name__ == '__main__':
    main()