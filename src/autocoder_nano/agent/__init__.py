from autocoder_nano.agent.agentic_edit import AgenticEdit
from autocoder_nano.agent.agentic_edit_types import AgenticEditRequest
from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import SourceCodeList, AutoCoderArgs


def run_edit_agentic(llm: AutoLLM, args: AutoCoderArgs):
    sources = SourceCodeList([])
    agentic_editor = AgenticEdit(
        args=args, llm=llm, files=sources, history_conversation=[]
    )
    request = AgenticEditRequest(user_input=args.query)
    agentic_editor.run_in_terminal(request)


__all__ = ["run_edit_agentic"]