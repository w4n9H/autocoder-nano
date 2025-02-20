import argparse
from typing import Optional, List

from autocoder_nano.llm_client import AutoLLM
from autocoder_nano.llm_types import AutoCoderArgs, ServerArgs
from autocoder_nano.rag.api_server import serve
from autocoder_nano.rag.doc_entry import RAGFactory


def main(input_args: Optional[List[str]] = None):
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
        "--hybrid_index_max_output_tokens", type=int, default=1000000,
        help="输出中的最大令牌数。仅在启用混合索引时使用。",
    )
    serve_parser.add_argument(
        "--disable_segment_reorder", action="store_true", help="禁用检索后文档段落的重新排序"
    )
    serve_parser.add_argument(
        "--disable_inference_enhance", action="store_true", help="禁用增强推理模式",
    )
    serve_parser.add_argument("--api_key", default="", help="API key for AI client")
    serve_parser.add_argument("--base_url", default="", help="Base URL")
    serve_parser.add_argument("--model_name", default="", help="Model Name")

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

        # 优化后的版本
        if any([not args.api_key, not args.base_url, not args.model_name]):
            missing = []
            if not args.api_key:
                missing.append("api_key")
            if not args.base_url:
                missing.append("base_url")
            if not args.model_name:
                missing.append("model_name")
            raise ValueError(f"缺少必要参数: {', '.join(missing)}")

        auto_llm = AutoLLM()
        # 将整个 RAG 召回划分成三个大的阶段
        # 1. recall_model: Recall召回阶段
        # 2. chunk_model: 动态片段抽取阶段
        # 3. qa_model: 问题回答阶段
        auto_llm.setup_sub_client("recall_model", args.api_key, args.base_url, args.model_name)
        auto_llm.setup_sub_client("chunk_model", args.api_key, args.base_url, args.model_name)
        auto_llm.setup_sub_client("qa_model", args.api_key, args.base_url, args.model_name)

        # 启动示例
        # auto-coder.nano.rag serve --port 8102 --doc_dir /Users/moofs/Code/antiy-rag/data --tokenizer_path
        # /Users/moofs/Code/antiy-rag/tokenizer.json --base_url https://ark.cn-beijing.volces.com/api/v3 --api_key
        # xxxxx --model_name xxxxx --disable_inference_enhance

        if not server_args.doc_dir:
            raise Exception("doc_dir is required")
        if not server_args.tokenizer_path:
            raise Exception("tokenizer_path is required")

        rag = RAGFactory.get_rag(
            llm=auto_llm,
            args=auto_coder_args,
            path=server_args.doc_dir,
            tokenizer_path=server_args.tokenizer_path,
        )
        serve(rag=rag, ser=server_args)
    elif args.command == "build_hybrid_index":
        pass


if __name__ == '__main__':
    main()
