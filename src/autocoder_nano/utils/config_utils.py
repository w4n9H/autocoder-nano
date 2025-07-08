import os
import uuid
from typing import Optional

import yaml
from jinja2 import Template

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


def convert_yaml_config_to_str(yaml_config):
    yaml_content = yaml.safe_dump(
        yaml_config,
        allow_unicode=True,
        default_flow_style=False,
        default_style=None,
    )
    return yaml_content


def convert_config_value(key, value):
    field_info = AutoCoderArgs.model_fields.get(key)
    if field_info:
        if value.lower() in ["true", "false"]:
            return value.lower() == "true"
        elif "int" in str(field_info.annotation):
            return int(value)
        elif "float" in str(field_info.annotation):
            return float(value)
        else:
            return value
    else:
        printer.print_text(f"无效的配置项: {key}", style="red")
        return None


def resolve_include_path(base_path, include_path):
    if include_path.startswith(".") or include_path.startswith(".."):
        full_base_path = os.path.abspath(base_path)
        parent_dir = os.path.dirname(full_base_path)
        return os.path.abspath(os.path.join(parent_dir, include_path))
    else:
        return include_path


def load_include_files(config, base_path, max_depth=10, current_depth=0):
    if current_depth >= max_depth:
        raise ValueError(
            f"Exceeded maximum include depth of {max_depth},you may have a circular dependency in your include files."
        )
    if "include_file" in config:
        include_files = config["include_file"]
        if not isinstance(include_files, list):
            include_files = [include_files]

        for include_file in include_files:
            abs_include_path = resolve_include_path(base_path, include_file)
            # printer.print_text(f"正在加载 Include file: {abs_include_path}", style="green")
            with open(abs_include_path, "r") as f:
                include_config = yaml.safe_load(f)
                if not include_config:
                    printer.print_text(f"Include file {abs_include_path} 为空，跳过处理.", style="green")
                    continue
                config.update(
                    {
                        **load_include_files(include_config, abs_include_path, max_depth, current_depth + 1),
                        **config,
                    }
                )
        del config["include_file"]
    return config


def convert_yaml_to_config(yaml_file: str | dict | AutoCoderArgs):
    # global args
    args = AutoCoderArgs()
    config = {}
    if isinstance(yaml_file, str):
        args.file = yaml_file
        with open(yaml_file, "r") as f:
            config = yaml.safe_load(f)
            config = load_include_files(config, yaml_file)
    if isinstance(yaml_file, dict):
        config = yaml_file
    if isinstance(yaml_file, AutoCoderArgs):
        config = yaml_file.model_dump()
    for key, value in config.items():
        if key != "file":  # 排除 --file 参数本身
            # key: ENV {{VARIABLE_NAME}}
            if isinstance(value, str) and value.startswith("ENV"):
                template = Template(value.removeprefix("ENV").strip())
                value = template.render(os.environ)
            setattr(args, key, value)
    return args


def get_final_config(project_root: str, memory: dict, query: str, delete_execute_file: bool = False) -> AutoCoderArgs:
    conf = memory.get("conf", {})
    yaml_config = {
        "include_file": ["./base/base.yml"],
        "skip_build_index": conf.get("skip_build_index", "true") == "true",
        "skip_confirm": conf.get("skip_confirm", "true") == "true",
        "chat_model": conf.get("chat_model", ""),
        "code_model": conf.get("code_model", ""),
        "auto_merge": conf.get("auto_merge", "editblock"),
        "exclude_files": memory.get("exclude_files", [])
    }
    current_files = memory["current_files"]["files"]
    yaml_config["urls"] = current_files
    yaml_config["query"] = query

    # 如果 conf 中有设置, 则以 conf 配置为主
    for key, value in conf.items():
        converted_value = convert_config_value(key, value)
        if converted_value is not None:
            yaml_config[key] = converted_value

    execute_file = os.path.join(project_root, "actions", f"{uuid.uuid4()}.yml")
    try:
        yaml_content = convert_yaml_config_to_str(yaml_config=yaml_config)
        with open(os.path.join(execute_file), "w") as f:  # 保存此次查询的细节
            f.write(yaml_content)
        args = convert_yaml_to_config(execute_file)  # 更新到args
    finally:
        if delete_execute_file:
            if os.path.exists(execute_file):
                os.remove(execute_file)
    return args


def get_last_yaml_file(project_root: str) -> Optional[str]:
    actions_dir = os.path.join(project_root, "actions")
    action_files = [f for f in os.listdir(actions_dir) if f[:3].isdigit() and "_" in f and f.endswith(".yml")]

    def get_old_seq(name):
        return int(name.split("_")[0])

    sorted_action_files = sorted(action_files, key=get_old_seq)
    return sorted_action_files[-1] if sorted_action_files else None


def prepare_chat_yaml(project_root: str):
    actions_dir = os.path.join(project_root, "actions")
    if not os.path.exists(actions_dir):
        printer.print_text("当前目录中未找到 actions 目录。请执行初始化 AutoCoder Nano", style="yellow")
        return

    action_files = [
        f for f in os.listdir(actions_dir) if f[:3].isdigit() and "_" in f and f.endswith(".yml")
    ]

    def get_old_seq(name):
        return name.split("_")[0]

    if not action_files:
        max_seq = 0
    else:
        seqs = [int(get_old_seq(f)) for f in action_files]
        max_seq = max(seqs)

    new_seq = str(max_seq + 1).zfill(12)
    prev_files = [f for f in action_files if int(get_old_seq(f)) < int(new_seq)]

    if not prev_files:
        new_file = os.path.join(actions_dir, f"{new_seq}_chat_action.yml")
        with open(new_file, "w") as f:
            pass
    else:
        prev_file = sorted(prev_files)[-1]  # 取序号最大的文件
        with open(os.path.join(actions_dir, prev_file), "r") as f:
            content = f.read()
        new_file = os.path.join(actions_dir, f"{new_seq}_chat_action.yml")
        with open(new_file, "w") as f:
            f.write(content)

    printer.print_text(f"已成功创建新的 action 文件: {new_file}", style="green")
    return