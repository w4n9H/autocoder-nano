import time
from typing import Any, Optional, List, Union, Dict, Iterable, Generator
from contextlib import contextmanager

from rich import box
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

    def print_table_compact(
            self,
            data: Iterable[Iterable[Any]],
            title: Optional[str] = None,
            headers: Optional[List[str]] = None,
            show_lines: bool = False,
            expand: bool = False,
            caption: Optional[str] = None,
            compact: bool = True,
            center: bool = True  # 新增居中参数
    ) -> None:
        """ 打印表格（紧凑版本） """
        table = Table(
            title=title,
            show_header=bool(headers),
            show_lines=show_lines,
            expand=expand,
            caption=caption,
            padding=(0, 0) if compact else (0, 1),  # 紧凑模式减少内边距
            box=box.SIMPLE if compact else box.ASCII  # 紧凑模式使用简单边框
        )

        # 列样式调整
        for header in (headers or []):
            table.add_column(
                header,
                style="cyan",
                header_style="bold magenta",
                min_width=20 if compact else None,
                justify="center" if center else "left"  # 列内容居中
            )

        # 行内容处理 - 确保所有元素可渲染
        for row in data:
            styled_row = [str(item) if not isinstance(item, Text) else item for item in row]
            table.add_row(*styled_row)

        # 自动添加面板
        self.print_panel(
            table,
            title=None,
            border_style="cyan" if compact else "blue",
            width=None if compact else 100,
            center=center  # 传递居中参数
        )

    def print_markdown(self, text: str, panel: bool = False) -> None:
        """打印Markdown文本"""
        md = Markdown(text)
        self._print_with_panel(md, panel)

    def print_code(
            self, code: str, lexer: str = "python", theme: str = "monokai",
            line_numbers: bool = True, panel: bool = False
    ) -> None:
        """高亮打印代码块"""
        syntax = Syntax(
            code,
            lexer,
            theme=theme,
            line_numbers=line_numbers,
            padding=(0, 2)
        )
        # self.console.print(syntax)
        self._print_with_panel(syntax, panel)

    def print_panel(
        self, content: Any, title: Optional[str] = None, border_style: str = "cyan",
        width: Optional[int] = None, padding: tuple = (0, 1), center: bool = False  # 新增居中参数
    ) -> None:
        """带边框的面板输出（支持居中版）"""
        # 创建居中包装器
        renderable = content
        if center:
            renderable = Columns([content], align="center", width=width)

        panel = Panel(
            renderable,
            title=title,
            border_style=border_style,
            width=width,
            padding=padding,
            box=box.SQUARE
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

    @contextmanager
    def progress_context_with_panel(
            self, title: Optional[str] = None, border_style: str = "cyan"
    ) -> Generator[Progress, Any, None]:
        self._progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[progress.description]{task.description}", justify="right"),
            BarColumn(bar_width=None, style="blue1", complete_style="bold blue", finished_style="bold green"),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%", style="bold"),
            TextColumn("•"),
            TextColumn("[cyan]{task.completed}/{task.total}", justify="left"),
            expand=True,
            transient=True
        )

        # 创建包含进度条的面板
        progress_panel = Panel(
            self._progress,
            title=title or "任务进度",
            border_style=border_style,
            padding=(1, 2),
            box=box.ROUNDED
        )

        # 使用单个Live实例包装整个面板
        with Live(progress_panel, console=self.console, refresh_per_second=10) as live:
            # 手动将Progress的live替换为我们创建的live
            self._progress.live = live
            with self._progress:
                yield self._progress
                self._progress = None

    def print_card(
        self, content: Union[str, Text, Markdown, Syntax], title: Optional[str] = None,
        border_style: str = "cyan", width: Optional[int] = None, icon: Optional[str] = None, box: Box = ROUNDED
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
            padding=(0, 1)
        )
        self.console.print(panel)

    def multi_col_cards(
        self, cards: List[Dict[str, Any]], equal: bool = True
    ) -> None:
        """
        多列卡片布局
        :param cards: 卡片参数列表
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
                border_style=card.get("border_style", "cyan"),
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

    def print_key_value(
        self, items: Dict[str, Any], key_style: str = "bold cyan",
        value_style: str = "green", separator: str = ": ", panel: bool = True
    ) -> None:
        """
        键值对格式化输出
        :param items: 字典数据
        :param key_style: 键的样式
        :param value_style: 值的样式
        :param separator: 键值分隔符
        :param panel: 是否用面板包裹
        """
        content = Group(*[
            Text.assemble(
                (f"{k}{separator}", key_style),
                (str(v), value_style)
            ) for k, v in items.items()
        ])
        self._print_with_panel(content, panel)

    def context_aware_help(
        self, help_content: Dict[str, str], current_context: str, width: int = 40
    ):
        """
        上下文感知帮助面板
        :param help_content: 帮助信息字典 {上下文关键字: 说明内容}
        :param current_context: 当前分析出的上下文
        :param width: 面板宽度
        """
        matched_keys = [k for k in help_content if k in current_context]
        if not matched_keys:
            return

        help_text = Text()
        for key in matched_keys:
            help_text.append(f"[bold]{key}[/]\n{help_content[key]}\n\n", style="dim")

        self.print_panel(
            help_text,
            title="相关帮助信息",
            border_style="cyan",
            width=width
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

    def get_console(self):
        return self.console


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
        show_lines=False
    )

    printer.print_table_compact(
        headers=["Name", "Age", "Country"],
        data=[
            ["Alice", 28, "USA"],
            ["Bob", Text("32 (senior)", style="bold red"), "UK"],
            ["Charlie", 45, "Australia"]
        ],
        title="User Info",
        show_lines=True,
        center=True,
        compact=True
    )

    # 键值对示例
    printer.print_key_value(
        {"版本": "1.2.3", "作者": "Alice", "许可证": "MIT"},
        panel=True
    )

    # Markdown示例
    printer.print_markdown("# 这是标题\n- 列表项1\n- 列表项2", panel=True)

    # 代码示例
    printer.print_code('print("Hello World!")', line_numbers=False)

    # Text示例
    printer.print_text(Text("32 (senior)", style="bold red"))
    printer.print_text(Text("32 (senior)", style="dim red"))
    printer.print_text("32 (senior)", style="dim red")

    # 动态内容示例
    # with printer.live_context():
    #     for i in range(10):
    #         printer.update_live(f"Processing... [bold green]{i + 1}/10")
    #         time.sleep(0.1)

    # 进度条示例
    # with printer.progress_context() as progress:
    #     task = progress.add_task("Downloading", total=10)
    #     for i in range(10):
    #         progress.update(task, advance=1)
    #         time.sleep(0.1)

    # with printer.progress_context_with_panel(title="数据处理进度") as progress:
    #     task = progress.add_task("[red]下载文件...", total=10)
    #
    #     for i in range(10):
    #         time.sleep(0.1)
    #         progress.update(task, advance=1)

    # 基础卡片
    printer.print_card(
        title="系统通知",
        content="当前系统版本：v2.4.1 , 可用存储空间：128GB",
        icon="package",
        border_style="dim blue",
        width=50
    )

    printer.print_card(
        title="第一阶段",
        content="处理 REST/RAG/Search 资源...",
        border_style="dim cyan"
    )

    # # 多列卡片
    # printer.multi_col_cards([
    #     {
    #         "title": "CPU使用率",
    #         "content": "```\n[██████ 75%]\n```",
    #         "border_style": "yellow"
    #     },
    #     {
    #         "title": "内存状态",
    #         "content": "已用：4.2/8.0 GB"
    #     },
    #     {
    #         "title": "网络状态",
    #         "content": Markdown("- Ping: 28ms\n- 带宽：↑1.2 ↓4.5 Mbps")
    #     }
    # ])

    # printer.status_card(
    #     status="error",
    #     message="无法连接到数据库：\n- 检查网络连接\n- 验证凭据有效性",
    #     title="严重错误"
    # )
