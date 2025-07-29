from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import (
    Horizontal, Vertical, Container, ScrollableContainer
)
from textual.widgets import (
    Tree, Label, Button, DataTable, RichLog, Select, TextArea
)


class LeftPanel(ScrollableContainer):
    """左侧边栏：AutoCoder / Operate / Chats"""
    def __init__(self) -> None:
        super().__init__(id="left-panel")

    def compose(self) -> ComposeResult:
        yield Label("AutoCoder Nano", classes="section-title")
        yield Label("Operate", classes="section-title")
        yield Button("Setings", compact=True)
        yield Button("Git Tools", compact=True)
        yield Button("Model Manager", compact=True)
        yield Label("Chats", classes="section-title")
        yield Button("+ New Chat", compact=True)
        yield Label("b661281d")


class TaskTable(DataTable):
    """任务列表"""

    def __init__(self) -> None:
        super().__init__(id="tasks-table")
        self.add_columns("id", "task", "model", "tok_in", "tok_out", "tok/sec", "cost", "runtime")
        self.add_row("001", "analyze.py", "claude-3.5", "128", "256", "42", "$0.002", "3.2s")


class ChatInput(TextArea):
    """底部多行输入框"""

    def __init__(self) -> None:
        super().__init__(id="command-input", language="markdown")
        self.show_line_numbers = False


class MiddlePanel(Container):
    """中间主工作区：Tasks + 终端 + 输入"""
    def __init__(self) -> None:
        super().__init__(id="middle-panel")

    def compose(self) -> ComposeResult:
        with Container(id="tasks-container"):
            yield Label("Tasks", classes="section-title")
            yield TaskTable()
        with Horizontal(id="begin-tasks"):
            yield Button("Start Tasks", id="start-tasks", compact=True)
            yield Button("Stop Tasks", id="stop-tasks", compact=True)
            yield Select(
                options=[
                    ("Chat Mode", "chat"),
                    ("Coding Mode", "coding"),
                    ("Agent Mode", "agent"),
                ],
                value="agent",
                prompt="Mode",
                id="mode-select",
                compact=True,
            )
        with Vertical(id="command-area"):
            yield RichLog(id="terminal-log", wrap=True, markup=True)
        with Container(id="input-area"):
            yield ChatInput()


class RightPanel(ScrollableContainer):
    """右侧边栏：Project Files + Model Tree"""
    def __init__(self) -> None:
        super().__init__(id="right-panel")

    def compose(self) -> ComposeResult:
        yield Label("Project Files", classes="section-title")
        tree = Tree("Project Name", id="project-files")
        tree.root.expand()
        for f in ["git", ".github", ".jrdev", "infra", "packages",
                  "patches", "scripts", "sdks", ".editorconfig", ".gitignore"]:
            tree.root.add_leaf(f)
        yield tree

        yield Label("Files Select", classes="section-title")
        mtree = Tree("Active Files", id="model-tree")
        mtree.root.expand()
        mtree.root.add_leaf("claude-3-5-haiku-20241022")

        # anth = mtree.root.add("anthropic", expand=True)
        # for m in ["claude-3-5-haiku-20241022", "claude-3-7-sonnet-2025622",
        #           "claude-opus-4-20250511", "claude-sonnet-4-20250511"]:
        #     anth.add_leaf(m)
        #
        # deep = mtree.root.add("deepseek", expand=True)
        # deep.add_leaf("deepseek-reasoner")
        # deep.add_leaf("deepseek-chat")
        #
        # router = mtree.root.add("open_router", expand=True)
        # for m in ["google/gemin1-2.5-pro", "google/gemin1-2.5-flash",
        #           "meta-llama/llama-4-mavera", "quen/quen3-30b-a3b-free"]:
        #     router.add_leaf(m)
        yield mtree


class FooterBar(Container):
    """底部状态栏"""

    def __init__(self) -> None:
        super().__init__(id="footer")  # ← 补上这一行

    def compose(self) -> ComposeResult:
        yield Label("🧠 Model: claude-3.5 | 💾 Project: my-app | ✅ Tasks: 1 running", id="status-bar")


class JrDevApp(App):
    """JrDev 终端应用（单文件重构版）"""

    CSS = """
        Screen {
            layout: grid;
            grid-size: 3;  # 改为3列2行
            grid-columns: 1fr 4fr 1.5fr;  /* 调整列宽比例 */
            grid-rows: 5fr auto;
            padding: 0;
            margin: 0;
            background: $surface;
        }

        #left-panel, #middle-panel, #right-panel {
            border: round $primary;
            border-title-align: center;
            height: 100%;
            padding: 0 1;
            background: $surface-lighten-1;
        }

        #left-panel {
            overflow-y: auto;
        }

        #middle-panel {
            layout: vertical;  /* 明确指定垂直布局 */
        }

        #right-panel {
            overflow-y: auto;
        }

        #footer {
            column-span: 3;  /* 横跨三列 */
            background: $surface-lighten-1;
            border-top: solid $primary;
            text-align: center;
            padding: 0;
        }

        #tasks-container {
            height: auto;
            padding: 0;
        }

        #begin-tasks {
            height: auto;
            padding: 0;
            align: center middle; /* 确保内容居中 */
        }

        #command-area {
            height: 1fr;
            min-height: 3;
            padding: 0;
            layout: vertical;
        }

        #input-area {
            height: auto;
            padding: 0;    /* 去除内边距 */
            margin: 0;     /* 去除外边距 */
            /* 添加顶部边框分隔 */
            border-top: solid $primary;
        }

        #command-input {
            height: auto;
            min-height: 3;
            max-height: 5;
            margin: 0 0;
            background: $surface-darken-2;
            /* 添加滚动条样式 */
            overflow-y: auto;
            scrollbar-size: 1 1;
            scrollbar-color: $primary $surface;
        }

        .section-title {
            text-style: bold;
            color: $accent;
            margin: 1 0 0 0;
            # background: $surface-darken-1;
            background: $surface-darken-3;
            padding: 0 1;
            # border-bottom: solid $primary;
        }

        #terminal-log {
            height: 1fr;
            overflow-y: auto; /* 添加滚动条 */
            padding: 0;
            background: $surface-darken-1;
            border: round $boost;
        }
        
        #project-files {
            margin-top: 1;
        }

        #model-tree {
            margin-top: 1;
        }

        #copy-selection {
            width: 100%;
            height: auto;
        }

        .highlight {
            background: $accent;
            color: $background;
        }

        Tree {
            width: 100%;
            background: $surface-darken-1;
        }

        Tree:focus > .tree--cursor {
            background: $accent 50%;
            color: $background;
            text-style: bold;
        }

        /* 文件树样式优化 */
        Tree > .tree-node > .tree-label {
            color: $text;
        }

        Tree > .tree-node--leaf > .tree-label {
            color: $text-muted;
        }

        DataTable {
            height: auto;   /* 让表格高度自适应内容 */
            background: $surface-darken-1;
        }

        Button {
            margin: 1 1;
            padding: 0;     /* 减少按钮内边距 */
        }

        /* 添加悬停效果 */
        Button:hover {
            background: $accent 20%;
        }

        Input {
            background: $surface-darken-1;
            border: round $boost;
        }

        Select {
            width: 20; /* 设置下拉框宽度 */
            margin: 1 1;
            padding: 0;
        }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "退出"),
        Binding("f1", "help", "帮助")
    ]

    def compose(self) -> ComposeResult:
        yield LeftPanel()
        yield MiddlePanel()
        yield RightPanel()
        yield FooterBar()

    def on_mount(self) -> None:
        self.title = "JrDev Terminal"
        self.sub_title = "AI 编程助手"
        log = self.query_one("#terminal-log", RichLog)
        log.write("\n[bold]Get Started:[/bold]")
        log.write("- New Chat: Click \"+ New Chat\" (left panel) to talk to the AI.")
        log.write("- Coding Tasks: Use /code [your task description] in this terminal.")
        log.write("- All Commands: Type /help for a full list.\n")
        log.write("[bold]Explore:[/bold] Use the right panels to manage Project Files & AI Models.\n")
        log.write("[bold]Quit:[/bold] Type /exit or press Ctrl+Q.\n")
        log.write("[bold red]Project context not found. Run '/init' to familiarize JrDev with important files the "
                  "code.[/bold red]")

    def action_help(self) -> None:
        log = self.query_one("#terminal-log", RichLog)
        log.write("\n[bold]Available Commands:[/bold]")
        log.write("/init - Initialize project context")
        log.write("/code <task> - Execute coding task")
        log.write("/model <name> - Switch AI model")
        log.write("/exit - Quit application")


if __name__ == "__main__":
    JrDevApp().run()