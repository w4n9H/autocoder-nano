import argparse
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Optional, List, Generator
from importlib import resources
from pathlib import Path
import autocoder_nano

from fastapi import APIRouter, Request
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from uvicorn import run as serve_run
from loguru import logger

from autocoder_nano.llm_client import AutoLLM
from autocoder_nano.llm_types import ServerArgs, AutoCoderArgs
from autocoder_nano.rag.doc_entry import RAGFactory
from autocoder_nano.rag.long_context_rag import LongContextRAG


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化操作
    yield
    # 清理操作

# FastAPI, APIRouter 初始化
app = FastAPI(lifespan=lifespan)
router = APIRouter()

serving_chat: LongContextRAG | None = None

# 配置静态文件
app.mount("/static", StaticFiles(directory=Path(autocoder_nano.__file__).parent / "app/static"), name="static")
templates = Jinja2Templates(directory=Path(autocoder_nano.__file__).parent / "app/templates")


def timestamp() -> str:  # 添加全局模板变量
    return str(int(time.time()))


templates.env.globals.update({
    'timestamp': timestamp,
    'debug': True
})


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    cache_size = serving_chat.document_retriever.get_cache_size()
    project_name = os.path.basename(serving_chat.path)
    enable_hybrid_index = serving_chat.args.enable_hybrid_index
    hybrid_index_max_output_tokens = serving_chat.args.hybrid_index_max_output_tokens
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "title": "AutoCoder Nano UI",
            "project": project_name,
            "cache_size": cache_size,
            "enable_hybrid_index": enable_hybrid_index,
            "hybrid_index_max_output_tokens": hybrid_index_max_output_tokens
        }
    )


# 模拟思考过程的句子
thinking_phrases = [
    "正在分析您的问题...",
    "正在查阅相关资料...",
    "正在整合多源信息...",
    "正在验证解决方案的可靠性...",
    "正在优化最终回答..."
]


async def generate_response_stream(prompt: str):
    for phrase in thinking_phrases:
        yield f"data: <thinking>{phrase}\n\n"  # SSE格式
        await asyncio.sleep(0.5)

    answer = "根据您的问题，经过综合分析，以下是详细解答：（此处为模拟回答内容）"
    yield f'data: \n\n'  # 初始容器+刷新

    for char in answer:
        yield f"data: {char}\n\n"  # 每个字符后刷新
        await asyncio.sleep(0.1)

    yield "data: \n\n"


@app.get("/chat")  # 改为 GET 方法
async def chat_stream(request: Request):
    prompt = request.query_params.get("prompt")  # 从查询参数获取

    conversations = [{"role": "user", "content": prompt}]
    # content_generator, context = openai_serving_chat.stream_chat_oai(conversations)

    # 流式响应
    if request.stream:
        async def stream_wrapper():
            await asyncio.sleep(0.5)

            yield f"data: <thinking>启用混合索引: {serving_chat.enable_hybrid_index}\n\n"
            await asyncio.sleep(0.5)

            yield f"data: <thinking>启用联网搜索: False\n\n"
            await asyncio.sleep(0.5)

            yield f"data: <thinking>启用深度思考: False\n\n"
            await asyncio.sleep(0.5)

            yield f"data: <thinking>加载缓存文件: {serving_chat.document_retriever.get_cache_size()} 个\n\n"
            await asyncio.sleep(0.5)

            source_list, stp1_time = serving_chat.search_step1(conversations)
            yield f"data: <thinking>正在进行文档检索, 共检索 {len(source_list)} 个文档, 耗时 {stp1_time:.2f} 秒\n\n"

            relevant_docs, stp2_time = serving_chat.search_step2(conversations, source_list)
            yield f"data: <thinking>正在进行文档过滤, 共过滤 {len(relevant_docs)} 个文档, 耗时 {stp2_time:.2f} 秒\n\n"

            relevant_docs_source, stp3_time = serving_chat.search_step3(conversations, relevant_docs)
            yield f"data: <thinking>正在进行文档裁剪, 最终发送到模型共 {len(relevant_docs_source)} 个文档, 耗时 {stp3_time:.2f} 秒\n\n"

            try:
                content_generator, context = serving_chat.search_step4(prompt, conversations, relevant_docs_source)
                yield f'data: \n\n'  # 初始容器+刷新
                for content_chunk in content_generator:
                    # 生成标准格式的流式响应
                    # yield f"data: {content_chunk}\n\n"
                    if content_chunk:
                        yield f"data: {json.dumps({'content': content_chunk})}\n\n"
                # yield "data: \n\n"
                yield "data: [DONE]\n\n"
            except Exception as err:
                error_json = json.dumps({"error": str(err)})
                yield f"data: {error_json}\n\n"

        return StreamingResponse(stream_wrapper(), media_type="text/event-stream")


app.include_router(router)  # 包含路由


def serve(rag: LongContextRAG, ser: ServerArgs):
    logger.info(f"Auto-Coder Nano UI 服务启动 ...")
    global serving_chat
    serving_chat = rag
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


def main(input_args: Optional[List[str]] = None):
    try:
        tokenizer_path = resources.files("autocoder_nano").joinpath("data/tokenizer.json").__str__()
    except FileNotFoundError:
        tokenizer_path = None

    parser = argparse.ArgumentParser(description="Auto-Coder Nano UI Server")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    serve_parser = subparsers.add_parser("serve", help="启动 RAG 服务")
    serve_parser.add_argument("--host", default="0.0.0.0", help="绑定主机地址 (默认: 0.0.0.0)")
    serve_parser.add_argument("--port", type=int, default=8000, help="监听端口号 (默认: 8000)")
    serve_parser.add_argument("--uvicorn_log_level", default="info",
                              help="Uvicorn日志级别 [debug|info|warning|error|critical] (默认: info)")
    serve_parser.add_argument("--allow_credentials", action="store_true",
                              help="允许跨域请求携带凭证(如cookies、授权头)")
    serve_parser.add_argument("--allowed_origins", default=["*"],
                              help="允许的CORS来源，支持列表格式 (默认: ['*'])")
    serve_parser.add_argument("--allowed_methods", default=["*"],
                              help="允许的HTTP方法，如GET/POST (默认: ['*'])")
    serve_parser.add_argument("--allowed_headers", default=["*"],
                              help="允许的HTTP请求头 (默认: ['*'])")
    serve_parser.add_argument("--doc_dir", default="",
                              help="文档存储目录路径(必填参数)")
    serve_parser.add_argument("--tokenizer_path", default=tokenizer_path,
                              help=f"预训练分词器路径")
    serve_parser.add_argument(
        "--rag_doc_filter_relevance", type=int, default=6, help="过滤器相关性"
    )
    serve_parser.add_argument(
        "--rag_context_window_limit", type=int, default=30000, help="RAG 输入上下文窗口的限制(默认30k)"
    )
    serve_parser.add_argument(
        "--full_text_ratio", type=float, default=0.7,
        help="输入上下文窗口中完整文本区域的比例(0.0 - 1.0, 默认0.7)",
    )
    serve_parser.add_argument(
        "--segment_ratio", type=float, default=0.2, help="输入上下文窗口中分段区域的比例(0.0 - 1.0, 默认0.2)",
    )
    serve_parser.add_argument("--required_exts", default="", help="文档构建所需的文件扩展名, 默认为空字符串")
    serve_parser.add_argument("--monitor_mode", action="store_true", help="文档更新的监控模式", )
    serve_parser.add_argument("--enable_hybrid_index", action="store_true", help="启用混合索引", )
    serve_parser.add_argument("--disable_auto_window", action="store_true", help="禁用文档的自动窗口适配", )
    serve_parser.add_argument(
        "--hybrid_index_max_output_tokens", type=int, default=30000,
        help="输出中的最大令牌数。仅在启用混合索引时使用。",
    )
    serve_parser.add_argument(
        "--disable_segment_reorder", action="store_true", help="禁用检索后文档段落的重新排序"
    )
    serve_parser.add_argument(
        "--disable_inference_enhance", action="store_true", help="禁用增强推理模式",
    )
    serve_parser.add_argument(
        "--emb_model", default="", help="指定使用的向量化模型",
    )
    serve_parser.add_argument(
        "--recall_model", default="", help="指定Recall召回阶段使用的模型",
    )
    serve_parser.add_argument(
        "--chunk_model", default="", help="指定动态片段抽取阶段使用的模型",
    )
    serve_parser.add_argument(
        "--qa_model", default="", help="指定问题回答阶段使用的模型",
    )

    args = parser.parse_args(input_args)

    server_args = ServerArgs(
        **{arg: getattr(args, arg) for arg in vars(ServerArgs()) if hasattr(args, arg)}
    )
    auto_coder_args = AutoCoderArgs(
        **{arg: getattr(args, arg) for arg in vars(AutoCoderArgs()) if hasattr(args, arg)}
    )

    if any([
        not args.doc_dir,
        not args.emb_model,
        not args.recall_model,
        not args.qa_model
    ]):
        missing = []
        if not args.doc_dir:
            missing.append("doc_dir")
        if not args.emb_model:
            missing.append("emb_model")
        if not args.recall_model:
            missing.append("recall_model")
        if not args.qa_model:
            missing.append("qa_model")
        raise ValueError(f"缺少必要参数: {', '.join(missing)}")

    if not server_args.tokenizer_path:
        raise Exception("tokenizer_path is required")

    project_root = args.doc_dir
    base_persist_dir = os.path.join(project_root, ".auto-coder", "plugins", "chat-auto-coder")
    memory_path = os.path.join(base_persist_dir, "nano-memory.json")

    if os.path.exists(memory_path):
        with open(memory_path, "r") as f:
            memory = json.load(f)
    else:
        raise ValueError(f"请运行 auto-coder.nano 对该项目进行初始化")

    models = memory.get("models", {})

    auto_llm = AutoLLM()
    # 将整个 RAG 召回划分成三个大的阶段
    # 开启混合索引(预处理步骤): 使用向量搜索/全文检索进行首轮过滤
    # 1. recall_model: Recall召回阶段
    # 2. chunk_model: 动态片段抽取阶段
    # 3. qa_model: 问题回答阶段
    if args.emb_model and args.emb_model in models:
        auto_llm.setup_sub_client(
            "emb_model",
            models[args.emb_model]["api_key"],
            models[args.emb_model]["base_url"],
            models[args.emb_model]["model"],
        )
    if args.recall_model and args.recall_model in models:
        auto_llm.setup_sub_client(
            "recall_model",
            models[args.recall_model]["api_key"],
            models[args.recall_model]["base_url"],
            models[args.recall_model]["model"],
        )
    if args.chunk_model and args.chunk_model in models:
        auto_llm.setup_sub_client(
            "chunk_model",
            models[args.chunk_model]["api_key"],
            models[args.chunk_model]["base_url"],
            models[args.chunk_model]["model"],
        )
    if args.qa_model and args.qa_model in models:
        auto_llm.setup_sub_client(
            "qa_model",
            models[args.qa_model]["api_key"],
            models[args.qa_model]["base_url"],
            models[args.qa_model]["model"],
        )

    rag = RAGFactory.get_rag(
        llm=auto_llm,
        args=auto_coder_args,
        path=server_args.doc_dir,
        tokenizer_path=server_args.tokenizer_path,
    )

    serve(rag=rag, ser=server_args)


if __name__ == '__main__':
    main()