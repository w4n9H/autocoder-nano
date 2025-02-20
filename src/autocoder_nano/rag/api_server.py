import json
import time
from typing import List, Optional, Generator

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel
from uvicorn import run as serve_run

from autocoder_nano.llm_types import ServerArgs
from autocoder_nano.rag.long_context_rag import LongContextRAG

app = FastAPI()
openai_serving_chat: LongContextRAG = None


# 定义与 OpenAI 兼容的请求/响应模型
# --- 定义数据结构 ---
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = "moofs"
    max_tokens: Optional[int] = 100
    temperature: Optional[float] = 1.0
    stream: Optional[bool] = False


class Model(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "local"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: List[Model]


# 实现 OpenAI 兼容的接口
@app.get("/v1/models", response_model=ModelListResponse)
async def list_models():
    return ModelListResponse(data=[
        Model(id="moofs", owned_by="openai"),  # LiteLLM 需要此字段
        Model(id="openai/moofs", owned_by="openai")  # 双格式兼容
    ])


# 流式格式工具函数（增强版）
def format_stream_response(content_chunk: str, _model_name: str) -> str:
    """构建兼容OpenAI的流式响应"""
    response_json = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": _model_name,
        "choices": [{
            "index": 0,
            "delta": {
                "content": content_chunk,
                # 可选：添加角色标识
                "role": "assistant"
            },
            "finish_reason": None
        }],
        # 可选：添加自定义元数据
        "custom_metadata": {
            "chunk_id": f"chk_{time.time_ns()}"
        }
    }
    json_str = json.dumps(response_json, ensure_ascii=False)
    return f"data: {json_str}\n\n"


# 增强模型解析逻辑
def resolve_model(model_name: str) -> str:
    """处理 openai/antiy 格式的模型名"""
    if "/" in model_name:
        return model_name.split("/")[1]
    return model_name


# --- 统一处理聊天请求 ---
@app.post("/v1/chat/completions")
async def chat_completion(request: ChatCompletionRequest, authorization: str = Header(None),):
    # 验证 API Key（示例仅做简单校验）
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid API Key")

    actual_model = resolve_model(request.model)

    # 合并对话历史
    # prompt = "\n".join([f"{msg.role}: {msg.content}" for msg in request.messages])
    conversations = []
    for msg in request.messages:
        conversations.append({"role": msg.role, "content": msg.content})

    # 调用你的自定义大模型函数
    try:
        content_generator, context = openai_serving_chat.stream_chat_oai(conversations)

        # 流式响应
        if request.stream:
            def stream_wrapper() -> Generator[str, None, None]:
                try:
                    for content_chunk in content_generator:
                        # 生成标准格式的流式响应
                        yield format_stream_response(content_chunk, request.model)

                        # 如果需要实时发送上下文（可选）
                        # yield format_context_metadata(context)

                    # 添加最终上下文（可选）
                    final_ctx = f"\n[相关上下文]: {str(context)[:200]}..."  # 截断长文本
                    final_ctx = f"\n[相关上下文]: {str(context)[:200]}..."  # 截断长文本
                    yield format_stream_response(final_ctx, request.model)

                    yield "data: [DONE]\n\n"
                except Exception as err:
                    error_json = json.dumps({"error": str(err)})
                    yield f"data: {error_json}\n\n"

            return StreamingResponse(stream_wrapper(), media_type="text/event-stream")

        # 非流式响应
        else:
            # 收集所有内容块
            full_content = "".join([chunk for chunk in content_generator])

            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_content,
                        # 如果需要附加上下文元数据
                        "context": context.dict() if hasattr(context, "dict") else str(context)
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": len(str(request.messages)),
                    "completion_tokens": len(full_content),
                    "total_tokens": len(str(request.messages)) + len(full_content),
                    "context_sources": getattr(context, "sources", [])  # 假设上下文包含来源
                }
            }

    except Exception as e:
        raise HTTPException(500, detail=str(e))


def serve(rag: LongContextRAG, ser: ServerArgs):
    logger.info(f"RAG API 服务启动 ...")
    global openai_serving_chat
    openai_serving_chat = rag
    # 允许跨域请求（如果前端需要）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ser.allowed_origins,
        allow_credentials=ser.allow_credentials,
        allow_methods=ser.allowed_methods,
        allow_headers=ser.allowed_headers,
    )
    serve_run(
        app,
        host=ser.host,
        port=ser.port,
        log_level=ser.uvicorn_log_level,
        timeout_keep_alive=5
    )