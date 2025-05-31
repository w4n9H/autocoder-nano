import argparse
import glob
import hashlib
import os
import json
import shutil
import subprocess
import textwrap
import time
import uuid

from autocoder_nano.edit import Dispacher
from autocoder_nano.helper import show_help
from autocoder_nano.index.entry import build_index_and_filter_files
from autocoder_nano.index.index_manager import IndexManager
from autocoder_nano.index.symbols_utils import extract_symbols
from autocoder_nano.llm_client import AutoLLM
from autocoder_nano.version import __version__
from autocoder_nano.llm_types import *
from autocoder_nano.llm_prompt import prompt, extract_code
from autocoder_nano.templates import create_actions
from autocoder_nano.git_utils import (repo_init, commit_changes, revert_changes,
                                      get_uncommitted_changes, generate_commit_message)
from autocoder_nano.sys_utils import default_exclude_dirs, detect_env
from autocoder_nano.project import PyProject, SuffixProject
from autocoder_nano.utils.printer_utils import Printer

import yaml
# import tabulate
from jinja2 import Template
# from loguru import logger
from prompt_toolkit import prompt as _toolkit_prompt, PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import confirm
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text


printer = Printer()
console = printer.get_console()
# console = Console()
project_root = os.getcwd()
base_persist_dir = os.path.join(project_root, ".auto-coder", "plugins", "chat-auto-coder")
# defaut_exclude_dirs = [".git", ".svn", "node_modules", "dist", "build", "__pycache__", ".auto-coder", "actions",
#                        ".vscode", ".idea", ".hg"]
commands = [
    "/add_files", "/remove_files", "/list_files", "/conf", "/coding", "/chat", "/revert", "/index/query",
    "/index/build", "/exclude_dirs", "/exclude_files", "/help", "/shell", "/exit", "/mode", "/models", "/commit", "/new"
]

memory = {
    "conversation": [],
    "current_files": {"files": [], "groups": {}},
    "conf": {
        "auto_merge": "editblock",
        # "current_chat_model": "",
        # "current_code_model": "",
        "chat_model": "",
        "code_model": "",
    },
    "exclude_dirs": [],
    "mode": "normal",  # 新增mode字段,默认为normal模式
    "models": {}
}


args: AutoCoderArgs = AutoCoderArgs()


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


COMMANDS = {
    "/add_files": {
        "/group": {"/add": "", "/drop": "", "/reset": ""},
        "/refresh": "",
    },
    "/remove_files": {"/all": ""},
    "/coding": {"/apply": ""},
    "/chat": {"/history": "", "/new": "", "/review": ""},
    "/models": {
        "/add_model": "",
        "/remove": "",
        "/list": "",
        "/check": ""
    },
    "/help": {
        "/add_files": "",
        "/remove_files": "",
        "/chat": "",
        "/coding": "",
        "/commit": "",
        "/conf": "",
        "/mode": "",
        "/models": ""
    },
    "/exclude_files": {"/list": "", "/drop": ""},
    "/exclude_dirs": {}
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

    def is_sub_command(self) -> bool | None:
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

    def is_start_tag(self) -> bool | None:
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

            elif words[0] == "/exclude_files":
                new_text = text[len("/exclude_files"):]
                parser = CommandTextParser(new_text, words[0])
                parser.add_files()
                current_word = parser.current_word()
                for command in parser.get_sub_commands():
                    if command.startswith(current_word):
                        yield Completion(command, start_position=-len(current_word))

            elif words[0] == "/models":
                new_text = text[len("/models"):]
                parser = CommandTextParser(new_text, words[0])
                parser.add_files()
                current_word = parser.current_word()
                for command in parser.get_sub_commands():
                    if command.startswith(current_word):
                        yield Completion(command, start_position=-len(current_word))

            elif words[0] == "/help":
                new_text = text[len("/help"):]
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
    update_config_to_args(query="", delete_execute_file=True)

    source_dir = os.path.abspath(args.source_dir)
    printer.print_text(f"开始对目录 {source_dir} 中的源代码进行索引", style="green")
    if args.project_type == "py":
        pp = PyProject(llm=llm, args=args)
    else:
        pp = SuffixProject(llm=llm, args=args)
    pp.run()
    _sources = pp.sources
    index_manager = IndexManager(args=args, source_codes=_sources, llm=llm)
    index_manager.build_index()


def index_export(export_path: str) -> bool:
    try:
        index_path = os.path.join(project_root, ".auto-coder", "index.json")
        if not os.path.exists(index_path):
            printer.print_text(Text(f"索引文件不存在. ", style="bold red"))
            return False

        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)

        converted_data = {}
        for abs_path, data in index_data.items():
            try:
                rel_path = os.path.relpath(abs_path, project_root)
                data["module_name"] = rel_path
                converted_data[rel_path] = data
            except ValueError:
                printer.print_text(Text(f"索引转换路径失败. ", style="dim yellow"))
                converted_data[abs_path] = data

        export_file = os.path.join(export_path, "index.json")
        with open(export_file, "w", encoding="utf-8") as f:
            json.dump(converted_data, f, indent=2)
        printer.print_text(Text(f"索引文件导出成功. ", style="bold green"))
        return True
    except Exception as err:
        printer.print_text(Text(f"索引文件导出失败: {err}", style="bold red"))
        return False


def index_import(import_path: str):
    try:
        import_file = os.path.join(import_path, "index.json")
        if not os.path.exists(import_file):
            printer.print_text(Text(f"导入索引文件不存在", style="bold red"))
            return False
        with open(import_file, "r", encoding="utf-8") as f:
            index_data = json.load(f)
        converted_data = {}
        for rel_path, data in index_data.items():
            try:
                abs_path = os.path.join(project_root, rel_path)
                data["module_name"] = abs_path
                converted_data[abs_path] = data
            except Exception as err:
                printer.print_text(Text(f"{rel_path} 索引转换路径失败: {err}", style="dim yellow"))
                converted_data[rel_path] = data
        # Backup existing index
        index_path = os.path.join(project_root, ".auto-coder", "index.json")
        if os.path.exists(index_path):
            printer.print_text(Text(f"原索引文件不存在", style="bold yellow"))
            backup_path = index_path + ".bak"
            shutil.copy2(index_path, backup_path)

        # Write new index
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(converted_data, f, indent=2)
        return True
    except Exception as err:
        printer.print_text(Text(f"索引文件导入失败: {err}", style="bold red"))
        return False


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
    update_config_to_args(query=query, delete_execute_file=True)

    # args.query = query
    if args.project_type == "py":
        pp = PyProject(llm=llm, args=args)
    else:
        pp = SuffixProject(llm=llm, args=args)
    pp.run()
    _sources = pp.sources

    final_files = []
    index_manager = IndexManager(args=args, source_codes=_sources, llm=llm)
    target_files = index_manager.get_target_files_by_query(query)

    if target_files:
        final_files.extend(target_files.file_list)

    if target_files and args.index_filter_level >= 2:

        related_fiels = index_manager.get_related_files([file.file_path for file in target_files.file_list])

        if related_fiels is not None:
            final_files.extend(related_fiels.file_list)

    all_results = list({file.file_path: file for file in final_files}.values())
    printer.print_key_value(
        {"索引过滤级别": f"{args.index_filter_level}", "查询条件": f"{args.query}", "过滤后的文件数": f"{len(all_results)}"},
        panel=True
    )

    # headers = TargetFile.model_fields.keys()
    # table_data = wrap_text_in_table(
    #     [[getattr(file_item, name) for name in headers] for file_item in all_results]
    # )
    # table_output = tabulate.tabulate(table_data, headers, tablefmt="grid")
    # print(table_output, flush=True)
    printer.print_table_compact(
        headers=["文件路径", "原因"],
        data=[[_target_file.file_path, _target_file.reason] for _target_file in all_results],
        title="Index Query 结果",
        show_lines=True,
    )
    return


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
        printer.print_text(f"无效的配置项: {key}", style="red")
        return None


def update_config_to_args(query, delete_execute_file: bool = False):
    conf = memory.get("conf", {})

    # 默认 chat 配置
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

    yaml_content = convert_yaml_config_to_str(yaml_config=yaml_config)
    execute_file = os.path.join(args.source_dir, "actions", f"{uuid.uuid4()}.yml")

    with open(os.path.join(execute_file), "w") as f:  # 保存此次查询的细节
        f.write(yaml_content)

    convert_yaml_to_config(execute_file)  # 更新到args

    if delete_execute_file:
        if os.path.exists(execute_file):
            os.remove(execute_file)


def print_chat_history(history, max_entries=5):
    recent_history = history[-max_entries:]
    data_list = []
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


def chat(query: str, llm: AutoLLM):
    update_config_to_args(query)

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
            old_chat_history["conversation_history"].append(
                old_chat_history.get("ask_conversation", []))
            chat_history = {"ask_conversation": [
            ], "conversation_history": old_chat_history["conversation_history"]}
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
        # if "conversation_history" in chat_history:
        #     show_chat.extend(chat_history["conversation_history"])
        if "ask_conversation" in chat_history:
            show_chat.extend(chat_history["ask_conversation"])
        print_chat_history(show_chat)
        return

    chat_history["ask_conversation"].append(
        {"role": "user", "content": query}
    )

    chat_llm = llm
    pre_conversations = []

    if args.project_type == "py":
        pp = PyProject(llm=llm, args=args)
    else:
        pp = SuffixProject(llm=llm, args=args)
    pp.run()
    _sources = pp.sources
    s = build_index_and_filter_files(args=args, llm=llm, sources=_sources)
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

    v = chat_llm.stream_chat_ai(conversations=loaded_conversations, model=args.chat_model)

    MAX_HISTORY_LINES = 15  # 最大保留历史行数
    lines_buffer = []
    current_line = ""
    assistant_response = ""

    try:
        with Live(Panel("", title="Response", style="cyan"), refresh_per_second=12) as live:
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
                        Panel(Markdown(display_content), title="模型返回", border_style="cyan",
                              height=min(25, live.console.height - 4))
                    )

            # 处理最后未换行的内容
            if current_line:
                lines_buffer.append(current_line)

            # 最终完整渲染
            live.update(
                Panel(Markdown(assistant_response), title="模型返回", border_style="dim blue")
            )
    except Exception as e:
        printer.print_panel(Text(f"{str(e)}", style="red"), title="模型返回", center=True)

    chat_history["ask_conversation"].append({"role": "assistant", "content": assistant_response})

    with open(memory_file, "w") as fp:
        json_str = json.dumps(chat_history, ensure_ascii=False)
        fp.write(json_str)

    return


def init_project():
    if not args.project_type:
        printer.print_text(
            f"请指定项目类型。可选的项目类型包括：py|ts| 或文件扩展名(例如:.java,.scala), 多个扩展名逗号分隔.", style="green"
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

    repo_init(source_dir)
    with open(os.path.join(source_dir, ".gitignore"), "a") as f:
        f.write("\n.auto-coder/")
        f.write("\nactions/")
        f.write("\noutput.txt")

    printer.print_text(f"已在 {os.path.abspath(args.source_dir)} 成功初始化 autocoder-nano 项目", style="green")
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
            printer.print_text(f"正在加载 Include file: {abs_include_path}", style="green")
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


def prepare_chat_yaml():
    # auto_coder_main(["next", "chat_action"]) 准备聊天 yaml 文件
    actions_dir = os.path.join(args.source_dir, "actions")
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
                printer.print_panel(
                    Text("No chat history found to apply.", style="yellow"), title="Chat History", center=True
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

        dispacher = Dispacher(args=args, llm=llm)
        dispacher.dispach()
    else:
        printer.print_text(f"创建新的 YAML 文件失败.", style="yellow")

    save_memory()
    completer.refresh_files()


def execute_revert():
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
    last_yaml_file = get_last_yaml_file(os.path.join(args.source_dir, "actions"))
    if last_yaml_file:
        file_path = os.path.join(args.source_dir, "actions", last_yaml_file)
        convert_yaml_to_config(file_path)
        execute_revert()
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
    repo_path = args.source_dir
    prepare_chat_yaml()  # 复制上一个序号的 yaml 文件, 生成一个新的聊天 yaml 文件

    latest_yaml_file = get_last_yaml_file(os.path.join(args.source_dir, "actions"))
    execute_file = None

    if latest_yaml_file:
        try:
            execute_file = os.path.join(args.source_dir, "actions", latest_yaml_file)
            conf = memory.get("conf", {})
            yaml_config = {
                "include_file": ["./base/base.yml"],
                "skip_build_index": conf.get("skip_build_index", "true") == "true",
                "skip_confirm": conf.get("skip_confirm", "true") == "true",
                "chat_model": conf.get("chat_model", ""),
                "code_model": conf.get("code_model", ""),
                "auto_merge": conf.get("auto_merge", "editblock")
            }
            for key, value in conf.items():
                converted_value = convert_config_value(key, value)
                if converted_value is not None:
                    yaml_config[key] = converted_value

            current_files = memory["current_files"]["files"]
            yaml_config["urls"] = current_files

            # 临时保存yaml文件，然后读取yaml文件，更新args
            temp_yaml = os.path.join(args.source_dir, "actions", f"{uuid.uuid4()}.yml")
            try:
                with open(temp_yaml, "w", encoding="utf-8") as f:
                    f.write(convert_yaml_config_to_str(yaml_config=yaml_config))
                convert_yaml_to_config(temp_yaml)
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


@prompt()
def _generate_shell_script(user_input: str) -> str:
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
    update_config_to_args(query=input_text, delete_execute_file=True)

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
        if not os.path.exists(os.path.join(args.source_dir, ".auto-coder")):
            first_time = True
            printer.print_text("当前目录未初始化为auto-coder项目.", style="yellow")
            init_choice = input(f"  是否现在初始化项目？(y/n): ").strip().lower()
            if init_choice == "y":
                try:
                    init_project()
                    printer.print_text("项目初始化成功.", style="green")
                except Exception as e:
                    printer.print_text(f"项目初始化失败, {str(e)}.", style="red")
                    exit(1)
            else:
                printer.print_text("退出而不初始化.", style="yellow")
                exit(1)

        if not os.path.exists(base_persist_dir):
            os.makedirs(base_persist_dir, exist_ok=True)
            printer.print_text("创建目录：{}".format(base_persist_dir), style="green")

        if first_time:  # 首次启动,配置项目类型
            configure_project_type()

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
        "1": {"name": "ark-deepseek-r1", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
              "model_name": "deepseek-r1-0528"},
        "2": {"name": "ark-deepseek-v3", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
              "model_name": "deepseek-v3-250324"},
        "3": {"name": "sili-deepseek-r1", "base_url": "https://api.siliconflow.cn/v1",
              "model_name": "deepseek-ai/DeepSeek-R1"},
        "4": {"name": "sili-deepseek-v3", "base_url": "https://api.siliconflow.cn/v1",
              "model_name": "deepseek-ai/DeepSeek-V3"},
        "5": {"name": "deepseek-r1", "base_url": "https://api.deepseek.com", "model_name": "deepseek-reasoner"},
        "6": {"name": "deepseek-v3", "base_url": "https://api.deepseek.com", "model_name": "deepseek-chat"},
    }

    print_header(f"\n=== 正在配置项目模型 ===\n")
    print_info("选择您的首选模型供应商: ")
    print_info(f"  1. 火山方舟 DeepSeek-R1")
    print_info(f"  2. 火山方舟 DeepSeek-V3")
    print_info(f"  3. 硅基流动 DeepSeek-R1(非Pro)")
    print_info(f"  4. 硅基流动 DeepSeek-V3(非Pro)")
    print_info(f"  5. 官方 DeepSeek-R1")
    print_info(f"  6. 官方 DeepSeek-V3")
    print_info(f"  7. 其他供应商")
    model_num = input(f"  请选择您想使用的模型供应商编号(1-6): ").strip().lower()

    if int(model_num) < 1 or int(model_num) > 7:
        printer.print_text("请选择 1-7", style="red")
        exit(1)

    if model_num == "7":
        current_model = input(f"  设置你的首选模型别名(例如: deepseek-v3/r1, ark-deepseek-v3/r1): ").strip().lower()
        current_model_name = input(f"  请输入你使用模型的 Model Name: ").strip().lower()
        current_base_url = input(f"  请输入你使用模型的 Base URL: ").strip().lower()
        current_api_key = input(f"  请输入您的API密钥: ").strip().lower()
        return current_model, current_model_name, current_base_url, current_api_key

    model_name_value = default_model[model_num].get("model_name", "")
    model_api_key = input(f"请输入您的 API 密钥：").strip().lower()
    return (
        default_model[model_num]["name"],
        model_name_value,
        default_model[model_num]["base_url"],
        model_api_key
    )


# def new_project(query, llm):
#     console.print(f"正在基于你的需求 {query} 构建项目 ...", style="bold green")
#     env_info = detect_env()
#     project = BuildNewProject(args=args, llm=llm,
#                               chat_model=memory["conf"]["chat_model"],
#                               code_model=memory["conf"]["code_model"])
#
#     console.print(f"正在完善项目需求 ...", style="bold green")
#
#     information = project.build_project_information(query, env_info, args.project_type)
#     if not information:
#         raise Exception(f"项目需求未正常生成 .")
#
#     table = Table(title=f"{query}")
#     table.add_column("需求说明", style="cyan")
#     table.add_row(f"{information[:50]}...")
#     console.print(table)
#
#     console.print(f"正在完善项目架构 ...", style="bold green")
#     architecture = project.build_project_architecture(query, env_info, args.project_type, information)
#
#     console.print(f"正在构建项目索引 ...", style="bold green")
#     index_file_list = project.build_project_index(query, env_info, args.project_type, information, architecture)
#
#     table = Table(title=f"索引列表")
#     table.add_column("路径", style="cyan")
#     table.add_column("用途", style="cyan")
#     for index_file in index_file_list.file_list:
#         table.add_row(index_file.file_path, index_file.purpose)
#     console.print(table)
#
#     for index_file in index_file_list.file_list:
#         full_path = os.path.join(args.source_dir, index_file.file_path)
#
#         # 获取目录路径
#         full_dir_path = os.path.dirname(full_path)
#         if not os.path.exists(full_dir_path):
#             os.makedirs(full_dir_path)
#
#         console.print(f"正在编码: {full_path} ...", style="bold green")
#         code = project.build_single_code(query, env_info, args.project_type, information, architecture, index_file)
#
#         with open(full_path, "w") as fp:
#             fp.write(code)
#
#     # 生成 readme
#     readme_context = information + architecture
#     readme_path = os.path.join(args.source_dir, "README.md")
#     with open(readme_path, "w") as fp:
#         fp.write(readme_context)
#
#     console.print(f"项目构建完成", style="bold green")


def is_old_version():
    """
    __version__ = "0.1.26" 开始使用兼容 AutoCoder 的 chat_model, code_model 参数
    不再使用 current_chat_model 和 current_chat_model
    """
    if 'current_chat_model' in memory['conf'] and 'current_code_model' in memory['conf']:
        printer.print_text(f"您当前使用的版本偏低 {__version__}, 正在进行配置兼容性处理", style="yellow")
        memory['conf']['chat_model'] = memory['conf']['current_chat_model']
        memory['conf']['code_model'] = memory['conf']['current_code_model']
        del memory['conf']['current_chat_model']
        del memory['conf']['current_code_model']


def main():
    _args, runing_args = parse_args()
    _args.source_dir = project_root
    convert_yaml_to_config(_args)

    if not runing_args.quick:
        initialize_system()

    load_memory()
    is_old_version()

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
            elif user_input.startswith("/index/build"):
                index_command(llm=auto_llm)
            elif user_input.startswith("/index/query"):
                query = user_input[len("/index/query"):].strip()
                index_query_command(query=query, llm=auto_llm)
            elif user_input.startswith("/index/export"):
                export_path = user_input[len("/index/export"):].strip()
                index_export(export_path)
            elif user_input.startswith("/index/import"):
                import_path = user_input[len("/index/import"):].strip()
                index_import(import_path)
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
            elif user_input.startswith("/commit"):
                query = user_input[len("/commit"):].strip()
                commit_info(query, auto_llm)
            elif user_input.startswith("/help"):
                query = user_input[len("/help"):].strip()
                show_help(query)
            elif user_input.startswith("/exit"):
                raise EOFError()
            elif user_input.startswith("/coding"):
                query = user_input[len("/coding"):].strip()
                if not query:
                    print("\033[91mPlease enter your request.\033[0m")
                    continue
                coding(query=query, llm=auto_llm)
            # elif user_input.startswith("/new"):
            #     query = user_input[len("/new"):].strip()
            #     if not query:
            #         print("\033[91mPlease enter your request.\033[0m")
            #         continue
            #     new_project(query=query, llm=auto_llm)
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
            if runing_args and runing_args.debug:
                import traceback
                traceback.print_exc()


if __name__ == '__main__':
    main()
