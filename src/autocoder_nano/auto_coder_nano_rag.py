import argparse
import json
import os
from typing import Optional, List
from importlib import resources

from autocoder_nano.llm_client import AutoLLM
from autocoder_nano.llm_types import AutoCoderArgs, ServerArgs
from autocoder_nano.rag.api_server import serve
from autocoder_nano.rag.doc_entry import RAGFactory


def main(input_args: Optional[List[str]] = None):
    try:
        tokenizer_path = resources.files("autocoder_nano").joinpath("data/tokenizer.json").__str__()
    except FileNotFoundError:
        tokenizer_path = None

    parser = argparse.ArgumentParser(description="Auto Coder Nano RAG Server")
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
    serve_parser.add_argument("--ssl_keyfile", default="",
                              help="SSL密钥文件路径(需与证书文件配合启用HTTPS)")
    serve_parser.add_argument("--ssl_certfile", default="",
                              help="SSL证书文件路径(需与密钥文件配合启用HTTPS)")
    serve_parser.add_argument("--response_role", default="assistant",
                              help="API响应中使用的角色标识 (默认: assistant)")
    serve_parser.add_argument("--doc_dir", default="",
                              help="文档存储目录路径(必填参数)")
    serve_parser.add_argument("--tokenizer_path", default=tokenizer_path,
                              help=f"预训练分词器路径(必填参数)")
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

    # Build hybrid index command
    build_index_parser = subparsers.add_parser(
        "build_hybrid_index", help="Build hybrid index for RAG"
    )
    # build_index_parser.add_argument("--emb_model", default="", help="")
    build_index_parser.add_argument(
        "--tokenizer_path", default=tokenizer_path, help="预训练分词器路径(必填参数)")
    build_index_parser.add_argument("--doc_dir", default="", help="文档存储目录路径(必填参数)")
    build_index_parser.add_argument("--enable_hybrid_index", action="store_true", help="启用混合索引")
    build_index_parser.add_argument(
        "--required_exts", default="", help="文档构建所需的文件扩展名, 默认为空字符串")
    build_index_parser.add_argument(
        "--emb_model", default="", help="指定使用的向量化模型",
    )

    args = parser.parse_args(input_args)

    if args.command == "benchmark":
        pass
    elif args.command == "serve":
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

        # 启动示例
        # auto-coder.nano.rag serve --port 8102 --doc_dir /Users/moofs/Code/antiy-rag/data --tokenizer_path
        # /Users/moofs/Code/antiy-rag/tokenizer.json --base_url https://ark.cn-beijing.volces.com/api/v3 --api_key
        # xxxxx --model_name xxxxx --disable_inference_enhance

        rag = RAGFactory.get_rag(
            llm=auto_llm,
            args=auto_coder_args,
            path=server_args.doc_dir,
            tokenizer_path=server_args.tokenizer_path,
        )
        serve(rag=rag, ser=server_args)
    elif args.command == "build_hybrid_index":
        auto_coder_args = AutoCoderArgs(
            **{arg: getattr(args, arg) for arg in vars(AutoCoderArgs()) if hasattr(args, arg)}
        )

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
        if args.emb_model and args.emb_model in models:
            auto_llm.setup_sub_client(
                "emb_model",
                models[args.emb_model]["api_key"],
                models[args.emb_model]["base_url"],
                models[args.emb_model]["model"],
            )

        rag = RAGFactory.get_rag(
            llm=auto_llm,
            args=auto_coder_args,
            path=args.doc_dir,
            tokenizer_path=args.tokenizer_path
        )

        if hasattr(rag.document_retriever, "cacher"):
            rag.document_retriever.cacher.build_cache()
        else:
            raise ValueError(f"文档检索器不支持混合索引构建")


if __name__ == '__main__':
    main()
