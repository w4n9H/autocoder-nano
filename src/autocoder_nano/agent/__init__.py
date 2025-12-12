import json

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
                     used_subagent: list[str]):
    llm.setup_default_model_name(args.chat_model)
    sources = SourceCodeList([])
    agentic_runner = AgenticRuntime(
        args=args, llm=llm, agent_type="main", used_subagent=used_subagent,
        files=sources, history_conversation=[], conversation_config=conversation_config,
    )
    request = AgenticEditRequest(user_input=args.query)
    agentic_runner.run_in_terminal(request)


__all__ = ["AgenticEditConversationConfig", "run_main_agentic"]