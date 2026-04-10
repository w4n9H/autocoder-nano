import os

from autocoder_nano.acmodels import BUILTIN_MODELS
from autocoder_nano.templates import create_actions
from autocoder_nano.utils.file_utils import auto_count_file_extensions
from autocoder_nano.utils.git_utils import repo_init
from autocoder_nano.utils.printer_utils import Printer, COLOR_INFO, COLOR_WARNING, COLOR_SUCCESS, COLOR_ERROR

printer = Printer()


def init_project(project_type: str, project_root: str):
    if not project_type:
        printer.print_text(
            f"请指定项目类型。可选的项目类型包括：py|ts| 或文件扩展名(例如:.java,.scala), 多个扩展名逗号分隔.", style=COLOR_SUCCESS
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

    printer.print_text(f"已在 {os.path.abspath(project_root)} 成功初始化 autocoder-nano 项目", style=COLOR_SUCCESS)
    return


def initialize_system(project_root: str):
    printer.print_text(f"正在初始化系统...", style=COLOR_INFO)

    def _init_project():
        base_persist_dir = os.path.join(project_root, ".auto-coder", "plugins", "chat-auto-coder")
        if not os.path.exists(os.path.join(project_root, ".auto-coder")):
            first_time = True
            printer.print_text("当前目录未初始化为auto-coder项目.", style=COLOR_WARNING)
            init_choice = input(f"  是否现在初始化项目？(y/n): ").strip().lower()
            if init_choice == "y":
                try:
                    if first_time:  # 首次启动,配置项目类型
                        if not os.path.exists(base_persist_dir):
                            os.makedirs(base_persist_dir, exist_ok=True)
                            # printer.print_text("创建目录：{}".format(base_persist_dir), style=COLOR_SUCCESS)
                        count_file_ext = auto_count_file_extensions(project_root)
                        project_type = ".py"
                        if len(count_file_ext) > 0:
                            project_type = ",".join(count_file_ext.keys())
                        printer.print_text(f"项目类型设置为： {project_type}", style=COLOR_SUCCESS)
                        init_project(project_type, project_root)
                        printer.print_text(f"您可以稍后使用以下命令更改此设置:", style=COLOR_WARNING)
                        printer.print_text("/conf project_type:<new_type>", style=COLOR_WARNING)
                    printer.print_text("项目初始化成功.", style=COLOR_SUCCESS)
                except Exception as e:
                    printer.print_text(f"项目初始化失败, {str(e)}.", style=COLOR_ERROR)
                    exit(1)
            else:
                printer.print_text("退出而不初始化.", style=COLOR_WARNING)
                exit(1)

        printer.print_text("项目初始化完成.", style=COLOR_SUCCESS)

    _init_project()


def configure_project_type() -> str:
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import print_formatted_text
    from prompt_toolkit.styles import Style
    from prompt_toolkit import prompt as _toolkit_prompt
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
        # configure(f"project_type:{project_type}", skip_print=True)
        # configure("skip_build_index:false", skip_print=True)
        print_info(f"\n项目类型设置为： {project_type}")
    else:
        print_info(f"\n使用默认项目类型：py")

    print_warning(f"\n您可以稍后使用以下命令更改此设置:")
    print_warning("/conf project_type:<new_type>\n")

    return project_type


def configure_project_model():
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import print_formatted_text
    from prompt_toolkit.styles import Style
    from html import escape

    style = Style.from_dict(
        {"info": "#ansicyan", "warning": "#ansiyellow", "input-area": "#ansigreen", "header": "#ansibrightyellow bold"}
    )

    def print_info(text):
        print_formatted_text(HTML(f"<info>{escape(text)}</info>"), style=style)

    def print_header(text):
        print_formatted_text(HTML(f"<header>{escape(text)}</header>"), style=style)

    def convert_models(builtin_models: dict[str: dict]):
        _result = {}
        for _key, _model_info in builtin_models.items():
            _model_id = _model_info["id"]
            _result[_model_id] = {
                "name": _key,
                "base_url": _model_info["base_url"],
                "model_name": _model_info["model_name"]
            }
        return _result

    default_model = convert_models(BUILTIN_MODELS)

    # 内置模型
    print_header(f"\n=== 正在配置项目模型 ===\n")
    print_info("Volcengine: https://www.volcengine.com/")
    print_info("OpenRouter: https://openrouter.ai/")
    print_info("iFlow: https://platform.iflow.cn/")
    print_info("")
    for key, model_info in BUILTIN_MODELS.items():
        model_id = model_info["id"]
        print_info(f"  {model_id}. {key}")
    print_info(f"  14. 其他模型")
    model_num = input(f"  请选择您想使用的模型供应商编号(1-14): ").strip().lower()

    if int(model_num) < 1 or int(model_num) > 14:
        printer.print_text("请选择 1-14", style=COLOR_ERROR)
        exit(1)

    if model_num == "14":  # 只有选择"其他模型"才需要手动输入所有信息
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