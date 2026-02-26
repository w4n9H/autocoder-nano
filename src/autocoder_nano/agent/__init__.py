import json
import os.path

from autocoder_nano.agent.agentic_runtime import AgenticRuntime
from autocoder_nano.agent.agentic_edit_types import AgenticEditRequest, AgenticEditConversationConfig
from autocoder_nano.core import AutoLLM, prompt, extract_code
from autocoder_nano.actypes import SourceCodeList, AutoCoderArgs


@prompt()
def _generate_agent_type(user_input: str):
    """
    收到用户需求后，你需要快速判断该需求的类型是编码需求还是深度研究需求

    # 用户需求

    {{ user_input }}

    # 最终输出格式

    ```json
    {
        "agent_type": "coding",
        "decision_rationale": "需求中带上了明确的代码文件名，函数名，类名，以及改动点，属于编码需求。"
    }
    ```

    - agent_type：根据用户需求快速判断 agent 任务类型
        * coding: 编码需求, 有明确的文件变更需求的都属于此类。
        * research: 深度研究需求，要求输出方案，报告的都属于研究需求。
    - decision_rationale：判断原因说明，在20字以内

    # 约束与核心规则

    - 果断明确：你的决策必须是非黑即白的，不允许使用 “可能”，“也许” 等模糊词汇。
    - 效率优先：你的分析应在最短时间内完成，进行初步判断，本身不应消耗过多Token成本。
    - 严格输出 json 格式
    """


# def run_agentic(llm: AutoLLM, args: AutoCoderArgs, conversation_config: AgenticEditConversationConfig):
#
#     llm.setup_default_model_name(args.code_model)
#     agent_router_raw = _generate_agent_type.with_llm(llm).run(user_input=args.query)
#     agent_router = json.loads(extract_code(agent_router_raw.output)[0][1])
#     agent_type = agent_router["agent_type"]
#
#     sources = SourceCodeList([])
#     agentic_runner = AgenticRuntime(
#         args=args, llm=llm, agent_type=agent_type,
#         files=sources, history_conversation=[], conversation_config=conversation_config,
#     )
#     request = AgenticEditRequest(user_input=args.query)
#     agentic_runner.run_in_terminal(request)


def run_main_agentic(llm: AutoLLM, args: AutoCoderArgs, conversation_config: AgenticEditConversationConfig,
                     agent_define: dict):
    llm.setup_default_model_name(args.chat_model)
    sources = SourceCodeList([])
    agentic_runner = AgenticRuntime(
        args=args, llm=llm, agent_define=agent_define,
        files=sources, history_conversation=[], conversation_config=conversation_config,
    )
    request = AgenticEditRequest(user_input=args.query)
    agentic_runner.run_in_terminal(request)


def run_web_agentic(llm: AutoLLM, args: AutoCoderArgs, conversation_config: AgenticEditConversationConfig,
                    agent_define: dict):
    # 定制 web 模式相关参数
    args.web_queue_db_path = os.path.join(args.source_dir, '.auto-coder', 'chat-bot.db')

    from autocoder_nano.core.queue import sqlite_queue
    messages = sqlite_queue.fetch_pending_user_messages(args.web_queue_db_path)
    if len(messages) == 1:
        msg = messages[0]
        args.web_client_id = msg["client_id"]
        args.web_message_id = msg["message_id"]
        args.query = msg["content"]
        sqlite_queue.mark_user_message_done(args.web_queue_db_path, msg["id"])
    else:
        raise Exception(f"当前暂时不支持同时处理多个Agent任务")

    llm.setup_default_model_name(args.chat_model)
    sources = SourceCodeList([])
    agentic_runner = AgenticRuntime(
        args=args, llm=llm, agent_define=agent_define,
        files=sources, history_conversation=[], conversation_config=conversation_config,
    )
    request = AgenticEditRequest(user_input=args.query)
    agentic_runner.run_in_web(request)


__all__ = ["AgenticEditConversationConfig", "run_main_agentic", "run_web_agentic"]