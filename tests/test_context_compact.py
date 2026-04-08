import asyncio
import json
import pprint

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.context.auto_compact import (
    get_effective_context_window_size,
    get_auto_compact_threshold,
    calculate_token_warning_state,
    should_auto_compact
)
from autocoder_nano.context.compact.compact_types import AutoCompactTrackingState
from autocoder_nano.core import AutoLLM
from autocoder_nano.utils.file_utils import load_tokenizer


def get_effective_context_window_size_test():
    result = get_effective_context_window_size('(MiniMax)minimax/m2-code-plan')
    print(result)


def get_auto_compact_threshold_test():
    result = get_auto_compact_threshold('(MiniMax)minimax/m2-code-plan')
    print(result)


def calculate_token_warning_state_test():
    result = calculate_token_warning_state(201_000, '(MiniMax)minimax/m2-code-plan')
    pprint.pprint(result)
    result = calculate_token_warning_state(211_000, '(MiniMax)minimax/m2-code-plan')
    pprint.pprint(result)
    result = calculate_token_warning_state(231_000, '(MiniMax)minimax/m2-code-plan')
    pprint.pprint(result)
    result = calculate_token_warning_state(237_000, '(MiniMax)minimax/m2-code-plan')
    pprint.pprint(result)


def should_auto_compact_test():
    load_tokenizer()
    old_conversations = [
        {"role": "system", "content": "You are a helpful coding assistant."},
        {"role": "user", "content": "Can you read the main.py file and analyze it?"},
        {"role": "assistant", "content": "I'll read the file for you.\n\n<read_file>\n<path>main.py</path>\n"
                                         "</read_file>"},
        {
            "role": "user",
            "content": f"<tool_result tool_name='ReadFileTool' success='true'><message>File read "
                       f"successfully</message><content>{'# ' + 'Very long file content ' * 50000}"
                       f"</content></tool_result>"
        },
        {"role": "assistant", "content": "I can see this is a large Python file. Let me analyze its structure..."},
        {"role": "user", "content": "Now can you list all Python files in the directory?"},
        {"role": "assistant", "content": "I'll list the Python files.\n\n<list_files>\n<path>.</path>\n<pattern"
                                         ">*.py</pattern>\n</list_files>"},
        {
            "role": "user",
            "content": f"<tool_result tool_name='ListFilesTool' success='true'><message>Files "
                       f"listed</message><content>{json.dumps(['file' + str(i) + '.py' for i in range(100)])}"
                       f"</content></tool_result>"
        }
    ]
    result = should_auto_compact(old_conversations, '(MiniMax)minimax/m2-code-plan')
    pprint.pprint(result)


if __name__ == '__main__':
    should_auto_compact_test()