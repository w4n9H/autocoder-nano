SubAgent = {
    "main": {
        "description": "MainAgent:擅长分析需求,拆解任务,代理调度,结果整合",
        "prompt": "main_system_prompt.md",
        "tools": [
            "todo_read",
            "todo_write",
            "search_files",
            "list_files",
            "read_file",
            "call_subagent",
            "ask_followup_question",
            "attempt_completion"
        ]
    },
    "coding": {
        "description": "软件工程师: 在众多编程语言,框架,设计模式和最佳实践方面拥有渊博知识",
        "prompt": "coding_system_prompt.md",
        "tools": [
            "execute_command",
            "read_file",
            "write_to_file",
            "replace_in_file",
            "search_files",
            "list_files",
            "ask_followup_question",
            "attempt_completion",
            "ac_mod_write",
            "ac_mod_search"
        ]
    },
    "research": {
        "description": "研究专家: 精通技术架构的深度调研,擅长市场分析,行业趋势洞察和产品可行性分析",
        "prompt": "research_system_prompt.md",
        "tools": [
            "web_search",
            "ask_followup_question",
            "attempt_completion",
            "write_to_file"
        ]
    }
}


def get_subagent_define() -> dict:
    return SubAgent