SubAgent = {
    "main": {
        "description": "MainAgent:擅长分析需求,拆解任务,代理调度,结果整合",
        "call": "",
        "prompt": "main_system_prompt.md",
        "tools": [
            "todo_read",
            "todo_write",
            # "search_files",
            "list_files",
            # "read_file",
            "call_subagent",
            "ask_followup_question",
            "attempt_completion"
        ]
    },
    "reader": {
        "description": "代码检索专家: 负责分析用户需求并从代码库中找出所有相关的文件,为后续的编码工作提供精准的上下文",
        "call": "调用时机:通常在进行编码任务之前调用，agent_type:reader",
        "prompt": "reader_system_prompt.md",
        "tools": [
            "read_file",
            "search_files",
            "list_files",
            "ask_followup_question",
            "attempt_completion",
        ]
    },
    "coding": {
        "description": "软件工程师: 在众多编程语言,框架,设计模式和最佳实践方面拥有渊博知识",
        "call": "调用时机:涉及具体代码变更的任务，agent_type:coding",
        "prompt": "coding_system_prompt.md",
        "tools": [
            "execute_command",
            "read_file",
            "write_to_file",
            "replace_in_file",
            "search_files",
            "list_files",
            "ask_followup_question",
            "attempt_completion"
        ]
    },
    "research": {
        "description": "研究专家: 精通技术架构的深度调研,擅长市场分析,行业趋势洞察和产品可行性分析",
        "call": "调用时机:需要通过联网搜索，调研或方案决策的任务，agent_type:research",
        "prompt": "research_system_prompt.md",
        "tools": [
            "web_search",
            "ask_followup_question",
            "attempt_completion",
            "write_to_file"
        ]
    },
    "codereview": {
        "description": "代码审查专家：精通多语言代码质量分析、安全漏洞检测和性能优化",
        "call": "调用时机:完成复杂的编码任务后，agent_type:codereview",
        "prompt": "codereview_system_prompt.md",
        "tools": [
            "execute_command",
            "read_file",
            "write_to_file",
            "search_files",
            "list_files",
            "ask_followup_question",
            "attempt_completion"
        ]
    },
    "agentic_rag": {
        "description": "智能检索增强生成代理：具备自主决策，多步骤推理和工具调用能力，通过动态规划和迭代检索，为用户提供准确，全面且有据可查的答案",
        "call": "调用时机:需要通过本地知识库检索，自主分析，多步查询才能解决的复杂问题场景，agent_type:agentic_rag",
        "prompt": "agentic_rag_system_prompt.md",
        "tools": [
            "write_to_file",
            "use_rag_tool",
            "ask_followup_question",
            "attempt_completion"
        ]
    }
}


def get_subagent_define() -> dict:
    return SubAgent