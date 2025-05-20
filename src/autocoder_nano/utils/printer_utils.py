import time
from typing import Any, Optional, List, Union, Dict, Iterable, Generator
from contextlib import contextmanager
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.box import Box, ROUNDED
from rich.columns import Columns
from rich.emoji import Emoji
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn


class Printer:
    def __init__(self, console: Optional[Console] = None):
        """
        增强版富文本打印机
        :param console: 可传入自定义的Rich Console实例
        """
        self.console = console or Console()
        self._live: Optional[Live] = None
        self._progress: Optional[Progress] = None

    def print_table(
        self, data: Iterable[Iterable[Any]], title: Optional[str] = None, headers: Optional[List[str]] = None,
        show_lines: bool = False, expand: bool = False, caption: Optional[str] = None
    ) -> None:
        """
        打印表格
        :param data: 二维可迭代数据
        :param title: 表格标题
        :param headers: 列标题列表
        :param show_lines: 是否显示行分隔线
        :param expand: 是否扩展表格宽度
        :param caption: 底部说明文字
        """
        table = Table(
            title=title, show_header=bool(headers), show_lines=show_lines, expand=expand,
            caption=caption, padding=(0, 1)
        )

        if headers:
            for header in headers:
                table.add_column(header, style="cyan", header_style="bold magenta")

        for row in data:
            styled_row = [str(item) if not isinstance(item, Text) else item for item in row]
            table.add_row(*styled_row)

        self.console.print(table)

    def print_markdown(self, text: str, panel: bool = False) -> None:
        """打印Markdown文本"""
        md = Markdown(text)
        self._print_with_panel(md, panel)

    def print_code(
        self, code: str, lexer: str = "python", theme: str = "monokai", line_numbers: bool = True
    ) -> None:
        """高亮打印代码块"""
        syntax = Syntax(
            code,
            lexer,
            theme=theme,
            line_numbers=line_numbers,
            padding=(0, 2)
        )
        self.console.print(syntax)

    def print_panel(
        self, content: Any, title: Optional[str] = None, border_style: str = "bold yellow", width: Optional[int] = None
    ) -> None:
        """带边框的面板输出"""
        panel = Panel(
            content,
            title=title,
            border_style=border_style,
            width=width,
            padding=(1, 2)
        )
        self.console.print(panel)

    def print_text(
        self, *texts: Union[str, Text], style: Optional[str] = None, justify: Optional[str] = "left"
    ) -> None:
        """灵活文本打印，支持样式和混合内容"""
        rich_text = Group(*[
            Text(str(t), style=style) if isinstance(t, str) else t
            for t in texts
        ])
        self.console.print(rich_text, justify=justify)

    @contextmanager
    def live_context(self, refresh_per_second: float = 4.0) -> Generator[None, Any, None]:
        """动态内容上下文管理器"""
        with Live(console=self.console, refresh_per_second=refresh_per_second) as live:
            self._live = live
            try:
                yield
            finally:
                self._live = None

    def update_live(self, content: Any) -> None:
        """更新动态内容"""
        if self._live:
            self._live.update(content)

    @contextmanager
    def progress_context(self) -> Generator[Progress, Any, None]:
        """进度条上下文管理器"""
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console
        )
        with self._progress:
            yield self._progress
            self._progress = None

    def print_card(
        self, content: Union[str, Text, Markdown, Syntax], title: Optional[str] = None, border_style: str = "blue",
        width: Optional[int] = 40, icon: Optional[str] = None, box: Box = ROUNDED
    ) -> None:
        """
        基础卡片输出
        :param content: 内容（支持多种格式）
        :param title: 卡片标题
        :param border_style: 边框样式
        :param width: 卡片宽度
        :param icon: 标题前图标（支持Emoji）
        :param box: 边框样式（来自rich.box）
        """
        if icon:
            title = f"{Emoji(icon)} {title}" if title else Emoji(icon)

        panel = Panel(
            content,
            title=title,
            box=box,
            border_style=border_style,
            width=width,
            padding=(1, 2)
        )
        self.console.print(panel)

    def multi_col_cards(
        self, cards: List[Dict[str, Any]], columns: int = 3, equal: bool = True
    ) -> None:
        """
        多列卡片布局
        :param cards: 卡片参数列表
        :param columns: 显示列数
        :param equal: 是否等宽
        """
        rendered_cards = []
        for card in cards:
            content = card.get("content", "")
            if isinstance(content, str):
                # 自动识别Markdown
                if content.strip().startswith(("#", "-", "*")):
                    content = Markdown(content)

            rendered = Panel(
                content,
                title=card.get("title"),
                box=card.get("box", ROUNDED),
                border_style=card.get("border_style", "dim blue"),
                width=card.get("width")
            )
            rendered_cards.append(rendered)

        self.console.print(Columns(rendered_cards, equal=equal))

    def status_card(
        self, message: str, status: str = "info", title: Optional[str] = None
    ) -> None:
        """
        状态卡片（预设样式）
        :param status: 状态类型（info/success/warning/error）
        :param message: 主要内容
        :param title: 可选标题
        """
        config = {
            "info": {"icon": "ℹ️", "color": "cyan"},
            "success": {"icon": "✅", "color": "green"},
            "warning": {"icon": "⚠️", "color": "yellow"},
            "error": {"icon": "❌", "color": "red"}
        }.get(status.lower(), {})

        title_text = Text()
        if config.get("icon"):
            title_text.append(f"{config['icon']}  ")
        if title:
            title_text.append(title, style=f"bold {config['color']}")

        self.print_card(
            content=Markdown(message),
            title=title_text,
            border_style=config.get("color", "cyan")
        )

    def _print_with_panel(self, content: Any, use_panel: bool) -> None:
        """内部方法：根据参数决定是否使用面板包装"""
        if use_panel:
            self.print_panel(content)
        else:
            self.console.print(content)

    @staticmethod
    def create_console(**kwargs) -> Console:
        """创建预配置的Console实例"""
        return Console(record=True, **kwargs)


if __name__ == '__main__':
    printer = Printer()
    # 表格示例
    printer.print_table(
        headers=["Name", "Age", "Country"],
        data=[
            ["Alice", 28, "USA"],
            ["Bob", Text("32 (senior)", style="bold red"), "UK"],
            ["Charlie", 45, "Australia"]
        ],
        title="User Info",
        show_lines=True
    )

    # Markdown示例
    printer.print_markdown("# 这是标题\n- 列表项1\n- 列表项2", panel=True)

    # 代码示例
    printer.print_code('print("Hello World!")', line_numbers=False)

    # Text示例
    printer.print_text('这是一段文字')

    # 动态内容示例
    with printer.live_context():
        for i in range(10):
            printer.update_live(f"Processing... [bold green]{i + 1}/10")
            time.sleep(0.1)

    # 进度条示例
    with printer.progress_context() as progress:
        task = progress.add_task("Downloading", total=100)
        for i in range(100):
            progress.update(task, advance=1)
            time.sleep(0.02)

    # 基础卡片
    printer.print_card(
        title="系统通知",
        content="当前系统版本：v2.4.1\n可用存储空间：128GB",
        icon="package",
        border_style="bright_magenta",
        width=30
    )

    # 多列卡片
    printer.multi_col_cards([
        {
            "title": "CPU使用率",
            "content": "```\n[██████ 75%]\n```",
            "border_style": "yellow"
        },
        {
            "title": "内存状态",
            "content": "已用：4.2/8.0 GB"
        },
        {
            "title": "网络状态",
            "content": Markdown("- Ping: 28ms\n- 带宽：↑1.2 ↓4.5 Mbps")
        }
    ])

    # 状态卡片
    printer.status_card(
        status="success",
        title="操作完成",
        message="已成功保存所有修改到：\n`/path/to/file.conf`"
    )

    printer.status_card(
        status="error",
        message="无法连接到数据库：\n- 检查网络连接\n- 验证凭据有效性",
        title="严重错误"
    )
