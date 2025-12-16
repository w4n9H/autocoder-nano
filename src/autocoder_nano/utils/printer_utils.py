from typing import Any, Optional, List, Union, Dict, Iterable

from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.align import Align


class Printer:
    def __init__(self, console: Optional[Console] = None):
        """
        增强版富文本打印机
        :param console: 可传入自定义的Rich Console实例
        """
        self.console = console or Console()

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
            show_lines: bool = True,
            expand: bool = True,
            caption: Optional[str] = None,
            compact: bool = True,
            center: bool = True,  # 新增居中参数
    ) -> None:
        # TUI风格的颜色配置
        title_style = "bold white on green"          # 更醒目的标题
        caption_style = "dim black on bright_blue"  # 蓝灰背景
        header_style = "bold black on yellow"         # 高对比度表头
        content_style = "bright_white"                # 亮白色内容
        alt_row_style = "white"                       # 斑马纹使用纯白色
        border_style = "bright_green"                 # 鲜绿色边框

        table = Table(
            title=Text(f"  {title}  ", style=title_style),
            caption=Text(f" {caption} ", style=caption_style) if caption else None,  # 使用灰黑色背景
            show_header=bool(headers),  # 显示标题行
            show_lines=show_lines,  # 在每行之间绘制分隔线
            show_edge=True,  # 在表格外部绘制边框, 默认为 True。
            expand=expand,  # 如果为 True，则扩展表格以填充可用空间；否则将自动计算表格宽度。默认为 False。
            padding=(0, 0) if compact else (1, 2),  # 紧凑模式减少内边距
            box=box.SQUARE,
            style="on black",
            row_styles=[content_style, alt_row_style],  # 斑马纹
            border_style=border_style,
        )

        for header in (headers or []):
            table.add_column(
                header,
                style=content_style,    # 内容为白色
                header_style=header_style,  # 表头加粗（继承白色）
                justify="center" if center else "left",  # 列内容居中
            )

        # 行内容处理 - 确保所有元素可渲染
        for row in data:
            styled_row = [str(item) if not isinstance(item, Text) else item for item in row]
            table.add_row(*styled_row)

        self.print_panel(
            table,
            border_style="bold green",
            padding=(0, 0),
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
            renderable = Align.center(content, width=width)

        panel = Panel(
            renderable,
            title=title,
            border_style=border_style,
            width=width,
            padding=padding,
            box=box.DOUBLE,
            expand=True
        )
        self.console.print(panel)

    def print_text(
        self, *texts: Union[str, Text], style: Optional[str] = None, justify: Optional[str] = "left",
        prefix: Optional[str] = "> "  # 新增前缀参数
    ) -> None:
        """灵活文本打印，支持样式和混合内容"""
        if prefix:
            processed_texts = []
            for t in texts:
                if isinstance(t, str):
                    processed_texts.append(Text(f"{prefix}{t}", style=style))
                else:
                    # 对于Text对象，创建新的Text并添加前缀
                    prefixed_text = Text(prefix)
                    prefixed_text.append(t)
                    processed_texts.append(prefixed_text)
            rich_text = Group(*processed_texts)
        else:
            rich_text = Group(*[
                Text(str(t), style=style) if isinstance(t, str) else t
                for t in texts
            ])
        self.console.print(rich_text, justify=justify)

    def print_key_value(
        self, items: Dict[str, Any], key_style: str = "bold cyan",
        value_style: str = "green", separator: str = ": ", panel: bool = True, title: Optional[str] = None
    ) -> None:
        """
        键值对格式化输出
        :param items: 字典数据
        :param key_style: 键的样式
        :param value_style: 值的样式
        :param separator: 键值分隔符
        :param panel: 是否用面板包裹
        :param title: 面板标题
        """
        content = Group(*[
            Text.assemble(
                (f"{k}{separator}", key_style),
                (str(v), value_style)
            ) for k, v in items.items()
        ])
        self._print_with_panel(content, panel, title)

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

    def _print_with_panel(self, content: Any, use_panel: bool, title: Optional[str] = None) -> None:
        """内部方法：根据参数决定是否使用面板包装"""
        if use_panel:
            self.print_panel(content, title)
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
