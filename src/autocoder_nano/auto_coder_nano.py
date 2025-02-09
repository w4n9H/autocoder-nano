import argparse
import dataclasses
import glob
import hashlib
import inspect
import os
import sys
import re
import json
import subprocess
import tempfile
import textwrap
import time
import traceback
import threading
import uuid
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional, Type, Union, Tuple

from autocoder_nano.version import __version__

import yaml
import tabulate
from git import Repo, GitCommandError
from jinja2 import Template
from loguru import logger
from openai import OpenAI, Stream
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from prompt_toolkit import prompt as _toolkit_prompt, PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import confirm
from prompt_toolkit.styles import Style
from pydantic import BaseModel, Field
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text


console = Console()
project_root = os.getcwd()
base_persist_dir = os.path.join(project_root, ".auto-coder", "plugins", "chat-auto-coder")
defaut_exclude_dirs = [".git", ".svn", "node_modules", "dist", "build", "__pycache__", ".auto-coder", "actions",
                       ".vscode", ".idea", ".hg"]
commands = [
    "/add_files", "/remove_files", "/list_files", "/conf", "/coding", "/chat", "/revert", "/index/query",
    "/index/build", "/exclude_dirs", "/help", "/shell", "/exit", "/mode", "/models",
]

memory = {
    "conversation": [],
    "current_files": {"files": [], "groups": {}},
    "conf": {
        "auto_merge": "editblock",
        "current_chat_model": "",
        "current_code_model": ""
    },
    "exclude_dirs": [],
    "mode": "normal",  # 新增mode字段,默认为normal模式
    "models": {}
}
# 全局变量，用于控制加载动画的停止
stop_buffering_event = threading.Event()
# 全局变量，用于初始测试连接状态次数
DEFAULT_CONN_TRY:int = 1

class AutoCoderArgs(BaseModel):
    request_id: Optional[str] = None  #
    file: Optional[str] = ''  #
    source_dir: Optional[str] = None  # 项目的路径
    git_url: Optional[str] = None  #
    target_file: Optional[str] = None  # 用于存储 提示词/生成代码 或其他信息的目标文件
    query: Optional[str] = None  # 你想让模型做什么
    template: Optional[str] = 'common'  #
    project_type: Optional[str] = None  # 项目的类型
    index_build_workers: Optional[int] = 1  # 构建索引的线程数量
    index_filter_level: Optional[int] = 0  # 用于查找相关文件的过滤级别
    index_filter_file_num: Optional[int] = -1  #
    index_filter_workers: Optional[int] = 1  # 过滤文件的线程数量
    filter_batch_size: Optional[int] = 5  #
    anti_quota_limit: Optional[int] = 1  # 请求模型时的间隔时间(s)
    skip_build_index: Optional[bool] = False  # 是否跳过索引构建(索引可以帮助您通过查询找到相关文件)
    skip_filter_index: Optional[bool] = False  #
    verify_file_relevance_score: Optional[int] = 6  #
    auto_merge: Optional[Union[bool, str]] = False  # 自动合并代码 True or False, 'editblock'
    enable_multi_round_generate: Optional[bool] = False  # 启用多轮生成
    editblock_similarity: Optional[float] = 0.9  # 编辑块相似性
    execute: Optional[bool] = None  # 模型是否生成代码
    context: Optional[str] = None  #
    human_as_model: Optional[bool] = False  #
    human_model_num: Optional[int] = 1  #
    include_project_structure: Optional[bool] = False  #
    urls: Optional[Union[str, List[str]]] = ""  # 一些文档的URL/路径，可以帮助模型了解你当前的工作
    model: Optional[str] = ""  # 您要驱动运行的模型
    model_max_input_length: Optional[int] = 6000  # 模型最大输入长度
    skip_confirm: Optional[bool] = False
    silence: Optional[bool] = False
    current_chat_model: Optional[str] = ""
    current_code_model: Optional[str] = ""

    class Config:
        protected_namespaces = ()


args: AutoCoderArgs = AutoCoderArgs()


class SourceCode(BaseModel):
    module_name: str
    source_code: str
    tag: str = ""
    tokens: int = -1
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LLMRequest(BaseModel):
    model: str  # 指定使用的语言模型名称
    messages: List[Dict[str, str]]  # 包含对话消息的列表，每个消息是一个字典，包含 "role"（角色）和 "content"（内容）
    stream: bool = False  # 是否以流式方式返回响应，默认为 False
    max_tokens: Optional[int] = None  # 生成的最大 token 数量，如果未指定，则使用模型默认值
    temperature: Optional[float] = None  # 控制生成文本的随机性，值越高生成的内容越随机，默认为模型默认值
    top_p: Optional[float] = None  # 控制生成文本的多样性，值越高生成的内容越多样，默认为模型默认值
    n: Optional[int] = None  # 生成多少个独立的响应，默认为 1
    stop: Optional[List[str]] = None  # 指定生成文本的停止条件，当生成的内容包含这些字符串时停止生成
    presence_penalty: Optional[float] = None  # 控制生成文本中是否鼓励引入新主题，值越高越鼓励新主题，默认为 0
    frequency_penalty: Optional[float] = None  # 控制生成文本中是否减少重复内容，值越高越减少重复，默认为 0


class LLMResponse(BaseModel):
    output: Union[str, List[float]] = ''  # 模型的输出，可以是字符串或浮点数列表
    input: Union[str, Dict[str, Any]] = ''  # 模型的输入，可以是字符串或字典
    metadata: Dict[str, Any] = dataclasses.field(
        default_factory=dict  # 元数据，包含与响应相关的额外信息，默认为空字典
    )


class IndexItem(BaseModel):
    module_name: str
    symbols: str
    last_modified: float
    md5: str  # 新增文件内容的MD5哈希值字段


class TargetFile(BaseModel):
    file_path: str
    reason: str = Field(
        ..., description="The reason why the file is the target file"
    )


class FileList(BaseModel):
    file_list: List[TargetFile]


class SymbolType(Enum):
    USAGE = "usage"
    FUNCTIONS = "functions"
    VARIABLES = "variables"
    CLASSES = "classes"
    IMPORT_STATEMENTS = "import_statements"


class SymbolsInfo(BaseModel):
    usage: Optional[str] = Field('', description="用途")
    functions: List[str] = Field([], description="函数")
    variables: List[str] = Field([], description="变量")
    classes: List[str] = Field([], description="类")
    import_statements: List[str] = Field([], description="导入语句")


class VerifyFileRelevance(BaseModel):
    relevant_score: int
    reason: str


class CodeGenerateResult(BaseModel):
    contents: List[str]
    conversations: List[List[Dict[str, Any]]]


class PathAndCode(BaseModel):
    path: str
    content: str


class RankResult(BaseModel):
    rank_result: List[int]


class MergeCodeWithoutEffect(BaseModel):
    success_blocks: List[Tuple[str, str]]
    failed_blocks: List[Any]


class CommitResult(BaseModel):
    success: bool
    commit_message: Optional[str] = None
    commit_hash: Optional[str] = None
    changed_files: Optional[List[str]] = None
    diffs: Optional[dict] = None
    error_message: Optional[str] = None


class Tag(BaseModel):
    start_tag: str
    content: str
    end_tag: str


class SymbolItem(BaseModel):
    symbol_name: str
    symbol_type: SymbolType
    file_name: str


def print_args_status():
    if not args.silence:
        print("Command Line Arguments:")
        print("-" * 50)
        for arg, value in vars(args).items():
            if arg == "context" and value:
                print(f"{arg:20}: {value[:30]}...")
            else:
                print(f"{arg:20}: {value}")
        print("-" * 50)


def extract_symbols(text: str) -> SymbolsInfo:
    patterns = {
        "usage": r"用途：(.+)",
        "functions": r"函数：(.+)",
        "variables": r"变量：(.+)",
        "classes": r"类：(.+)",
        "import_statements": r"导入语句：(.+)",
    }

    info = SymbolsInfo()
    for field, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            if field == "import_statements":
                value = [v.strip() for v in value.split("^^")]
            elif field == "functions" or field == "variables" or field == "classes":
                value = [v.strip() for v in value.split(",")]
            setattr(info, field, value)

    return info


def get_all_file_names_in_project() -> List[str]:
    file_names = []
    final_exclude_dirs = defaut_exclude_dirs + memory.get("exclude_dirs", [])
    for root, dirs, files in os.walk(project_root, followlinks=True):
        dirs[:] = [d for d in dirs if d not in final_exclude_dirs]
        file_names.extend(files)
    return file_names


def get_all_file_in_project() -> List[str]:
    file_names = []
    final_exclude_dirs = defaut_exclude_dirs + memory.get("exclude_dirs", [])
    for root, dirs, files in os.walk(project_root, followlinks=True):
        dirs[:] = [d for d in dirs if d not in final_exclude_dirs]
        for file in files:
            file_names.append(os.path.join(root, file))
    return file_names


def get_all_dir_names_in_project() -> List[str]:
    dir_names = []
    final_exclude_dirs = defaut_exclude_dirs + memory.get("exclude_dirs", [])
    for root, dirs, files in os.walk(project_root, followlinks=True):
        dirs[:] = [d for d in dirs if d not in final_exclude_dirs]
        for _dir in dirs:
            dir_names.append(_dir)
    return dir_names


def get_all_file_in_project_with_dot() -> List[str]:
    file_names = []
    final_exclude_dirs = defaut_exclude_dirs + memory.get("exclude_dirs", [])
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
    final_exclude_dirs = defaut_exclude_dirs + memory.get("exclude_dirs", [])

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


COMMANDS = {
    "/add_files": {
        "/group": {"/add": "", "/drop": "", "/reset": ""},
        "/refresh": {},
    },
    "/coding": {"/apply": {}, "/next": {}},
    "/chat": {"/review": {}},
    "/models": {
        "/add_model": "",
        "/remove": "",
        "/list": ""
    }
}


class CommandTextParser:
    def __init__(self, text: str, command: str):
        self.text = text
        self.pos = -1
        self.len = len(text)
        self.is_extracted = False
        self.current_word_start_pos = 0
        self.current_word_end_pos = 0
        self.in_current_sub_command = ""
        self.completions = []
        self.command = command
        self.current_hiararchy = COMMANDS[command]
        self.sub_commands = []
        self.tags = []

    def first_sub_command(self):
        if len(self.sub_commands) == 0:
            return None
        return self.sub_commands[0]

    def last_sub_command(self):
        if len(self.sub_commands) == 0:
            return None
        return self.sub_commands[-1]

    def peek(self):
        if self.pos + 1 < self.len:
            return self.text[self.pos + 1]
        return None

    def peek2(self):
        if self.pos + 2 < self.len:
            return self.text[self.pos + 2]
        return None

    def peek3(self):
        if self.pos + 3 < self.len:
            return self.text[self.pos + 3]
        return None

    def next(self):
        if self.pos < self.len - 1:
            self.pos += 1
            char = self.text[self.pos]
            return char
        return None

    def consume_blank(self):
        while self.peek() == "\n" or self.peek() == " " or self.peek() == "\t" or self.peek() == "\r":
            self.next()

    def is_blank(self) -> bool:
        return self.peek() == "\n" or self.peek() == " " or self.peek() == "\t" or self.peek() == "\r"

    def is_sub_command(self) -> bool:
        backup_pos = self.pos
        self.consume_blank()
        try:
            if self.peek() == "/":
                current_sub_command = ""
                while self.peek() is not None and self.peek() != " " and self.peek() != "\n":
                    current_sub_command += self.next()

                if current_sub_command.count("/") > 1:
                    self.pos = backup_pos
                    return False
                return True
            return False
        finally:
            self.pos = backup_pos

    def consume_sub_command(self) -> str:
        # backup_pos = self.pos
        self.consume_blank()
        current_sub_command = ""
        while self.peek() is not None and self.peek() != " " and self.peek() != "\n":
            current_sub_command += self.next()

        if self.peek() is None:
            self.is_extracted = True
            self.current_word_end_pos = self.pos + 1
            self.current_word_start_pos = self.current_word_end_pos - len(
                current_sub_command
            )
            self.in_current_sub_command = current_sub_command
        else:
            if current_sub_command in self.current_hiararchy:
                self.current_hiararchy = self.current_hiararchy[current_sub_command]
                self.sub_commands.append(current_sub_command)

        return current_sub_command

    def consume_command_value(self):
        current_word = ""
        while self.peek() is not None:
            v = self.next()
            if v == " ":
                current_word = ""
            else:
                current_word += v
        self.is_extracted = True
        self.current_word_end_pos = self.pos + 1
        self.current_word_start_pos = self.current_word_end_pos - len(current_word)

    def previous(self):
        if self.pos > 1:
            return self.text[self.pos - 1]
        return None

    def is_start_tag(self) -> bool:
        backup_pos = self.pos
        tag = ""
        try:
            if self.peek() == "<" and self.peek2() != "/":
                while (
                        self.peek() is not None
                        and self.peek() != ">"
                        and not self.is_blank()
                ):
                    tag += self.next()
                if self.peek() == ">":
                    tag += self.next()
                    return True
                else:
                    return False
            return False
        finally:
            self.pos = backup_pos

    def consume_tag(self):
        start_tag = ""
        content = ""
        end_tag = ""

        # consume start tag
        self.current_word_start_pos = self.pos + 1
        while self.peek() is not None and self.peek() != ">" and not self.is_blank():
            start_tag += self.next()
        if self.peek() == ">":
            start_tag += self.next()
        self.current_word_end_pos = self.pos + 1
        tag = Tag(start_tag=start_tag, content=content, end_tag=end_tag)
        self.tags.append(tag)

        # consume content
        self.current_word_start_pos = self.pos + 1
        while self.peek() is not None and not (
                self.peek() == "<" and self.peek2() == "/"
        ):
            content += self.next()

        tag.content = content
        self.current_word_end_pos = self.pos + 1

        # consume end tag
        self.current_word_start_pos = self.pos + 1
        if self.peek() == "<" and self.peek2() == "/":
            while (
                    self.peek() is not None and self.peek() != ">" and not self.is_blank()
            ):
                end_tag += self.next()
            if self.peek() == ">":
                end_tag += self.next()
        tag.end_tag = end_tag
        self.current_word_end_pos = self.pos + 1

        # check is finished
        if self.peek() is None:
            self.is_extracted = True

    def consume_coding_value(self):
        current_word = ""
        while self.peek() is not None and not self.is_start_tag():
            v = self.next()
            if v == " ":
                current_word = ""
            else:
                current_word += v
        if self.peek() is None:
            self.is_extracted = True

        self.current_word_end_pos = self.pos + 1
        self.current_word_start_pos = self.current_word_end_pos - len(current_word)

    def current_word(self) -> str:
        return self.text[self.current_word_start_pos: self.current_word_end_pos]

    def get_current_word(self) -> str:
        return self.current_word()

    def get_sub_commands(self) -> list[str]:
        if self.get_current_word() and not self.get_current_word().startswith("/"):
            return []

        if isinstance(self.current_hiararchy, str):
            return []

        return [item for item in list(self.current_hiararchy.keys()) if item]

    def add_files(self):
        """
        for exmaple:
        /add_files file1 file2 file3
        /add_files /group/abc/cbd /group/abc/bc2
        /add_files /group1 /add xxxxx
        /add_files /group
        /add_files /group /add <groupname>
        /add_files /group /drop <groupname>
        /add_files /group <groupname>,<groupname>
        /add_files /refresh
        """
        while True:
            if self.pos == self.len - 1:
                break
            elif self.is_extracted:
                break
            elif self.is_sub_command():
                self.consume_sub_command()
            else:
                self.consume_command_value()
        return self

    def coding(self):
        while True:
            if self.pos == self.len - 1:
                break
            elif self.is_extracted:
                break
            elif self.is_sub_command():
                self.consume_sub_command()
            elif self.is_start_tag():
                self.consume_tag()
            else:
                self.consume_coding_value()


class CommandCompleter(Completer):
    def __init__(self, _commands):
        self.commands = _commands
        self.all_file_names = get_all_file_names_in_project()
        self.all_files = get_all_file_in_project()
        self.all_dir_names = get_all_dir_names_in_project()
        self.all_files_with_dot = get_all_file_in_project_with_dot()
        self.symbol_list = get_symbol_list()
        self.current_file_names = []

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()

        if len(words) > 0:
            if words[0] == "/mode":
                left_word = text[len("/mode"):]
                for mode in ["normal", "auto_detect"]:
                    if mode.startswith(left_word.strip()):
                        yield Completion(mode, start_position=-len(left_word.strip()))

            if words[0] == "/add_files":
                new_text = text[len("/add_files"):]
                parser = CommandTextParser(new_text, words[0])
                parser.add_files()
                current_word = parser.current_word()

                if parser.last_sub_command() == "/refresh":
                    return

                for command in parser.get_sub_commands():
                    if command.startswith(current_word):
                        yield Completion(command, start_position=-len(current_word))

                if parser.first_sub_command() == "/group" and (
                        parser.last_sub_command() == "/group"
                        or parser.last_sub_command() == "/drop"
                ):
                    group_names = memory["current_files"]["groups"].keys()
                    if "," in current_word:
                        current_word = current_word.split(",")[-1]

                    for group_name in group_names:
                        if group_name.startswith(current_word):
                            yield Completion(
                                group_name, start_position=-len(current_word)
                            )

                if parser.first_sub_command() != "/group":
                    if current_word and current_word.startswith("."):
                        for file_name in self.all_files_with_dot:
                            if file_name.startswith(current_word):
                                yield Completion(file_name, start_position=-len(current_word))
                    else:
                        for file_name in self.all_file_names:
                            if file_name.startswith(current_word):
                                yield Completion(file_name, start_position=-len(current_word))
                        for file_name in self.all_files:
                            if current_word and current_word in file_name:
                                yield Completion(file_name, start_position=-len(current_word))

            elif words[0] in ["/chat", "/coding"]:
                image_extensions = (
                    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".svg", ".ico",
                    ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw", ".dng", ".orf", ".rw2", ".pef",
                    ".srw", ".eps", ".ai", ".psd", ".xcf",
                )
                new_text = text[len(words[0]):]
                parser = CommandTextParser(new_text, words[0])

                parser.coding()
                current_word = parser.current_word()

                if len(new_text.strip()) == 0 or new_text.strip() == "/":
                    for command in parser.get_sub_commands():
                        if command.startswith(current_word):
                            yield Completion(command, start_position=-len(current_word))

                all_tags = parser.tags

                if current_word.startswith("@"):
                    name = current_word[1:]
                    target_set = set()

                    for file_name in self.current_file_names:
                        base_file_name = os.path.basename(file_name)
                        if name in base_file_name:
                            target_set.add(base_file_name)
                            path_parts = file_name.split(os.sep)
                            display_name = (
                                os.sep.join(path_parts[-3:])
                                if len(path_parts) > 3
                                else file_name
                            )
                            relative_path = os.path.relpath(
                                file_name, project_root)
                            yield Completion(
                                relative_path,
                                start_position=-len(name),
                                display=f"{display_name} (in active files)",
                            )

                    for file_name in self.all_file_names:
                        if file_name.startswith(name) and file_name not in target_set:
                            target_set.add(file_name)

                            path_parts = file_name.split(os.sep)
                            display_name = (
                                os.sep.join(path_parts[-3:])
                                if len(path_parts) > 3
                                else file_name
                            )
                            relative_path = os.path.relpath(
                                file_name, project_root)

                            yield Completion(
                                relative_path,
                                start_position=-len(name),
                                display=f"{display_name}",
                            )

                    for file_name in self.all_files:
                        if name in file_name and file_name not in target_set:
                            path_parts = file_name.split(os.sep)
                            display_name = (
                                os.sep.join(path_parts[-3:])
                                if len(path_parts) > 3
                                else file_name
                            )
                            relative_path = os.path.relpath(
                                file_name, project_root)
                            yield Completion(
                                relative_path,
                                start_position=-len(name),
                                display=f"{display_name}",
                            )

                if current_word.startswith("@@"):
                    name = current_word[2:]
                    for symbol in self.symbol_list:
                        if name in symbol.symbol_name:
                            file_name = symbol.file_name
                            path_parts = file_name.split(os.sep)
                            display_name = (
                                os.sep.join(path_parts[-3:])
                                if len(path_parts) > 3
                                else symbol.symbol_name
                            )
                            relative_path = os.path.relpath(
                                file_name, project_root)
                            yield Completion(
                                f"{symbol.symbol_name}(location: {relative_path})",
                                start_position=-len(name),
                                display=f"{symbol.symbol_name} ({display_name}/{symbol.symbol_type})",
                            )

                tags = [tag for tag in parser.tags]

                if current_word.startswith("<"):
                    name = current_word[1:]
                    for tag in ["<img>", "</img>"]:
                        if all_tags and all_tags[-1].start_tag == "<img>":
                            if tag.startswith(name):
                                yield Completion(
                                    "</img>", start_position=-len(current_word)
                                )
                        elif tag.startswith(name):
                            yield Completion(tag, start_position=-len(current_word))

                if tags and tags[-1].start_tag == "<img>" and tags[-1].end_tag == "":
                    raw_file_name = tags[0].content
                    file_name = raw_file_name.strip()
                    parent_dir = os.path.dirname(file_name)
                    file_basename = os.path.basename(file_name)
                    search_dir = parent_dir if parent_dir else "."
                    for root, dirs, files in os.walk(search_dir):
                        # 只处理直接子目录
                        if root != search_dir:
                            continue

                        # 补全子目录
                        for _dir in dirs:
                            full_path = os.path.join(root, _dir)
                            if full_path.startswith(file_name):
                                relative_path = os.path.relpath(full_path, search_dir)
                                yield Completion(relative_path, start_position=-len(file_basename))

                        # 补全文件
                        for file in files:
                            if file.lower().endswith(
                                    image_extensions
                            ) and file.startswith(file_basename):
                                full_path = os.path.join(root, file)
                                relative_path = os.path.relpath(full_path, search_dir)
                                yield Completion(
                                    relative_path,
                                    start_position=-len(file_basename),
                                )

                        # 只处理一层子目录，然后退出循环
                        break

            elif words[0] == "/remove_files":
                new_words = text[len("/remove_files"):].strip().split(",")

                is_at_space = text[-1] == " "
                last_word = new_words[-2] if len(new_words) > 1 else ""
                current_word = new_words[-1] if new_words else ""

                if is_at_space:
                    last_word = current_word
                    current_word = ""

                # /remove_files /all [cursor] or /remove_files /all p[cursor]
                if not last_word and not current_word:
                    if "/all".startswith(current_word):
                        yield Completion("/all", start_position=-len(current_word))
                    for file_name in self.current_file_names:
                        yield Completion(file_name, start_position=-len(current_word))

                # /remove_files /a[cursor] or /remove_files p[cursor]
                if current_word:
                    if "/all".startswith(current_word):
                        yield Completion("/all", start_position=-len(current_word))
                    for file_name in self.current_file_names:
                        if current_word and current_word in file_name:
                            yield Completion(
                                file_name, start_position=-len(current_word)
                            )

            elif words[0] == "/exclude_dirs":
                new_words = text[len("/exclude_dirs"):].strip().split(",")
                current_word = new_words[-1]

                for file_name in self.all_dir_names:
                    if current_word and current_word in file_name:
                        yield Completion(file_name, start_position=-len(current_word))

            elif words[0] == "/models":
                new_text = text[len("/models"):]
                parser = CommandTextParser(new_text, words[0])
                parser.add_files()
                current_word = parser.current_word()
                for command in parser.get_sub_commands():
                    if command.startswith(current_word):
                        yield Completion(command, start_position=-len(current_word))

            elif words[0] == "/conf":
                new_words = text[len("/conf"):].strip().split()
                is_at_space = text[-1] == " "
                last_word = new_words[-2] if len(new_words) > 1 else ""
                current_word = new_words[-1] if new_words else ""
                completions = []

                if is_at_space:
                    last_word = current_word
                    current_word = ""

                # /conf /drop [curor] or /conf /drop p[cursor]
                if last_word == "/drop":
                    completions = [
                        field_name
                        for field_name in memory["conf"].keys()
                        if field_name.startswith(current_word)
                    ]
                # /conf [curosr]
                elif not last_word and not current_word:
                    completions = [
                        "/drop"] if "/drop".startswith(current_word) else []
                    completions += [
                        field_name + ":"
                        for field_name in AutoCoderArgs.model_fields.keys()
                        if field_name.startswith(current_word)
                    ]
                # /conf p[cursor]
                elif not last_word and current_word:
                    completions = [
                        "/drop"] if "/drop".startswith(current_word) else []
                    completions += [
                        field_name + ":"
                        for field_name in AutoCoderArgs.model_fields.keys()
                        if field_name.startswith(current_word)
                    ]

                for completion in completions:
                    yield Completion(completion, start_position=-len(current_word))

            else:
                for command in self.commands:
                    if command.startswith(text):
                        yield Completion(command, start_position=-len(text))
        else:
            for command in self.commands:
                if command.startswith(text):
                    yield Completion(command, start_position=-len(text))

    def update_current_files(self, files):
        self.current_file_names = [f for f in files]

    def refresh_files(self):
        self.all_file_names = get_all_file_names_in_project()
        self.all_files = get_all_file_in_project()
        self.all_dir_names = get_all_dir_names_in_project()
        self.all_files_with_dot = get_all_file_in_project_with_dot()
        self.symbol_list = get_symbol_list()


completer = CommandCompleter(commands)


def save_memory():
    with open(os.path.join(base_persist_dir, "nano-memory.json"), "w") as fp:
        json_str = json.dumps(memory, indent=2, ensure_ascii=False)
        fp.write(json_str)
    load_memory()


def load_memory():
    global memory
    memory_path = os.path.join(base_persist_dir, "nano-memory.json")
    if os.path.exists(memory_path):
        with open(memory_path, "r") as f:
            memory = json.load(f)
    completer.update_current_files(memory["current_files"]["files"])


def format_prompt(func, **kargs):
    """
    根据函数的文档字符串生成提示模板，并使用提供的参数格式化该模板。
    参数:
    - func: 目标函数，其文档字符串将用于生成提示模板。
    - **kargs: 用于格式化提示模板的参数。
    返回值:
    - 格式化后的提示字符串。
    步骤:
    1. 获取目标函数的文档字符串。
    2. 将文档字符串按行分割，并去除每行的前导空白字符。
    3. 使用 LangChain 的 PromptTemplate 从处理后的文档字符串生成提示模板。
    4. 使用提供的参数格式化提示模板，返回格式化后的提示字符串。
    """
    # from langchain import PromptTemplate
    from string import Template
    doc = func.__doc__
    lines = doc.splitlines()
    # get the first line to get the whitespace prefix
    first_non_empty_line = next(line for line in lines if line.strip())
    prefix_whitespace_length = len(first_non_empty_line) - len(first_non_empty_line.lstrip())
    _prompt = "\n".join([line[prefix_whitespace_length:] for line in lines])
    # tpl = PromptTemplate.from_template(_prompt)
    tpl = Template(_prompt)
    # return tpl.format(**kargs)
    return tpl.safe_substitute(**kargs)


def format_prompt_jinja2(func, **kargs):
    from jinja2 import Template
    doc = func.__doc__
    lines = doc.splitlines()
    # get the first line to get the whitespace prefix
    first_non_empty_line = next(line for line in lines if line.strip())
    prefix_whitespace_length = len(first_non_empty_line) - len(first_non_empty_line.lstrip())
    _prompt = "\n".join([line[prefix_whitespace_length:] for line in lines])
    tpl = Template(_prompt)
    return tpl.render(kargs)


def format_str_jinja2(s, **kargs):
    from jinja2 import Template
    tpl = Template(s)
    return tpl.render(kargs)


def symbols_info_to_str(info: SymbolsInfo, symbol_types: List[SymbolType]) -> str:
    result = []
    for symbol_type in symbol_types:
        value = getattr(info, symbol_type.value)
        if value:
            if symbol_type == SymbolType.IMPORT_STATEMENTS:
                value_str = "^^".join(value)
            elif symbol_type in [SymbolType.FUNCTIONS, SymbolType.VARIABLES, SymbolType.CLASSES,]:
                value_str = ",".join(value)
            else:
                value_str = value
            result.append(f"{symbol_type.value}：{value_str}")

    return "\n".join(result)


def content_str(content: Union[str, List, None]) -> str:
    """
    将 content 转换为字符串格式。
    此函数处理可能是字符串、混合文本和图像 URL 的列表或 None 的内容，并将其转换为字符串。
    文本直接附加到结果字符串中，而图像 URL 则由占位符图像标记表示。如果内容为 None，则返回空字符串。
    参数:
    - content (Union[str, List, None]): 要处理的内容。可以是字符串、表示文本和图像 URL 的字典列表，或 None。
    返回:
    - str: 输入内容的字符串表示形式。图像 URL 被替换为图像标记。
    注意:
      该函数期望列表中的每个字典都有一个 "type" 键，其值为 "text" 或 "image_url"。对于 "text" 类型，"text" 键的值将附加到结果中。
      对于 "image_url"，将附加一个图像标记。
      此函数适用于处理可能包含文本和图像引用的内容，特别是在需要将图像表示为占位符的上下文中。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise TypeError(f"content must be None, str, or list, but got {type(content)}")

    rst = ""
    for item in content:
        if not isinstance(item, dict):
            raise TypeError("Wrong content format: every element should be dict if the content is a list.")
        assert "type" in item, "Wrong content format. Missing 'type' key in content's dict."
        if item["type"] == "text":
            rst += item["text"]
        elif item["type"] == "image_url":
            rst += "<image>"
        else:
            raise ValueError(f"Wrong content format: unknown type {item['type']} within the content")
    return rst


def extract_code(
        text: Union[str, List],
        pattern: str = r"```[ \t]*(\w+)?[ \t]*\r?\n(.*?)\r?\n[ \t]*```",
        detect_single_line_code: bool = False
) -> List[Tuple[str, str]]:
    """
    从文本中提取代码。
    参数:
    - text (str 或 List): 要从中提取代码的内容。内容可以是字符串或列表，通常由标准 GPT 或多模态 GPT 返回。
    - pattern (str, 可选): 用于查找代码块的正则表达式模式。默认为 CODE_BLOCK_PATTERN。
    - detect_single_line_code (bool, 可选): 启用提取单行代码的新功能。默认为 False。
    返回:
    - list: 一个包含元组的列表，每个元组包含语言和代码。
      - 如果输入文本中没有代码块，则语言为 "unknown"。
      - 如果有代码块但未指定语言，则语言为 ""。
    """
    text = content_str(text)
    if not detect_single_line_code:
        match = re.findall(pattern, text, flags=re.DOTALL)
        return match if match else [("unknown", text)]

    # Extract both multi-line and single-line code block, separated by the | operator
    # `([^`]+)`: Matches inline code.
    code_pattern = re.compile(pattern + r"|`([^`]+)`")
    code_blocks = code_pattern.findall(text)

    # Extract the individual code blocks and languages from the matched groups
    extracted = []
    for lang, group1, group2 in code_blocks:
        if group1:
            extracted.append((lang.strip(), group1.strip()))
        elif group2:
            extracted.append(("", group2.strip()))

    return extracted


class _PrompRunner:
    def __init__(self, func, instance, llm, render: str, check_result: bool, options: Dict[str, Any]) -> None:
        self.func = func
        self.instance = instance
        self.llm = llm
        self.render = render
        self.check_result = check_result
        self._options = options
        self.response_markers = None
        self.return_prefix = None
        self.extractor = None
        self.model_class = None
        self.max_turns = 10

    def __call__(self, *args, **kwargs) -> Any:
        return self.prompt(*args, **kwargs)

    def options(self, options: Dict[str, Any]):
        self._options = {**self._options, **options}
        return self

    def prompt(self, *args, **kwargs):
        signature = inspect.signature(self.func)
        if self.instance:
            arguments = signature.bind(self.instance, *args, **kwargs)
        else:
            arguments = signature.bind(*args, **kwargs)

        arguments.apply_defaults()
        input_dict = {}
        for param in signature.parameters:
            input_dict.update({param: arguments.arguments[param]})

        new_input_dic = self.func(**input_dict)
        if new_input_dic and not isinstance(new_input_dic, dict):
            raise TypeError(f"Return value of {self.func.__name__} should be a dict")
        if new_input_dic:
            input_dict = {**input_dict, **new_input_dic}

        if "self" in input_dict:
            input_dict.pop("self")

        if self.render == "jinja2" or self.render == "jinja":
            return format_prompt_jinja2(self.func, **input_dict)

        return format_prompt(self.func, **input_dict)

    def with_llm(self, llm):
        self.llm = llm
        return self

    def with_return_type(self, model_class: Type[Any]):
        self.model_class = model_class
        return self

    def with_extractor(self, func):
        self.extractor = func
        return self

    @staticmethod
    def is_instance_of_generator(v):
        from typing import get_origin, get_args
        import collections

        if get_origin(v) is collections.abc.Generator:
            _args = get_args(v)
            if _args == (str, type(None), type(None)):
                return True
        return False

    def to_model(self, result: str):
        json_data = {}
        if not isinstance(result, str):
            raise ValueError("The decorated function must return a string")
        try:
            # quick path for json string
            if result.startswith("```json") and result.endswith("```"):
                json_str = result[len("```json"):-len("```")]
            else:
                json_str = extract_code(result)[0][1]
            json_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"The returned string is not a valid JSON, e: {str(e)} string: {result}")

        try:
            if isinstance(json_data, list):
                return [self.model_class(**item) for item in json_data]
            return self.model_class(**json_data)
        except TypeError:
            raise TypeError("Unable to create model instance from the JSON data")

    def run(self, *args, **kwargs):
        llm = self.llm

        if isinstance(llm, AutoLLM):
            origin_input = self.prompt(*args, **kwargs)

            conversations = [
                {"role": "system", "content": "You are a programming expert."},
                {"role": "user", "content": origin_input}
            ]

            v = llm.chat_ai(conversations)

            if self.model_class:
                return self.to_model(f"{v.output}")

            return v
        return None


class _DescriptorPrompt:
    def __init__(self, func, wrapper, llm, render: str, check_result: bool, options: Dict[str, Any]):
        self.func = func
        self.wrapper = wrapper
        self.llm = llm
        self.render = render
        self.check_result = check_result
        self._options = options
        self.prompt_runner = _PrompRunner(self.wrapper, None, self.llm, self.render, self.check_result,
                                          options=self._options)

    def __get__(self, instance, owner):
        if instance is None:
            return self
        else:
            return _PrompRunner(self.wrapper, instance, self.llm, self.render, self.check_result, options=self._options)

    def __call__(self, *args, **kwargs):
        return self.prompt_runner(*args, **kwargs)

    def with_llm(self, llm):
        self.llm = llm
        self.prompt_runner.with_llm(llm)
        return self

    def run(self, *args, **kwargs):
        return self.prompt_runner.run(*args, **kwargs)

    def prompt(self, *args, **kwargs):
        return self.prompt_runner.prompt(*args, **kwargs)


class prompt:
    """
    1.LLM 提示管理: 管理和执行与 LLM 相关的提示操作，提供灵活的配置选项。
    2.结果提取和转换: 支持从 LLM 返回的字符串中提取结果，并将其转换为指定模型实例。
    """
    def __init__(self, llm=None, render: str = "jinja2", check_result: bool = False,
                 options: Optional[Dict[str, Any]] = None):
        self.llm = llm
        self.render = render
        self.check_result = check_result
        self.options = options if options is not None else {}

    def __call__(self, func):
        wrapper = func
        return self._make_wrapper(func, wrapper)

    def _make_wrapper(self, func, wrapper):
        return _DescriptorPrompt(func, wrapper, self.llm, self.render, self.check_result, options=self.options)


class PyProject:
    def __init__(self, exclude_files=""):
        self.target_file = args.target_file
        self.directory = args.source_dir
        self.exclude_files = exclude_files
        self.exclude_patterns = self.parse_exclude_files(self.exclude_files)
        self.sources = []
        self.default_exclude_dirs = [".git", ".svn", ".hg", "build", "dist", "__pycache__", "node_modules",
                                     ".auto-coder", "actions", ".vscode", ".idea",]

    @staticmethod
    def parse_exclude_files(exclude_files):
        if not exclude_files:
            return []

        if isinstance(exclude_files, str):
            exclude_files = [exclude_files]

        exclude_patterns = []
        for pattern in exclude_files:
            if pattern.startswith("regex://"):
                pattern = pattern[8:]
                exclude_patterns.append(re.compile(pattern))
            else:
                raise ValueError(
                    "Invalid exclude_files format. Expected 'regex://<pattern>' or 'human://<description>' "
                )
        return exclude_patterns

    def should_exclude(self, file_path):
        for pattern in self.exclude_patterns:
            if pattern.search(file_path):
                return True
        return False

    @staticmethod
    def read_file_content(file_path):  # 读取代码文件
        with open(file_path, "r") as file:
            return file.read()

    def convert_to_source_code(self, file_path):
        module_name = file_path
        try:
            source_code = self.read_file_content(file_path)
        except Exception as e:
            logger.warning(f"Failed to read file: {file_path}. Error: {str(e)}")
            return None
        return SourceCode(module_name=module_name, source_code=source_code)

    @staticmethod
    def is_python_file(file_path):  # 判断是否为py文件
        return file_path.endswith(".py")

    def get_source_codes(self):
        for root, dirs, files in os.walk(self.directory):
            dirs[:] = [d for d in dirs if d not in self.default_exclude_dirs]
            for file in files:
                file_path = os.path.join(root, file)
                if self.should_exclude(file_path):  # 应该排除掉的
                    continue
                if self.is_python_file(file_path):
                    source_code = self.convert_to_source_code(file_path)
                    if source_code is not None:
                        yield source_code

    def output(self):
        return open(self.target_file, "r").read()

    def run(self):
        if self.target_file:
            # v1:写入文件版本
            with open(self.target_file, "w") as file:
                for code in self.get_source_codes():
                    self.sources.append(code)
                    file.write(f"##File: {code.module_name}\n")
                    file.write(f"{code.source_code}\n\n")
        else:
            # v2:写入self.sources版本
            for code in self.get_source_codes():
                self.sources.append(code)


class SuffixProject:
    def __init__(self, exclude_files=""):
        self.target_file = args.target_file
        self.directory = args.source_dir
        self.project_type = args.project_type
        self.suffixs = [
            suffix.strip() if suffix.startswith(".") else f".{suffix.strip()}"
            for suffix in self.project_type.split(",") if suffix.strip()
        ]
        self.exclude_files = exclude_files
        self.exclude_patterns = self.parse_exclude_files(self.exclude_files)
        self.sources = []
        self.default_exclude_dirs = [".git", ".svn", ".hg", "build", "dist", "__pycache__", "node_modules",
                                     ".auto-coder", "actions", ".vscode", ".idea", ]

    @staticmethod
    def parse_exclude_files(exclude_files):
        if not exclude_files:
            return []

        if isinstance(exclude_files, str):
            exclude_files = [exclude_files]

        exclude_patterns = []
        for pattern in exclude_files:
            if pattern.startswith("regex://"):
                pattern = pattern[8:]
                exclude_patterns.append(re.compile(pattern))
            else:
                raise ValueError(
                    "Invalid exclude_files format. Expected 'regex://<pattern>' or 'human://<description>' "
                )
        return exclude_patterns

    def should_exclude(self, file_path):
        for pattern in self.exclude_patterns:
            if pattern.search(file_path):
                return True
        return False

    @staticmethod
    def read_file_content(file_path):  # 读取代码文件
        with open(file_path, "r") as file:
            return file.read()

    def convert_to_source_code(self, file_path):
        module_name = file_path
        try:
            source_code = self.read_file_content(file_path)
        except Exception as e:
            logger.warning(f"Failed to read file: {file_path}. Error: {str(e)}")
            return None
        return SourceCode(module_name=module_name, source_code=source_code)

    def is_suffix_file(self, file_path):
        return any([file_path.endswith(suffix) for suffix in self.suffixs])

    def get_source_codes(self):
        for root, dirs, files in os.walk(self.directory, followlinks=True):
            dirs[:] = [d for d in dirs if d not in self.default_exclude_dirs]
            for file in files:
                file_path = os.path.join(root, file)
                if self.should_exclude(file_path):
                    continue
                if self.is_suffix_file(file_path):
                    source_code = self.convert_to_source_code(file_path)
                    if source_code is not None:
                        yield source_code

    def output(self):
        return open(self.target_file, "r").read()

    def run(self):
        if self.target_file:
            # v1:写入文件版本
            with open(self.target_file, "w") as file:
                for code in self.get_source_codes():
                    self.sources.append(code)
                    file.write(f"##File: {code.module_name}\n")
                    file.write(f"{code.source_code}\n\n")
        else:
            # v2:写入self.sources版本
            for code in self.get_source_codes():
                self.sources.append(code)


class AutoLLM:
    # def __init__(self, api_key: str, base_url: Optional[str] = None):
    def __init__(self):
        # self.api_key = api_key
        # self.url = base_url
        # self.client = OpenAI(api_key=self.api_key, base_url=self.url)
        self.default_model_name = None
        self.sub_clients = {}

    def setup_sub_client(self, client_name: str, api_key: str, base_url: str, conn_try: int | None = None)-> Tuple[bool, str]:
        self.sub_clients[client_name] = OpenAI(api_key=api_key, base_url=base_url)
        # test connection with ping-pong 
        def _test_client(client, name):
            start_time = time.monotonic()
            try:
                response = client.chat.completions.create(
                    model=memory["models"][name]["model"],
                    messages=[{"role": "user", "content": "ping, are you there?"}],
                    max_tokens=10,
                    stream=True
                )
                # stream read
                for chunk in response:
                    pass
                latency = time.monotonic() - start_time
                return True, latency
            except Exception as e:
                return False, str(e)
        # Try connection test {conn_try} times 
        ok = False
        total_latency = 0
        success_count = 0
        try:
            for _ in range(conn_try or DEFAULT_CONN_TRY):
                attempt_ok, attempt_latency = _test_client(self.sub_clients[client_name], client_name)
                if attempt_ok:
                    success_count += 1
                total_latency += attempt_latency
                time.sleep(0.01)  # Add delay between attempts
        except KeyboardInterrupt:
            print("\n连接尝试被用户中断。")
        if success_count > 0:
            ok = True
            latency = total_latency / success_count
        else:
            ok = False
            latency = f"Connection failed after {conn_try or DEFAULT_CONN_TRY} attempts"
        return ok, latency
    
    def remove_sub_client(self, client_name: str):
        if client_name in self.sub_clients:
            del self.sub_clients[client_name]

    def get_sub_client(self, client_name: str):
        return self.sub_clients.get(client_name, None)

    def setup_default_model_name(self, model_name: str):
        self.default_model_name = model_name

    def stream_chat_ai(self, conversations, model=None) -> Stream[ChatCompletionChunk]:
        if not model and not self.default_model_name:
            raise Exception("model name is required")

        if not model:
            model = self.default_model_name

        model_name = memory["models"][model]["model"]
        logger.info(f"正在使用 {model} 模型, 模型名称 {model_name}")
        request = LLMRequest(
            model=model_name,
            messages=conversations
        )
        res = self._query(model, request, stream=True)
        return res

    def chat_ai(self, conversations, model=None) -> LLMResponse:
        # conversations = [{"role": "user", "content": prompt_str}]  deepseek-chat
        if not model and not self.default_model_name:
            raise Exception("model name is required")

        if not model:
            model = self.default_model_name

        if isinstance(conversations, str):
            conversations = [{"role": "user", "content": conversations}]

        model_name = memory["models"][model]["model"]
        logger.info(f"正在使用 {model} 模型, 模型名称 {model_name}")
        request = LLMRequest(
            model=model_name,
            messages=conversations
        )

        res = self._query(model, request)
        return LLMResponse(
            output=res.choices[0].message.content,
            input="",
            metadata={
                "id": res.id,
                "model": res.model,
                "created": res.created
            }
        )

    def _query(self, model_name: str, request: LLMRequest, stream=False) -> ChatCompletion | Stream[ChatCompletionChunk]:
        """ 与 LLM 交互 """
        response = self.sub_clients[model_name].chat.completions.create(
            model=request.model,
            messages=request.messages,
            stream=stream,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            n=request.n,
            stop=request.stop,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
        )
        return response


class IndexManager:
    def __init__(self, source_codes: List[SourceCode], llm: AutoLLM = None):
        self.args = args
        self.sources = source_codes
        self.source_dir = args.source_dir
        self.index_dir = os.path.join(self.source_dir, ".auto-coder")
        self.index_file = os.path.join(self.index_dir, "index.json")
        self.llm = llm
        self.llm.setup_default_model_name(memory["conf"]["current_chat_model"])
        self.max_input_length = args.model_max_input_length  # 模型输入最大长度
        # 使用 time.sleep(self.anti_quota_limit) 防止超过 API 频率限制
        self.anti_quota_limit = args.anti_quota_limit
        # 如果索引目录不存在,则创建它
        if not os.path.exists(self.index_dir):
            os.makedirs(self.index_dir)

    def build_index(self):
        """ 构建或更新索引，使用多线程处理多个文件，并将更新后的索引数据写入文件 """
        if os.path.exists(self.index_file):
            with open(self.index_file, "r") as file:  # 读缓存
                index_data = json.load(file)
        else:  # 首次 build index
            logger.info("首次生成索引.")
            index_data = {}

        @prompt()
        def error_message(source_dir: str, file_path: str):
            """
            The source_dir is different from the path in index file (e.g. file_path:{{ file_path }} source_dir:{{
            source_dir }}). You may need to replace the prefix with the source_dir in the index file or Just delete
            the index file to rebuild it.
            """

        for item in index_data.keys():
            if not item.startswith(self.source_dir):
                logger.warning(error_message(source_dir=self.source_dir, file_path=item))
                break

        updated_sources = []
        wait_to_build_files = []
        for source in self.sources:
            source_code = source.source_code
            md5 = hashlib.md5(source_code.encode("utf-8")).hexdigest()
            if source.module_name not in index_data or index_data[source.module_name]["md5"] != md5:
                wait_to_build_files.append(source)
        counter = 0
        num_files = len(wait_to_build_files)
        total_files = len(self.sources)
        logger.info(f"总文件数: {total_files}, 需要索引文件数: {num_files}")

        for source in wait_to_build_files:
            build_result = self.build_index_for_single_source(source)
            if build_result is not None:
                counter += 1
                logger.info(f"正在构建索引:{counter}/{num_files}...")
                module_name = build_result["module_name"]
                index_data[module_name] = build_result
                updated_sources.append(module_name)
        if updated_sources:
            with open(self.index_file, "w") as fp:
                json_str = json.dumps(index_data, indent=2, ensure_ascii=False)
                fp.write(json_str)
        return index_data

    def split_text_into_chunks(self, text):
        """ 文本分块,将大文本分割成适合 LLM 处理的小块 """
        lines = text.split("\n")
        chunks = []
        current_chunk = []
        current_length = 0
        for line in lines:
            if current_length + len(line) + 1 <= self.max_input_length:
                current_chunk.append(line)
                current_length += len(line) + 1
            else:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_length = len(line) + 1
        if current_chunk:
            chunks.append("\n".join(current_chunk))
        return chunks

    @prompt()
    def get_all_file_symbols(self, path: str, code: str) -> str:
        """
        你的目标是从给定的代码中获取代码里的符号，需要获取的符号类型包括：

        1. 函数
        2. 类
        3. 变量
        4. 所有导入语句

        如果没有任何符号,返回空字符串就行。
        如果有符号，按如下格式返回:

        ```
        {符号类型}: {符号名称}, {符号名称}, ...
        ```

        注意：
        1. 直接输出结果，不要尝试使用任何代码
        2. 不要分析代码的内容和目的
        3. 用途的长度不能超过100字符
        4. 导入语句的分隔符为^^

        下面是一段示例：

        ## 输入
        下列是文件 /test.py 的源码：

        import os
        import time
        from loguru import logger
        import byzerllm

        a = ""

        @byzerllm.prompt(render="jinja")
        def auto_implement_function_template(instruction:str, content:str)->str:

        ## 输出
        用途：主要用于提供自动实现函数模板的功能。
        函数：auto_implement_function_template
        变量：a
        类：
        导入语句：import os^^import time^^from loguru import logger^^import byzerllm

        现在，让我们开始一个新的任务:

        ## 输入
        下列是文件 {{ path }} 的源码：

        {{ code }}

        ## 输出
        """

    def build_index_for_single_source(self, source: SourceCode):
        """ 处理单个源文件，提取符号信息并存储元数据 """
        file_path = source.module_name
        if not os.path.exists(file_path):  # 过滤不存在的文件
            return None

        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".md", ".html", ".txt", ".doc", ".pdf"]:  # 过滤文档文件
            return None

        if source.source_code.strip() == "":
            return None

        md5 = hashlib.md5(source.source_code.encode("utf-8")).hexdigest()

        try:
            start_time = time.monotonic()
            source_code = source.source_code
            if len(source.source_code) > self.max_input_length:
                logger.warning(
                    f"警告[构建索引]: 源代码({source.module_name})长度过长 "
                    f"({len(source.source_code)}) > 模型最大输入长度({self.max_input_length})，"
                    f"正在分割为多个块..."
                )
                chunks = self.split_text_into_chunks(source_code)
                symbols_list = []
                for chunk in chunks:
                    chunk_symbols = self.get_all_file_symbols.with_llm(self.llm).run(source.module_name, chunk)
                    time.sleep(self.anti_quota_limit)
                    symbols_list.append(chunk_symbols.output)
                symbols = "\n".join(symbols_list)
            else:
                single_symbols = self.get_all_file_symbols.with_llm(self.llm).run(source.module_name, source_code)
                symbols = single_symbols.output
                time.sleep(self.anti_quota_limit)

            logger.info(f"解析并更新索引：文件 {file_path}（MD5: {md5}），耗时 {time.monotonic() - start_time:.2f} 秒")
        except Exception as e:
            logger.warning(f"源文件 {file_path} 处理失败: {e}")
            return None

        return {
            "module_name": source.module_name,
            "symbols": symbols,
            "last_modified": os.path.getmtime(file_path),
            "md5": md5,
        }

    @prompt()
    def _get_target_files_by_query(self, indices: str, query: str) -> str:
        """
        下面是已知文件以及对应的符号信息：

        {{ indices }}

        用户的问题是：

        {{ query }}

        现在，请根据用户的问题以及前面的文件和符号信息，寻找相关文件路径。返回结果按如下格式：

        ```json
        {
            "file_list": [
                {
                    "file_path": "path/to/file.py",
                    "reason": "The reason why the file is the target file"
                },
                {
                    "file_path": "path/to/file.py",
                    "reason": "The reason why the file is the target file"
                }
            ]
        }
        ```

        如果没有找到，返回如下 json 即可：

        ```json
            {"file_list": []}
        ```

        请严格遵循以下步骤：

        1. 识别特殊标记：
           - 查找query中的 `@` 符号，它后面的内容是用户关注的文件路径。
           - 查找query中的 `@@` 符号，它后面的内容是用户关注的符号（如函数名、类名、变量名）。

        2. 匹配文件路径：
           - 对于 `@` 标记，在indices中查找包含该路径的所有文件。
           - 路径匹配应该是部分匹配，因为用户可能只提供了路径的一部分。

        3. 匹配符号：
           - 对于 `@@` 标记，在indices中所有文件的符号信息中查找该符号。
           - 检查函数、类、变量等所有符号类型。

        4. 分析依赖关系：
           - 利用 "导入语句" 信息确定文件间的依赖关系。
           - 如果找到了相关文件，也包括与之直接相关的依赖文件。

        5. 考虑文件用途：
           - 使用每个文件的 "用途" 信息来判断其与查询的相关性。

        6. 请严格按格式要求返回结果,无需额外的说明

        请确保结果的准确性和完整性，包括所有可能相关的文件。
        """

    def read_index(self) -> List[IndexItem]:
        """ 读取并解析索引文件，将其转换为 IndexItem 对象列表 """
        if not os.path.exists(self.index_file):
            return []

        with open(self.index_file, "r") as file:
            index_data = json.load(file)

        index_items = []
        for module_name, data in index_data.items():
            index_item = IndexItem(module_name=module_name, symbols=data["symbols"], last_modified=data["last_modified"],
                                   md5=data["md5"])
            index_items.append(index_item)

        return index_items

    def _get_meta_str(self, includes: Optional[List[SymbolType]] = None):
        index_items = self.read_index()
        current_chunk = []
        for item in index_items:
            symbols_str = item.symbols
            if includes:
                symbol_info = extract_symbols(symbols_str)
                symbols_str = symbols_info_to_str(symbol_info, includes)

            item_str = f"##{item.module_name}\n{symbols_str}\n\n"
            if len(current_chunk) > self.args.filter_batch_size:
                yield "".join(current_chunk)
                current_chunk = [item_str]
            else:
                current_chunk.append(item_str)
        if current_chunk:
            yield "".join(current_chunk)

    def get_target_files_by_query(self, query: str):
        """ 根据查询条件查找相关文件，考虑不同过滤级别 """
        all_results = []
        completed = 0
        total = 0

        includes = None
        if self.args.index_filter_level == 0:
            includes = [SymbolType.USAGE]
        if self.args.index_filter_level >= 1:
            includes = None

        for chunk in self._get_meta_str(includes=includes):
            result = self._get_target_files_by_query.with_llm(self.llm).with_return_type(FileList).run(chunk, query)
            if result is not None:
                all_results.extend(result.file_list)
                completed += 1
            else:
                logger.warning(f"无法找到分块的目标文件。原因可能是模型响应未返回 JSON 格式数据，或返回的 JSON 为空。")
            total += 1
            time.sleep(self.anti_quota_limit)

        logger.info(f"已完成 {completed}/{total} 个分块(基于查询条件)")
        all_results = list({file.file_path: file for file in all_results}.values())
        if self.args.index_filter_file_num > 0:
            limited_results = all_results[: self.args.index_filter_file_num]
            return FileList(file_list=limited_results)
        return FileList(file_list=all_results)

    @prompt()
    def _get_related_files(self, indices: str, file_paths: str) -> str:
        """
        下面是所有文件以及对应的符号信息：

        {{ indices }}

        请参考上面的信息，找到被下列文件使用或者引用到的文件列表：

        {{ file_paths }}

        请按如下格式进行输出：

        ```json
        {
            "file_list": [
                {
                    "file_path": "path/to/file.py",
                    "reason": "The reason why the file is the target file"
                },
                {
                    "file_path": "path/to/file.py",
                    "reason": "The reason why the file is the target file"
                }
            ]
        }
        ```

        如果没有相关的文件，输出如下 json 即可：

        ```json
        {"file_list": []}
        ```

        注意，
        1. 找到的文件名必须出现在上面的文件列表中
        2. 原因控制在20字以内, 且使用中文
        3. 请严格按格式要求返回结果,无需额外的说明
        """

    def get_related_files(self, file_paths: List[str]):
        """ 根据文件路径查询相关文件 """
        all_results = []

        completed = 0
        total = 0

        for chunk in self._get_meta_str():
            result = self._get_related_files.with_llm(self.llm).with_return_type(
                FileList).run(chunk, "\n".join(file_paths))
            if result is not None:
                all_results.extend(result.file_list)
                completed += 1
            else:
                logger.warning(f"无法找到与分块相关的文件。原因可能是模型限制或查询条件与文件不匹配。")
            total += 1
            time.sleep(self.anti_quota_limit)
        logger.info(f"已完成 {completed}/{total} 个分块(基于相关文件)")
        all_results = list({file.file_path: file for file in all_results}.values())
        return FileList(file_list=all_results)

    @prompt()
    def verify_file_relevance(self, file_content: str, query: str) -> str:
        """
        请验证下面的文件内容是否与用户问题相关:

        文件内容:
        {{ file_content }}

        用户问题:
        {{ query }}

        相关是指，需要依赖这个文件提供上下文，或者需要修改这个文件才能解决用户的问题。
        请给出相应的可能性分数：0-10，并结合用户问题，理由控制在50字以内，并且使用中文。
        请严格按格式要求返回结果。
        格式如下:

        ```json
        {
            "relevant_score": 0-10,
            "reason": "这是相关的原因..."
        }
        ```
        """


def index_command(llm):
    source_dir = os.path.abspath(args.source_dir)
    logger.info(f"开始对目录 {source_dir} 中的源代码进行索引")
    if args.project_type == "py":
        pp = PyProject()
    else:
        pp = SuffixProject()
    pp.run()
    _sources = pp.sources
    index_manager = IndexManager(source_codes=_sources, llm=llm)
    index_manager.build_index()


def wrap_text_in_table(data, max_width=60):
    """
    Wraps text in each cell of the table to a specified width.

    :param data: A list of lists, where each inner list represents a row in the table.
    :param max_width: The maximum width of text in each cell.
    :return: A new table data with wrapped text.
    """
    wrapped_data = []
    for row in data:
        wrapped_row = [textwrap.fill(str(cell), width=max_width) for cell in row]
        wrapped_data.append(wrapped_row)

    return wrapped_data


def index_query_command(query: str, llm: AutoLLM):
    # args.query = query
    if args.project_type == "py":
        pp = PyProject()
    else:
        pp = SuffixProject()
    pp.run()
    _sources = pp.sources

    final_files = []
    index_manager = IndexManager(source_codes=_sources, llm=llm)
    target_files = index_manager.get_target_files_by_query(query)

    if target_files:
        final_files.extend(target_files.file_list)

    if target_files and args.index_filter_level >= 2:

        related_fiels = index_manager.get_related_files([file.file_path for file in target_files.file_list])

        if related_fiels is not None:
            final_files.extend(related_fiels.file_list)

    all_results = list({file.file_path: file for file in final_files}.values())
    logger.info(
        f"索引过滤级别: {args.index_filter_level}，根据查询条件: {args.query}, 过滤后的文件数: {len(all_results)}"
    )

    headers = TargetFile.model_fields.keys()
    table_data = wrap_text_in_table(
        [[getattr(file_item, name) for name in headers] for file_item in all_results]
    )
    table_output = tabulate.tabulate(table_data, headers, tablefmt="grid")
    print(table_output, flush=True)
    return


def build_index_and_filter_files(llm, sources: List[SourceCode]) -> str:
    def get_file_path(_file_path):
        if _file_path.startswith("##"):
            return _file_path.strip()[2:]
        return _file_path

    final_files: Dict[str, TargetFile] = {}
    logger.info("第一阶段：处理 REST/RAG/Search 资源(开发中)...")
    # ...

    if not args.skip_build_index and llm:
        logger.info("第二阶段：为所有文件构建索引...")
        index_manager = IndexManager(llm=llm, source_codes=sources)
        index_manager.build_index()

        if not args.skip_filter_index:
            logger.info("第三阶段：执行 Level 1 过滤(基于查询) ...")
            target_files = index_manager.get_target_files_by_query(args.query)
            if target_files:
                for file in target_files.file_list:
                    file_path = file.file_path.strip()
                    final_files[get_file_path(file_path)] = file

            if target_files is not None and args.index_filter_level >= 2:
                logger.info("第四阶段：执行 Level 2 过滤（基于相关文件）...")
                related_files = index_manager.get_related_files(
                    [file.file_path for file in target_files.file_list]
                )
                if related_files is not None:
                    for file in related_files.file_list:
                        file_path = file.file_path.strip()
                        final_files[get_file_path(file_path)] = file

            # 如果 Level 1 filtering 和 Level 2 filtering 都为获取路径，则使用全部文件
            if not final_files:
                logger.warning("Level 1, Level 2 过滤未找到相关文件, 将使用所有文件 ...")
                for source in sources:
                    final_files[get_file_path(source.module_name)] = TargetFile(
                        file_path=source.module_name,
                        reason="No related files found, use all files",
                    )

            logger.info("第五阶段：执行相关性验证 ...")
            verified_files = {}
            temp_files = list(final_files.values())
            verification_results = []

            def verify_single_file(single_file: TargetFile):
                for source in sources:
                    if source.module_name == single_file.file_path:
                        file_content = source.source_code
                        try:
                            result = index_manager.verify_file_relevance.with_llm(llm).with_return_type(
                                VerifyFileRelevance).run(
                                file_content=file_content,
                                query=args.query
                            )
                            if result.relevant_score >= args.verify_file_relevance_score:
                                verified_files[single_file.file_path] = TargetFile(
                                    file_path=single_file.file_path,
                                    reason=f"Score:{result.relevant_score}, {result.reason}"
                                )
                                return single_file.file_path, result.relevant_score, "PASS", result.reason
                            else:
                                return single_file.file_path, result.relevant_score, "FAIL", result.reason
                        except Exception as e:
                            error_msg = str(e)
                            verified_files[single_file.file_path] = TargetFile(
                                file_path=single_file.file_path,
                                reason=f"Verification failed: {error_msg}"
                            )
                            return single_file.file_path, None, "ERROR", error_msg
                return

            for pending_verify_file in temp_files:
                result = verify_single_file(pending_verify_file)
                if result:
                    verification_results.append(result)
                time.sleep(args.anti_quota_limit)

            # Keep all files, not just verified ones
            final_files = verified_files

    logger.info("第六阶段：筛选文件并应用限制条件 ...")
    if args.index_filter_file_num > 0:
        logger.info(f"从 {len(final_files)} 个文件中获取前 {args.index_filter_file_num} 个文件(Limit)")
    final_filenames = [file.file_path for file in final_files.values()]
    if not final_filenames:
        logger.warning("未找到目标文件，你可能需要重新编写查询并重试.")
    if args.index_filter_file_num > 0:
        final_filenames = final_filenames[: args.index_filter_file_num]

    logger.info("第七阶段：准备最终输出 ...")
    result_source_code = ""
    depulicated_sources = set()

    for file in sources:
        if file.module_name in final_filenames:
            if file.module_name in depulicated_sources:
                continue
            depulicated_sources.add(file.module_name)
            result_source_code += f"##File: {file.module_name}\n"
            result_source_code += f"{file.source_code}\n\n"

    return result_source_code


def convert_yaml_config_to_str(yaml_config):
    yaml_content = yaml.safe_dump(
        yaml_config,
        allow_unicode=True,
        default_flow_style=False,
        default_style=None,
    )
    return yaml_content


def convert_yaml_to_config(yaml_file: str | dict | AutoCoderArgs):
    global args
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
        logger.error(f"无效的配置项: {key}")
        return None


def chat(query: str, llm: AutoLLM):
    conf = memory.get("conf", {})
    # 默认 chat 配置
    yaml_config = {
        "include_file": ["./base/base.yml"],
        "include_project_structure": conf.get("include_project_structure", "true") in ["true", "True"],
        "human_as_model": conf.get("human_as_model", "false") == "true",
        "skip_build_index": conf.get("skip_build_index", "true") == "true",
        "skip_confirm": conf.get("skip_confirm", "true") == "true",
        "silence": conf.get("silence", "true") == "true",
        "query": query
    }
    current_files = memory["current_files"]["files"]  # get_llm_friendly_package_docs
    yaml_config["urls"] = current_files

    yaml_config["query"] = query

    # 如果 conf 中有设置, 则以 conf 配置为主
    for key, value in conf.items():
        converted_value = convert_config_value(key, value)
        if converted_value is not None:
            yaml_config[key] = converted_value

    yaml_content = convert_yaml_config_to_str(yaml_config=yaml_config)
    execute_file = os.path.join(args.source_dir, "actions", f"{uuid.uuid4()}.yml")

    with open(os.path.join(execute_file), "w") as f:  # 保存此次查询的细节
        f.write(yaml_content)

    convert_yaml_to_config(execute_file)  # 更新到args

    memory_dir = os.path.join(args.source_dir, ".auto-coder", "memory")
    os.makedirs(memory_dir, exist_ok=True)
    memory_file = os.path.join(memory_dir, "chat_history.json")

    if os.path.exists(memory_file):
        with open(memory_file, "r") as f:
            chat_history = json.load(f)
        if "conversation_history" not in chat_history:
            chat_history["conversation_history"] = []
    else:
        chat_history = {"ask_conversation": [],
                        "conversation_history": []}

    chat_history["ask_conversation"].append(
        {"role": "user", "content": query}
    )

    chat_llm = llm
    pre_conversations = []

    if args.project_type == "py":
        pp = PyProject()
    else:
        pp = SuffixProject()
    pp.run()
    _sources = pp.sources
    s = build_index_and_filter_files(llm=llm, sources=_sources)
    if s:
        pre_conversations.append(
            {
                "role": "user",
                "content": f"下面是一些文档和源码，如果用户的问题和他们相关，请参考他们：\n{s}",
            }
        )
        pre_conversations.append(
            {"role": "assistant", "content": "read"})

    loaded_conversations = pre_conversations + chat_history["ask_conversation"]

    v = chat_llm.stream_chat_ai(conversations=loaded_conversations, model=memory["conf"]["current_chat_model"])

    MAX_HISTORY_LINES = 15  # 最大保留历史行数
    lines_buffer = []
    current_line = ""
    assistant_response = ""

    try:
        with Live(Panel("", title="Response"), refresh_per_second=12) as live:
            for chunk in v:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    assistant_response += content

                    # 处理换行符分割
                    parts = (current_line + content).split('\n')

                    # 最后一部分是未完成的新行
                    if len(parts) > 1:
                        # 将完整行加入缓冲区
                        lines_buffer.extend(parts[:-1])
                        # 保留最近N行历史
                        if len(lines_buffer) > MAX_HISTORY_LINES:
                            del lines_buffer[0: len(lines_buffer) - MAX_HISTORY_LINES]
                    # 更新当前行（最后未完成的部分）
                    current_line = parts[-1]
                    # 构建显示内容 = 历史行 + 当前行
                    display_content = '\n'.join(lines_buffer[-MAX_HISTORY_LINES:] + [current_line])

                    live.update(
                        Panel(Markdown(display_content), title="模型返回", border_style="green",
                              height=min(25, live.console.height - 4))
                    )

            # 处理最后未换行的内容
            if current_line:
                lines_buffer.append(current_line)

            # 最终完整渲染
            live.update(
                Panel(Markdown(assistant_response), title="模型返回", border_style="blue")
            )
    except Exception as e:
        logger.error(str(e))

    chat_history["ask_conversation"].append({"role": "assistant", "content": assistant_response})

    with open(memory_file, "w") as fp:
        json_str = json.dumps(chat_history, ensure_ascii=False)
        fp.write(json_str)

    return


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
    index_model_max_input_length: 30000

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


def git_repo_init(repo_path: str) -> bool:
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)

    if os.path.exists(os.path.join(repo_path, ".git")):
        logger.warning(f"目录 {repo_path} 已是一个 Git 仓库，跳过初始化操作。")
        return False
    try:
        Repo.init(repo_path)
        logger.info(f"已在 {repo_path} 初始化新的 Git 仓库")
        return True
    except GitCommandError as e:
        logger.error(f"Git 初始化过程中发生错误: {e}")
        return False


def git_get_repo(repo_path: str) -> Repo:
    repo = Repo(repo_path)
    return repo


def git_commit_changes(repo_path: str, message: str) -> CommitResult:
    repo = git_get_repo(repo_path)
    if repo is None:
        return CommitResult(
            success=False, error_message="Repository is not initialized."
        )

    try:
        repo.git.add(all=True)
        if repo.is_dirty():
            commit = repo.index.commit(message)
            result = CommitResult(
                success=True,
                commit_message=message,
                commit_hash=commit.hexsha,
                changed_files=[],
                diffs={},
            )
            if commit.parents:
                changed_files = repo.git.diff(
                    commit.parents[0].hexsha, commit.hexsha, name_only=True
                ).split("\n")
                result.changed_files = [file for file in changed_files if file.strip()]

                for file in result.changed_files:
                    diff = repo.git.diff(
                        commit.parents[0].hexsha, commit.hexsha, "--", file
                    )
                    result.diffs[file] = diff
            else:
                result.error_message = (
                    "This is the initial commit, no parent to compare against."
                )

            return result
        else:
            return CommitResult(success=False, error_message="No changes to commit.")
    except GitCommandError as e:
        return CommitResult(success=False, error_message=str(e))


def git_print_commit_info(commit_result: CommitResult):
    table = Table(
        title="Commit Information (Use /revert to revert this commit)", show_header=True, header_style="bold magenta"
    )
    table.add_column("Attribute", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    table.add_row("Commit Hash", commit_result.commit_hash)
    table.add_row("Commit Message", commit_result.commit_message)
    table.add_row("Changed Files", "\n".join(commit_result.changed_files))

    console.print(
        Panel(table, expand=False, border_style="green", title="Git Commit Summary")
    )

    if commit_result.diffs:
        for file, diff in commit_result.diffs.items():
            console.print(f"\n[bold blue]File: {file}[/bold blue]")
            syntax = Syntax(diff, "diff", theme="monokai", line_numbers=True)
            console.print(
                Panel(syntax, expand=False, border_style="yellow", title="File Diff")
            )


def git_revert_changes(repo_path: str, message: str) -> bool:
    repo = git_get_repo(repo_path)
    if repo is None:
        logger.error("仓库未初始化。")
        return False

    try:
        # 检查当前工作目录是否有未提交的更改
        if repo.is_dirty():
            logger.warning("工作目录有未提交的更改，请在回退前提交或暂存您的修改。")
            return False

        # 通过message定位到commit_hash
        commit = repo.git.log("--all", f"--grep={message}", "--format=%H", "-n", "1")
        if not commit:
            logger.warning(f"未找到提交信息包含 '{message}' 的提交记录。")
            return False

        commit_hash = commit

        # 获取从指定commit到HEAD的所有提交
        commits = list(repo.iter_commits(f"{commit_hash}..HEAD"))

        if not commits:
            repo.git.revert(commit, no_edit=True)
            logger.info(f"已回退单条提交记录: {commit}")
        else:
            # 从最新的提交开始，逐个回滚
            for commit in reversed(commits):
                try:
                    repo.git.revert(commit.hexsha, no_commit=True)
                    logger.info(f"已回退提交 {commit.hexsha} 的更改")
                except GitCommandError as e:
                    logger.error(f"回退提交 {commit.hexsha} 时发生错误: {e}")
                    repo.git.revert("--abort")
                    return False
            # 提交所有的回滚更改
            repo.git.commit(message=f"Reverted all changes up to {commit_hash}")
        logger.info(f"已成功回退到提交 {commit_hash} 的状态")
        # this is a mark, chat_auto_coder.py need this
        print(f"Successfully reverted changes", flush=True)
        return True
    except GitCommandError as e:
        logger.error(f"回退操作过程中发生错误: {e}")
        return False


def init_project():
    if not args.project_type:
        logger.error(
            "请指定项目类型。可选的项目类型包括：py|ts| 或其他文件扩展名(例如：.java,.scala), 多个扩展名可用逗号分隔。"
        )
        return
    os.makedirs(os.path.join(args.source_dir, "actions"), exist_ok=True)
    os.makedirs(os.path.join(args.source_dir, ".auto-coder"), exist_ok=True)
    source_dir = os.path.abspath(args.source_dir)
    create_actions(
        source_dir=source_dir,
        params={"project_type": args.project_type,
                "source_dir": source_dir},
    )

    git_repo_init(source_dir)
    with open(os.path.join(source_dir, ".gitignore"), "a") as f:
        f.write("\n.auto-coder/")
        f.write("\nactions/")
        f.write("\noutput.txt")

    logger.info(f"已在 {os.path.abspath(args.source_dir)} 成功初始化 autocoder-nano 项目(兼容autocoder)")
    return


def get_last_yaml_file(actions_dir: str) -> Optional[str]:
    action_files = [f for f in os.listdir(actions_dir) if f[:3].isdigit() and "_" in f and f.endswith(".yml")]

    def get_old_seq(name):
        return int(name.split("_")[0])

    sorted_action_files = sorted(action_files, key=get_old_seq)
    return sorted_action_files[-1] if sorted_action_files else None


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
            logger.info(f"正在加载 Include file: {abs_include_path}")
            with open(abs_include_path, "r") as f:
                include_config = yaml.safe_load(f)
                if not include_config:
                    logger.info(f"Include file {abs_include_path} 为空，跳过处理。")
                    continue
                config.update(
                    {
                        **load_include_files(include_config, abs_include_path, max_depth, current_depth + 1),
                        **config,
                    }
                )
        del config["include_file"]
    return config


class CodeAutoGenerateEditBlock:
    def __init__(self, llm: AutoLLM, action=None, fence_0: str = "```", fence_1: str = "```"):
        self.llm = llm
        self.llm.setup_default_model_name(memory["conf"]["current_code_model"])
        self.args = args
        self.action = action
        self.fence_0 = fence_0
        self.fence_1 = fence_1
        if not self.llm:
            raise ValueError("Please provide a valid model instance to use for code generation.")
        self.llms = [self.llm]

    @prompt()
    def single_round_instruction(self, instruction: str, content: str, context: str = ""):
        """
        如果你需要生成代码，对于每个需要更改的文件,你需要按 *SEARCH/REPLACE block* 的格式进行生成。

        # *SEARCH/REPLACE block* Rules:

        Every *SEARCH/REPLACE block* must use this format:
        1. The opening fence and code language, eg: {{ fence_0 }}python
        2. The file path alone on a line, starting with "##File:" and verbatim. No bold asterisks, no quotes around it,
        no escaping of characters, etc.
        3. The start of search block: <<<<<<< SEARCH
        4. A contiguous chunk of lines to search for in the existing source code
        5. The dividing line: =======
        6. The lines to replace into the source code
        7. The end of the replacement block: >>>>>>> REPLACE
        8. The closing fence: {{ fence_1 }}

        Every *SEARCH* section must *EXACTLY MATCH* the existing source code, character for character,
        including all comments, docstrings, etc.

        *SEARCH/REPLACE* blocks will replace *all* matching occurrences.
        Include enough lines to make the SEARCH blocks unique.

        Include *ALL* the code being searched and replaced!

        To move code within a file, use 2 *SEARCH/REPLACE* blocks: 1 to delete it from its current location,
        1 to insert it in the new location.

        If you want to put code in a new file, use a *SEARCH/REPLACE block* with:
        - A new file path, including dir name if needed
        - An empty `SEARCH` section
        - The new file's contents in the `REPLACE` section

        ONLY EVER RETURN CODE IN A *SEARCH/REPLACE BLOCK*!

        下面我们来看一个例子：

        当前项目目录结构：
        1. 项目根目录： /tmp/projects/mathweb
        2. 项目子目录/文件列表(类似tree 命令输出)
        flask/
            app.py
            templates/
                index.html
            static/
                style.css

        用户需求： Change get_factorial() to use math.factorial

        回答： To make this change we need to modify `/tmp/projects/mathweb/flask/app.py` to:

        1. Import the math package.
        2. Remove the existing factorial() function.
        3. Update get_factorial() to call math.factorial instead.

        Here are the *SEARCH/REPLACE* blocks:

        ```python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
        from flask import Flask
        =======
        import math
        from flask import Flask
        >>>>>>> REPLACE
        ```

        ```python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
        def factorial(n):
            "compute factorial"

            if n == 0:
                return 1
            else:
                return n * factorial(n-1)

        =======
        >>>>>>> REPLACE
        ```

        ```python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
            return str(factorial(n))
        =======
            return str(math.factorial(n))
        >>>>>>> REPLACE
        ```

        用户需求： Refactor hello() into its own file.

        回答：To make this change we need to modify `main.py` and make a new file `hello.py`:

        1. Make a new hello.py file with hello() in it.
        2. Remove hello() from main.py and replace it with an import.

        Here are the *SEARCH/REPLACE* blocks:

        ```python
        ##File: /tmp/projects/mathweb/hello.py
        <<<<<<< SEARCH
        =======
        def hello():
            "print a greeting"

            print("hello")
        >>>>>>> REPLACE
        ```

        ```python
        ##File: /tmp/projects/mathweb/main.py
        <<<<<<< SEARCH
        def hello():
            "print a greeting"

            print("hello")
        =======
        from hello import hello
        >>>>>>> REPLACE
        ```

        现在让我们开始一个新的任务:

        {%- if structure %}
        {{ structure }}
        {%- endif %}

        {%- if content %}
        下面是一些文件路径以及每个文件对应的源码：
        <files>
        {{ content }}
        </files>
        {%- endif %}

        {%- if context %}
        <extra_context>
        {{ context }}
        </extra_context>
        {%- endif %}

        下面是用户的需求：

        {{ instruction }}

        """

    @prompt()
    def auto_implement_function(self, instruction: str, content: str) -> str:
        """
        下面是一些文件路径以及每个文件对应的源码：

        {{ content }}

        请参考上面的内容，重新实现所有文件下方法体标记了如下内容的方法：

        ```python
        raise NotImplementedError("This function should be implemented by the model.")
        ```

        {{ instruction }}

        """

    def single_round_run(self, query: str, source_content: str) -> CodeGenerateResult:
        init_prompt = ''
        if self.args.template == "common":
            init_prompt = self.single_round_instruction.prompt(
                instruction=query, content=source_content, context=self.args.context
            )
        elif self.args.template == "auto_implement":
            init_prompt = self.auto_implement_function.prompt(
                instruction=query, content=source_content
            )

        with open(self.args.target_file, "w") as file:
            file.write(init_prompt)

        conversations = [{"role": "user", "content": init_prompt}]

        conversations_list = []
        results = []

        for llm in self.llms:
            v = llm.chat_ai(conversations=conversations)
            results.append(v.output)
        for result in results:
            conversations_list.append(conversations + [{"role": "assistant", "content": result}])

        return CodeGenerateResult(contents=results, conversations=conversations_list)

    @prompt()
    def multi_round_instruction(self, instruction: str, content: str, context: str = "") -> str:
        """
        如果你需要生成代码，对于每个需要更改的文件,你需要按 *SEARCH/REPLACE block* 的格式进行生成。

        # *SEARCH/REPLACE block* Rules:

        Every *SEARCH/REPLACE block* must use this format:
        1. The opening fence and code language, eg: {{ fence_0 }}python
        2. The file path alone on a line, starting with "##File:" and verbatim. No bold asterisks, no quotes around it,
        no escaping of characters, etc.
        3. The start of search block: <<<<<<< SEARCH
        4. A contiguous chunk of lines to search for in the existing source code
        5. The dividing line: =======
        6. The lines to replace into the source code
        7. The end of the replacement block: >>>>>>> REPLACE
        8. The closing fence: {{ fence_1 }}

        Every *SEARCH* section must *EXACTLY MATCH* the existing source code, character for character,
        including all comments, docstrings, etc.

        *SEARCH/REPLACE* blocks will replace *all* matching occurrences.
        Include enough lines to make the SEARCH blocks unique.

        Include *ALL* the code being searched and replaced!

        To move code within a file, use 2 *SEARCH/REPLACE* blocks: 1 to delete it from its current location,
        1 to insert it in the new location.

        If you want to put code in a new file, use a *SEARCH/REPLACE block* with:
        - A new file path, including dir name if needed
        - An empty `SEARCH` section
        - The new file's contents in the `REPLACE` section

        ONLY EVER RETURN CODE IN A *SEARCH/REPLACE BLOCK*!

        下面我们来看一个例子：

        当前项目目录结构：
        1. 项目根目录： /tmp/projects/mathweb
        2. 项目子目录/文件列表(类似tree 命令输出)
        flask/
            app.py
            templates/
                index.html
            static/
                style.css

        用户需求： Change get_factorial() to use math.factorial

        回答： To make this change we need to modify `/tmp/projects/mathweb/flask/app.py` to:

        1. Import the math package.
        2. Remove the existing factorial() function.
        3. Update get_factorial() to call math.factorial instead.

        Here are the *SEARCH/REPLACE* blocks:

        {{ fence_0 }}python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
        from flask import Flask
        =======
        import math
        from flask import Flask
        >>>>>>> REPLACE
        {{ fence_1 }}

        {{ fence_0 }}python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
        def factorial(n):
            "compute factorial"

            if n == 0:
                return 1
            else:
                return n * factorial(n-1)

        =======
        >>>>>>> REPLACE
        {{ fence_1 }}

        {{ fence_0 }}python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
            return str(factorial(n))
        =======
            return str(math.factorial(n))
        >>>>>>> REPLACE
        {{ fence_1 }}

        用户需求： Refactor hello() into its own file.

        回答：To make this change we need to modify `main.py` and make a new file `hello.py`:

        1. Make a new hello.py file with hello() in it.
        2. Remove hello() from main.py and replace it with an import.

        Here are the *SEARCH/REPLACE* blocks:


        {{ fence_0 }}python
        ##File: /tmp/projects/mathweb/hello.py
        <<<<<<< SEARCH
        =======
        def hello():
            "print a greeting"

            print("hello")
        >>>>>>> REPLACE
        {{ fence_1 }}

        {{ fence_0 }}python
        ##File: /tmp/projects/mathweb/main.py
        <<<<<<< SEARCH
        def hello():
            "print a greeting"

            print("hello")
        =======
        from hello import hello
        >>>>>>> REPLACE
        {{ fence_1 }}

        现在让我们开始一个新的任务:

        {%- if structure %}
        {{ structure }}
        {%- endif %}

        {%- if content %}
        下面是一些文件路径以及每个文件对应的源码：
        <files>
        {{ content }}
        </files>
        {%- endif %}

        {%- if context %}
        <extra_context>
        {{ context }}
        </extra_context>
        {%- endif %}

        下面是用户的需求：

        {{ instruction }}

        每次生成一个文件的*SEARCH/REPLACE* blocks，然后询问我是否继续，当我回复继续，
        继续生成下一个文件的*SEARCH/REPLACE* blocks。当没有后续任务时，请回复 "__完成__" 或者 "__EOF__"。
        """

    def multi_round_run(self, query: str, source_content: str, max_steps: int = 3) -> CodeGenerateResult:
        init_prompt = ''
        if self.args.template == "common":
            init_prompt = self.multi_round_instruction.prompt(
                instruction=query, content=source_content, context=self.args.context
            )
        elif self.args.template == "auto_implement":
            init_prompt = self.auto_implement_function.prompt(
                instruction=query, content=source_content
            )

        with open(self.args.target_file, "w") as file:
            file.write(init_prompt)

        results = []
        conversations = [{"role": "user", "content": init_prompt}]

        code_llm = self.llms[0]
        v = code_llm.chat_ai(conversations=conversations)
        results.append(v.output)

        conversations.append({"role": "assistant", "content": v.output})

        if "__完成__" in v.output or "/done" in v.output or "__EOF__" in v.output:
            return CodeGenerateResult(contents=["\n\n".join(results)], conversations=[conversations])

        current_step = 0

        while current_step < max_steps:
            conversations.append({"role": "user", "content": "继续"})

            with open(self.args.target_file, "w") as file:
                file.write("继续")

            t = code_llm.chat_ai(conversations=conversations)

            results.append(t.output)
            conversations.append({"role": "assistant", "content": t.output})
            current_step += 1

            if "__完成__" in t.output or "/done" in t.output or "__EOF__" in t.output:
                return CodeGenerateResult(contents=["\n\n".join(results)], conversations=[conversations])

        return CodeGenerateResult(contents=["\n\n".join(results)], conversations=[conversations])


class CodeModificationRanker:
    def __init__(self, llm: AutoLLM):
        self.llm = llm
        self.llm.setup_default_model_name(memory["conf"]["current_code_model"])
        self.args = args
        self.llms = [self.llm]

    @prompt()
    def _rank_modifications(self, s: CodeGenerateResult) -> str:
        """
        对一组代码修改进行质量评估并排序。

        下面是修改需求：

        <edit_requirement>
        {{ s.conversations[0][-2]["content"] }}
        </edit_requirement>

        下面是相应的代码修改：
        {% for content in s.contents %}
        <edit_block id="{{ loop.index0 }}">
        {{content}}
        </edit_block>
        {% endfor %}

        请输出如下格式的评估结果,只包含 JSON 数据:

        ```json
        {
            "rank_result": [id1, id2, id3]  // id 为 edit_block 的 id,按质量从高到低排序
        }
        ```

        注意：
        1. 只输出前面要求的 Json 格式就好，不要输出其他内容，Json 需要使用 ```json ```包裹
        """

    def rank_modifications(self, generate_result: CodeGenerateResult) -> CodeGenerateResult:
        import time
        from collections import defaultdict

        start_time = time.time()
        logger.info(f"开始对 {len(generate_result.contents)} 个候选结果进行排序")

        try:
            results = []
            for llm in self.llms:
                v = self._rank_modifications.with_llm(llm).with_return_type(RankResult).run(generate_result)
                results.append(v.rank_result)

            if not results:
                raise Exception("All ranking requests failed")

            # 计算每个候选人的分数
            candidate_scores = defaultdict(float)
            for rank_result in results:
                for idx, candidate_id in enumerate(rank_result):
                    # Score is 1/(position + 1) since position starts from 0
                    candidate_scores[candidate_id] += 1.0 / (idx + 1)
            # 按分数降序对候选人进行排序
            sorted_candidates = sorted(candidate_scores.keys(),
                                       key=lambda x: candidate_scores[x],
                                       reverse=True)

            elapsed = time.time() - start_time
            score_details = ", ".join([f"candidate {i}: {candidate_scores[i]:.2f}" for i in sorted_candidates])
            logger.info(
                f"排序完成，耗时 {elapsed:.2f} 秒，最佳候选索引: {sorted_candidates[0]}，评分详情: {score_details}"
            )

            rerank_contents = [generate_result.contents[i] for i in sorted_candidates]
            rerank_conversations = [generate_result.conversations[i] for i in sorted_candidates]

            return CodeGenerateResult(contents=rerank_contents, conversations=rerank_conversations)

        except Exception as e:
            logger.error(f"排序过程失败: {str(e)}")
            logger.debug(traceback.format_exc())
            elapsed = time.time() - start_time
            logger.warning(f"排序失败，耗时 {elapsed:.2f} 秒，将使用原始顺序")
            return generate_result


class TextSimilarity:
    """
    找到 text_b 中与 text_a 最相似的部分(滑动窗口)
    返回相似度分数和最相似的文本片段
    """

    def __init__(self, text_a, text_b):
        self.text_a = text_a
        self.text_b = text_b
        self.lines_a = self._split_into_lines(text_a)
        self.lines_b = self._split_into_lines(text_b)
        self.m = len(self.lines_a)
        self.n = len(self.lines_b)

    @staticmethod
    def _split_into_lines(text):
        return text.splitlines()

    @staticmethod
    def _levenshtein_ratio(s1, s2):
        return SequenceMatcher(None, s1, s2).ratio()

    def get_best_matching_window(self):
        best_similarity = 0
        best_window = []

        for i in range(self.n - self.m + 1):  # 滑动窗口
            window_b = self.lines_b[i:i + self.m]
            similarity = self._levenshtein_ratio("\n".join(self.lines_a), "\n".join(window_b))

            if similarity > best_similarity:
                best_similarity = similarity
                best_window = window_b

        return best_similarity, "\n".join(best_window)


class CodeAutoMergeEditBlock:
    def __init__(self, llm: AutoLLM, fence_0: str = "```", fence_1: str = "```"):
        self.llm = llm
        self.llm.setup_default_model_name(memory["conf"]["current_code_model"])
        self.args = args
        self.fence_0 = fence_0
        self.fence_1 = fence_1

    @staticmethod
    def run_pylint(code: str) -> tuple[bool, str]:
        """
        --disable=all 禁用所有 Pylint 的检查规则
        --enable=E0001,W0311,W0312 启用指定的 Pylint 检查规则,
        E0001：语法错误(Syntax Error),
        W0311：代码缩进使用了 Tab 而不是空格(Bad indentation)
        W0312：代码缩进不一致(Mixed indentation)
        :param code:
        :return:
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
            temp_file.write(code)
            temp_file_path = temp_file.name

        try:
            result = subprocess.run(
                ["pylint", "--disable=all", "--enable=E0001,W0311,W0312", temp_file_path,],
                capture_output=True,
                text=True,
                check=False,
            )
            os.unlink(temp_file_path)
            if result.returncode != 0:
                error_message = result.stdout.strip() or result.stderr.strip()
                logger.warning(f"Pylint 检查代码失败: {error_message}")
                return False, error_message
            return True, ""
        except subprocess.CalledProcessError as e:
            error_message = f"运行 Pylint 时发生错误: {str(e)}"
            logger.error(error_message)
            os.unlink(temp_file_path)
            return False, error_message

    def parse_whole_text(self, text: str) -> List[PathAndCode]:
        """
        从文本中抽取如下格式代码(two_line_mode)：

        ```python
        ##File: /project/path/src/autocoder/index/index.py
        <<<<<<< SEARCH
        =======
        >>>>>>> REPLACE
        ```

        或者 (one_line_mode)

        ```python:/project/path/src/autocoder/index/index.py
        <<<<<<< SEARCH
        =======
        >>>>>>> REPLACE
        ```
        """
        HEAD = "<<<<<<< SEARCH"
        DIVIDER = "======="
        UPDATED = ">>>>>>> REPLACE"
        lines = text.split("\n")
        lines_len = len(lines)
        start_marker_count = 0
        block = []
        path_and_code_list = []
        # two_line_mode or one_line_mode
        current_editblock_mode = "two_line_mode"
        current_editblock_path = None

        def guard(_index):
            return _index + 1 < lines_len

        def start_marker(_line, _index):
            nonlocal current_editblock_mode
            nonlocal current_editblock_path
            if _line.startswith(self.fence_0) and guard(_index) and ":" in _line and lines[_index + 1].startswith(HEAD):
                current_editblock_mode = "one_line_mode"
                current_editblock_path = _line.split(":", 1)[1].strip()
                return True
            if _line.startswith(self.fence_0) and guard(_index) and lines[_index + 1].startswith("##File:"):
                current_editblock_mode = "two_line_mode"
                current_editblock_path = None
                return True
            return False

        def end_marker(_line, _index):
            return _line.startswith(self.fence_1) and UPDATED in lines[_index - 1]

        for index, line in enumerate(lines):
            if start_marker(line, index) and start_marker_count == 0:
                start_marker_count += 1
            elif end_marker(line, index) and start_marker_count == 1:
                start_marker_count -= 1
                if block:
                    if current_editblock_mode == "two_line_mode":
                        path = block[0].split(":", 1)[1].strip()
                        content = "\n".join(block[1:])
                    else:
                        path = current_editblock_path
                        content = "\n".join(block)
                    block = []
                    path_and_code_list.append(PathAndCode(path=path, content=content))
            elif start_marker_count > 0:
                block.append(line)

        return path_and_code_list

    def get_edits(self, content: str):
        edits = self.parse_whole_text(content)
        HEAD = "<<<<<<< SEARCH"
        DIVIDER = "======="
        UPDATED = ">>>>>>> REPLACE"
        result = []
        for edit in edits:
            heads = []
            updates = []
            c = edit.content
            in_head = False
            in_updated = False
            for line in c.splitlines():
                if line.strip() == HEAD:
                    in_head = True
                    continue
                if line.strip() == DIVIDER:
                    in_head = False
                    in_updated = True
                    continue
                if line.strip() == UPDATED:
                    in_head = False
                    in_updated = False
                    continue
                if in_head:
                    heads.append(line)
                if in_updated:
                    updates.append(line)
            result.append((edit.path, "\n".join(heads), "\n".join(updates)))
        return result

    @prompt()
    def git_require_msg(self, source_dir: str, error: str) -> str:
        """
        auto_merge only works for git repositories.

        Try to use git init in the source directory.

        ```shell
        cd {{ source_dir }}
        git init .
        ```

        Then try to run auto-coder again.
        Error: {{ error }}
        """

    def _merge_code_without_effect(self, content: str) -> MergeCodeWithoutEffect:
        """
        合并代码时不会产生任何副作用，例如 Git 操作、代码检查或文件写入。
        返回一个元组，包含：
        - 成功合并的代码块的列表，每个元素是一个 (file_path, new_content) 元组，
          其中 file_path 是文件路径，new_content 是合并后的新内容。
        - 合并失败的代码块的列表，每个元素是一个 (file_path, head, update) 元组，
          其中：file_path 是文件路径，head 是原始内容，update 是尝试合并的内容。
        """
        codes = self.get_edits(content)
        file_content_mapping = {}
        failed_blocks = []

        for block in codes:
            file_path, head, update = block
            if not os.path.exists(file_path):
                file_content_mapping[file_path] = update
            else:
                if file_path not in file_content_mapping:
                    with open(file_path, "r") as f:
                        temp = f.read()
                        file_content_mapping[file_path] = temp
                existing_content = file_content_mapping[file_path]

                # First try exact match
                new_content = (
                    existing_content.replace(head, update, 1)
                    if head
                    else existing_content + "\n" + update
                )

                # If exact match fails, try similarity match
                if new_content == existing_content and head:
                    similarity, best_window = TextSimilarity(
                        head, existing_content
                    ).get_best_matching_window()
                    if similarity > self.args.editblock_similarity:
                        new_content = existing_content.replace(
                            best_window, update, 1
                        )

                if new_content != existing_content:
                    file_content_mapping[file_path] = new_content
                else:
                    failed_blocks.append((file_path, head, update))
        return MergeCodeWithoutEffect(
            success_blocks=[(path, content) for path, content in file_content_mapping.items()],
            failed_blocks=failed_blocks
        )

    def choose_best_choice(self, generate_result: CodeGenerateResult) -> CodeGenerateResult:
        """ 选择最佳代码 """
        if len(generate_result.contents) == 1:  # 仅一份代码立即返回
            logger.info("仅有一个候选结果，跳过排序")
            return generate_result

        ranker = CodeModificationRanker(self.llm)
        ranked_result = ranker.rank_modifications(generate_result)
        # 过滤掉包含失败块的内容
        for content, conversations in zip(ranked_result.contents, ranked_result.conversations):
            merge_result = self._merge_code_without_effect(content)
            if not merge_result.failed_blocks:
                return CodeGenerateResult(contents=[content], conversations=[conversations])
        # 如果所有内容都包含失败块，则返回第一个
        return CodeGenerateResult(contents=[ranked_result.contents[0]], conversations=[ranked_result.conversations[0]])

    def _merge_code(self, content: str, force_skip_git: bool = False):
        file_content = open(self.args.file).read()
        md5 = hashlib.md5(file_content.encode("utf-8")).hexdigest()
        file_name = os.path.basename(self.args.file)

        codes = self.get_edits(content)
        changes_to_make = []
        changes_made = False
        unmerged_blocks = []
        merged_blocks = []

        # First, check if there are any changes to be made
        file_content_mapping = {}
        for block in codes:
            file_path, head, update = block
            if not os.path.exists(file_path):
                changes_to_make.append((file_path, None, update))
                file_content_mapping[file_path] = update
                merged_blocks.append((file_path, "", update, 1))
                changes_made = True
            else:
                if file_path not in file_content_mapping:
                    with open(file_path, "r") as f:
                        temp = f.read()
                        file_content_mapping[file_path] = temp
                existing_content = file_content_mapping[file_path]
                new_content = (
                    existing_content.replace(head, update, 1)
                    if head
                    else existing_content + "\n" + update
                )
                if new_content != existing_content:
                    changes_to_make.append(
                        (file_path, existing_content, new_content))
                    file_content_mapping[file_path] = new_content
                    merged_blocks.append((file_path, head, update, 1))
                    changes_made = True
                else:
                    # If the SEARCH BLOCK is not found exactly, then try to use
                    # the similarity ratio to find the best matching block
                    similarity, best_window = TextSimilarity(head, existing_content).get_best_matching_window()
                    if similarity > self.args.editblock_similarity:  # 相似性比较
                        new_content = existing_content.replace(
                            best_window, update, 1)
                        if new_content != existing_content:
                            changes_to_make.append(
                                (file_path, existing_content, new_content)
                            )
                            file_content_mapping[file_path] = new_content
                            merged_blocks.append(
                                (file_path, head, update, similarity))
                            changes_made = True
                    else:
                        unmerged_blocks.append((file_path, head, update, similarity))

        if unmerged_blocks:
            if self.args.request_id and not self.args.skip_events:
                # collect unmerged blocks
                event_data = []
                for file_path, head, update, similarity in unmerged_blocks:
                    event_data.append(
                        {
                            "file_path": file_path,
                            "head": head,
                            "update": update,
                            "similarity": similarity,
                        }
                    )
                return
            logger.warning(f"发现 {len(unmerged_blocks)} 个未合并的代码块，更改将不会应用，请手动检查这些代码块后重试。")
            self._print_unmerged_blocks(unmerged_blocks)
            return

        # lint check
        for file_path, new_content in file_content_mapping.items():
            if file_path.endswith(".py"):
                pylint_passed, error_message = self.run_pylint(new_content)
                if not pylint_passed:
                    logger.warning(f"代码文件 {file_path} 的 Pylint 检查未通过，本次更改未应用。错误信息: {error_message}")

        if changes_made and not force_skip_git:
            try:
                git_commit_changes(self.args.source_dir, f"auto_coder_pre_{file_name}_{md5}")
            except Exception as e:
                logger.error(
                    self.git_require_msg(
                        source_dir=self.args.source_dir, error=str(e))
                )
                return
        # Now, apply the changes
        for file_path, new_content in file_content_mapping.items():
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(new_content)

        if self.args.request_id and not self.args.skip_events:
            # collect modified files
            event_data = []
            for code in merged_blocks:
                file_path, head, update, similarity = code
                event_data.append(
                    {
                        "file_path": file_path,
                        "head": head,
                        "update": update,
                        "similarity": similarity,
                    }
                )

        if changes_made:
            if not force_skip_git:
                try:
                    commit_result = git_commit_changes(self.args.source_dir, f"auto_coder_{file_name}_{md5}")
                    git_print_commit_info(commit_result=commit_result)
                except Exception as e:
                    logger.error(
                        self.git_require_msg(
                            source_dir=self.args.source_dir, error=str(e)
                        )
                    )
            logger.info(
                f"已在 {len(file_content_mapping.keys())} 个文件中合并更改，"
                f"完成 {len(changes_to_make)}/{len(codes)} 个代码块。"
            )
        else:
            logger.warning("未对任何文件进行更改。")

    def merge_code(self, generate_result: CodeGenerateResult, force_skip_git: bool = False):
        result = self.choose_best_choice(generate_result)
        self._merge_code(result.contents[0], force_skip_git)
        return result

    @staticmethod
    def _print_unmerged_blocks(unmerged_blocks: List[tuple]):
        console.print(f"\n[bold red]未合并的代码块:[/bold red]")
        for file_path, head, update, similarity in unmerged_blocks:
            console.print(f"\n[bold blue]文件:[/bold blue] {file_path}")
            console.print(
                f"\n[bold green]搜索代码块（相似度：{similarity}）:[/bold green]")
            syntax = Syntax(head, "python", theme="monokai", line_numbers=True)
            console.print(Panel(syntax, expand=False))
            console.print("\n[bold yellow]替换代码块:[/bold yellow]")
            syntax = Syntax(update, "python", theme="monokai",
                            line_numbers=True)
            console.print(Panel(syntax, expand=False))
        console.print(f"\n[bold red]未合并的代码块总数: {len(unmerged_blocks)}[/bold red]")


class BaseAction:
    @staticmethod
    def _get_content_length(content: str) -> int:
        return len(content)


class ActionPyProject(BaseAction):
    def __init__(self, llm: Optional[AutoLLM] = None) -> None:
        self.args = args
        self.llm = llm
        self.pp = None

    def run(self):
        if self.args.project_type != "py":
            return False
        pp = PyProject()
        self.pp = pp
        pp.run()
        source_code = pp.output()
        if self.llm:
            source_code = build_index_and_filter_files(llm=self.llm, sources=pp.sources)
        self.process_content(source_code)
        return True

    def process_content(self, content: str):
        # args = self.args
        if self.args.execute and self.llm:
            content_length = self._get_content_length(content)
            if content_length > self.args.model_max_input_length:
                logger.warning(
                    f"发送给模型的内容长度为 {content_length} 个 token（可能收集了过多文件），"
                    f"已超过最大输入长度限制 {self.args.model_max_input_length}。"
                )

        if args.execute:
            logger.info("正在自动生成代码...")
            start_time = time.time()
            # diff, strict_diff, editblock 是代码自动生成或合并的不同策略, 通常用于处理代码的变更或生成
            # diff 模式,基于差异生成代码,生成最小的变更集,适用于局部优化,代码重构
            # strict_diff 模式,严格验证差异,确保生成的代码符合规则,适用于代码审查,自动化测试
            # editblock 模式,基于编辑块生成代码，支持较大范围的修改,适用于代码重构,功能扩展
            if args.auto_merge == "editblock":
                generate = CodeAutoGenerateEditBlock(llm=self.llm, action=self)
            else:
                generate = None

            if self.args.enable_multi_round_generate:
                generate_result = generate.multi_round_run(query=args.query, source_content=content)
            else:
                generate_result = generate.single_round_run(query=args.query, source_content=content)
            logger.info(f"代码生成完成，耗时 {time.time() - start_time:.2f} 秒")

            if args.auto_merge:
                logger.info("正在自动合并代码...")
                if args.auto_merge == "editblock":
                    code_merge = CodeAutoMergeEditBlock(llm=self.llm)
                    merge_result = code_merge.merge_code(generate_result=generate_result)
                else:
                    merge_result = None

                content = merge_result.contents[0]
            else:
                content = generate_result.contents[0]
            with open(args.target_file, "w") as file:
                file.write(content)


class ActionSuffixProject(BaseAction):
    def __init__(self, llm: Optional[AutoLLM] = None) -> None:
        self.args = args
        self.llm = llm
        self.pp = None

    def run(self):
        pp = SuffixProject()
        self.pp = pp
        pp.run()
        source_code = pp.output()
        if self.llm:
            source_code = build_index_and_filter_files(llm=self.llm, sources=pp.sources)
        self.process_content(source_code)

    def process_content(self, content: str):
        if self.args.execute and self.llm:
            content_length = self._get_content_length(content)
            if content_length > self.args.model_max_input_length:
                logger.warning(
                    f"发送给模型的内容长度为 {content_length} 个 token（可能收集了过多文件），"
                    f"已超过最大输入长度限制 {self.args.model_max_input_length}。"
                )

        if args.execute:
            logger.info("正在自动生成代码...")
            start_time = time.time()
            # diff, strict_diff, editblock 是代码自动生成或合并的不同策略, 通常用于处理代码的变更或生成
            # diff 模式,基于差异生成代码,生成最小的变更集,适用于局部优化,代码重构
            # strict_diff 模式,严格验证差异,确保生成的代码符合规则,适用于代码审查,自动化测试
            # editblock 模式,基于编辑块生成代码，支持较大范围的修改,适用于代码重构,功能扩展
            if args.auto_merge == "editblock":
                generate = CodeAutoGenerateEditBlock(llm=self.llm, action=self)
            else:
                generate = None

            if self.args.enable_multi_round_generate:
                generate_result = generate.multi_round_run(query=args.query, source_content=content)
            else:
                generate_result = generate.single_round_run(query=args.query, source_content=content)
            logger.info(f"代码生成完成，耗时 {time.time() - start_time:.2f} 秒")

            if args.auto_merge:
                logger.info("正在自动合并代码...")
                if args.auto_merge == "editblock":
                    code_merge = CodeAutoMergeEditBlock(llm=self.llm)
                    merge_result = code_merge.merge_code(generate_result=generate_result)
                else:
                    merge_result = None

                content = merge_result.contents[0]
            else:
                content = generate_result.contents[0]
            with open(args.target_file, "w") as file:
                file.write(content)


class Dispacher:
    def __init__(self, llm: Optional[AutoLLM] = None):
        self.args = args
        self.llm = llm

    def dispach(self):
        actions = [
            ActionPyProject(llm=self.llm),
            ActionSuffixProject(llm=self.llm)
        ]
        for action in actions:
            if action.run():
                return


def prepare_chat_yaml():
    # auto_coder_main(["next", "chat_action"]) 准备聊天 yaml 文件
    actions_dir = os.path.join(args.source_dir, "actions")
    if not os.path.exists(actions_dir):
        logger.warning("当前目录中未找到 actions 目录。请执行初始化 AutoCoder Nano")
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

    logger.info(f"已成功创建新的 action 文件: {new_file}")
    return


def coding(query: str, llm: AutoLLM):
    is_apply = query.strip().startswith("/apply")
    if is_apply:
        query = query.replace("/apply", "", 1).strip()

    memory["conversation"].append({"role": "user", "content": query})
    conf = memory.get("conf", {})

    current_files = memory["current_files"]["files"]
    current_groups = memory["current_files"].get("current_groups", [])
    groups = memory["current_files"].get("groups", {})
    groups_info = memory["current_files"].get("groups_info", {})

    prepare_chat_yaml()  # 复制上一个序号的 yaml 文件, 生成一个新的聊天 yaml 文件

    latest_yaml_file = get_last_yaml_file(os.path.join(args.source_dir, "actions"))

    if latest_yaml_file:
        yaml_config = {
            "include_file": ["./base/base.yml"],
            "auto_merge": conf.get("auto_merge", "editblock"),
            "human_as_model": conf.get("human_as_model", "false") == "true",
            "skip_build_index": conf.get("skip_build_index", "true") == "true",
            "skip_confirm": conf.get("skip_confirm", "true") == "true",
            "silence": conf.get("silence", "true") == "true",
            "include_project_structure": conf.get("include_project_structure", "true") == "true",
            "context": ""
        }

        for key, value in conf.items():
            converted_value = convert_config_value(key, value)
            if converted_value is not None:
                yaml_config[key] = converted_value

        yaml_config["urls"] = current_files
        yaml_config["query"] = query

        if current_groups:
            active_groups_context = "下面是对上面文件按分组给到的一些描述，当用户的需求正好匹配描述的时候，参考描述来做修改：\n"
            for group in current_groups:
                group_files = groups.get(group, [])
                query_prefix = groups_info.get(group, {}).get("query_prefix", "")
                active_groups_context += f"组名: {group}\n"
                active_groups_context += f"文件列表:\n"
                for file in group_files:
                    active_groups_context += f"- {file}\n"
                active_groups_context += f"组描述: {query_prefix}\n\n"

            yaml_config["context"] = active_groups_context + "\n"

        if is_apply:
            memory_dir = os.path.join(args.source_dir, ".auto-coder", "memory")
            os.makedirs(memory_dir, exist_ok=True)
            memory_file = os.path.join(memory_dir, "chat_history.json")

            def error_message():
                console.print(
                    Panel("No chat history found to apply.", title="Chat History",
                          expand=False, border_style="yellow",)
                )

            if not os.path.exists(memory_file):
                error_message()
                return

            with open(memory_file, "r") as f:
                chat_history = json.load(f)

            if not chat_history["ask_conversation"]:
                error_message()
                return
            conversations = chat_history["ask_conversation"]

            yaml_config["context"] += f"下面是我们的历史对话，参考我们的历史对话从而更好的理解需求和修改代码。\n\n<history>\n"
            for conv in conversations:
                if conv["role"] == "user":
                    yaml_config["context"] += f"用户: {conv['content']}\n"
                elif conv["role"] == "assistant":
                    yaml_config["context"] += f"你: {conv['content']}\n"
            yaml_config["context"] += "</history>\n"

        yaml_config["file"] = latest_yaml_file
        yaml_content = convert_yaml_config_to_str(yaml_config=yaml_config)
        execute_file = os.path.join(args.source_dir, "actions", latest_yaml_file)
        with open(os.path.join(execute_file), "w") as f:
            f.write(yaml_content)
        convert_yaml_to_config(execute_file)

        dispacher = Dispacher(llm)
        dispacher.dispach()
    else:
        logger.warning("创建新的 YAML 文件失败。")

    save_memory()
    completer.refresh_files()


def execute_revert():
    repo_path = args.source_dir

    file_content = open(args.file).read()
    md5 = hashlib.md5(file_content.encode("utf-8")).hexdigest()
    file_name = os.path.basename(args.file)

    revert_result = git_revert_changes(repo_path, f"auto_coder_{file_name}_{md5}")
    if revert_result:
        os.remove(args.file)
        logger.info(f"已成功回退最后一次 chat action 的更改，并移除 YAML 文件 {args.file}")
    else:
        logger.error(f"回退文件 {args.file} 的更改失败")
    return


def revert():
    last_yaml_file = get_last_yaml_file(os.path.join(args.source_dir, "actions"))
    if last_yaml_file:
        file_path = os.path.join(args.source_dir, "actions", last_yaml_file)
        convert_yaml_to_config(file_path)
        execute_revert()
    else:
        logger.warning("No previous chat action found to revert.")


@prompt()
def _generate_shell_script(user_input: str) -> str:
    """
    根据用户的输入以及当前的操作系统生成合适的 shell 脚本。

    用户输入: {{ user_input }}

    请生成一个适当的 shell 脚本来执行用户的请求。确保脚本是安全的，并且可以在 Linux/Mac 操作系统支持的 shell 中运行。
    脚本应该包含必要的注释来解释每个步骤。
    脚本内容请用如下方式返回：

    ```shell
    # 你的 shell 脚本内容
    ```
    """


def generate_shell_command(input_text: str, llm: AutoLLM):
    conf = memory.get("conf", {})
    yaml_config = {
        "include_file": ["./base/base.yml"],
    }
    if "model" in conf:
        yaml_config["model"] = conf["model"]
    yaml_config["query"] = input_text

    yaml_content = convert_yaml_config_to_str(yaml_config=yaml_config)

    execute_file = os.path.join(args.source_dir, "actions", f"{uuid.uuid4()}.yml")

    with open(os.path.join(execute_file), "w") as f:
        f.write(yaml_content)

    try:
        console.print(
            Panel(
                f"正在根据用户输入 {input_text} 生成 Shell 脚本...",
                title="命令生成",
                border_style="green",
            )
        )
        llm.setup_default_model_name(memory["conf"]["current_code_model"])
        result = _generate_shell_script.with_llm(llm).run(user_input=input_text)
        shell_script = extract_code(result.output)[0][1]
        console.print(
            Panel(
                shell_script,
                title="Shell 脚本",
                border_style="magenta",
            )
        )
        return shell_script
    finally:
        os.remove(execute_file)


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
                            Text("\n".join(output[-20:])),
                            title="Shell 输出",
                            border_style="green",
                        )
                    )
                if error_line:
                    output.append(f"ERROR: {error_line.strip()}")
                    live.update(
                        Panel(
                            Text("\n".join(output[-20:])),
                            title="Shell 输出",
                            border_style="red",
                        )
                    )
                if output_line == "" and error_line == "" and process.poll() is not None:
                    break

        if process.returncode != 0:
            console.print(f"[bold red]命令执行失败，返回码: {process.returncode}[/bold red]")
        else:
            console.print("[bold green]命令执行成功[/bold green]")
    except FileNotFoundError:
        console.print(f"[bold red]未找到命令:[/bold red] [yellow]{command}[/yellow]")
    except subprocess.SubprocessError as e:
        console.print(f"[bold red]命令执行错误:[/bold red] [yellow]{str(e)}[/yellow]")


def parse_args(input_args: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="使用AI编程")

    parser.add_argument("--debug", action="store_true",
                        help="Enable debug mode")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Enter the auto-coder.chat without initializing the system",
    )

    parser.add_argument("--request_id", default="", help="Request ID")
    parser.add_argument("--source_dir", required=False, help="项目源代码目录路径")
    parser.add_argument("--git_url", help="用于克隆源代码的Git仓库URL")
    parser.add_argument("--target_file", required=False, help="生成的源代码的输出文件路径")
    parser.add_argument("--query", help="用户查询或处理源代码的指令")
    parser.add_argument("--template", default="common", help="生成源代码使用的模板。默认为'common'")
    parser.add_argument("--project_type", default="py",
                        help="项目类型。当前可选值:py。默认为'py'")
    parser.add_argument("--execute", action="store_true", help="模型是否生成代码")
    parser.add_argument("--model", default="", help="使用的模型名称。默认为空")
    parser.add_argument(
        "--model_max_input_length",
        type=int,
        default=6000,
        help="模型的最大输入长度。默认为6000。",
    )
    parser.add_argument(
        "--index_filter_level", type=int, default=0,
        help="索引过滤级别,0:仅过滤query 中提到的文件名，1. 过滤query 中提到的文件名以及可能会隐含会使用的文件 2. 从0,1 中获得的文件，再寻找这些文件相关的文件。"
    )
    parser.add_argument(
        "--index_filter_workers", type=int, default=1, help="用于通过索引过滤文件的工作线程数"
    )
    parser.add_argument(
        "--index_filter_file_num",
        type=int,
        default=-1,
        help="过滤后的最大文件数。默认为-1,即全部",
    )
    parser.add_argument(
        "--index_build_workers", type=int, default=1, help="用于构建索引的工作线程数"
    )
    parser.add_argument("--file", default=None, required=False, help="YAML配置文件路径")
    parser.add_argument(
        "--anti_quota_limit", type=int, default=1, help="每次API请求后等待的秒数。默认为1秒"
    )
    parser.add_argument(
        "--skip_build_index", action="store_false", help="是否跳过构建源代码索引。默认为False"
    )
    parser.add_argument(
        "--skip_filter_index", action="store_true", help="是否跳过使用索引过滤文件。默认为False"
    )
    parser.add_argument(
        "--human_as_model", action="store_true", help="是否使用人工作为模型(功能开发中)。默认为False"
    )
    parser.add_argument(
        "--human_model_num", type=int, default=1, help="使用的人工模型数量。默认为1"
    )
    parser.add_argument("--urls", default="", help="要爬取并提取文本的URL,多个URL以逗号分隔")
    parser.add_argument(
        "--auto_merge", nargs="?", const=True, default=False,
        help="是否自动将生成的代码合并到现有文件中。默认为False。"
    )
    parser.add_argument(
        "--editblock_similarity", type=float, default=0.9,
        help="合并编辑块时TextSimilarity的相似度阈值。默认为0.9",
    )
    parser.add_argument(
        "--enable_multi_round_generate", action="store_true",
        help="是否开启多轮对话生成。默认为False",
    )
    parser.add_argument(
        "--skip_confirm", action="store_true", help="跳过任何确认。默认为False"
    )
    parser.add_argument(
        "--silence",
        action="store_true",
        help="是否静默执行,不打印任何信息。默认为False",
    )

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
    print_info("对于混合语言项目，使用逗号分隔的值。")
    print_info("示例：'.java,.scala' 或 '.py,.ts'")

    print_warning(f"如果留空，默认为 'py'。\n")

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


def print_status(message, status):
    if status == "success":
        print(f"\033[32m✓ {message}\033[0m")
    elif status == "warning":
        print(f"\033[33m! {message}\033[0m")
    elif status == "error":
        print(f"\033[31m✗ {message}\033[0m")
    elif status == "buffering":  # Add buffering status
        chars = ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷']
        def show_loading():
            while not stop_buffering_event.is_set():
                for char in chars:
                    if stop_buffering_event.is_set():
                        break
                    sys.stdout.write(f'\r\033[33m{char} {message}\033[0m')
                    sys.stdout.flush()
                    time.sleep(0.1)
        # 创建并启动加载动画线程
        loading_thread = threading.Thread(target=show_loading)
        loading_thread.start()
        return loading_thread
    else:
        print(f"  {message}")


def initialize_system():
    print(f"\n\033[1;34m🚀 正在初始化系统...\033[0m")

    def _init_project():
        first_time = False
        if not os.path.exists(os.path.join(args.source_dir, ".auto-coder")):
            first_time = True
            print_status("当前目录未初始化为auto-coder项目。", "warning")
            init_choice = input(f"  是否现在初始化项目？(y/n): ").strip().lower()
            if init_choice == "y":
                try:
                    init_project()
                    print_status("项目初始化成功。", "success")
                except Exception as e:
                    print_status(f"项目初始化失败, {str(e)}。", "error")
                    exit(1)
            else:
                print_status("退出而不初始化。", "warning")
                exit(1)

        if not os.path.exists(base_persist_dir):
            os.makedirs(base_persist_dir, exist_ok=True)
            print_status("创建目录：{}".format(base_persist_dir), "success")

        if first_time:  # 首次启动,配置项目类型
            configure_project_type()

        print_status("项目初始化完成。", "success")

    _init_project()


def show_help():
    print(f"\033[1m支持的命令：\033[0m")
    print(f"  \033[94m命令\033[0m - \033[93m描述\033[0m")
    print(f"  \033[94m/add_files\033[0m \033[93m<file1> <file2> ...\033[0m - \033[92m将文件添加到当前会话\033[0m")
    print(f"  \033[94m/remove_files\033[0m \033[93m<file1>,<file2> ...\033[0m - \033[92m从当前会话中移除文件\033[0m")
    print(f"  \033[94m/chat\033[0m \033[93m<query>\033[0m - \033[92m与AI聊天，获取关于当前活动文件的见解\033[0m")
    print(f"  \033[94m/coding\033[0m \033[93m<query>\033[0m - \033[92m根据需求请求AI修改代码\033[0m")
    print(f"  \033[94m/revert\033[0m - \033[92m撤销上次代码聊天的提交\033[0m")
    print(
        f"  \033[94m/conf\033[0m \033[93m<key>:<value>\033[0m  - \033[92m设置配置。使用 /conf project_type:<type> "
        f"设置索引的项目类型\033[0m"
    )
    print(f"  \033[94m/index/build\033[0m - \033[92m触发构建项目索引\033[0m")
    print(f"  \033[94m/index/query\033[0m \033[93m<args>\033[0m - \033[92m查询项目索引进行查询\033[0m")
    print(f"  \033[94m/list_files\033[0m - \033[92m列出当前会话中的所有活动文件\033[0m")
    print(f"  \033[94m/help\033[0m - \033[92m显示此帮助消息\033[0m")
    print(f"  \033[94m/exclude_dirs\033[0m \033[93m<dir1>,<dir2> ...\033[0m - \033[92m添加要从项目中排除的目录\033[0m")
    print(f"  \033[94m/shell\033[0m \033[93m<command>\033[0m - \033[92m执行shell命令\033[0m")
    print(f"  \033[94m/exit\033[0m - \033[92m退出程序\033[0m")
    print()


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
        console.print(
            Panel("请为 /add_files 命令提供参数.", title="错误", border_style="red")
        )
        return

    if add_files_args[0] == "/refresh":  # 刷新
        completer.refresh_files()
        load_memory()
        console.print(
            Panel("已刷新的文件列表.", title="文件刷新", border_style="green")
        )
        return

    if add_files_args[0] == "/group":
        # 列出组
        if len(add_files_args) == 1 or (len(add_files_args) == 2 and add_files_args[1] == "list"):
            if not groups:
                console.print(
                    Panel("未定义任何文件组.", title="文件组",
                          border_style="yellow")
                )
            else:
                table = Table(
                    title="已定义文件组",
                    show_header=True,
                    header_style="bold magenta",
                    show_lines=True,
                )
                table.add_column("Group Name", style="cyan", no_wrap=True)
                table.add_column("Files", style="green")
                table.add_column("Query Prefix", style="yellow")
                table.add_column("Active", style="magenta")

                for i, (group_name, files) in enumerate(groups.items()):
                    query_prefix = groups_info.get(group_name, {}).get("query_prefix", "")
                    is_active = ("✓" if group_name in memory["current_files"]["current_groups"] else "")
                    table.add_row(
                        group_name,
                        "\n".join([os.path.relpath(f, project_root) for f in files]),
                        query_prefix,
                        is_active,
                        end_section=(i == len(groups) - 1),
                    )
                console.print(Panel(table, border_style="blue"))  #
        # 重置活动组
        elif len(add_files_args) >= 2 and add_files_args[1] == "/reset":
            memory["current_files"]["current_groups"] = []
            console.print(
                Panel(
                    "活动组名称已重置。如果你想清除活动文件，可使用命令 /remove_files /all .",
                    title="活动组重置",
                    border_style="green",
                )
            )
        # 新增组
        elif len(add_files_args) >= 3 and add_files_args[1] == "/add":
            group_name = add_files_args[2]
            groups[group_name] = memory["current_files"]["files"].copy()
            console.print(
                Panel(
                    f"已将当前文件添加到组 '{group_name}' .",
                    title="新增组",
                    border_style="green",
                )
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
                console.print(
                    Panel(
                        f"已删除组 '{group_name}'.",
                        title="删除组",
                        border_style="green",
                    )
                )
            else:
                console.print(
                    Panel(
                        f"组 '{group_name}' 未找到.",
                        title="Error",
                        border_style="red",
                    )
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
                console.print(
                    Panel(
                        f"未找到组: {', '.join(missing_groups)}",
                        title="Error",
                        border_style="red",
                    )
                )
            if merged_files:
                memory["current_files"]["files"] = list(merged_files)
                memory["current_files"]["current_groups"] = [
                    name for name in group_names if name in groups
                ]
                console.print(
                    Panel(
                        f"合并来自组 {', '.join(group_names)} 的文件 .",
                        title="文件合并",
                        border_style="green",
                    )
                )
                table = Table(
                    title="当前文件",
                    show_header=True,
                    header_style="bold magenta",
                    show_lines=True,  # 这会在每行之间添加分割线
                )
                table.add_column("File", style="green")
                for i, f in enumerate(memory["current_files"]["files"]):
                    table.add_row(
                        os.path.relpath(f, project_root),
                        end_section=(
                                i == len(memory["current_files"]["files"]) - 1
                        ),  # 在最后一行之后不添加分割线
                    )
                console.print(Panel(table, border_style="blue"))
                console.print(
                    Panel(
                        f"当前组: {', '.join(memory['current_files']['current_groups'])}",
                        title="当前组",
                        border_style="green",
                    )
                )
            elif not missing_groups:
                console.print(
                    Panel(
                        "指定组中没有文件.",
                        title="未添加任何文件",
                        border_style="yellow",
                    )
                )

    else:
        existing_files = memory["current_files"]["files"]
        matched_files = find_files_in_project(add_files_args)

        files_to_add = [f for f in matched_files if f not in existing_files]
        if files_to_add:
            memory["current_files"]["files"].extend(files_to_add)
            table = Table(
                title="新增文件",
                show_header=True,
                header_style="bold magenta",
                show_lines=True,  # 这会在每行之间添加分割线
            )
            table.add_column("File", style="green")
            for i, f in enumerate(files_to_add):
                table.add_row(
                    os.path.relpath(f, project_root),
                    end_section=(i == len(files_to_add) - 1),  # 在最后一行之后不添加分割线
                )
            console.print(Panel(table, border_style="green"))
        else:
            console.print(
                Panel(
                    "所有指定文件已存在于当前会话中，或者未找到匹配的文件.",
                    title="未新增文件",
                    border_style="yellow",
                )
            )

    completer.update_current_files(memory["current_files"]["files"])
    save_memory()


def remove_files(file_names: List[str]):
    if "/all" in file_names:
        memory["current_files"]["files"] = []
        memory["current_files"]["current_groups"] = []
        console.print(Panel("已移除所有文件。", title="文件移除", border_style="green"))
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
            table = Table(title="文件移除", show_header=True, header_style="bold magenta")
            table.add_column("File", style="green")
            for f in removed_files:
                table.add_row(os.path.relpath(f, project_root))
            console.print(Panel(table, border_style="green"))
        else:
            console.print(Panel("未移除任何文件。", title="未移除文件", border_style="yellow"))
    completer.update_current_files(memory["current_files"]["files"])
    save_memory()


def list_files():
    current_files = memory["current_files"]["files"]

    if current_files:
        table = Table(
            title="当前活跃文件", show_header=True, header_style="bold magenta"
        )
        table.add_column("File", style="green")
        for file in current_files:
            table.add_row(os.path.relpath(file, project_root))
        console.print(Panel(table, border_style="blue"))
    else:
        console.print(Panel("当前会话中无文件。", title="当前文件", border_style="yellow"))


def print_conf(content: Dict[str, Any]):
    table = Table(title=f"[italic]使用 /conf <key>:<value> 修改这些设置[/italic]", expand=True, show_lines=True)
    table.add_column("键", style="cyan", justify="right", width=30, no_wrap=True)
    table.add_column("值", style="green", justify="left", width=50, no_wrap=True)
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
        table.add_row(str(key), formatted_value)
    console.print(table)


def print_models(content: Dict[str, Any]):
    table = Table(title="模型", expand=True, show_lines=True)
    table.add_column("Name", style="cyan", width=40, no_wrap=False)
    table.add_column("Model Name", style="magenta", width=30, overflow="fold")
    table.add_column("Base URL", style="white", width=50, overflow="fold")
    if content:
        for name in content:
            table.add_row(
                name,
                content[name].get("model", ""),
                content[name].get("base_url", "")
            )
    else:
        table.add_row("", "", "")
    console.print(table)


def manage_models(models_args, models_data, llm: AutoLLM):
    """
      /models /list - List all models (default + custom)
      /models /add <name> <api_key> - Add model with simplified params
      /models /add_model name=xxx base_url=xxx api_key=xxxx model=xxxxx ... - Add model with custom params
      /models /remove <name> - Remove model by name
    """
    if models_args[0] == "/list":
        print_models(models_data)
    elif models_args[0] == "/add_model":
        add_model_args = models_args[1:]
        add_model_info = {item.split('=')[0]: item.split('=')[1] for item in add_model_args if item}
        _name = add_model_info["name"]
        logger.info(f"正在为 {_name} 更新缓存信息")
        if _name not in memory["models"]:
            memory["models"][_name] = {
                "base_url": add_model_info["base_url"],
                "api_key": add_model_info["api_key"],
                "model": add_model_info["model"]
            }
        else:
            logger.error(f"{_name} 已经存在, 请执行 /models /remove <name> 进行删除")
        logger.info(f"正在部署 {_name} 模型")
        llm.setup_sub_client(_name, add_model_info["api_key"], add_model_info["base_url"])
    elif models_args[0] == "/remove":
        remove_model_name = models_args[1]
        logger.info(f"正在清理 {remove_model_name} 缓存信息")
        if remove_model_name in memory["models"]:
            del memory["models"][remove_model_name]
        logger.info(f"正在卸载 {remove_model_name} 模型")
        if llm.get_sub_client(remove_model_name):
            llm.remove_sub_client(remove_model_name)
        if remove_model_name == memory["conf"]["current_chat_model"]:
            logger.warning(f"当前首选 Chat 模型 {remove_model_name} 已被删除, 请立即 /conf current_chat_model: 调整 !!!")
        if remove_model_name == memory["conf"]["current_code_model"]:
            logger.warning(f"当前首选 Code 模型 {remove_model_name} 已被删除, 请立即 /conf current_code_model: 调整 !!!")


def main():
    _args, runing_args = parse_args()
    _args.source_dir = project_root
    convert_yaml_to_config(_args)

    if not runing_args.quick:
        initialize_system()

    load_memory()

    if len(memory["models"]) == 0:
        print_status("正在配置模型...", "warning")
        _current_model = input(f"  设置你的首选模型名称(例如: deepseek-v3/r1, ark-deepseek-v3/r1): ").strip().lower()
        _current_model_name = input(f"  请输入你使用模型的 Model Name: ").strip().lower()
        _current_base_url = input(f"  请输入你使用模型的 Base URL: ").strip().lower()
        _current_api_key = input(f"  请输入您的API密钥: ").strip().lower()
        print_status(f"正在更新缓存...", "warning")
        memory["conf"]["current_chat_model"] = _current_model
        memory["conf"]["current_code_model"] = _current_model
        memory["models"][_current_model] = {
            "base_url": _current_base_url, "api_key": _current_api_key, "model": _current_model_name
        }

    auto_llm = AutoLLM()  # 创建模型
    if len(memory["models"]) > 0:
        conn_dict = {}
        for _model_name in memory["models"]:
            if memory["models"][_model_name].get("skip","false") == "true":
                print_status(f"跳过 {_model_name} 模型...", "warning")
                continue
            else:
                try:
                    buffer_thread = print_status(f"正在部署 {_model_name} 模型", "buffering")
                    _conn, _lag = auto_llm.setup_sub_client(_model_name,
                                    memory["models"][_model_name]["api_key"],
                                    memory["models"][_model_name]["base_url"])
                    # 设置停止标志
                    stop_buffering_event.set()
                    buffer_thread.join()
                    conn_dict[_model_name] = (_conn,_lag)
                    # 重置事件标志，以便下一个线程能正常工作
                    stop_buffering_event.clear()
                    print_status(f"", "success")
                except Exception as e:
                    stop_buffering_event.set()
                    print_status(f"部署 {_model_name} 模型时出错: {e}", "error")
                    # 重置事件标志，以便下一个线程能正常工作
                    stop_buffering_event.clear()

            # print_status(f"正在部署 {_model_name} 模型...", "warning")
            # auto_llm.setup_sub_client(_model_name,
            #                           memory["models"][_model_name]["api_key"],
            #                           memory["models"][_model_name]["base_url"])
    # Create table to show model status
    status_table = Table(title="Model Connection Status", show_header=True, header_style="bold magenta")
    status_table.add_column("Model Name", style="cyan")
    status_table.add_column("Status", justify="center")
    status_table.add_column("Latency", justify="right", style="green")
    # Track best model based on latency
    best_model = None
    min_latency = float('inf')
    # Add rows for each model
    for _model_name, (_ok, _latency) in conn_dict.items():
        status = "✓" if _ok else "✗"
        status_style = "green" if _ok else "red"
        
        if _ok:
            latency_text = f"{_latency:.2f}s"
            if _latency < min_latency:
                min_latency = _latency
                best_model = _model_name
        else:
            latency_text = f"Error: {_latency}"
        
        status_table.add_row(
        _model_name,
        Text(status, style=status_style),
        latency_text
        )

    # Add recommendation 
    if best_model:
        status_table.caption = f"[green]Recommendation: Use '{best_model}' for best performance (lowest latency)[/green]"
    else:
        status_table.caption = "[red]Warning: No working models found[/red]"
        
    console.print(status_table)
    #回到原始setup_subclient步骤
    print_status("初始化完成。", "success")

    if memory["conf"]["current_chat_model"] not in memory["models"].keys():
        print_status("首选 Chat 模型与部署模型不一致, 请使用 /conf current_chat_model:xxx 设置", "error")
    if memory["conf"]["current_code_model"] not in memory["models"].keys():
        print_status("首选 Code 模型与部署模型不一致, 请使用 /conf current_code_model:xxx 设置", "error")

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

    def _update_bottom_toolbar(toolbar_arg):
        if toolbar_arg in memory['conf']:
            return memory['conf'][toolbar_arg]
        return args.model_dump()[toolbar_arg]

    def get_bottom_toolbar():
        if "mode" not in memory:
            memory["mode"] = "normal"
        mode = memory["mode"]
        skip_build_toolbar = _update_bottom_toolbar('skip_build_index')
        skip_filter_toolbar = _update_bottom_toolbar('skip_filter_index')
        index_filter_toolbar = _update_bottom_toolbar('index_filter_level')
        return (f" 当前模式: {MODES[mode]} (ctl+k 切换模式) | 跳过索引: {skip_build_toolbar} "
                f"| 跳过过滤: {skip_filter_toolbar} | 过滤等级: {index_filter_toolbar}")

    session = PromptSession(
        history=InMemoryHistory(),
        auto_suggest=AutoSuggestFromHistory(),
        enable_history_search=False,
        completer=completer,
        complete_while_typing=True,
        key_bindings=kb,
        bottom_toolbar=get_bottom_toolbar,
    )
    print(f"""\033[1;32mAutoCoder Nano   v{__version__}\033[0m""")
    print("\033[1;34m输入 /help 可以查看可用的命令.\033[0m\n")
    # show_help()

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
            elif user_input.startswith("/index/build"):
                index_command(llm=auto_llm)
            elif user_input.startswith("/index/query"):
                query = user_input[len("/index/query"):].strip()
                index_query_command(query=query, llm=auto_llm)
            elif user_input.startswith("/list_files"):
                list_files()
            elif user_input.startswith("/conf"):
                conf = user_input[len("/conf"):].strip()
                if not conf:
                    # print(memory["conf"])
                    print_conf(memory["conf"])
                else:
                    configure(conf)
            elif user_input.startswith("/revert"):
                revert()
            elif user_input.startswith("/help"):
                show_help()
            elif user_input.startswith("/exit"):
                raise EOFError()
            elif user_input.startswith("/coding"):
                query = user_input[len("/coding"):].strip()
                if not query:
                    print("\033[91mPlease enter your request.\033[0m")
                    continue
                coding(query=query, llm=auto_llm)
            elif user_input.startswith("/chat"):
                query = user_input[len("/chat"):].strip()
                if not query:
                    print("\033[91mPlease enter your request.\033[0m")
                else:
                    chat(query=query, llm=auto_llm)
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
            if runing_args and runing_args.debug:
                import traceback
                traceback.print_exc()


if __name__ == '__main__':
    main()
