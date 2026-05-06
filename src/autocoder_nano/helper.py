from rich.text import Text

from autocoder_nano.utils.printer_utils import Printer

printer = Printer()


def show_help():
    help_prefix = ""
    printer.print_text(Text.assemble(("支持的命令：", 'bold')), prefix=help_prefix)
    printer.print_text(Text.assemble(("  命令", "cyan"), (" - ", "default"), ("描述", "green")), prefix=help_prefix)

    commands_data = [
        ("/auto", " <query> | /new | /resume", "使用Agent完成你的任务, /new新建会话, /resume继续会话"),
        ("/chat", " <query> | /new | /history", "与AI聊天, /new新建会话, /history查看历史记录"),
        ("/coding", " <query> | /apply", "修改当前活动文件代码, /apply会带上历史记录"),
        ("/help", "", "显示此帮助消息"),
        ("/models", " <subcommand>", "管理LLM模型"),
        ("    /models /list", "", "列出所有部署模型"),
        ("    /models /add", "", "添加新的模型"),
        ("    /models /check", "", "检查所有部署模型的可用性"),
        ("/conf", " <key>:<value>", "设置AutoCoder配置"),
        ("/git", " | /revert | /commit", "Git操作, /revert撤销, /commit自动生成yaml提交"),
        ("/rules", "", "基于当前活动文件或Commit变更生成功能模式和设计模式"),
        ("/add_files", " <file1> <file2> ... | /refresh", "将文件添加到当前会话, /refresh刷新"),
        ("/list_files", "", "列出当前会话中的所有活跃文件"),
        ("/remove_files", " <file1>,<file2> ... | /all", "从当前会话中移除文件, /all移除全部"),
        ("/exclude_dirs", " <dir1>,<dir2> ...", "添加要从项目中排除的目录"),
        ("/exclude_files", " <pattern> | /list | /drop", "排除文件, /list查看, /drop删除"),
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
