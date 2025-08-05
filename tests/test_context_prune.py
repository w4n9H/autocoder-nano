import json
import pprint

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.context import ContentPruner, ConversationsPruner
from autocoder_nano.core import AutoLLM
from autocoder_nano.project import project_source
from autocoder_nano.utils.file_utils import load_tokenizer


def pruner_content_test():
    load_tokenizer()
    auto_args = AutoCoderArgs()
    auto_args.project_type = "py"
    auto_args.source_dir = "/Users/moofs/Code/autocoder-nano"
    auto_args.target_file = "/Users/moofs/Code/autocoder-nano/output.txt"
    auto_args.exclude_files = ["regex://.*/src/*."]
    auto_args.chat_model = "glm-4.5"
    auto_llm = AutoLLM()
    auto_llm.setup_sub_client(
        "glm-4.5",
        "",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-4.5"
    )
    context_pruner = ContentPruner(
        max_tokens=1500,
        args=auto_args,
        llm=auto_llm
    )
    sources_codes = project_source(source_llm=auto_llm, args=auto_args)
    pruned_files = context_pruner.prune(
        sources_codes,  # 源文件列表 (SourceCode 对象)
        [{"role": "user", "content": "如何测试代码功能？"}],  # 对话上下文，用于智能评估相关性和抽取
        strategy="extract"  # 裁剪策略：score/delete/extract
    )
    for i in pruned_files:
        print(i)


def conversations_pruner_test():
    load_tokenizer()
    auto_args = AutoCoderArgs()
    auto_args.project_type = "py"
    auto_args.source_dir = "/Users/moofs/Code/autocoder-nano"
    auto_args.target_file = "/Users/moofs/Code/autocoder-nano/output.txt"
    auto_args.exclude_files = ["regex://.*/src/*."]
    auto_args.chat_model = "glm-4.5"
    auto_llm = AutoLLM()
    auto_llm.setup_sub_client(
        "glm-4.5",
        "",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-4.5"
    )
    conversations_pruner = ConversationsPruner(args=auto_args, llm=auto_llm)
    old_conversations = [
            {"role": "system", "content": "You are a helpful coding assistant."},
            {"role": "user", "content": "Can you read the main.py file and analyze it?"},
            {"role": "assistant", "content": "I'll read the file for you.\n\n<read_file>\n<path>main.py</path>\n"
                                             "</read_file>"},
            {
                "role": "user",
                "content": f"<tool_result tool_name='ReadFileTool' success='true'><message>File read "
                           f"successfully</message><content>{'# ' + 'Very long file content ' *  1000}"
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
    new_conversations = conversations_pruner.prune_conversations(conversations=old_conversations)
    pprint.pprint(conversations_pruner.get_cleanup_statistics(old_conversations, new_conversations))


if __name__ == '__main__':
    conversations_pruner_test()