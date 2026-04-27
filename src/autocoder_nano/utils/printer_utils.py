import difflib
import os
import threading
import time
from typing import Any, Optional, List, Union, Dict, Iterable

from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.align import Align

COLOR_SYSTEM = "grey58"  # 系统信息 - 暗灰色 60
COLOR_SUCCESS = "green3"  # 成功状态 - 亮绿色
COLOR_ERROR = "red3"  # 错误信息 - 亮红色
COLOR_WARNING = "yellow3"  # 警告信息 - 亮黄色
COLOR_INFO = "grey58"  # 一般信息 - 暗灰色（低调显示）
COLOR_BORDER = "grey30"
COLOR_PRIMARY = "cyan"


class Printer:
    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self.indent_level = 0
        self.current_agent: Optional[str] = None
        self._spinner_running = False
        self._spinner_thread = None

    # Agent

    def set_agent(self, name: str):
        """设置当前 Agent（planner / coder / reviewer）"""
        self.current_agent = name

    def clear_agent(self):
        self.current_agent = None

    def _agent_prefix(self) -> str:
        if not self.current_agent:
            return ""
        return f"* ({self.current_agent}) "

    # 缩进系统

    def indent(self):
        self.indent_level += 1

    def dedent(self):
        self.indent_level = max(0, self.indent_level - 1)

    def _prefix(self):
        return "  " * self.indent_level

    def _print(self, content: Any, style: Optional[str] = None):
        prefix = self._agent_prefix() + self._prefix()

        if isinstance(content, Text):
            self.console.print(Text(prefix) + content)
        else:
            self.console.print(f"{prefix}{content}", style=style)

    # Spinner

    def start_spinner(self, message: str = "Running..."):
        if getattr(self, "_spinner_running", False):
            return  # 防止重复启动

        self._spinner_running = True

        def run():
            frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            i = 0

            while self._spinner_running:
                prefix = self._agent_prefix() + self._prefix()
                frame = frames[i % len(frames)]

                text = f"{prefix}{frame} {message}"

                self.console.file.write("\r" + text)
                self.console.file.flush()

                time.sleep(0.1)
                i += 1

        self._spinner_thread = threading.Thread(target=run)
        self._spinner_thread.daemon = True
        self._spinner_thread.start()

    def end_spinner(self):
        if not getattr(self, "_spinner_running", False):
            return

        self._spinner_running = False

        if self._spinner_thread:
            self._spinner_thread.join()

        # 清掉当前行（关键）
        self.console.file.write("\r" + " " * 120 + "\r")
        self.console.file.flush()

    # Section（顶层结构）

    def section(self, title: str):
        self.console.print()
        self.console.print(Text(f"{self._agent_prefix()}• {title}", style="grey60"))

    # Thinking

    def thinking(self, content: str, expanded: bool = True):
        self.section("Thinking")
        self.indent()
        if expanded:
            # prefix = self._agent_prefix() + self._prefix()
            # self.console.print(prefix, end="")
            self.console.print(Markdown(content, style="grey50"))
        else:
            self._print("(hidden)", style="grey50")
        self.dedent()

    # Output

    def output(self, content: str, expanded: bool = True):
        self.section("Output")
        self.indent()

        if expanded:
            # prefix = self._agent_prefix() + self._prefix()
            # self.console.print(prefix, end="")
            self.console.print(Markdown(content, style="grey50"))
        else:
            self._print("(hidden)", style="grey50")

        self.dedent()

    # Diff

    def diff_file(self, file: str, old_code: str, new_code: str, context: int = 3):
        old_lines = old_code.splitlines()
        new_lines = new_code.splitlines()

        diff_lines = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file}",
            tofile=f"b/{file}",
            lineterm="",
            n=context,
        )

        self.section("Diff")
        self.indent()

        for line in diff_lines:
            if line.startswith("+++") or line.startswith("---"):
                self.console.print(line, style="grey50")
            elif line.startswith("@@"):
                self.console.print(line, style="cyan")
            elif line.startswith("+"):
                self.console.print(line, style=COLOR_SUCCESS)
            elif line.startswith("-"):
                self.console.print(line, style=COLOR_ERROR)
            else:
                self.console.print(line, style="grey70")

        self.dedent()

    # Tool Call

    def tool_call(self, name: str, desc: str):
        self.section("Tool Call")
        self.indent()

        self.console.print(
            Text.assemble(
                (self._agent_prefix() + self._prefix() + "› ", "grey50"),
                (name, "cyan"),
                ("  ", ""),
                (desc, "grey50"),
            )
        )

    def tool_result(self, success: bool, msg: Optional[str] = None, content: Optional[str] = None):
        icon = "✓" if success else "✗"
        color = COLOR_SUCCESS if success else COLOR_ERROR

        self.console.print(
            Text.assemble(
                (self._agent_prefix() + self._prefix() + icon + " ", color),
                (msg, "grey50"),
            )
        )
        if content:
            self.print_markdown(content)

        self.dedent()

    # 简单文本 / KV
    def kv(self, data: Dict[str, Any]):
        for k, v in data.items():
            self.console.print(
                Text.assemble(
                    (self._agent_prefix() + self._prefix() + k, "grey50"),
                    (": ", "grey50"),
                    (str(v), "grey82"),
                )
            )

    # Agent Flow

    def agent_step(
            self,
            agent_type: str,
            thinking: Optional[str] = None,
            tool: Optional[tuple] = None,
            result: Optional[bool] = None,
            output: Optional[str] = None,
    ):
        self.set_agent(agent_type)
        if thinking:
            self.thinking(thinking)
        if output:
            self.output(output)
        if tool:
            self.tool_call(*tool)
        if result is not None:
            self.tool_result(result)
        self.clear_agent()

    # 其他

    def separator(self):
        width = min(os.get_terminal_size().columns, 100)
        self.console.print(Text("─" * width, style="grey50"))

    def success(self, msg: str):
        self.console.print(Text.assemble(("✓ ", COLOR_SUCCESS), (msg, COLOR_SYSTEM)))

    def error(self, msg: str):
        self.console.print(Text.assemble(("✗ ", COLOR_ERROR), (msg, COLOR_SYSTEM)))

    def warnning(self, msg: str):
        self.console.print(Text.assemble(("! ", COLOR_WARNING), (msg, COLOR_SYSTEM)))

    def info(self, msg: str):
        self.console.print(Text.assemble(("ℹ ", COLOR_INFO), (msg, COLOR_INFO)))

    # Token

    def token_status(self, iteration: int, input_tokens: int, output_tokens: int, context_tokens: int, max_context: int,):
        def fmt(n):
            if n >= 1000:
                return f"{n / 1000:.1f}k"
            return str(n)

        ratio = context_tokens / max_context if max_context else 0
        percent = int(ratio * 100)

        # 颜色策略（很关键）
        if percent < 60:
            color = "grey50"
        elif percent < 80:
            color = "yellow"
        else:
            color = "red"

        text = Text.assemble(
            (f"round: {iteration} | ", "grey50"),
            ("tokens: ", "grey50"),
            (fmt(input_tokens), "grey70"),
            (" in / ", "grey50"),
            (fmt(output_tokens), "grey70"),
            (" out", "grey50"),
            ("  |  ctx: ", "grey50"),
            (f"{percent}%", color),
        )

        self.section("Token")
        self.console.print(
            text
        )

    # 旧UI组件

    def print_table_compact(
            self,
            data: Iterable[Iterable[Any]],
            title: Optional[str] = None,
            headers: Optional[List[str]] = None,
            show_lines: bool = False,
            expand: bool = False,
            caption: Optional[str] = None,
            compact: bool = False,
            center: bool = False,  # 新增居中参数
    ) -> None:
        # TUI风格的颜色配置
        title_style = "bold cyan"
        caption_style = "dim grey50"
        header_style = "grey50"
        content_style = "grey85"
        alt_row_style = "grey70"
        border_style = None  # "grey35"

        table = Table(
            title=Text(f"  {title}  ", style=title_style),
            caption=Text(f" {caption} ", style=caption_style) if caption else None,  # 使用灰黑色背景
            show_header=bool(headers),  # 显示标题行
            show_lines=show_lines,  # 在每行之间绘制分隔线
            show_edge=False,  # 在表格外部绘制边框, 默认为 True。
            expand=expand,  # 如果为 True，则扩展表格以填充可用空间；否则将自动计算表格宽度。默认为 False。
            padding=(0, 1),  # 紧凑模式减少内边距
            box=None,
            row_styles=[content_style, alt_row_style],  # 斑马纹
            border_style=border_style,
        )

        for header in (headers or []):
            table.add_column(
                header,
                style=content_style,  # 内容为白色
                header_style=header_style,  # 表头加粗（继承白色）
                justify="center" if center else "left",  # 列内容居中,
                min_width=10
            )

        # 行内容处理 - 确保所有元素可渲染
        for row in data:
            styled_row = [str(item) if not isinstance(item, Text) else item for item in row]
            table.add_row(*styled_row)

        self.console.print(table)

    def print_markdown(self, text: str, panel: bool = False) -> None:
        """打印Markdown文本"""
        md = Markdown(text, style="grey50")
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
            width: Optional[int] = None, padding: tuple = (0, 4, 0, 4), center: bool = False  # 新增居中参数
    ) -> None:
        """带边框的面板输出（支持居中版）"""
        # 创建居中包装器
        renderable = content
        if center:
            renderable = Align.center(content, width=width)

        panel = Panel(
            renderable,
            title=title,
            title_align="left",
            border_style=border_style,
            width=width,
            padding=padding,
            box=box.SIMPLE,
            expand=True
        )
        self.console.print(panel)

    def print_text(
            self, *texts: Union[str, Text], style: Optional[str] = None, justify: Optional[str] = "left",
            prefix: Optional[str] = ""  # 新增前缀参数
    ) -> None:
        """灵活文本打印，支持样式和混合内容"""
        processed_texts = Text()
        if prefix:
            processed_texts.append(Text(prefix, style="grey50"))
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
    # 表格示例
    printer.print_table_compact(
        headers=["Name", "Age", "Country"],
        data=[
            ["Alice", 28, "USA"],
            ["Bob", Text("32 (senior)", style="bold red"), "UK"],
            ["Charlie", 45, "Australia"]
        ],
        title="User Info"
    )

    # 键值对示例
    printer.kv(
        {"版本": "1.2.3", "作者": "Alice", "许可证": "MIT"}
    )

    printer.set_agent("coder")
    printer.token_status(20, 1000, 2000, 5000, 200_000)
    printer.thinking("- 需要修改 add 函数逻辑")
    printer.output("- 修改 add 函数")
    printer.tool_call("WriteToFileTool", "写入文件: math.py")
    printer.start_spinner()
    time.sleep(1)
    printer.end_spinner()
    printer.tool_result(False, "1. 错误原因是函数逻辑修改失败")
    old = """def add(a, b):
        return a + b
    """

    new = """def add(a, b):
        return a + b + 1
    """
    printer.diff_file("math.py", old, new)
    printer.clear_agent()

    markdown = "# 我是标题1 \n- 需要修改 add 函数逻辑"

    printer.print_markdown(markdown, panel=True)
