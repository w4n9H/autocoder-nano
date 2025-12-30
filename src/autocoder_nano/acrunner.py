import hashlib
import json
import os
import subprocess
from datetime import datetime

from rich.text import Text
from rich.live import Live
from rich.panel import Panel

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.agent import AgenticEditConversationConfig, run_main_agentic
from autocoder_nano.chat import stream_chat_display
from autocoder_nano.context import ContextManagerConfig, get_context_manager
from autocoder_nano.core import AutoLLM, prompt, extract_code
from autocoder_nano.editor import run_editor
from autocoder_nano.index import index_build_and_filter, index_build
from autocoder_nano.project import project_source
from autocoder_nano.rag import rag_build_cache, rag_retrieval
from autocoder_nano.utils.config_utils import get_final_config, get_last_yaml_file, convert_yaml_to_config
from autocoder_nano.utils.git_utils import revert_changes
from autocoder_nano.utils.printer_utils import Printer, COLOR_ERROR, COLOR_SUCCESS, COLOR_WARNING, COLOR_BORDER
from autocoder_nano.utils.sys_utils import detect_env

printer = Printer()
console = printer.get_console()


def print_chat_history(history, max_entries=5):
    recent_history = history[-max_entries:]
    for entry in recent_history:
        role = entry["role"]
        content = entry["content"]
        if role == "user":
            printer.print_text(Text(content, style=COLOR_ERROR))
        else:
            printer.print_markdown(content, panel=True)


def chat_command(project_root: str, query: str, memory: dict, llm: AutoLLM):
    args = get_final_config(project_root, memory, query)

    is_history = query.strip().startswith("/history")
    is_new = "/new" in query
    if is_new:
        query = query.replace("/new", "", 1).strip()

    memory_dir = os.path.join(args.source_dir, ".auto-coder", "memory")
    os.makedirs(memory_dir, exist_ok=True)
    memory_file = os.path.join(memory_dir, "chat_history.json")

    if is_new:
        new_conversation_history = []
        if os.path.exists(memory_file):
            with open(memory_file, "r") as f:
                old_chat_history = json.load(f)
            if "ask_conversation" in old_chat_history:
                new_conversation_history.append(old_chat_history["ask_conversation"])
        chat_history = {
            "ask_conversation": [],
            "conversation_history": new_conversation_history
        }
        with open(memory_file, "w") as fp:
            json_str = json.dumps(chat_history, indent=2, ensure_ascii=False)
            fp.write(json_str)

        printer.print_panel(
            Text("新会话已开始, 之前的聊天历史已存档.", style=COLOR_SUCCESS),
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

    share_file_path = os.path.join(project_root, ".auto-coder", "SHARE.md")
    with open(memory_file, "w") as fp, open(share_file_path, "w") as sfp:
        fp.write(json.dumps(chat_history, indent=2, ensure_ascii=False))
        sfp.write(assistant_response)
    return


def index_command(project_root: str, memory: dict, llm: AutoLLM):
    args = get_final_config(project_root, memory, query="", delete_execute_file=True)
    index_build(llm=llm, args=args, sources_codes=project_source(source_llm=llm, args=args))
    return


def index_query_command(project_root: str, memory: dict, query: str, llm: AutoLLM):
    args = get_final_config(project_root, memory, query=query, delete_execute_file=True)
    index_build_and_filter(llm=llm, args=args, sources_codes=project_source(source_llm=llm, args=args))
    return


def rag_build_command(project_root: str, memory: dict, llm: AutoLLM):
    args = get_final_config(project_root, memory, query="", delete_execute_file=True)
    if not args.rag_url:
        printer.print_text("请通过 /conf 设置 rag_url 参数, 即本地目录", style=COLOR_ERROR)
        return
    rag_build_cache(llm=llm, args=args, path=args.rag_url)
    return


def rag_query_command(project_root: str, memory: dict, query: str, llm: AutoLLM):
    args = get_final_config(project_root, memory, query=query, delete_execute_file=True)
    if not args.rag_url:
        printer.print_text("请通过 /conf 设置 rag_url 参数, 即本地目录", style=COLOR_ERROR)
        return
    contexts = rag_retrieval(llm=llm, args=args, path=args.rag_url)
    if contexts:
        printer.print_markdown(
            text=contexts[0].source_code,
            panel=True
        )
    return


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
                            Text("\n".join(output[-20:]), style=COLOR_SUCCESS),
                            title="Shell 输出",
                            border_style=COLOR_BORDER,
                        )
                    )
                if error_line:
                    output.append(f"ERROR: {error_line.strip()}")
                    live.update(
                        Panel(
                            Text("\n".join(output[-20:]), style=COLOR_ERROR),
                            title="Shell 输出",
                            border_style=COLOR_BORDER,
                        )
                    )
                if output_line == "" and error_line == "" and process.poll() is not None:
                    break

        if process.returncode != 0:
            printer.print_text(f"命令执行失败，返回码: {process.returncode}", style=COLOR_ERROR)
        else:
            printer.print_text(f"命令执行成功", style=COLOR_SUCCESS)
    except FileNotFoundError:
        printer.print_text(f"未找到命令:", style=COLOR_WARNING)
    except subprocess.SubprocessError as e:
        printer.print_text(f"命令执行错误: {e}", style=COLOR_WARNING)


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


def generate_shell_command(project_root: str, memory: dict, input_text: str, llm: AutoLLM) -> str | None:
    args = get_final_config(project_root, memory, query=input_text, delete_execute_file=True)

    try:
        printer.print_panel(
            Text(f"正在根据用户输入 {input_text} 生成 Shell 脚本...", style=COLOR_SUCCESS), title="命令生成",
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


def execute_revert(args: AutoCoderArgs):
    repo_path = args.source_dir

    file_content = open(args.file).read()
    md5 = hashlib.md5(file_content.encode("utf-8")).hexdigest()
    file_name = os.path.basename(args.file)

    revert_result = revert_changes(repo_path, f"auto_coder_nano_{file_name}_{md5}")
    if revert_result:
        os.remove(args.file)
        printer.print_text(f"已成功回退最后一次 chat action 的更改，并移除 YAML 文件 {args.file}", style=COLOR_SUCCESS)
    else:
        printer.print_text(f"回退文件 {args.file} 的更改失败", style=COLOR_ERROR)
    return


def revert(project_root: str):
    last_yaml_file = get_last_yaml_file(project_root)
    if last_yaml_file:
        file_path = os.path.join(project_root, "actions", last_yaml_file)
        args = convert_yaml_to_config(file_path)
        execute_revert(args)
    else:
        printer.print_text(f"No previous chat action found to revert.", style=COLOR_WARNING)


def printer_conversation_table(_conversation_list):
    data_list = []
    for i in _conversation_list:
        data_list.append([
            i["conversation_id"],
            f"{i['description'][:20]} ......",
            datetime.fromtimestamp(i["updated_at"]).strftime("%Y-%m-%d %H:%M"),
            len(i["messages"])
        ])
    printer.print_table_compact(
        title="历史会话列表",
        headers=["会话ID", "会话需求", "更新时间", "对话数量"],
        data=data_list
    )


def auto_command(project_root: str, memory: dict, query: str, llm: AutoLLM):
    # args = get_final_config(project_root, memory, query=query.strip(), delete_execute_file=True)
    conversation_config = AgenticEditConversationConfig()
    # 获取上下文管理器实例
    cmc = ContextManagerConfig()
    cmc.storage_path = os.path.join(project_root, ".auto-coder", "context")
    gcm = get_context_manager(config=cmc)

    used_subagent_list = []
    if "/sub:reader" in query:
        query = query.replace("/sub:reader", "", 1).strip()
        used_subagent_list.append("reader")
    if "/sub:coding" in query:
        query = query.replace("/sub:coding", "", 1).strip()
        used_subagent_list.extend(["reader", "coding"])
    if "/sub:research" in query:
        query = query.replace("/sub:research", "", 1).strip()
        used_subagent_list.append("research")
    if "/sub:codereview" in query:
        query = query.replace("/sub:codereview", "", 1).strip()
        used_subagent_list.append("codereview")
    if "/sub:agentic_rag" in query:
        query = query.replace("/sub:agentic_rag", "", 1).strip()
        used_subagent_list.append("agentic_rag")

    if not used_subagent_list:
        used_subagent_list.extend(["reader", "coding"])    # 默认只带 reader + coding subagent

    def _printer_resume_conversation(_conversation_id):
        printer.print_panel(
            Text(f"Agent 恢复对话[{_conversation_id}]", style=COLOR_SUCCESS),
            title="Agent Session Status",
            center=True
        )

    def _resume_conversation(_query):
        _conv_id = gcm.get_current_conversation_id()
        if not _conv_id:
            printer.print_text(f"未获取到当前会话ID, 请手动进行选择", style=COLOR_WARNING)
            _convs = gcm.list_conversations(limit=10)
            if _convs:
                printer_conversation_table(_convs)
                _conv_id = input(f"  以上为最近10个会话列表, 请选择您想要恢复对话的ID: ").strip().lower()
                conversation_config.action = "resume"
                conversation_config.query = query.strip()
                conversation_config.conversation_id = _conv_id
                _printer_resume_conversation(_conv_id)
            else:
                printer.print_text(f"未获取到历史会话, 默认创建新会话开始 Agent", style=COLOR_WARNING)
                conversation_config.action = "new"
                conversation_config.query = query.strip()
                conversation_config.conversation_id = None
                printer.print_text(f"Agent 新会话已开始.", style=COLOR_SUCCESS)
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
        printer.print_text(f"Agent 新会话已开始.", style=COLOR_SUCCESS)
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

    run_main_agentic(llm=llm, args=args, conversation_config=conversation_config,
                     used_subagent=list(set(used_subagent_list)))


def context_command(project_root, context_args):
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
            printer.print_text(f"该会话不存在 {delete_conv_id}", style=COLOR_WARNING)
        if isinstance(delete_conv, dict):
            try:
                if gcm.delete_conversation(delete_conv_id):
                    printer.print_text(f"删除会话 {delete_conv_id} 成功, 会话条数 {len(delete_conv['messages'])}",
                                       style=COLOR_SUCCESS)
                else:
                    printer.print_text(f"删除会话 {delete_conv_id} 失败, 会话可能不存在", style=COLOR_ERROR)
            except Exception as e:
                printer.print_text(f"{e}", style=COLOR_ERROR)


def editor_command(project_root, command_or_path):
    if command_or_path[0] == "/share.md":
        share_file_path = os.path.join(project_root, ".auto-coder", "SHARE.md")
        if os.path.exists(share_file_path):
            run_editor(share_file_path)
    elif command_or_path[0] == "/rules.md":
        rules_file_path = os.path.join(project_root, ".auto-coder", "RULES.md")
        if os.path.exists(rules_file_path):
            run_editor(rules_file_path)
    elif command_or_path[0] == "/agents.md":
        agents_file_path = os.path.join(project_root, ".auto-coder", "AGENTS.md")
        if os.path.exists(agents_file_path):
            run_editor(agents_file_path)
    else:
        file_path = command_or_path[0]
        abs_input_path = os.path.abspath(os.path.join(project_root, file_path)) if not os.path.isabs(file_path) else file_path
        run_editor(abs_input_path)