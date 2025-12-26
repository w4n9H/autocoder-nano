from typing import Any, Optional, List, Union, Dict, Iterable

from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.align import Align


COLOR_SYSTEM = "grey62"                      # 系统信息 - 暗灰色 60
COLOR_SUCCESS = "bright_green"               # 成功状态 - 亮绿色
COLOR_ERROR = "bright_red"                   # 错误信息 - 亮红色
COLOR_WARNING = "bright_yellow"              # 警告信息 - 亮黄色
COLOR_INFO = "grey50"                        # 一般信息 - 暗灰色（低调显示）
COLOR_BORDER = "dim cyan"                    # 边框颜色 - 青色


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
        title_style = "bold white on green"  # 更醒目的标题
        caption_style = "dim black on cyan"  # 蓝灰背景
        header_style = "bold white on yellow"  # 高对比度表头
        content_style = "bright_white"  # 亮灰色
        alt_row_style = "white"  # 暗灰色
        border_style = COLOR_BORDER  # 鲜绿色边框

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
                style=content_style,  # 内容为白色
                header_style=header_style,  # 表头加粗（继承白色）
                justify="center" if center else "left",  # 列内容居中
            )

        # 行内容处理 - 确保所有元素可渲染
        for row in data:
            styled_row = [str(item) if not isinstance(item, Text) else item for item in row]
            table.add_row(*styled_row)

        self.print_panel(
            table,
            border_style=COLOR_BORDER,
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
        self, content: Any, title: Optional[str] = None, border_style: str = COLOR_BORDER,
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
        processed_texts = Text()
        if prefix:
            processed_texts.append(Text(prefix, style="sandy_brown"))
            for t in texts:
                if isinstance(t, str):
                    processed_texts.append(Text(t, style=style))
                else:
                    processed_texts.append(t)
        else:
            for t in texts:
                processed_texts.append(Text(str(t), style=style) if isinstance(t, str) else t)
        self.console.print(processed_texts, justify=justify)

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

    def print_llm_output(self, content: str, style: str = "grey50"):
        md = Panel(
            Markdown(
                content, style=style
            ),
            padding=(0, 0, 0, 6),
            expand=True,
            box=box.SIMPLE_HEAD
        )
        self.console.print(md)

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
    printer.print_text(
        Text.assemble(
            ("Token 使用: ", "grey62"),
            (f"Input(10000)", "grey50"), (f"/", "grey62"),
            (f"Output(500)", "grey50")
        ),
        prefix=f"* (sub:reader) "
    )
    # agent 中表示模型 thinking 过程
    printer.print_text(f"LLM Thinking :", style="grey62", prefix=f"* (sub:reader) ")
    printer.print_llm_output("- 可能需要多次调整，确保每段话既全面又简洁。")
    # agent 工具调用
    printer.print_text(
        Text.assemble(
            (f"WriteToFileTool: ", "bold grey62"),
            (f"写入文件: /path/path/", "grey50")
        ),
        prefix=f"* (sub:reader) "
    )
    # agent 工具调用状态
    printer.print_text(
        Text.assemble(
            (f"WriteToFileTool: ", "bold grey62"),
            (f"成功", "bright_green")
        ),
        prefix=f"* (sub:reader) "
    )
    printer.print_llm_output("- 可能需要多次调整，确保每段话既全面又简洁。")
    printer.print_text(f"任务完成", style="bright_green", prefix=f"* (sub:reader) ")
    printer.print_text(f"任务失败", style="bright_red", prefix=f"* (sub:reader) ")
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
