import argparse
import glob
import hashlib
import os
import json
import subprocess
import time
import uuid
from datetime import datetime

from autocoder_nano.utils.file_utils import load_tokenizer
from autocoder_nano.context import get_context_manager, ContextManagerConfig
from autocoder_nano.chat import stream_chat_display
from autocoder_nano.edit import run_edit
from autocoder_nano.helper import show_help
from autocoder_nano.project import project_source
from autocoder_nano.index import (index_export, index_import, index_build,
                                  index_build_and_filter, extract_symbols)
from autocoder_nano.rules import rules_from_active_files, rules_from_commit_changes, get_rules_context
from autocoder_nano.agent import AgenticEditConversationConfig, run_agentic, run_main_agentic
from autocoder_nano.rag import rag_build_cache, rag_retrieval
from autocoder_nano.core import prompt, extract_code, AutoLLM
from autocoder_nano.actypes import *
from autocoder_nano.editor import run_editor
from autocoder_nano.utils.completer_utils import CommandCompleter
from autocoder_nano.version import __version__
from autocoder_nano.templates import create_actions
from autocoder_nano.utils.git_utils import (repo_init, commit_changes, revert_changes,
                                            get_uncommitted_changes, generate_commit_message)
from autocoder_nano.utils.sys_utils import default_exclude_dirs, detect_env
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.utils.config_utils import (get_final_config, convert_yaml_config_to_str, convert_config_value,
                                               convert_yaml_to_config, get_last_yaml_file, prepare_chat_yaml)

from prompt_toolkit import prompt as _toolkit_prompt, PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import confirm
from prompt_toolkit.styles import Style
from rich.live import Live
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


printer = Printer()
console = printer.get_console()


project_root = os.getcwd()
base_persist_dir = os.path.join(project_root, ".auto-coder", "plugins", "chat-auto-coder")


commands = [
    "/add_files", "/remove_files", "/list_files", "/conf", "/coding", "/chat", "/revert", "/index/query",
    "/index/build", "/exclude_dirs", "/exclude_files", "/help", "/shell", "/exit", "/mode", "/models", "/commit",
    "/rules", "/auto", "/rag/build", "/rag/query", "/editor", "/long_context_auto", "/context"
]

memory = {
    "conversation": [],
    "current_files": {"files": [], "groups": {}},
    "conf": {
        "auto_merge": "editblock",
        "chat_model": "",
        "code_model": "",
    },
    "exclude_dirs": [],
    "mode": "normal",  # 新增mode字段,默认为normal模式
    "models": {}
}


# args: AutoCoderArgs = AutoCoderArgs()


def get_all_file_names_in_project() -> List[str]:
    file_names = []
    final_exclude_dirs = default_exclude_dirs + memory.get("exclude_dirs", [])
    for root, dirs, files in os.walk(project_root, followlinks=True):
        dirs[:] = [d for d in dirs if d not in final_exclude_dirs]
        file_names.extend(files)
    return file_names


def get_all_file_in_project() -> List[str]:
    file_names = []
    final_exclude_dirs = default_exclude_dirs + memory.get("exclude_dirs", [])
    for root, dirs, files in os.walk(project_root, followlinks=True):
        dirs[:] = [d for d in dirs if d not in final_exclude_dirs]
        for file in files:
            file_names.append(os.path.join(root, file))
    return file_names


def get_all_dir_names_in_project() -> List[str]:
    dir_names = []
    final_exclude_dirs = default_exclude_dirs + memory.get("exclude_dirs", [])
    for root, dirs, files in os.walk(project_root, followlinks=True):
        dirs[:] = [d for d in dirs if d not in final_exclude_dirs]
        for _dir in dirs:
            dir_names.append(_dir)
    return dir_names


def get_all_file_in_project_with_dot() -> List[str]:
    file_names = []
    final_exclude_dirs = default_exclude_dirs + memory.get("exclude_dirs", [])
    for root, dirs, files in os.walk(project_root, followlinks=True):
        dirs[:] = [d for d in dirs if d not in final_exclude_dirs]
        for file in files:
            file_names.append(os.path.join(
                root, file).replace(project_root, "."))
    return file_names


def get_symbol_list() -> List[SymbolItem]:
    list_of_symbols = []
    index_file = os.path.join(project_root, ".auto-coder", "index.json")

    if os.path.exists(index_file):
        with open(index_file, "r") as file:
            index_data = json.load(file)
    else:
        index_data = {}

    for item in index_data.values():
        symbols_str = item["symbols"]
        module_name = item["module_name"]
        info1 = extract_symbols(symbols_str)
        for name in info1.classes:
            list_of_symbols.append(
                SymbolItem(symbol_name=name, symbol_type=SymbolType.CLASSES, file_name=module_name)
            )
        for name in info1.functions:
            list_of_symbols.append(
                SymbolItem(symbol_name=name, symbol_type=SymbolType.FUNCTIONS, file_name=module_name)
            )
        for name in info1.variables:
            list_of_symbols.append(
                SymbolItem(symbol_name=name, symbol_type=SymbolType.VARIABLES, file_name=module_name)
            )
    return list_of_symbols


def find_files_in_project(patterns: List[str]) -> List[str]:
    matched_files = []
    final_exclude_dirs = default_exclude_dirs + memory.get("exclude_dirs", [])

    for pattern in patterns:
        if "*" in pattern or "?" in pattern:
            for file_path in glob.glob(pattern, recursive=True):
                if os.path.isfile(file_path):
                    abs_path = os.path.abspath(file_path)
                    if not any(exclude_dir in abs_path.split(os.sep) for exclude_dir in final_exclude_dirs):
                        matched_files.append(abs_path)
        else:
            is_added = False
            # add files belongs to project
            for root, dirs, files in os.walk(project_root, followlinks=True):
                dirs[:] = [d for d in dirs if d not in final_exclude_dirs]
                if pattern in files:
                    matched_files.append(os.path.join(root, pattern))
                    is_added = True
                else:
                    for file in files:
                        _pattern = os.path.abspath(pattern)
                        if _pattern in os.path.join(root, file):
                            matched_files.append(os.path.join(root, file))
                            is_added = True
            # add files not belongs to project
            if not is_added:
                matched_files.append(pattern)
    return list(set(matched_files))


def save_memory():
    with open(os.path.join(base_persist_dir, "nano-memory.json"), "w") as fp:
        json_str = json.dumps(memory, indent=2, ensure_ascii=False)
        fp.write(json_str)
    load_memory()


def load_memory():
    global memory
    memory_path = os.path.join(base_persist_dir, "nano-memory.json")
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r") as f:
                memory = json.load(f)
        except json.JSONDecodeError as e:
            raise Exception(f"打开配置文件失败, 文件内容不是有效的JSON格式, 错误原因: {str(e)} , 文件位置: {memory_path}")


def get_memory():
    load_memory()
    return memory


completer = CommandCompleter(
    commands=commands,
    file_system_model=FileSystemModel(
        project_root=project_root,
        get_all_file_names_in_project=get_all_file_names_in_project,
        get_all_file_in_project=get_all_file_in_project,
        get_all_dir_names_in_project=get_all_dir_names_in_project,
        get_all_file_in_project_with_dot=get_all_file_in_project_with_dot,
        get_symbol_list=get_symbol_list
    ),
    memory_model=MemoryConfig(
        get_memory_func=get_memory,
        save_memory_func=save_memory
    )
)


def exclude_dirs(dir_names: List[str]):
    new_dirs = dir_names
    existing_dirs = memory.get("exclude_dirs", [])
    dirs_to_add = [d for d in new_dirs if d not in existing_dirs]

    if dirs_to_add:
        existing_dirs.extend(dirs_to_add)
        if "exclude_dirs" not in memory:
            memory["exclude_dirs"] = existing_dirs
        printer.print_text(Text(f"已添加排除目录: {dirs_to_add}", style="bold green"))
        for d in dirs_to_add:
            exclude_files(f"regex://.*/{d}/*.")
        # exclude_files([f"regex://.*/{d}/*." for d in dirs_to_add])
    else:
        printer.print_text(Text(f"所有指定目录已在排除列表中. ", style="bold green"))
    save_memory()
    completer.refresh_files()


def exclude_files(query: str):
    if "/list" in query:
        query = query.replace("/list", "", 1).strip()
        existing_file_patterns = memory.get("exclude_files", [])

        printer.print_table_compact(
            headers=["File Pattern"],
            data=[[file_pattern] for file_pattern in existing_file_patterns],
            title="Exclude Files",
            show_lines=False
        )
        return

    if "/drop" in query:
        query = query.replace("/drop", "", 1).strip()
        existing_file_patterns = memory.get("exclude_files", [])
        existing_file_patterns.remove(query.strip())
        memory["exclude_files"] = existing_file_patterns
        if query.startswith("regex://.*/") and query.endswith("/*."):
            existing_dirs_patterns = memory.get("exclude_dirs", [])
            dir_query = query.replace("regex://.*/", "", 1).replace("/*.", "", 1)
            if dir_query in existing_dirs_patterns:
                existing_dirs_patterns.remove(dir_query.strip())
        save_memory()
        completer.refresh_files()
        return

    new_file_patterns = query.strip().split(",")

    existing_file_patterns = memory.get("exclude_files", [])
    file_patterns_to_add = [f for f in new_file_patterns if f not in existing_file_patterns]

    for file_pattern in file_patterns_to_add:
        if not file_pattern.startswith("regex://"):
            raise

    if file_patterns_to_add:
        existing_file_patterns.extend(file_patterns_to_add)
        if "exclude_files" not in memory:
            memory["exclude_files"] = existing_file_patterns
        save_memory()
        printer.print_text(f"已添加排除文件: {file_patterns_to_add}. ", style="green")
    else:
        printer.print_text(f"所有指定文件已在排除列表中. ", style="green")


def index_command(llm):
    args = get_final_config(project_root, memory, query="", delete_execute_file=True)
    index_build(llm=llm, args=args, sources_codes=project_source(source_llm=llm, args=args))
    return


def index_query_command(query: str, llm: AutoLLM):
    args = get_final_config(project_root, memory, query=query, delete_execute_file=True)
    index_build_and_filter(llm=llm, args=args, sources_codes=project_source(source_llm=llm, args=args))
    return


def rag_build_command(llm: AutoLLM):
    args = get_final_config(project_root, memory, query="", delete_execute_file=True)
    if not args.rag_url:
        printer.print_text("请通过 /conf 设置 rag_url 参数, 即本地目录", style="red")
        return
    rag_build_cache(llm=llm, args=args, path=args.rag_url)
    return


def rag_query_command(query: str, llm: AutoLLM):
    args = get_final_config(project_root, memory, query=query, delete_execute_file=True)
    if not args.rag_url:
        printer.print_text("请通过 /conf 设置 rag_url 参数, 即本地目录", style="red")
        return
    contexts = rag_retrieval(llm=llm, args=args, path=args.rag_url)
    if contexts:
        printer.print_markdown(
            text=contexts[0].source_code,
            panel=True
        )
    return


def print_chat_history(history, max_entries=5):
    recent_history = history[-max_entries:]
    for entry in recent_history:
        role = entry["role"]
        content = entry["content"]
        if role == "user":
            printer.print_text(Text(content, style="bold red"))
        else:
            printer.print_markdown(content, panel=True)


@prompt()
def code_review(query: str) -> str:
    """
    前面提供了上下文，对代码进行review，参考如下检查点。
    1. 有没有调用不符合方法，类的签名的调用，包括对第三方类，模块，方法的检查（如果上下文提供了这些信息）
    2. 有没有未声明直接使用的变量，方法，类
    3. 有没有明显的语法错误
    4. 如果是python代码，检查有没有缩进方面的错误
    5. 如果是python代码，检查是否 try 后面缺少 except 或者 finally
    {% if query %}
    6. 用户的额外的检查需求：{{ query }}
    {% endif %}

    如果用户的需求包含了@一个文件名 或者 @@符号， 那么重点关注这些文件或者符号（函数，类）进行上述的review。
    review 过程中严格遵循上述的检查点，不要遗漏，没有发现异常的点直接跳过，只对发现的异常点，给出具体的修改后的代码。
    """


def chat_command(query: str, llm: AutoLLM):
    args = get_final_config(project_root, memory, query)

    is_history = query.strip().startswith("/history")
    is_new = "/new" in query
    if is_new:
        query = query.replace("/new", "", 1).strip()

    if "/review" in query and "/commit" in query:
        pass  # 审核最近的一次commit代码，开发中
    else:
        #
        is_review = query.strip().startswith("/review")
        if is_review:
            query = query.replace("/review", "", 1).strip()
            query = code_review.prompt(query)

    memory_dir = os.path.join(args.source_dir, ".auto-coder", "memory")
    os.makedirs(memory_dir, exist_ok=True)
    memory_file = os.path.join(memory_dir, "chat_history.json")

    if is_new:
        if os.path.exists(memory_file):
            with open(memory_file, "r") as f:
                old_chat_history = json.load(f)
            if "conversation_history" not in old_chat_history:
                old_chat_history["conversation_history"] = []
            old_chat_history["conversation_history"].append(old_chat_history.get("ask_conversation", []))
            chat_history = {"ask_conversation": [], "conversation_history": old_chat_history["conversation_history"]}
        else:
            chat_history = {"ask_conversation": [],
                            "conversation_history": []}
        with open(memory_file, "w") as fp:
            json_str = json.dumps(chat_history, ensure_ascii=False)
            fp.write(json_str)

        printer.print_panel(
            Text("新会话已开始, 之前的聊天历史已存档.", style="green"),
            title="Session Status",
            center=True
        )
        if not query:
            return

    if os.path.exists(memory_file):
        with open(memory_file, "r") as f:
            chat_history = json.load(f)
        if "conversation_history" not in chat_history:
            chat_history["conversation_history"] = []
    else:
        chat_history = {"ask_conversation": [],
                        "conversation_history": []}

    if is_history:
        show_chat = []
        if "ask_conversation" in chat_history:
            show_chat.extend(chat_history["ask_conversation"])
        print_chat_history(show_chat)
        return

    chat_history["ask_conversation"].append(
        {"role": "user", "content": query}
    )

    pre_conversations = []
    s = index_build_and_filter(llm=llm, args=args, sources_codes=project_source(source_llm=llm, args=args))
    if s:
        pre_conversations.append(
            {
                "role": "user",
                "content": f"下面是一些文档和源码，如果用户的问题和他们相关，请参考他们：\n{s}",
            }
        )
        pre_conversations.append(
            {"role": "assistant", "content": "read"})
    else:
        return

    loaded_conversations = pre_conversations + chat_history["ask_conversation"]

    assistant_response = stream_chat_display(chat_llm=llm, args=args, conversations=loaded_conversations)

    chat_history["ask_conversation"].append({"role": "assistant", "content": assistant_response})

    with open(memory_file, "w") as fp:
        json_str = json.dumps(chat_history, ensure_ascii=False)
        fp.write(json_str)

    return


def init_project(project_type):
    if not project_type:
        printer.print_text(
            f"请指定项目类型。可选的项目类型包括：py|ts| 或文件扩展名(例如:.java,.scala), 多个扩展名逗号分隔.", style="green"
        )
        return
    os.makedirs(os.path.join(project_root, "actions"), exist_ok=True)
    os.makedirs(os.path.join(project_root, ".auto-coder"), exist_ok=True)
    os.makedirs(os.path.join(project_root, ".auto-coder", "autocoderrules"), exist_ok=True)
    source_dir = os.path.abspath(project_root)
    create_actions(
        source_dir=source_dir,
        params={"project_type": project_type,
                "source_dir": source_dir},
    )

    repo_init(source_dir)
    with open(os.path.join(source_dir, ".gitignore"), "a") as f:
        f.write("\n.auto-coder/")
        f.write("\nactions/")
        f.write("\noutput.txt")

    printer.print_text(f"已在 {os.path.abspath(project_root)} 成功初始化 autocoder-nano 项目", style="green")
    return


def get_conversation_history() -> str:
    memory_dir = os.path.join(project_root, ".auto-coder", "memory")
    os.makedirs(memory_dir, exist_ok=True)
    memory_file = os.path.join(memory_dir, "chat_history.json")

    def error_message():
        printer.print_panel(Text("未找到可应用聊天记录.", style="yellow"), title="Chat History", center=True)

    if not os.path.exists(memory_file):
        error_message()
        return ""

    with open(memory_file, "r") as f:
        chat_history = json.load(f)

    if not chat_history["ask_conversation"]:
        error_message()
        return ""

    conversations = chat_history["ask_conversation"]

    context = ""
    context += f"下面是我们的历史对话，参考我们的历史对话从而更好的理解需求和修改代码。\n\n<history>\n"
    for conv in conversations:
        if conv["role"] == "user":
            context += f"用户: {conv['content']}\n"
        elif conv["role"] == "assistant":
            context += f"你: {conv['content']}\n"
    context += "</history>\n"
    return context


def coding_command(query: str, llm: AutoLLM):
    is_apply = query.strip().startswith("/apply")
    if is_apply:
        query = query.replace("/apply", "", 1).strip()
    is_rules = False

    memory["conversation"].append({"role": "user", "content": query})
    conf = memory.get("conf", {})

    prepare_chat_yaml(project_root)  # 复制上一个序号的 yaml 文件, 生成一个新的聊天 yaml 文件
    latest_yaml_file = get_last_yaml_file(project_root)

    if latest_yaml_file:
        yaml_config = {
            "include_file": ["./base/base.yml"],
            "skip_build_index": conf.get("skip_build_index", "true") == "true",
            "skip_confirm": conf.get("skip_confirm", "true") == "true",
            "chat_model": conf.get("chat_model", ""),
            "code_model": conf.get("code_model", ""),
            "auto_merge": conf.get("auto_merge", "editblock"),
            "context": ""
        }

        for key, value in conf.items():
            converted_value = convert_config_value(key, value)
            if converted_value is not None:
                yaml_config[key] = converted_value

        yaml_config["urls"] = memory["current_files"]["files"]
        yaml_config["query"] = query

        if is_apply:
            yaml_config["context"] += get_conversation_history()

        if is_rules:
            yaml_config["context"] += get_rules_context(project_root)

        yaml_config["file"] = latest_yaml_file
        yaml_content = convert_yaml_config_to_str(yaml_config=yaml_config)
        execute_file = os.path.join(project_root, "actions", latest_yaml_file)
        with open(os.path.join(execute_file), "w") as f:
            f.write(yaml_content)
        args = convert_yaml_to_config(execute_file)

        run_edit(llm=llm, args=args)
    else:
        printer.print_text(f"创建新的 YAML 文件失败.", style="yellow")

    save_memory()
    completer.refresh_files()


def execute_revert(args: AutoCoderArgs):
    repo_path = args.source_dir

    file_content = open(args.file).read()
    md5 = hashlib.md5(file_content.encode("utf-8")).hexdigest()
    file_name = os.path.basename(args.file)

    revert_result = revert_changes(repo_path, f"auto_coder_{file_name}_{md5}")
    if revert_result:
        os.remove(args.file)
        printer.print_text(f"已成功回退最后一次 chat action 的更改，并移除 YAML 文件 {args.file}", style="green")
    else:
        printer.print_text(f"回退文件 {args.file} 的更改失败", style="red")
    return


def revert():
    last_yaml_file = get_last_yaml_file(project_root)
    if last_yaml_file:
        file_path = os.path.join(project_root, "actions", last_yaml_file)
        args = convert_yaml_to_config(file_path)
        execute_revert(args)
    else:
        printer.print_text(f"No previous chat action found to revert.", style="yellow")


def print_commit_info(commit_result: CommitResult):
    printer.print_table_compact(
        data=[
            ["提交哈希", commit_result.commit_hash],
            ["提交信息", commit_result.commit_message],
            ["更改的文件", "\n".join(commit_result.changed_files) if commit_result.changed_files else "No files changed"]
        ],
        title="提交信息", headers=["属性", "值"], caption="(使用 /revert 撤销此提交)"
    )

    if commit_result.diffs:
        for file, diff in commit_result.diffs.items():
            printer.print_text(f"File: {file}", style="green")
            syntax = Syntax(diff, "diff", theme="monokai", line_numbers=True)
            printer.print_panel(syntax, title="File Diff", center=True)


def commit_info(query: str, llm: AutoLLM):
    repo_path = project_root
    prepare_chat_yaml(project_root)  # 复制上一个序号的 yaml 文件, 生成一个新的聊天 yaml 文件

    latest_yaml_file = get_last_yaml_file(project_root)
    execute_file = None

    if latest_yaml_file:
        try:
            execute_file = os.path.join(project_root, "actions", latest_yaml_file)
            conf = memory.get("conf", {})
            yaml_config = {
                "include_file": ["./base/base.yml"],
                "skip_build_index": conf.get("skip_build_index", "true") == "true",
                "skip_confirm": conf.get("skip_confirm", "true") == "true",
                "chat_model": conf.get("chat_model", ""),
                "code_model": conf.get("code_model", ""),
                "auto_merge": conf.get("auto_merge", "editblock"),
                "context": ""
            }
            for key, value in conf.items():
                converted_value = convert_config_value(key, value)
                if converted_value is not None:
                    yaml_config[key] = converted_value

            current_files = memory["current_files"]["files"]
            yaml_config["urls"] = current_files

            # 临时保存yaml文件，然后读取yaml文件，更新args
            temp_yaml = os.path.join(project_root, "actions", f"{uuid.uuid4()}.yml")
            try:
                with open(temp_yaml, "w", encoding="utf-8") as f:
                    f.write(convert_yaml_config_to_str(yaml_config=yaml_config))
                args = convert_yaml_to_config(temp_yaml)
            finally:
                if os.path.exists(temp_yaml):
                    os.remove(temp_yaml)

            # commit_message = ""
            commit_llm = llm
            commit_llm.setup_default_model_name(args.chat_model)
            printer.print_text(f"Commit 信息生成中...", style="green")

            try:
                uncommitted_changes = get_uncommitted_changes(repo_path)
                commit_message = generate_commit_message.with_llm(commit_llm).run(
                    uncommitted_changes
                )
                memory["conversation"].append({"role": "user", "content": commit_message.output})
            except Exception as err:
                printer.print_text(f"Commit 信息生成失败: {err}", style="red")
                return

            yaml_config["query"] = commit_message.output
            yaml_content = convert_yaml_config_to_str(yaml_config=yaml_config)
            with open(os.path.join(execute_file), "w", encoding="utf-8") as f:
                f.write(yaml_content)

            file_content = open(execute_file).read()
            md5 = hashlib.md5(file_content.encode("utf-8")).hexdigest()
            file_name = os.path.basename(execute_file)
            commit_result = commit_changes(repo_path, f"auto_coder_nano_{file_name}_{md5}\n{commit_message}")
            print_commit_info(commit_result=commit_result)
            if commit_message:
                printer.print_text(f"Commit 成功", style="green")
        except Exception as err:
            import traceback
            traceback.print_exc()
            printer.print_text(f"Commit 失败: {err}", style="red")
            if execute_file:
                os.remove(execute_file)


def printer_conversation_table(_conversation_list):
    data_list = []
    for i in _conversation_list:
        data_list.append([
            i["conversation_id"], f"{i['description'][:20]} ......",
            datetime.fromtimestamp(i["updated_at"]).strftime("%Y-%m-%d %H:%M"),
            len(i["messages"])
        ])
    printer.print_table_compact(
        title="历史会话列表",
        headers=["会话ID", "会话描述", "会话更新时间", "会话消息数量"],
        data=data_list
    )


def auto_command(query: str, llm: AutoLLM):
    # args = get_final_config(project_root, memory, query=query.strip(), delete_execute_file=True)
    conversation_config = AgenticEditConversationConfig()
    # 获取上下文管理器实例
    cmc = ContextManagerConfig()
    cmc.storage_path = os.path.join(project_root, ".auto-coder", "context")
    gcm = get_context_manager(config=cmc)

    def _printer_resume_conversation(_conversation_id):
        printer.print_panel(
            Text(f"Agent 恢复对话[{_conversation_id}]", style="green"),
            title="Agent Session Status",
            center=True
        )

    def _resume_conversation(_query):
        _conv_id = gcm.get_current_conversation_id()
        if not _conv_id:
            printer.print_text(f"未获取到当前会话ID, 请手动进行选择", style="yellow")
            _convs = gcm.list_conversations(limit=10)
            if _convs:
                printer_conversation_table(_convs)
                _conv_id = input(f"  以上为最近10个会话列表, 请选择您想要恢复对话的ID: ").strip().lower()
                conversation_config.action = "resume"
                conversation_config.query = query.strip()
                conversation_config.conversation_id = _conv_id
                _printer_resume_conversation(_conv_id)
            else:
                printer.print_text(f"未获取到历史会话, 默认创建新会话开始 Agent", style="yellow")
                conversation_config.action = "new"
                conversation_config.query = query.strip()
                conversation_config.conversation_id = None
                printer.print_text(f"Agent 新会话已开始.", style="green")
        else:
            # 这里可能需要判断一下会话id是否真实存在
            conversation_config.action = "resume"
            conversation_config.query = query.strip()
            conversation_config.conversation_id = _conv_id
            _printer_resume_conversation(_conv_id)

    if "/new" in query:
        query = query.replace("/new", "", 1).strip()
        conversation_config.action = "new"
        conversation_config.query = query
        conversation_config.conversation_id = None
        printer.print_text(f"Agent 新会话已开始.", style="green")
    elif "/resume" in query:
        query = query.replace("/resume", "", 1).strip()
        convs = gcm.list_conversations(limit=10)
        if convs:
            printer_conversation_table(convs)
            conv_id = input(f" 以上为最近10个会话列表, 请选择您想要恢复对话的ID: ").strip().lower()
            conversation_config.action = "resume"
            conversation_config.query = query.strip()
            conversation_config.conversation_id = conv_id
            _printer_resume_conversation(conv_id)
        else:
            raise Exception("未获取到历史会话, 请直接使用 /auto 或者 /auto /new")
        # _resume_conversation(query)
    else:
        _resume_conversation(query)

    args = get_final_config(project_root, memory, query=query, delete_execute_file=True)

    run_main_agentic(llm=llm, args=args, conversation_config=conversation_config)


def long_context_auto_command(llm: AutoLLM):
    import tempfile
    initial_content = f"请输入你的需求: \n"
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w+', delete=True, suffix='.txt') as tmpfile:
        tmpfile.write(initial_content)
        tmpfile.flush()
        temp_path = tmpfile.name
        query = run_editor(temp_path)

    args = get_final_config(project_root, memory, query=query.strip(), delete_execute_file=True)
    conversation_config = AgenticEditConversationConfig(
        action="new",
        query=query.strip()
    )
    run_main_agentic(llm=llm, args=args, conversation_config=conversation_config)


def context_command(context_args):
    # 获取上下文管理器实例
    cmc = ContextManagerConfig()
    cmc.storage_path = os.path.join(project_root, ".auto-coder", "context")
    gcm = get_context_manager(config=cmc)

    if context_args[0] == "/list":
        printer_conversation_table(gcm.list_conversations(limit=10))

    if context_args[0] == "/remove":
        printer_conversation_table(gcm.list_conversations(limit=10))
        delete_conv_id = input(f" 以上为最近10个会话列表, 请选择您想要删除的对话ID: ").strip().lower()
        delete_conv = gcm.get_conversation(delete_conv_id)
        if delete_conv is None:
            printer.print_text(f"该会话不存在 {delete_conv_id}", style="yellow")
        if isinstance(delete_conv, dict):
            try:
                if gcm.delete_conversation(delete_conv_id):
                    printer.print_text(f"删除会话 {delete_conv_id} 成功, 会话条数 {len(delete_conv['messages'])}", style="green")
                else:
                    printer.print_text(f"删除会话 {delete_conv_id} 失败, 会话可能不存在", style="red")
            except Exception as e:
                printer.print_text(f"{e}", style="red")


def editor_command(file_path: str):
    abs_input_path = os.path.abspath(os.path.join(project_root, file_path)) if not os.path.isabs(file_path) else file_path
    run_editor(abs_input_path)


@prompt()
def _generate_shell_script(user_input: str):
    """
    环境信息如下:

    操作系统: {{ env_info.os_name }} {{ env_info.os_version }}
    Python版本: {{ env_info.python_version }}
    终端类型: {{ env_info.shell_type }}
    终端编码: {{ env_info.shell_encoding }}
    {%- if env_info.conda_env %}
    Conda环境: {{ env_info.conda_env }}
    {%- endif %}
    {%- if env_info.virtualenv %}
    虚拟环境: {{ env_info.virtualenv }}
    {%- endif %}

    根据用户的输入以及当前的操作系统和终端类型以及脚本类型生成脚本，
    注意只能生成一个shell脚本，不要生成多个。

    用户输入: {{ user_input }}

    请生成一个适当的 shell 脚本来执行用户的请求。确保脚本是安全的, 并且可以在当前Shell环境中运行。
    脚本应该包含必要的注释来解释每个步骤。
    脚本应该以注释的方式告知我当前操作系统版本, Python版本, 终端类型, 终端编码, Conda环境 等信息。
    脚本内容请用如下方式返回：

    ```script
    # 你的 script 脚本内容
    ```
    """
    env_info = detect_env()
    return {
        "env_info": env_info
    }


def generate_shell_command(input_text: str, llm: AutoLLM) -> str | None:
    args = get_final_config(project_root, memory, query=input_text, delete_execute_file=True)

    try:
        printer.print_panel(
            Text(f"正在根据用户输入 {input_text} 生成 Shell 脚本...", style="green"), title="命令生成",
        )
        llm.setup_default_model_name(args.code_model)
        result = _generate_shell_script.with_llm(llm).run(user_input=input_text)
        shell_script = extract_code(result.output)[0][1]
        printer.print_code(
            code=shell_script, lexer="shell", panel=True
        )
        return shell_script
    finally:
        pass
        # os.remove(execute_file)


def execute_shell_command(command: str):
    try:
        # Use shell=True to support shell mode
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            shell=True,
        )

        output = []
        with Live(console=console, refresh_per_second=4) as live:
            while True:
                output_line = process.stdout.readline()
                error_line = process.stderr.readline()

                if output_line:
                    output.append(output_line.strip())
                    live.update(
                        Panel(
                            Text("\n".join(output[-20:]), style="green"),
                            title="Shell 输出",
                            border_style="dim blue",
                        )
                    )
                if error_line:
                    output.append(f"ERROR: {error_line.strip()}")
                    live.update(
                        Panel(
                            Text("\n".join(output[-20:]), style="red"),
                            title="Shell 输出",
                            border_style="dim blue",
                        )
                    )
                if output_line == "" and error_line == "" and process.poll() is not None:
                    break

        if process.returncode != 0:
            printer.print_text(f"命令执行失败，返回码: {process.returncode}", style="red")
        else:
            printer.print_text(f"命令执行成功", style="green")
    except FileNotFoundError:
        printer.print_text(f"未找到命令:", style="yellow")
    except subprocess.SubprocessError as e:
        printer.print_text(f"命令执行错误:", style="yellow")


def parse_args(input_args: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="Auto-Coder Nano")

    parser.add_argument("--debug", action="store_true", help="开启 debug 模式")
    parser.add_argument("--quick", action="store_true", help="进入 auto-coder.nano 无需初始化系统")
    # 新增 --agent 参数
    parser.add_argument("--agent", type=str, help="指定要执行的代理指令")

    if input_args:
        _args = parser.parse_args(input_args)
    else:
        _args = parser.parse_args()

    return AutoCoderArgs(**vars(_args)), _args


def configure(conf: str, skip_print=False):
    parts = conf.split(None, 1)
    if len(parts) == 2 and parts[0] in ["/drop", "/unset", "/remove"]:
        key = parts[1].strip()
        if key in memory["conf"]:
            del memory["conf"][key]
            save_memory()
            print(f"\033[92mDeleted configuration: {key}\033[0m")
        else:
            print(f"\033[93mConfiguration not found: {key}\033[0m")
    else:
        parts = conf.split(":", 1)
        if len(parts) != 2:
            print(
                "\033[91mError: Invalid configuration format. Use 'key:value' or '/drop key'.\033[0m"
            )
            return
        key, value = parts
        key = key.strip()
        value = value.strip()
        if not value:
            print("\033[91mError: Value cannot be empty. Use 'key:value'.\033[0m")
            return
        memory["conf"][key] = value
        save_memory()
        if not skip_print:
            print(f"\033[92mSet {key} to {value}\033[0m")


def configure_project_type() -> str:
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import print_formatted_text
    from prompt_toolkit.styles import Style
    from html import escape

    style = Style.from_dict(
        {
            "info": "#ansicyan",
            "warning": "#ansiyellow",
            "input-area": "#ansigreen",
            "header": "#ansibrightyellow bold",
        }
    )

    def print_info(text):
        print_formatted_text(
            HTML(f"<info>{escape(text)}</info>"), style=style)

    def print_warning(text):
        print_formatted_text(
            HTML(f"<warning>{escape(text)}</warning>"), style=style)

    def print_header(text):
        print_formatted_text(
            HTML(f"<header>{escape(text)}</header>"), style=style)

    print_header(f"\n=== 项目类型配置 ===\n")
    print_info("项目类型支持：")
    print_info("  - 语言后缀（例如：.py, .java, .ts）")
    print_info("  - 预定义类型：py（Python）, ts（TypeScript/JavaScript）")
    print_info("对于混合语言项目，使用逗号分隔的值.")
    print_info("示例：'.java,.scala' 或 '.py,.ts'")

    print_warning(f"如果留空, 默认为 'py'.\n")

    project_type = _toolkit_prompt("请输入项目类型：", default="py", style=style).strip()

    if project_type:
        configure(f"project_type:{project_type}", skip_print=True)
        configure("skip_build_index:false", skip_print=True)
        print_info(f"\n项目类型设置为： {project_type}")
    else:
        print_info(f"\n使用默认项目类型：py")

    print_warning(f"\n您可以稍后使用以下命令更改此设置:")
    print_warning("/conf project_type:<new_type>\n")

    return project_type


def initialize_system():
    printer.print_text(f"🚀 正在初始化系统...", style="green")

    def _init_project():
        first_time = False
        if not os.path.exists(os.path.join(project_root, ".auto-coder")):
            first_time = True
            printer.print_text("当前目录未初始化为auto-coder项目.", style="yellow")
            init_choice = input(f"  是否现在初始化项目？(y/n): ").strip().lower()
            if init_choice == "y":
                try:
                    if first_time:  # 首次启动,配置项目类型
                        if not os.path.exists(base_persist_dir):
                            os.makedirs(base_persist_dir, exist_ok=True)
                            printer.print_text("创建目录：{}".format(base_persist_dir), style="green")
                        project_type = configure_project_type()
                        init_project(project_type)
                    printer.print_text("项目初始化成功.", style="green")
                except Exception as e:
                    printer.print_text(f"项目初始化失败, {str(e)}.", style="red")
                    exit(1)
            else:
                printer.print_text("退出而不初始化.", style="yellow")
                exit(1)

        printer.print_text("项目初始化完成.", style="green")

    _init_project()


def add_files(add_files_args: List[str]):
    if "groups" not in memory["current_files"]:
        memory["current_files"]["groups"] = {}
    if "groups_info" not in memory["current_files"]:
        memory["current_files"]["groups_info"] = {}
    if "current_groups" not in memory["current_files"]:
        memory["current_files"]["current_groups"] = []
    groups = memory["current_files"]["groups"]
    groups_info = memory["current_files"]["groups_info"]

    if not add_files_args:
        printer.print_panel(Text("请为 /add_files 命令提供参数.", style="red"), title="错误", center=True)
        return

    if add_files_args[0] == "/refresh":  # 刷新
        completer.refresh_files()
        load_memory()
        printer.print_panel(Text("已刷新的文件列表.", style="green"), title="文件刷新", center=True)
        return

    if add_files_args[0] == "/group":
        # 列出组
        if len(add_files_args) == 1 or (len(add_files_args) == 2 and add_files_args[1] == "list"):
            if not groups:
                printer.print_panel(Text("未定义任何文件组.", style="yellow"), title="文件组", center=True)
            else:
                data_list = []
                for i, (group_name, files) in enumerate(groups.items()):
                    query_prefix = groups_info.get(group_name, {}).get("query_prefix", "")
                    is_active = ("✓" if group_name in memory["current_files"]["current_groups"] else "")
                    data_list.append([
                        group_name,
                        "\n".join([os.path.relpath(f, project_root) for f in files]),
                        query_prefix,
                        is_active
                    ])
                printer.print_table_compact(
                    data=data_list,
                    title="已定义文件组",
                    headers=["Group Name", "Files", "Query Prefix", "Active"]
                )
        # 重置活动组
        elif len(add_files_args) >= 2 and add_files_args[1] == "/reset":
            memory["current_files"]["current_groups"] = []
            printer.print_panel(
                Text("活动组名称已重置。如果你想清除活动文件，可使用命令 /remove_files /all .", style="green"),
                title="活动组重置", center=True
            )
        # 新增组
        elif len(add_files_args) >= 3 and add_files_args[1] == "/add":
            group_name = add_files_args[2]
            groups[group_name] = memory["current_files"]["files"].copy()
            printer.print_panel(
                Text(f"已将当前文件添加到组 '{group_name}' .", style="green"), title="新增组", center=True
            )
        # 删除组
        elif len(add_files_args) >= 3 and add_files_args[1] == "/drop":
            group_name = add_files_args[2]
            if group_name in groups:
                del memory["current_files"]["groups"][group_name]
                if group_name in groups_info:
                    del memory["current_files"]["groups_info"][group_name]
                if group_name in memory["current_files"]["current_groups"]:
                    memory["current_files"]["current_groups"].remove(group_name)
                printer.print_panel(
                    Text(f"已删除组 '{group_name}'.", style="green"), title="删除组", center=True
                )
            else:
                printer.print_panel(
                    Text(f"组 '{group_name}' 未找到.", style="red"), title="Error", center=True
                )
        # 支持多个组的合并，允许组名之间使用逗号或空格分隔
        elif len(add_files_args) >= 2:
            group_names = " ".join(add_files_args[1:]).replace(",", " ").split()
            merged_files = set()
            missing_groups = []
            for group_name in group_names:
                if group_name in groups:
                    merged_files.update(groups[group_name])
                else:
                    missing_groups.append(group_name)
            if missing_groups:
                printer.print_panel(
                    Text(f"未找到组: {', '.join(missing_groups)}", style="red"), title="Error", center=True
                )
            if merged_files:
                memory["current_files"]["files"] = list(merged_files)
                memory["current_files"]["current_groups"] = [
                    name for name in group_names if name in groups
                ]
                printer.print_panel(
                    Text(f"合并来自组 {', '.join(group_names)} 的文件 .", style="green"), title="文件合并", center=True
                )
                printer.print_table_compact(
                    data=[[os.path.relpath(f, project_root)] for f in memory["current_files"]["files"]],
                    title="当前文件",
                    headers=["File"]
                )
                printer.print_panel(
                    Text(f"当前组: {', '.join(memory['current_files']['current_groups'])}", style="green"),
                    title="当前组", center=True
                )
            elif not missing_groups:
                printer.print_panel(
                    Text(f"指定组中没有文件.", style="yellow"), title="未添加任何文件", center=True
                )

    else:
        existing_files = memory["current_files"]["files"]
        matched_files = find_files_in_project(add_files_args)

        files_to_add = [f for f in matched_files if f not in existing_files]
        if files_to_add:
            memory["current_files"]["files"].extend(files_to_add)
            printer.print_table_compact(
                data=[[os.path.relpath(f, project_root)] for f in files_to_add],
                title="新增文件",
                headers=["文件"]
            )
        else:
            printer.print_panel(
                Text(f"所有指定文件已存在于当前会话中，或者未找到匹配的文件.", style="yellow"), title="未新增文件", center=True
            )

    completer.update_current_files(memory["current_files"]["files"])
    save_memory()


def remove_files(file_names: List[str]):
    if "/all" in file_names:
        memory["current_files"]["files"] = []
        memory["current_files"]["current_groups"] = []
        printer.print_panel("已移除所有文件", title="文件移除", center=True)
    else:
        removed_files = []
        for file in memory["current_files"]["files"]:
            if os.path.basename(file) in file_names:
                removed_files.append(file)
            elif file in file_names:
                removed_files.append(file)
        for file in removed_files:
            memory["current_files"]["files"].remove(file)

        if removed_files:
            printer.print_table_compact(
                data=[[os.path.relpath(f, project_root)] for f in removed_files],
                title="文件移除",
                headers=["File"]
            )
        else:
            printer.print_panel("未移除任何文件", title="未移除文件", border_style="dim yellow", center=True)
    completer.update_current_files(memory["current_files"]["files"])
    save_memory()


def list_files():
    current_files = memory["current_files"]["files"]

    if current_files:
        printer.print_table_compact(
            data=[[os.path.relpath(file, project_root)] for file in current_files],
            title="当前活跃文件",
            headers=["File"]
        )
    else:
        printer.print_panel("当前会话中无文件。", title="当前文件", center=True)


def print_conf(content: Dict[str, Any]):
    data_list = []
    for key in sorted(content.keys()):
        value = content[key]
        # Format value based on type
        if isinstance(value, (dict, list)):
            formatted_value = Text(json.dumps(value, indent=2), style="yellow")
        elif isinstance(value, bool):
            formatted_value = Text(str(value), style="bright_green" if value else "red")
        elif isinstance(value, (int, float)):
            formatted_value = Text(str(value), style="bright_cyan")
        else:
            formatted_value = Text(str(value), style="green")
        data_list.append([str(key), formatted_value])
    printer.print_table_compact(
        data=data_list,
        title="Conf 配置",
        headers=["键", "值"],
        caption="使用 /conf <key>:<value> 修改这些设置"
    )


def print_models(content: Dict[str, Any]):
    data_list = []
    if content:
        for name in content:
            data_list.append([name, content[name].get("model", ""), content[name].get("base_url", "")])
    else:
        data_list.append(["", "", ""])
    printer.print_table_compact(
        headers=["Name", "Model Name", "Base URL"],
        title="模型列表",
        data=data_list,
        show_lines=True,
        expand=True
    )


def check_models(content: Dict[str, Any], llm: AutoLLM):
    def _check_single_llm(model):
        _start_time = time.monotonic()
        try:
            _response = llm.stream_chat_ai(
                conversations=[{"role": "user", "content": "ping, are you there?"}], model=model
            )
            for _chunk in _response:
                pass
            _latency = time.monotonic() - _start_time
            return True, _latency
        except Exception as e:
            return False, str(e)

    data_list = []
    if content:
        for name in content:
            attempt_ok, attempt_latency = _check_single_llm(name)
            if attempt_ok:
                data_list.append([name, Text("✓", style="green"), f"{attempt_latency:.2f}s"])
            else:
                data_list.append([name, Text("✗", style="red"), "-"])
    else:
        data_list.append(["", "", ""])
    printer.print_table_compact(
        headers=["模型名称", "状态", "延迟情况"],
        title="模型状态检测",
        data=data_list
    )


def manage_models(models_args, models_data, llm: AutoLLM):
    """
      /models /list - List all models (default + custom)
      /models /check - Check all models status (Latency)
      /models /add <name> <api_key> - Add model with simplified params
      /models /add_model name=xxx base_url=xxx api_key=xxxx model=xxxxx ... - Add model with custom params
      /models /remove <name> - Remove model by name
    """
    if models_args[0] == "/list":
        print_models(models_data)
    if models_args[0] == "/check":
        check_models(models_data, llm)
    if models_args[0] == "/add":
        m1, m2, m3, m4 = configure_project_model()
        printer.print_text("正在更新缓存...", style="yellow")
        memory["models"][m1] = {"base_url": m3, "api_key": m4, "model": m2}
        printer.print_text(f"供应商配置已成功完成！后续你可以使用 /models 命令, 查看, 新增和修改所有模型", style="green")
        printer.print_text(f"正在部署 {m1} 模型...", style="green")
        llm.setup_sub_client(m1,
                             memory["models"][m1]["api_key"],
                             memory["models"][m1]["base_url"],
                             memory["models"][m1]["model"])
    elif models_args[0] == "/add_model":
        add_model_args = models_args[1:]
        add_model_info = {item.split('=')[0]: item.split('=')[1] for item in add_model_args if item}
        mn = add_model_info["name"]
        printer.print_text(f"正在为 {mn} 更新缓存信息", style="green")
        if mn not in memory["models"]:
            memory["models"][mn] = {
                "base_url": add_model_info["base_url"],
                "api_key": add_model_info["api_key"],
                "model": add_model_info["model"]
            }
        else:
            printer.print_text(f"{mn} 已经存在, 请执行 /models /remove <name> 进行删除", style="red")
        printer.print_text(f"正在部署 {mn} 模型", style="green")
        llm.setup_sub_client(mn, add_model_info["api_key"], add_model_info["base_url"], add_model_info["model"])
    elif models_args[0] == "/remove":
        rmn = models_args[1]
        printer.print_text(f"正在清理 {rmn} 缓存信息", style="green")
        if rmn in memory["models"]:
            del memory["models"][rmn]
        printer.print_text(f"正在卸载 {rmn} 模型", style="green")
        if llm.get_sub_client(rmn):
            llm.remove_sub_client(rmn)
        if rmn == memory["conf"]["chat_model"]:
            printer.print_text(f"当前首选Chat模型 {rmn} 已被删除, 请立即 /conf chat_model: 调整", style="yellow")
        if rmn == memory["conf"]["code_model"]:
            printer.print_text(f"当前首选Code模型 {rmn} 已被删除, 请立即 /conf code_model: 调整", style="yellow")


def configure_project_model():
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import print_formatted_text
    from prompt_toolkit.styles import Style
    from html import escape

    style = Style.from_dict(
        {
            "info": "#ansicyan",
            "warning": "#ansiyellow",
            "input-area": "#ansigreen",
            "header": "#ansibrightyellow bold",
        }
    )

    def print_info(text):
        print_formatted_text(
            HTML(f"<info>{escape(text)}</info>"), style=style)

    def print_header(text):
        print_formatted_text(
            HTML(f"<header>{escape(text)}</header>"), style=style)

    default_model = {
        "1": {"name": "(Volcengine)deepseek/deepseek-r1-0528",
              "base_url": "https://ark.cn-beijing.volces.com/api/v3",
              "model_name": "deepseek-r1-250528"},
        "2": {"name": "(Volcengine)deepseek/deepseek-v3.1-terminus",
              "base_url": "https://ark.cn-beijing.volces.com/api/v3",
              "model_name": "deepseek-v3-1-terminus"},
        "3": {"name": "(Volcengine)byte/doubao-seed-1.6-250615",
              "base_url": "https://ark.cn-beijing.volces.com/api/v3",
              "model_name": "doubao-seed-1-6-250615"},
        "4": {"name": "(Volcengine)moonshotai/kimi-k2",
              "base_url": "https://ark.cn-beijing.volces.com/api/v3",
              "model_name": "kimi-k2-250711"},
        "5": {"name": "(OpenRouter)google/gemini-2.5-pro",
              "base_url": "https://openrouter.ai/api/v1",
              "model_name": "google/gemini-2.5-pro"},
        "6": {"name": "(OpenRouter)google/gemini-2.5-flash",
              "base_url": "https://openrouter.ai/api/v1",
              "model_name": "google/gemini-2.5-flash"},
        "7": {"name": "(OpenRouter)anthropic/claude-opus-4",
              "base_url": "https://openrouter.ai/api/v1",
              "model_name": "anthropic/claude-opus-4"},
        "8": {"name": "(OpenRouter)anthropic/claude-sonnet-4",
              "base_url": "https://openrouter.ai/api/v1",
              "model_name": "anthropic/claude-sonnet-4"},
        "9": {"name": "(OpenRouter)moonshotai/kimi-k2",
              "base_url": "https://openrouter.ai/api/v1",
              "model_name": "moonshotai/kimi-k2"},
        "10": {"name": "(OpenRouter)openai/gpt-5",
               "base_url": "https://openrouter.ai/api/v1",
               "model_name": "openai/gpt-5"},
        "11": {"name": "(BigModel)bigmodel/glm-4.5",
               "base_url": "https://open.bigmodel.cn/api/paas/v4",
               "model_name": "glm-4.5"},
        "12": {"name": "(BigModel)bigmodel/coding-plan",
               "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
               "model_name": "glm-4.6"},
    }

    # 内置模型
    print_header(f"\n=== 正在配置项目模型 ===\n")
    print_info("Volcengine: https://www.volcengine.com/")
    print_info("OpenRouter: https://openrouter.ai/")
    print_info("")
    print_info(f"  1. (Volcengine)deepseek/deepseek-r1-0528")
    print_info(f"  2. (Volcengine)deepseek/deepseek-v3.1-0821")
    print_info(f"  3. (Volcengine)byte/doubao-seed-1.6-250615")
    print_info(f"  4. (Volcengine)moonshotai/kimi-k2")
    print_info(f"  5. (OpenRouter)google/gemini-2.5-pro")
    print_info(f"  6. (OpenRouter)google/gemini-2.5-flash")
    print_info(f"  7. (OpenRouter)anthropic/claude-opus-4")
    print_info(f"  8. (OpenRouter)anthropic/claude-sonnet-4")
    print_info(f"  9. (OpenRouter)moonshotai/kimi-k2")
    print_info(f"  10. (OpenRouter)openai/gpt-5")
    print_info(f"  11. (BigModel)bigmodel/glm-4.5")
    print_info(f"  12. (BigModel)bigmodel/coding-plan")
    print_info(f"  13. 其他模型")
    model_num = input(f"  请选择您想使用的模型供应商编号(1-13): ").strip().lower()

    if int(model_num) < 1 or int(model_num) > 13:
        printer.print_text("请选择 1-13", style="red")
        save_memory()
        exit(1)

    if model_num == "13":  # 只有选择"其他模型"才需要手动输入所有信息
        current_model = input(f"  设置你的首选模型别名(例如: deepseek-v3/r1, ark-deepseek-v3/r1): ").strip().lower()
        current_model_name = input(f"  请输入你使用模型的 Model Name: ").strip().lower()
        current_base_url = input(f"  请输入你使用模型的 Base URL: ").strip().lower()
        current_api_key = input(f"  请输入您的API密钥: ").strip()
        return current_model, current_model_name, current_base_url, current_api_key

    model_name_value = default_model[model_num].get("model_name", "")
    model_api_key = input(f"请输入您的 API 密钥：").strip()
    return (
        default_model[model_num]["name"],
        model_name_value,
        default_model[model_num]["base_url"],
        model_api_key
    )


def rules(query_args: List[str], llm: AutoLLM):
    """
    /rules 命令帮助:
    /rules /list            - 列出规则文件
    /rules /show            - 查看规则文件内容
    /rules /remove          - 删除规则文件
    /rules /analyze         - 分析当前文件，可选提供查询内容
    /rules /commit <提交ID>  - 分析特定提交，必须提供提交ID和查询内容
    """
    args = get_final_config(project_root, memory, query="", delete_execute_file=True)
    rules_dir_path = os.path.join(project_root, ".auto-coder", "autocoderrules")
    if query_args[0] == "/list":
        printer.print_table_compact(
            data=[[rules_name] for rules_name in os.listdir(rules_dir_path)],
            title="Rules 列表",
            headers=["Rules 文件"],
            center=True
        )

    if query_args[0] == "/remove":
        remove_rules_name = query_args[1].strip()
        remove_rules_path = os.path.join(rules_dir_path, remove_rules_name)
        if os.path.exists(remove_rules_path):
            os.remove(remove_rules_path)
            printer.print_text(f"Rules 文件[{remove_rules_name}]移除成功", style="green")
        else:
            printer.print_text(f"Rules 文件[{remove_rules_name}]不存在", style="yellow")

    if query_args[0] == "/show":  # /rules /show 参数检查
        show_rules_name = query_args[1].strip()
        show_rules_path = os.path.join(rules_dir_path, show_rules_name)
        if os.path.exists(show_rules_path):
            with open(show_rules_path, "r") as fp:
                printer.print_markdown(text=fp.read(), panel=True)
        else:
            printer.print_text(f"Rules 文件[{show_rules_name}]不存在", style="yellow")

    if query_args[0] == "/commit":
        commit_id = query_args[1].strip()
        rules_from_commit_changes(commit_id=commit_id, llm=llm, args=args)

    if query_args[0] == "/analyze":
        files = memory.get("current_files", {}).get("files", [])
        if not files:
            printer.print_text("当前无活跃文件用于生成 Rules", style="yellow")
            return

        rules_from_active_files(files=files, llm=llm, args=args)

    completer.refresh_files()


def is_old_version():
    # "0.1.26" 开始使用兼容 AutoCoder 的 chat_model, code_model 参数
    # 不再使用 current_chat_model 和 current_chat_model
    if 'current_chat_model' in memory['conf'] and 'current_code_model' in memory['conf']:
        printer.print_text(f"0.1.26 新增 chat_model, code_model 参数, 正在进行配置兼容性处理", style="yellow")
        memory['conf']['chat_model'] = memory['conf']['current_chat_model']
        memory['conf']['code_model'] = memory['conf']['current_code_model']
        del memory['conf']['current_chat_model']
        del memory['conf']['current_code_model']
    # "0.1.31" 在 .auto-coder 目录中新增 autocoderrules 目录
    rules_dir_path = os.path.join(project_root, ".auto-coder", "autocoderrules")
    if not os.path.exists(rules_dir_path):
        printer.print_text(f"0.1.31 .auto-coder 目录中新增 autocoderrules 目录, 正在进行配置兼容性处理", style="yellow")
        os.makedirs(rules_dir_path, exist_ok=True)


def main():
    _args, _raw_args = parse_args()
    _args.source_dir = project_root
    convert_yaml_to_config(_args)

    if not _raw_args.quick:
        initialize_system()

    try:
        load_memory()
        load_tokenizer()
        is_old_version()
    except Exception as e:
        print(f"\033[91m发生异常:\033[0m \033[93m{type(e).__name__}\033[0m - {str(e)}")
        exit(1)

    completer.update_current_files(memory["current_files"]["files"])

    if len(memory["models"]) == 0:
        _model_pass = input(f"  是否跳过模型配置(y/n): ").strip().lower()
        if _model_pass == "n":
            m1, m2, m3, m4 = configure_project_model()
            printer.print_text("正在更新缓存...", style="yellow")
            memory["conf"]["chat_model"] = m1
            memory["conf"]["code_model"] = m1
            memory["models"][m1] = {"base_url": m3, "api_key": m4, "model": m2}
            printer.print_text(f"供应商配置已成功完成！后续你可以使用 /models 命令, 查看, 新增和修改所有模型", style="green")
        else:
            printer.print_text("你已跳过模型配置,后续请使用 /models /add_model 添加模型...", style="yellow")
            printer.print_text("添加示例 /models /add_model name=& base_url=& api_key=& model=&", style="yellow")

    auto_llm = AutoLLM()  # 创建模型
    if len(memory["models"]) > 0:
        for _model_name in memory["models"]:
            printer.print_text(f"正在部署 {_model_name} 模型...", style="green")
            auto_llm.setup_sub_client(_model_name,
                                      memory["models"][_model_name]["api_key"],
                                      memory["models"][_model_name]["base_url"],
                                      memory["models"][_model_name]["model"])

    printer.print_text("初始化完成.", style="green")

    if memory["conf"]["chat_model"] not in memory["models"].keys():
        printer.print_text("首选 Chat 模型与部署模型不一致, 请使用 /conf chat_model:& 设置", style="red")
    if memory["conf"]["code_model"] not in memory["models"].keys():
        printer.print_text("首选 Code 模型与部署模型不一致, 请使用 /conf code_model:& 设置", style="red")

    if _raw_args and _raw_args.agent:
        instruction = _raw_args.agent
        try:
            auto_command(query=instruction, llm=auto_llm)
        except Exception as e:
            print(f"\033[91m发生异常:\033[0m \033[93m{type(e).__name__}\033[0m - {str(e)}")
            if _raw_args.debug:
                import traceback
                traceback.print_exc()
        finally:
            return

    MODES = {
        "normal": "正常模式",
        "auto_detect": "自然语言模式",
    }

    kb = KeyBindings()

    @kb.add("c-c")
    def _(event):
        event.app.exit()

    @kb.add("c-k")
    def _(event):
        if "mode" not in memory:
            memory["mode"] = "normal"
        current_mode = memory["mode"]
        if current_mode == "normal":
            memory["mode"] = "auto_detect"
        else:
            memory["mode"] = "normal"
        event.app.invalidate()

    def get_bottom_toolbar():
        if "mode" not in memory:
            memory["mode"] = "normal"
        mode = memory["mode"]
        return f" 当前模式: {MODES[mode]} (ctl+k 切换模式) | 当前项目: {project_root}"

    session = PromptSession(
        history=InMemoryHistory(),
        auto_suggest=AutoSuggestFromHistory(),
        enable_history_search=False,
        completer=completer,
        complete_while_typing=True,
        key_bindings=kb,
        bottom_toolbar=get_bottom_toolbar,
    )
    printer.print_key_value(
        {
            "AutoCoder Nano": f"v{__version__}",
            "Url": "https://github.com/w4n9H/autocoder-nano",
            "Help": "输入 /help 可以查看可用的命令."
        }
    )

    style = Style.from_dict(
        {
            "username": "#884444",
            "at": "#00aa00",
            "colon": "#0000aa",
            "pound": "#00aa00",
            "host": "#00ffff bg:#444400",
        }
    )

    new_prompt = ""

    while True:
        try:
            prompt_message = [
                ("class:username", "coding"),
                ("class:at", "@"),
                ("class:host", "auto-coder.nano"),
                ("class:colon", ":"),
                ("class:path", "~"),
                ("class:dollar", "$ "),
            ]

            if new_prompt:
                user_input = session.prompt(FormattedText(prompt_message), default=new_prompt, style=style)
            else:
                user_input = session.prompt(FormattedText(prompt_message), style=style)
            new_prompt = ""

            if "mode" not in memory:
                memory["mode"] = "normal"  # 默认为正常模式
            if memory["mode"] == "auto_detect" and user_input and not user_input.startswith("/"):
                shell_script = generate_shell_command(input_text=user_input, llm=auto_llm)
                if confirm("是否要执行此脚本?"):
                    execute_shell_command(shell_script)
                else:
                    continue
            elif user_input.startswith("/add_files"):
                add_files_args = user_input[len("/add_files"):].strip().split()
                add_files(add_files_args)
            elif user_input.startswith("/remove_files"):
                file_names = user_input[len("/remove_files"):].strip().split(",")
                remove_files(file_names)
            elif user_input.startswith("/editor"):
                editor_files = user_input[len("/editor"):].strip()
                editor_command(editor_files)
            elif user_input.startswith("/index/build"):
                index_command(llm=auto_llm)
            elif user_input.startswith("/index/query"):
                query = user_input[len("/index/query"):].strip()
                index_query_command(query=query, llm=auto_llm)
            elif user_input.startswith("/rag/build"):
                rag_build_command(llm=auto_llm)
            elif user_input.startswith("/rag/query"):
                query = user_input[len("/rag/query"):].strip()
                rag_query_command(query=query, llm=auto_llm)
            elif user_input.startswith("/index/export"):
                export_path = user_input[len("/index/export"):].strip()
                index_export(project_root, export_path)
            elif user_input.startswith("/index/import"):
                import_path = user_input[len("/index/import"):].strip()
                index_import(project_root, import_path)
            elif user_input.startswith("/list_files"):
                list_files()
            elif user_input.startswith("/conf"):
                conf = user_input[len("/conf"):].strip()
                if not conf:
                    print_conf(memory["conf"])
                else:
                    configure(conf)
            elif user_input.startswith("/revert"):
                revert()
            elif user_input.startswith("/commit"):
                query = user_input[len("/commit"):].strip()
                commit_info(query, auto_llm)
            elif user_input.startswith("/rules"):
                query_args = user_input[len("/rules"):].strip().split()
                if not query_args:
                    printer.print_text("Please enter your request.", style="yellow")
                    continue
                rules(query_args=query_args, llm=auto_llm)
            elif user_input.startswith("/help"):
                query = user_input[len("/help"):].strip()
                show_help(query)
            elif user_input.startswith("/exit"):
                raise EOFError()
            elif user_input.startswith("/coding"):
                query = user_input[len("/coding"):].strip()
                if not query:
                    printer.print_text("Please enter your request.", style="yellow")
                    continue
                coding_command(query=query, llm=auto_llm)
            elif user_input.startswith("/auto"):
                query = user_input[len("/auto"):].strip()
                if not query:
                    print("\033[91mPlease enter your request.\033[0m")
                    continue
                auto_command(query=query, llm=auto_llm)
            elif user_input.startswith("/long_context_auto"):
                long_context_auto_command(llm=auto_llm)
            elif user_input.startswith("/context"):
                context_args = user_input[len("/context"):].strip().split()
                if not context_args:
                    print("\033[91mPlease enter your request.\033[0m")
                    continue
                context_command(context_args)
            elif user_input.startswith("/chat"):
                query = user_input[len("/chat"):].strip()
                if not query:
                    print("\033[91mPlease enter your request.\033[0m")
                else:
                    chat_command(query=query, llm=auto_llm)
            elif user_input.startswith("/models"):
                models_args = user_input[len("/models"):].strip().split()
                if not models_args:
                    print("请输入相关参数.")
                else:
                    manage_models(models_args, memory["models"], auto_llm)
            elif user_input.startswith("/mode"):
                conf = user_input[len("/mode"):].strip()
                if not conf:
                    print(f"{memory['mode']} [{MODES[memory['mode']]}]")
                else:
                    memory["mode"] = conf
            elif user_input.startswith("/exclude_dirs"):
                dir_names = user_input[len("/exclude_dirs"):].strip().split(",")
                exclude_dirs(dir_names)
            elif user_input.startswith("/exclude_files"):
                query = user_input[len("/exclude_files"):].strip()
                exclude_files(query)
            else:
                command = user_input
                if user_input.startswith("/shell"):
                    command = user_input[len("/shell"):].strip()
                if not command:
                    print("Please enter a shell command to execute.")
                else:
                    execute_shell_command(command)
        except KeyboardInterrupt:
            continue
        except EOFError:
            try:
                save_memory()
            except Exception as e:
                print(f"\033[91m保存配置时发生异常:\033[0m \033[93m{type(e).__name__}\033[0m - {str(e)}")
            print("\n\033[93m退出 AutoCoder Nano...\033[0m")
            break
        except Exception as e:
            print(f"\033[91m发生异常:\033[0m \033[93m{type(e).__name__}\033[0m - {str(e)}")
            if _raw_args and _raw_args.debug:
                import traceback
                traceback.print_exc()


if __name__ == '__main__':
    main()
