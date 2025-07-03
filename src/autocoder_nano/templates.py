import os
from pathlib import Path
from typing import Dict


from autocoder_nano.core import prompt


@prompt()
def base_base(source_dir: str, project_type: str):
    """
    project_type: {{ project_type }}
    source_dir: {{ source_dir }}
    target_file: {{ target_file }}

    model: deepseek_chat
    model_max_input_length: 100000
    index_filter_workers: 1
    index_build_workers: 1
    index_filter_level: 2

    execute: true
    auto_merge: true
    human_as_model: false
    """
    return {
        "target_file": Path(source_dir) / "output.txt"
    }


@prompt()
def base_enable_index():
    """
    skip_build_index: false
    anti_quota_limit: 1
    index_filter_level: 2
    index_filter_workers: 1
    index_build_workers: 1
    """


@prompt()
def base_exclude_files():
    """
    exclude_files:
      - human://所有包含xxxx目录的路径
      - regex://.*.git.*
    """


@prompt()
def base_enable_wholefile():
    """
    auto_merge: wholefile
    """


@prompt()
def base_000_example():
    """
    include_file:
      - ./base/base.yml
      - ./base/enable_index.yml
      - ./base/enable_wholefile.yml

    query: |
      YOUR QUERY HERE
    """


@prompt()
def init_command_template(source_dir: str):
    """
    ## 关于配置文件的更多细节可以在这里找到: https://gitcode.com/allwefantasy11/auto-coder/tree/master/docs/zh

    ## 你项目的路径
    source_dir: {{ source_dir }}

    ## 用于存储 prompt/generated code 或其他信息的目标文件
    target_file: {{ source_dir }}/output.txt

    ## 一些文档的URL，可以帮助模型了解你当前的工作
    ## 多个文档可以用逗号分隔
    # urls: <SOME DOCUMENTATION URLs>

    ## 你项目的类型，py,ts或者你可以使用后缀，例如.java .scala .go
    ## 如果你使用后缀，你可以使用逗号来组合多个类型，例如.java,.scala
    project_type: py

    ## 您要驱动AutoCoder运行的模型
    model: deepseek-chat

    ## 启用索引构建，可以帮助您通过查询找到相关文件
    skip_build_index: false

    ## 用于查找相关文件的过滤级别
    ## 0: 仅查找文件名
    ## 1: 查找文件名和文件中的符号
    ## 2. 查找0和1中的文件引用的相关文件
    ## 第一次建议使用0
    index_filter_level: 0
    index_model_max_input_length: 100000

    ## 过滤文件的线程数量
    ## 如果您有一个大项目，可以增加这个数字
    index_filter_workers: 1

    ## 构建索引的线程数量
    ## 如果您有一个大项目，可以增加这个数字
    index_build_workers: 1

    ## 模型将为您生成代码
    execute: true

    ## 如果您想生成多个文件，可以启用此选项，以便在多个回合中生成代码
    ## 以避免超过模型的最大令牌限制
    enable_multi_round_generate: false

    ## AutoCoder将合并生成的代码到您的项目中
    auto_merge: true

    ## AutoCoder将要求您将内容传递给Web模型，然后将答案粘贴回终端
    human_as_model: false

    ## 你想让模型做什么
    query: |
      YOUR QUERY HERE

    ## 您可以使用以下命令执行此文件
    ## 并在目标文件中检查输出
    ## auto-coder --file 101_current_work.yml
    """


def create_actions(source_dir: str, params: Dict[str, str]):
    mapping = {
        "base": base_base.prompt(**params),
        "enable_index": base_enable_index.prompt(),
        "exclude_files": base_exclude_files.prompt(),
        # "enable_diff": base_enable_diff.prompt(),
        "enable_wholefile": base_enable_wholefile.prompt(),
        "000_example": base_000_example.prompt(),
    }
    init_file_path = os.path.join(source_dir, "actions", "101_current_work.yml")
    with open(init_file_path, "w") as f:
        f.write(init_command_template.prompt(source_dir=source_dir))

    for k, v in mapping.items():
        base_dir = os.path.join(source_dir, "actions", "base")
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

        file_path = os.path.join(source_dir, "actions", "base", f"{k}.yml")

        if k == "000_example":
            file_path = os.path.join(source_dir, "actions", f"{k}.yml")

        with open(file_path, "w") as f:
            f.write(v)