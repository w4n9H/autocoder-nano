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


def conversations_truncate_pruner_test():
    load_tokenizer()
    auto_args = AutoCoderArgs()
    auto_args.project_type = "py"
    auto_args.source_dir = "/Users/moofs/Code/autocoder-nano"
    auto_args.target_file = "/Users/moofs/Code/autocoder-nano/output.txt"
    auto_args.exclude_files = ["regex://.*/src/*."]
    auto_args.chat_model = "glm-4.5"
    auto_args.conversation_prune_safe_zone_tokens = 3000
    auto_args.conversation_prune_group_size = 2
    auto_args.conversation_prune_strategy = "truncate"
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
                       f"successfully</message><content>{'# ' + 'Very long file content ' * 1000}"
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


def conversations_summarize_pruner_test():
    load_tokenizer()
    auto_args = AutoCoderArgs()
    auto_args.project_type = "py"
    auto_args.source_dir = "/Users/moofs/Code/autocoder-nano"
    auto_args.target_file = "/Users/moofs/Code/autocoder-nano/output.txt"
    auto_args.exclude_files = ["regex://.*/src/*."]
    auto_args.chat_model = "doubao-seed-1.6"
    auto_args.conversation_prune_safe_zone_tokens = 350
    auto_args.conversation_prune_group_size = 4
    auto_args.conversation_prune_strategy = "summarize"
    auto_llm = AutoLLM()
    auto_llm.setup_sub_client(
        "doubao-seed-1.6",
        "",
        "https://ark.cn-beijing.volces.com/api/v3",
        "doubao-seed-1-6-250615"
    )
    conversations_pruner = ConversationsPruner(args=auto_args, llm=auto_llm)
    old_conversations = [
        {"role": "system", "context": "包含Pandas、NumPy和Matplotlib的使用问题与解答"},
        {"role": "user", "content": "如何用Pandas按条件筛选DataFrame？比如筛选'年龄>30'且'城市=北京'的行？"},
        {"context": "可以组合布尔条件：\n"
                    "import pandas as pd\n"
                    "df = pd.DataFrame(...)  # 假设已有数据\n"
                    "result = df[(df['年龄'] > 30) & (df['城市'] == '北京')]",
         "role": "assistant"},
        {"role": "user", "context": "DataFrame中有很多NaN值，怎么高效处理？需要保留大部分数据"},
        {"context": "分情况处理：\n"
                    "1. 数值列：用均值/中位数填充\n"
                    "   df['数值列'].fillna(df['数值列'].median(), inplace=True)\n"
                    "2. 类别列：用众数填充\n"
                    "   df['类别列'].fillna(df['类别列'].mode()[0], inplace=True)\n",
         "role": "assistant"},
        {"role": "user", "context": "如何用Matplotlib画一个带误差线的柱状图？需要显示每个柱子的标准差"},
        {"context": "示例代码：\n"
                    "import matplotlib.pyplot as plt\n"
                    "x = ['A', 'B', 'C']\n"
                    "y = [20, 35, 30]\n"
                    "error = [2, 4, 3]  # 标准差\n"
                    "plt.bar(x, y, yerr=error, capsize=5)\n"
                    "plt.title('带误差线的柱状图')\n"
                    "plt.show()",
         "role": "assistant"}
    ]
    new_conversations = conversations_pruner.prune_conversations(conversations=old_conversations)
    pprint.pprint(new_conversations)
    pprint.pprint(conversations_pruner.get_cleanup_statistics(old_conversations, new_conversations))


if __name__ == '__main__':
    conversations_summarize_pruner_test()