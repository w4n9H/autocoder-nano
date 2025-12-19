"""
AutoCoder Nano 终端配色方案
直接定义颜色常量，简单直接使用
"""

# 系统状态类
COLOR_SYSTEM = "bright_blue"          # 系统信息 - 亮蓝色加粗
COLOR_SUCCESS = "bright_green"               # 成功状态 - 绿色加粗
COLOR_ERROR = "bright_red"                   # 错误信息 - 红色加粗
COLOR_WARNING = "bright_yellow"              # 警告信息 - 黄色加粗
COLOR_INFO = "grey50"                   # 一般信息 - 暗白色（低调显示）

# Agent交互类
COLOR_AGENT_START = COLOR_SYSTEM           # Agent启动 - 亮洋红色加粗
COLOR_AGENT_END = COLOR_SUCCESS            # Agent结束 - 亮绿色加粗
COLOR_ITERATION = COLOR_INFO               # 迭代计数 - 亮黄色
COLOR_TOKEN_USAGE = COLOR_INFO             # Token使用 - 亮青色

# 工具相关
COLOR_TOOL_CALL = COLOR_INFO               # 工具调用 - 亮青色加粗
COLOR_TOOL_SUCCESS = COLOR_SUCCESS         # 工具成功 - 亮绿色
COLOR_TOOL_FAILURE = COLOR_ERROR           # 工具失败 - 亮红色

# LLM交互
COLOR_LLM_THINKING = COLOR_INFO            # LLM思考 - 暗白色（低调显示）
COLOR_LLM_OUTPUT = COLOR_INFO              # LLM输出 - 亮白色（清晰显示）
COLOR_LLM_STREAM = COLOR_INFO              # LLM流式输出 - 青色
COLOR_LLM_CALL = COLOR_INFO                # LLM请求 - 暗白色（低调显示）

# 文件操作
COLOR_FILE_READ = COLOR_INFO               # 文件读取 - 亮蓝色
COLOR_FILE_WRITE = COLOR_INFO              # 文件写入 - 亮绿色
COLOR_FILE_CHANGE = COLOR_WARNING          # 文件变更 - 亮黄色

# 特殊状态
COLOR_COMPLETION = COLOR_SUCCESS           # 任务完成 - 亮绿色加粗
COLOR_PROGRESS = COLOR_INFO                # 进度信息 - 亮蓝色
COLOR_DEBUG = COLOR_INFO                   # 调试信息 - 暗白色

# 面板样式
COLOR_PANEL_SUCCESS = COLOR_SUCCESS        # 成功面板边框 - 绿色
COLOR_PANEL_ERROR = COLOR_ERROR            # 错误面板边框 - 红色
COLOR_PANEL_INFO = COLOR_INFO              # 信息面板边框 - 蓝色
COLOR_PANEL_WARNING = COLOR_WARNING        # 警告面板边框 - 黄色
COLOR_PANEL_TOOL = COLOR_INFO              # 工具面板边框 - 青色

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