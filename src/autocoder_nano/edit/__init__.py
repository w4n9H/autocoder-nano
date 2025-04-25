from typing import Optional

from autocoder_nano.edit.actions import ActionPyProject, ActionSuffixProject
from autocoder_nano.llm_client import AutoLLM
from autocoder_nano.llm_types import AutoCoderArgs


class Dispacher:
    def __init__(self, args: AutoCoderArgs, llm: Optional[AutoLLM] = None):
        self.args = args
        self.llm = llm

    def dispach(self):
        dispacher_actions = [
            ActionPyProject(args=self.args, llm=self.llm),
            ActionSuffixProject(args=self.args, llm=self.llm)
        ]
        for action in dispacher_actions:
            if action.run():
                return