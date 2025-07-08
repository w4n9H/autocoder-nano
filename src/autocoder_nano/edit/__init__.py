import os
from typing import Optional

from autocoder_nano.edit.actions import ActionPyProject, ActionSuffixProject
from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.config_utils import prepare_chat_yaml, get_last_yaml_file


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


def run_edit(llm: AutoLLM, args: AutoCoderArgs):
    dispacher = Dispacher(args=args, llm=llm)
    dispacher.dispach()


__all__ = ["run_edit"]