import argparse
import logging
import sys
import uvicorn

from loguru import logger

from autocoder_nano.gateway import GatewayServer, GatewayConfig


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='OpenClaw Gateway Server (FastAPI + Uvicorn)',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # 服务器配置
    parser.add_argument('--host', default='0.0.0.0', help='服务器监听地址')
    parser.add_argument('--port', type=int, default=8080, help='服务器端口')
    # 认证配置
    parser.add_argument('--token', default='demo-token-12345', help='认证Token')
    parser.add_argument('--password', help='认证密码（可选）')
    parser.add_argument('--no-auth', action='store_true', help='禁用认证（不推荐）')
    # 高级配置
    parser.add_argument('--max-connections', type=int, default=1000, help='最大连接数')
    parser.add_argument('--rate-limit', type=int, default=100, help='每分钟每IP最大请求数')
    # Uvicorn配置
    parser.add_argument('--workers', type=int, default=1, help='工作进程数（生产环境建议设置）')
    parser.add_argument('--reload', action='store_true', help='启用自动重载（开发环境）')
    parser.add_argument('--ssl-cert', help='SSL证书文件路径')
    parser.add_argument('--ssl-key', help='SSL密钥文件路径')
    # 其他选项
    parser.add_argument('--verbose', '-v', action='store_true', help='启用详细日志')

    return parser.parse_args()


def run_gateway_server():
    args = parse_args()
    # 配置日志
    logger.configure(
        handlers=[
            {
                "sink": sys.stdout,
                "level": "DEBUG" if args.verbose else "INFO",
                "format": "{time:HH:mm:ss} | {level} | {message}",
                "colorize": True
            }
        ]
    )
    logger.info("=" * 60)
    logger.info("Supa Nano Gateway Server")
    logger.info("=" * 60)

    # 创建认证配置
    auth_config = {
        "mode": "none" if args.no_auth else "token",
        "token": args.token,
        "rate_limit_enabled": args.rate_limit > 0,
        "rate_limit_requests": args.rate_limit,
        "rate_limit_window_ms": 60000
    }
    if args.password:
        auth_config["password"] = args.password

    # 创建Gateway配置
    gateway_config = GatewayConfig(
        host=args.host,
        port=args.port,
        auth_config=auth_config,
        max_connections=args.max_connections
    )

    # 创建Gateway服务器
    server = GatewayServer(gateway_config)

    # 打印信息
    logger.info("")
    logger.info("Server Configuration:")
    logger.info(f"  Host: {args.host}")
    logger.info(f"  Port: {args.port}")
    logger.info(f"  Workers: {args.workers}")
    logger.info("Endpoints:")
    logger.info(f"  HTTP API: http://{args.host}:{args.port}")
    logger.info(f"  WebSocket: ws://{args.host}:{args.port}/gateway")
    logger.info(f"  Health: http://{args.host}:{args.port}/health")
    logger.info(f"  Version: http://{args.host}:{args.port}/version")
    if not args.no_auth:
        logger.info("Authentication:")
        logger.info(f"  Token: {args.token}")
        logger.info("")
    logger.info("Press Ctrl+C to stop the server")
    logger.info("")

    # 使用uvicorn启动
    app = server.get_app()

    # 配置uvicorn
    uvicorn_config = {
        "host": args.host,
        "port": args.port,
        "workers": args.workers if not args.reload else 1,
        "reload": args.reload,
        "log_level": "debug" if args.verbose else "info",
    }

    if args.ssl_cert and args.ssl_key:
        uvicorn_config["ssl_certfile"] = args.ssl_cert
        uvicorn_config["ssl_keyfile"] = args.ssl_key

    # 启动服务器
    uvicorn.run(app, **uvicorn_config)


def main():
    try:
        run_gateway_server()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)