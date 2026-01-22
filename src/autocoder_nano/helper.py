from rich.text import Text

from autocoder_nano.utils.printer_utils import Printer

printer = Printer()


def show_help():
    help_prefix = ""
    printer.print_text(Text.assemble(("支持的命令：", 'bold')), prefix=help_prefix)
    printer.print_text(Text.assemble(("  命令", "cyan"), (" - ", "default"), ("描述", "green")), prefix=help_prefix)

    commands_data = [
        ("/auto", " <query>", "使用Agent完成你的任务"),
        ("    /auto /new", " <query>", "创建一个新的会话来完成任务"),
        ("    /auto /resume", " <query>", "使用历史会话来继续完成任务"),
        ("/chat", " <query>", "与AI聊天，获取关于当前活动文件的见解"),
        ("    /chat /new", " <query>", "开启一个新的AI会话,此时历史沟通记录会移除,不会通过/history显示"),
        ("    /chat /history", "", "显示你与AI最近几条沟通记录"),
        ("/coding", " <query>", "根据需求请求AI修改当前活动文件代码"),
        ("    /coding /apply", " <query>", "会带上/chat历史记录与AI沟通,会被/chat /new重置"),
        ("/help", "", "显示此帮助消息"),
        ("/models", " <subcommand>", "管理LLM模型(/models /list查看,/models /add添加)"),
        ("    /models /list", "", "列出所有部署模型"),
        ("    /models /add", "", "添加新的模型"),
        ("    /models /check", "", "检查所有部署模型的可用性"),
        ("/conf", " <key>:<value>", "使用/conf <args>:<type>设置你的AutoCoder配置"),
        ("/index", "", "与索引相关的操作"),
        ("    /index /code", "", "触发构建项目代码索引"),
        ("    /index /rag", "", "为/conf rag_url:<local_path> 设置的目录构建RAG索引"),
        ("/git", "", "与Git相关的操作"),
        ("    /git /revert", "", "撤销上次由 /auto 或 /coding 提交的代码"),
        ("    /git /commit", "", "根据用户人工修改的代码自动生成yaml文件并提交更改"),
        ("/rules", "", "基于当前活动文件或者Commit变更生成功能模式和设计模式"),
        ("/add_files", " <file1> <file2> ...", "将文件添加到当前会话"),
        ("    /add_files /refresh", "", "刷新文件，用于新增文件后但是通过/add_files无法添加时"),
        ("/list_files", "", "列出当前会话中的所有活跃文件"),
        ("/remove_files", " <file1>,<file2> ...", "从当前会话中移除文件"),
        ("    /remove_files /all", "", "移除当前会话中的全部活跃文件"),
        ("/exclude_dirs", " <dir1>,<dir2> ...", "添加要从项目中排除的目录"),
        ("/exclude_files", " <pattern>/<subcommand>", "排除文件(/exclude_files /list查看,/exclude_files /drop删除)"),
        ("/exit", "", "退出程序"),
    ]

    for cmd, args, desc in commands_data:
        printer.print_text(Text.assemble(
            ("  ", "default"),
            (cmd, "cyan"),
            (args, "yellow"),
            (" - ", "default"),
            (desc, "green")
        ), prefix=help_prefix)

    print()
