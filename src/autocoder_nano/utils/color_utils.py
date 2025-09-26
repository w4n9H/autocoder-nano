"""
AutoCoder Nano 终端配色方案
直接定义颜色常量，简单直接使用
"""

# 系统状态类
COLOR_SYSTEM = "bold bright_blue"          # 系统信息 - 亮蓝色加粗
COLOR_SUCCESS = "bold green"               # 成功状态 - 绿色加粗
COLOR_ERROR = "bold red"                   # 错误信息 - 红色加粗
COLOR_WARNING = "bold yellow"              # 警告信息 - 黄色加粗
COLOR_INFO = "bright_cyan"                 # 一般信息 - 亮青色

# Agent交互类
COLOR_AGENT_START = "bold bright_magenta"  # Agent启动 - 亮洋红色加粗
COLOR_AGENT_END = "bold bright_green"      # Agent结束 - 亮绿色加粗
COLOR_ITERATION = "bright_yellow"          # 迭代计数 - 亮黄色
COLOR_TOKEN_USAGE = "bright_cyan"          # Token使用 - 亮青色

# 工具相关
COLOR_TOOL_CALL = "bold bright_cyan"       # 工具调用 - 亮青色加粗
COLOR_TOOL_SUCCESS = "bright_green"        # 工具成功 - 亮绿色
COLOR_TOOL_FAILURE = "bright_red"          # 工具失败 - 亮红色

# LLM交互
COLOR_LLM_THINKING = "dim white"           # LLM思考 - 暗白色（低调显示）
COLOR_LLM_OUTPUT = "bright_white"          # LLM输出 - 亮白色（清晰显示）
COLOR_LLM_STREAM = "cyan"                  # LLM流式输出 - 青色
COLOR_LLM_CALL = "dim white"               # LLM请求 - 暗白色（低调显示）

# 文件操作
COLOR_FILE_READ = "bright_blue"            # 文件读取 - 亮蓝色
COLOR_FILE_WRITE = "bright_green"          # 文件写入 - 亮绿色
COLOR_FILE_CHANGE = "bright_yellow"        # 文件变更 - 亮黄色

# 特殊状态
COLOR_COMPLETION = "bold bright_green"     # 任务完成 - 亮绿色加粗
COLOR_PROGRESS = "bright_blue"             # 进度信息 - 亮蓝色
COLOR_DEBUG = "dim white"                  # 调试信息 - 暗白色

# 面板样式
COLOR_PANEL_SUCCESS = "green"              # 成功面板边框 - 绿色
COLOR_PANEL_ERROR = "red"                  # 错误面板边框 - 红色
COLOR_PANEL_INFO = "blue"                  # 信息面板边框 - 蓝色
COLOR_PANEL_WARNING = "yellow"             # 警告面板边框 - 黄色
COLOR_PANEL_TOOL = "cyan"                  # 工具面板边框 - 青色

# 工具类型颜色映射
TOOL_COLORS = {
    "ReadFileTool": COLOR_FILE_READ,            # 文件读取工具 - 亮蓝色
    "WriteToFileTool": COLOR_FILE_WRITE,        # 文件写入工具 - 亮绿色
    "ReplaceInFileTool": COLOR_FILE_WRITE,      # 文件替换工具 - 亮绿色
    "ExecuteCommandTool": COLOR_SYSTEM,         # 命令执行工具 - 亮蓝色加粗
    "ListFilesTool": COLOR_FILE_READ,           # 文件列表工具 - 亮蓝色
    "SearchFilesTool": COLOR_FILE_READ,         # 文件搜索工具 - 亮蓝色
    "AskFollowupQuestionTool": COLOR_INFO,      # 提问工具 - 亮青色
    "AttemptCompletionTool": COLOR_COMPLETION,  # 完成任务工具 - 亮绿色加粗
    "WebSearchTool": COLOR_SYSTEM,               # 网络搜索工具 - 亮蓝色加粗
    "TodoReadTool": COLOR_SYSTEM,
    "TodoWriteTool": COLOR_SYSTEM
}


def get_tool_color(tool_name):
    """根据工具名称获取对应的颜色"""
    return TOOL_COLORS.get(tool_name, COLOR_TOOL_CALL)  # 默认使用工具调用颜色