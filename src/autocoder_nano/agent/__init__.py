from autocoder_nano.agent.agentic_ask import AgenticAsk
from autocoder_nano.agent.agentic_edit import AgenticEdit
from autocoder_nano.agent.agentic_edit_types import AgenticEditRequest, AgenticEditConversationConfig
from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import SourceCodeList, AutoCoderArgs


def run_edit_agentic(llm: AutoLLM, args: AutoCoderArgs, conversation_config: AgenticEditConversationConfig):
    sources = SourceCodeList([])
    agentic_editor = AgenticEdit(
        args=args, llm=llm, files=sources, history_conversation=[], conversation_config=conversation_config,
    )
    request = AgenticEditRequest(user_input=args.query)
    agentic_editor.run_in_terminal(request)


def run_ask_agentic(llm: AutoLLM, args: AutoCoderArgs, conversation_config: AgenticEditConversationConfig):
    sources = SourceCodeList([])
    agentic_asker = AgenticAsk(
        args=args, llm=llm, files=sources, history_conversation=[], conversation_config=conversation_config,
    )
    request = AgenticEditRequest(user_input=args.query)
    agentic_asker.run_in_terminal(request)


__all__ = ["run_edit_agentic", "AgenticEditConversationConfig", "run_ask_agentic"]