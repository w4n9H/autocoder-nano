from prompt_toolkit.styles import Style


# GitHub Dark (推荐)
github_dark_style = Style.from_dict({
    "username": "#79c0ff bold",        # GitHub蓝亮色
    "at": "#7ee787",                   # GitHub绿色
    "colon": "#d2a8ff",                # GitHub紫色
    "pound": "#7ee787",                # GitHub绿色
    "host": "#ff7b72",                 # GitHub红色
    "dollar": "#7ee787 bold",          # 绿色+粗体
    "bottom-toolbar": "bg:#161b22 #f0f6fc",  # 更深的背景 + 更亮的文字
    "keyword": "bold #ff7b72",         # 粗体+红色(关键词)
    "keyword2": "bold #79c0ff",        # 粗体+蓝色(次要关键词)
    "other": "#c9d1d9",                # GitHub默认文字色
    # 代码高亮扩展
    "string": "#a5d6ff",
    "comment": "#8b949e italic",
    "function": "#d2a8ff",
    "variable": "#ffa657",
})


# Nord Theme (北欧风)
nord_style = Style.from_dict({
    "username": "#88c0d0 bold",        # 青色+
    "at": "#a3be8c",                   # 北欧绿
    "colon": "#b48ead",                # 紫色
    "pound": "#a3be8c",                # 北欧绿
    "host": "#bf616a",                 # 北欧红
    "dollar": "#a3be8c bold",          # 绿色+粗体
    "bottom-toolbar": "bg:#3b4252 #eceff4",  # Nord深色背景
    "keyword": "bold #bf616a",         # 粗体+红色
    "keyword2": "bold #88c0d0",        # 粗体+青色
    "other": "#d8dee9",                # Nord亮色
    # 代码高亮扩展
    "string": "#a3be8c",
    "comment": "#4c566a italic",
    "function": "#b48ead",
    "variable": "#ebcb8b",
})


# One Dark (VS Code热门)
one_dark_style = Style.from_dict({
    "username": "#61afef bold",        # 蓝色+
    "at": "#98c379",                   # 绿色
    "colon": "#c678dd",                # 紫色
    "pound": "#98c379",                # 绿色
    "host": "#e06c75",                 # 红色
    "dollar": "#98c379 bold",          # 绿色+粗体
    "bottom-toolbar": "bg:#21252b #e5e5e5",  # One Dark背景
    "keyword": "bold #e06c75",         # 粗体+红色
    "keyword2": "bold #61afef",        # 粗体+蓝色
    "other": "#abb2bf",                # 默认文字色
    # 代码高亮扩展
    "string": "#98c379",
    "comment": "#5c6370 italic",
    "function": "#c678dd",
    "variable": "#e5c07b",
})


# Dracula (经典暗色)
dracula_style = Style.from_dict({
    "username": "#8be9fd bold",        # 青色+
    "at": "#50fa7b",                   # 绿色
    "colon": "#bd93f9",                # 紫色
    "pound": "#50fa7b",                # 绿色
    "host": "#ff5555",                 # 红色
    "dollar": "#50fa7b bold",          # 绿色+粗体
    "bottom-toolbar": "bg:#44475a #f8f8f2",  # Dracula背景
    "keyword": "bold #ff5555",         # 粗体+红色
    "keyword2": "bold #8be9fd",        # 粗体+青色
    "other": "#f8f8f2",                # Dracula亮色
    # 代码高亮扩展
    "string": "#f1fa8c",
    "comment": "#6272a4 italic",
    "function": "#bd93f9",
    "variable": "#ffb86c",
})


# Cyberpunk Neon (赛博朋克)
cyberpunk_style = Style.from_dict({
    "username": "#00ffff bold",        # 荧光青
    "at": "#00ff00",                   # 荧光绿
    "colon": "#ff00ff",                # 荧光紫
    "pound": "#00ff00",                # 荧光绿
    "host": "#ff0080",                 # 荧光粉
    "dollar": "#00ff00 bold",          # 绿色+粗体
    "bottom-toolbar": "bg:#1a1a1a #e0e0e0",  # 稍亮的纯黑背景 + 亮灰色文字
    "keyword": "bold #ff0080",         # 粗体+粉色
    "keyword2": "bold #00ffff",        # 粗体+青色
    "other": "#ffffff",                # 纯白
    # 代码高亮扩展
    "string": "#ffff00",
    "comment": "#808080 italic",
    "function": "#ff00ff",
    "variable": "#00ff00",
})


class ThemeManager:
    """主题管理类，用于管理所有可用主题"""

    def __init__(self):
        self.themes = {
            "github_dark": {
                "name": "GitHub Dark",
                "style": github_dark_style,
                "description": "GitHub官方暗色主题"
            },
            "nord": {
                "name": "Nord",
                "style": nord_style,
                "description": "北欧风格主题"
            },
            "one_dark": {
                "name": "One Dark",
                "style": one_dark_style,
                "description": "VS Code热门暗色主题"
            },
            "dracula": {
                "name": "Dracula",
                "style": dracula_style,
                "description": "经典暗色主题"
            },
            "cyberpunk": {
                "name": "Cyberpunk",
                "style": cyberpunk_style,
                "description": "赛博朋克霓虹风格"
            }
        }
        self.default_theme = "cyberpunk"

    def get_theme(self, theme_name: str) -> Style:
        """获取指定主题的样式"""
        if theme_name in self.themes:
            return self.themes[theme_name]["style"]
        return self.themes[self.default_theme]["style"]

    def get_theme_name(self, theme_name: str) -> str:
        """获取主题信息"""
        return self.themes.get(theme_name, {}).get("name", "")

    def list_themes(self) -> dict:
        """列出所有可用主题"""
        return self.themes

    def is_valid_theme(self, theme_name: str) -> bool:
        """检查主题是否有效"""
        return theme_name in self.themes