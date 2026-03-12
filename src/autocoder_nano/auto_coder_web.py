import os
import asyncio
import json
import uuid
import subprocess
import argparse
from typing import Dict
from pathlib import Path
from datetime import datetime
import autocoder_nano

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse
from contextlib import asynccontextmanager

from autocoder_nano.core.queue import sqlite_queue


def parse_args():
    parser = argparse.ArgumentParser(description="AI Agent Server")
    parser.add_argument(
        "--username",
        default="admin",
        help="login username (default: admin)"
    )
    parser.add_argument(
        "--password",
        default="123456",
        help="login password (default: 123456)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8321,
        help="server port (default: 8321)"
    )
    return parser.parse_args()


project_root = os.getcwd()
queue_db_path = os.path.join(project_root, ".auto-coder", "chat-bot.db")
AUTH_COOKIE = "agent_auth"

# ===== 任务队列和连接管理 =====
active_connections: Dict[str, WebSocket] = {}  # 客户端ID -> WebSocket


async def watch_process(process, run_id):
    try:
        exit_code = await asyncio.to_thread(process.wait)
        if exit_code == 0:
            sqlite_queue.finish_agent_run(queue_db_path, run_id, "finished")
        else:
            sqlite_queue.finish_agent_run(queue_db_path, run_id, "failed")
    except Exception as e:
        sqlite_queue.finish_agent_run(queue_db_path, run_id, "failed", str(e))


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
    # ===== shutdown ===== 关闭时：清理任务和连接
    print("开始关闭服务...")

    # 1 关闭消费者
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        print("消费者已取消")

    # 2 关闭 websocket
    for ws in active_connections.values():
        await ws.close()
    active_connections.clear()

    # 3 kill 所有运行中的 agent
    running_runs = sqlite_queue.list_running_runs(queue_db_path)
    for run in running_runs:
        pid = run["pid"]
        run_id = run["run_id"]
        try:
            os.kill(pid, 9)
            print(f"已终止 Agent PID={pid}")
        except ProcessLookupError:
            print(f"进程不存在 PID={pid}")
        sqlite_queue.finish_agent_run(queue_db_path, run_id, "killed")
    print("Agent 清理完成")

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
                # 决定是否 new session
                today_user_messages_size = await asyncio.get_running_loop().run_in_executor(
                    None, sqlite_queue.fetch_user_messages_size_bytime,
                    queue_db_path, datetime.now().strftime("%Y-%m-%d")
                )
                agent_start_command = ['auto-coder.nano', '--agent-model', '--agent-query', f'{content}']
                if today_user_messages_size == 1:
                    # todo 开启新 session 前，将前一天的数据总结后形成 memory 文件
                    agent_start_command.append('--agent-new-session')

                run_id = str(uuid.uuid4())
                process = subprocess.Popen(agent_start_command,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                await asyncio.get_running_loop().run_in_executor(
                    None, sqlite_queue.insert_agent_run,
                    queue_db_path, run_id, client_id, conversation_id, message_id, content, process.pid
                )
                asyncio.create_task(watch_process(process, run_id))
    except WebSocketDisconnect:
        active_connections.pop(client_id, None)
        print(f"客户端 {client_id} 断开连接")


# ===== HTTP 页面入口 =====
@app.get("/")
async def get_index(request: Request):
    if request.cookies.get(AUTH_COOKIE) != "ok":
        return RedirectResponse("/login")
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/runs")
async def list_runs():
    runs = sqlite_queue.list_agent_runs(queue_db_path)
    return {
        "runs": runs
    }


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = sqlite_queue.get_agent_run(queue_db_path, run_id)
    if not run:
        raise HTTPException(
            status_code=404,
            detail="run not found"
        )
    return run


@app.post("/runs/{run_id}/kill")
async def kill_run(run_id: str):
    run = sqlite_queue.get_agent_run(queue_db_path, run_id)
    if not run:
        raise HTTPException(
            status_code=404,
            detail="run not found"
        )
    if run["status"] != "running":
        return {
            "status": "ignored",
            "reason": f"run already {run['status']}"
        }
    pid = run["pid"]

    try:
        os.kill(pid, 9)
        sqlite_queue.finish_agent_run(queue_db_path, run_id, "killed")
        return {
            "status": "killed",
            "run_id": run_id
        }
    except ProcessLookupError:
        sqlite_queue.finish_agent_run(queue_db_path, run_id, "failed", "process not found")
        return {
            "status": "process_missing"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.post("/login")
async def login(request: Request):
    data = await request.json()
    username = data.get("username")
    password = data.get("password")

    if username == USERNAME and password == PASSWORD:
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            key=AUTH_COOKIE,
            value="ok",
            httponly=True
        )
        return response
    return {"success": False}


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request}
    )


@app.post("/logout")
async def logout():
    response = JSONResponse({"success": True})
    response.delete_cookie(AUTH_COOKIE)
    return response


def main():
    global USERNAME, PASSWORD

    args = parse_args()
    USERNAME = args.username
    PASSWORD = args.password

    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == '__main__':
    main()
