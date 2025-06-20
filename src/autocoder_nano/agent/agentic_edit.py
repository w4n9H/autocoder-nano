import json
import os
import re
import time
import xml.sax.saxutils
from importlib import resources
from typing import List, Dict, Any, Optional, Generator, Union, Tuple, Type

from rich.markdown import Markdown
from tokenizers import Tokenizer

from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.git_utils import commit_changes, get_uncommitted_changes
from autocoder_nano.llm_client import AutoLLM, stream_chat_with_continue
from autocoder_nano.llm_prompt import prompt, format_str_jinja2
from autocoder_nano.llm_types import AutoCoderArgs, SourceCodeList, SingleOutputMeta
from autocoder_nano.sys_utils import detect_env
from autocoder_nano.utils.formatted_log_utils import save_formatted_log
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.agent.agentic_edit_tools import (  # Import specific resolvers
    BaseToolResolver,
    ExecuteCommandToolResolver, ReadFileToolResolver, WriteToFileToolResolver,
    ReplaceInFileToolResolver, SearchFilesToolResolver, ListFilesToolResolver,
    ListCodeDefinitionNamesToolResolver, AskFollowupQuestionToolResolver,
    AttemptCompletionToolResolver, PlanModeRespondToolResolver, ListPackageInfoToolResolver
)

printer = Printer()

TOOL_DISPLAY_MESSAGES: Dict[Type[BaseTool], Dict[str, str]] = {
    ReadFileTool: {
        "zh": "AutoCoder Nano 想要读取此文件：\n {{ path }}"
    },
    WriteToFileTool: {
        "zh": (
            "AutoCoder Nano 想要写入此文件：\n{{ path }} \n\n内容片段：\n{{ content_snippet }} {{ ellipsis }} "
        )
    },
    ReplaceInFileTool: {
        "zh": (
            "AutoCoder Nano 想要替换此文件中的内容：\n{{ path }} \n\n差异片段：\n{{ diff_snippet }}{{ ellipsis }}"
        )
    },
    ExecuteCommandTool: {
        "zh": (
            "AutoCoder Nano 想要执行此命令：\n{{ command }}\n(需要批准：{{ requires_approval }})"
        )
    },
    ListFilesTool: {
        "zh": (
            "AutoCoder Nano 想要列出此目录中的文件：\n{{ path }} {{ recursive_text }}"
        )
    },
    SearchFilesTool: {
        "zh": (
            "AutoCoder Nano 想要在此目录中搜索文件：\n{{ path }}\n文件模式: {{ file_pattern }}\n正则表达式：{{ regex }}"
        )
    },
    ListCodeDefinitionNamesTool: {
        "zh": "AutoCoder Nano 想要列出此路径中的定义：\n{{ path }}"
    },
    AskFollowupQuestionTool: {
        "zh": (
            "AutoCoder Nano 正在提问：\n{{ question }}\n{{ options_text }}"
        )
    },
}


def get_tool_display_message(tool: BaseTool, lang: str = "zh") -> str:
    """ Generates a user-friendly, internationalized string representation for a tool call. """
    tool_type = type(tool)

    if tool_type not in TOOL_DISPLAY_MESSAGES:
        # Fallback for unknown tools
        return f"Unknown tool type: {tool_type.__name__}\nData: {tool.model_dump_json(indent=2)}"

    templates = TOOL_DISPLAY_MESSAGES[tool_type]
    template = templates.get(lang, templates.get("en", "Tool display template not found"))  # Fallback to English

    # Prepare context specific to each tool type
    context = {}
    if isinstance(tool, ReadFileTool):
        context = {"path": tool.path}
    elif isinstance(tool, WriteToFileTool):
        snippet = tool.content[:150]
        context = {
            "path": tool.path, "content_snippet": snippet, "ellipsis": '...' if len(tool.content) > 150 else ''
        }
    elif isinstance(tool, ReplaceInFileTool):
        snippet = tool.diff
        context = {
            "path": tool.path, "diff_snippet": snippet, "ellipsis": ''
        }
    elif isinstance(tool, ExecuteCommandTool):
        context = {"command": tool.command, "requires_approval": tool.requires_approval}
    elif isinstance(tool, ListFilesTool):
        context = {"path": tool.path, "recursive_text": '（递归）' if tool.recursive else '（顶层）'}
    elif isinstance(tool, SearchFilesTool):
        context = {
            "path": tool.path, "file_pattern": tool.file_pattern or '*', "regex": tool.regex
        }
    elif isinstance(tool, ListCodeDefinitionNamesTool):
        context = {"path": tool.path}
    elif isinstance(tool, AskFollowupQuestionTool):
        options_text_zh = ""
        if tool.options:
            options_list_zh = "\n".join(
                [f"- {opt}" for opt in tool.options])  # Assuming options are simple enough not to need translation
            options_text_zh = f"选项：\n{options_list_zh}"
        context = {
            "question": tool.question, "options_text": options_text_zh
        }
    else:
        # Generic context for tools not specifically handled above
        context = tool.model_dump()

    try:
        return format_str_jinja2(template, **context)
    except Exception as e:
        # Fallback in case of formatting errors
        return f"Error formatting display for {tool_type.__name__}: {e}\nTemplate: {template}\nContext: {context}"


# Map Pydantic Tool Models to their Resolver Classes
TOOL_RESOLVER_MAP: Dict[Type[BaseTool], Type[BaseToolResolver]] = {
    ExecuteCommandTool: ExecuteCommandToolResolver,
    ReadFileTool: ReadFileToolResolver,
    WriteToFileTool: WriteToFileToolResolver,
    ReplaceInFileTool: ReplaceInFileToolResolver,
    SearchFilesTool: SearchFilesToolResolver,
    ListFilesTool: ListFilesToolResolver,
    ListCodeDefinitionNamesTool: ListCodeDefinitionNamesToolResolver,
    ListPackageInfoTool: ListPackageInfoToolResolver,
    AskFollowupQuestionTool: AskFollowupQuestionToolResolver,
    AttemptCompletionTool: AttemptCompletionToolResolver,  # Will stop the loop anyway
    PlanModeRespondTool: PlanModeRespondToolResolver
}


class AgenticEdit:
    def __init__(
            self, args: AutoCoderArgs, llm: AutoLLM, files: SourceCodeList, history_conversation: List[Dict[str, Any]]
    ):
        self.args = args
        self.llm = llm
        self.files = files
        self.history_conversation = history_conversation
        self.current_conversations = []

        self.shadow_manager = None

        # self.project_type_analyzer = ""
        # self.checkpoint_manager = FileChangeManager(
        #     project_dir=args.source_dir,
        #     backup_dir=os.path.join(args.source_dir, ".auto-coder", "checkpoint"),
        #     store_dir=os.path.join(args.source_dir, ".auto-coder", "checkpoint_store"),
        #     max_history=10
        # )
        # self.linter = ""
        # self.compiler = ""

        # 变更跟踪信息
        # 格式: { file_path: FileChangeEntry(...) }
        self.file_changes: Dict[str, FileChangeEntry] = {}

        try:
            tokenizer_path = resources.files("autocoder_nano").joinpath("data/tokenizer.json").__str__()
        except FileNotFoundError:
            tokenizer_path = None
        self.tokenizer_model = Tokenizer.from_file(tokenizer_path)

    def count_tokens(self, text: str) -> int:
        try:
            encoded = self.tokenizer_model.encode(text)
            v = len(encoded.ids)
            return v
        except Exception as e:
            return -1

    def record_file_change(
            self, file_path: str, change_type: str, diff: Optional[str] = None, content: Optional[str] = None
    ):
        """
        记录单个文件的变更信息。
        Args:
            file_path: 相对路径
            change_type: 'added' 或 'modified'
            diff: 对于 replace_in_file，传入 diff 内容
            content: 最新文件内容（可选，通常用于 write_to_file）
        """
        entry = self.file_changes.get(file_path)
        if entry is None:
            entry = FileChangeEntry(
                type=change_type, diffs=[], content=content)
            self.file_changes[file_path] = entry
        else:
            # 文件已经存在，可能之前是 added，现在又被 modified，或者多次 modified
            # 简单起见，type 用 added 优先，否则为 modified
            if entry.type != "added":
                entry.type = change_type

            # content 以最新为准
            if content is not None:
                entry.content = content

        if diff:
            entry.diffs.append(diff)

    def get_all_file_changes(self) -> Dict[str, FileChangeEntry]:
        """ 获取当前记录的所有文件变更信息 """
        return self.file_changes

    @prompt()
    def _analyze(self, request: AgenticEditRequest):
        """
        你是一位技术精湛的软件工程师，在众多编程语言、框架、设计模式和最佳实践方面拥有渊博知识。

        ====
        工具使用说明

        你可使用一系列工具，且需经用户批准才能执行。每条消息中仅能使用一个工具，用户回复中会包含该工具的执行结果。你要借助工具逐步完成给定任务，每个工具的使用都需依据前一个工具的使用结果。

        # 工具使用格式

        工具使用采用 XML 风格标签进行格式化。工具名称包含在开始和结束标签内，每个参数同样包含在各自的标签中。其结构如下：
        <tool_name>
        <parameter1_name>value1</parameter1_name>
        <parameter2_name>value2</parameter2_name>
        ...
        </tool_name>
        例如：
        <read_file>
        <path>src/main.js</path>
        </read_file>

        务必严格遵循此工具使用格式，以确保正确解析和执行。

        # 工具列表

        ## execute_command（执行命令）
        描述：请求在系统上执行 CLI 命令。当需要执行系统操作或运行特定命令来完成用户任务的任何步骤时使用此工具。你必须根据用户的系统调整命令，并清晰解释命令的作用。对于命令链，使用适合用户 shell 的链式语法。相较于创建可执行脚本，优先执行复杂的 CLI 命令，因为它们更灵活且易于运行。命令将在当前工作目录{{current_project}}中执行。
        参数：
        - command（必填）：要执行的 CLI 命令。该命令应适用于当前操作系统，且需正确格式化，不得包含任何有害指令。
        - requires_approval（必填）：一个布尔值，表示此命令在用户启用自动批准模式的情况下是否需要明确的用户批准。对于可能产生影响的操作，如安装/卸载软件包、删除/覆盖文件、系统配置更改、网络操作或任何可能产生意外副作用的命令，设置为 'true'；对于安全操作，如读取文件/目录、运行开发服务器、构建项目和其他非破坏性操作，设置为 'false'。
        用法：
        <execute_command>
        <command>需要运行的命令</command>
        <requires_approval>true 或 false</requires_approval>
        </execute_command>

        ## list_package_info（列出软件包信息）
        描述：请求检索有关源代码包的信息，如最近的更改或文档摘要，以更好地理解代码上下文。它接受一个目录路径（相对于当前项目的绝对或相对路径）。
        参数：
        - path（必填）：源代码包目录路径。
        用法：
        <list_package_info>
        <path>相对或绝对的软件包路径</path>
        </list_package_info>

        ## read_file（读取文件）
        描述：请求读取指定路径文件的内容。当需要检查现有文件的内容（例如分析代码、查看文本文件或从配置文件中提取信息）且不知道文件内容时使用此工具。它可自动从 PDF 和 DOCX 文件中提取纯文本，可能不适用于其他类型的二进制文件，因为它会将原始内容作为字符串返回。
        参数：
        - path（必填）：要读取的文件路径（相对于当前工作目录{{ current_project }}）。
        用法：
        <read_file>
        <path>文件路径在此</path>
        </read_file>

        write_to_file（写入文件）
        描述：请求将内容写入指定路径的文件。如果文件存在，将用提供的内容覆盖；如果文件不存在，将创建该文件。此工具会自动创建写入文件所需的任何目录。
        参数：
        - path（必填）：要写入的文件路径（相对于当前工作目录{{ current_project }}）。
        - content（必填）：要写入文件的内容。必须提供文件的完整预期内容，不得有任何截断或遗漏，必须包含文件的所有部分，即使它们未被修改。
        用法：
        <write_to_file>
        <path>文件路径在此</path>
        <content>
            你的文件内容在此
        </content>
        </write_to_file>

        ## replace_in_file（替换文件内容）
        描述：请求使用定义对文件特定部分进行精确更改的 SEARCH/REPLACE 块来替换现有文件中的部分内容。此工具应用于需要对文件特定部分进行有针对性更改的情况。
        参数：
        - path（必填）：要修改的文件路径（相对于当前工作目录{{ current_project }}）。
        - diff（必填）：一个或多个遵循以下精确格式的 SEARCH/REPLACE 块：
        ```
        <<<<<<< SEARCH
        [exact content to find]
        =======
        [new content to replace with]
        >>>>>>> REPLACE
        ```
        关键规则：
        1. SEARCH 内容必须与关联的文件部分完全匹配：
            * 逐字符匹配，包括空格、缩进、行尾符。
            * 包含所有注释、文档字符串等。
        2. SEARCH/REPLACE 块仅替换第一个匹配项：
            * 如果需要进行多次更改，需包含多个唯一的 SEARCH/REPLACE 块。
            * 每个块的 SEARCH 部分应包含足够的行，以唯一匹配需要更改的每组行。
            * 使用多个 SEARCH/REPLACE 块时，按它们在文件中出现的顺序列出。
        3. 保持 SEARCH/REPLACE 块简洁：
            * 将大型 SEARCH/REPLACE 块分解为一系列较小的块，每个块更改文件的一小部分。
            * 仅包含更改的行，必要时包含一些周围的行以确保唯一性。
            * 不要在 SEARCH/REPLACE 块中包含长段未更改的行。
            * 每行必须完整，切勿在中途截断行，否则可能导致匹配失败。
        4. 特殊操作：
            * 移动代码：使用两个 SEARCH/REPLACE 块（一个从原始位置删除，一个插入到新位置）。
            * 删除代码：使用空的 REPLACE 部分。
        用法：
        <replace_in_file>
        <path>File path here</path>
        <diff>
        Search and replace blocks here
        </diff>
        </replace_in_file>

        ## search_files（搜索文件）
        描述：请求在指定目录的文件中执行正则表达式搜索，提供富含上下文的结果。此工具在多个文件中搜索模式或特定内容，并显示每个匹配项及其周围的上下文。
        参数：
        - path（必填）：要搜索的目录路径（相对于当前工作目录{{ current_project }}），该目录将被递归搜索。
        - regex（必填）：要搜索的正则表达式模式，使用 Rust 正则表达式语法。
        - file_pattern（可选）：用于过滤文件的 Glob 模式（例如，'.ts' 表示 TypeScript 文件），若未提供，则搜索所有文件（*）。
        用法：
        <search_files>
        <path>Directory path here</path>
        <regex>Your regex pattern here</regex>
        <file_pattern>file pattern here (optional)</file_pattern>
        </search_files>

        ## list_files（列出文件）
        描述：请求列出指定目录中的文件和目录。如果 recursive 为 true，将递归列出所有文件和目录；如果 recursive 为 false 或未提供，仅列出顶级内容。请勿使用此工具确认你可能已创建的文件的存在，因为用户会告知你文件是否成功创建。
        参数：
        - path（必填）：要列出内容的目录路径（相对于当前工作目录{{ current_project }}）。
        - recursive（可选）：是否递归列出文件，true 表示递归列出，false 或省略表示仅列出顶级内容。
        用法：
        <list_files>
        <path>Directory path here</path>
        <recursive>true or false (optional)</recursive>
        </list_files>

        ## list_code_definition_names（列出代码定义名称）
        描述：请求列出指定目录顶级源文件中的定义名称（类、函数、方法等）。此工具提供对代码库结构和重要构造的洞察，概括对于理解整体架构至关重要的高级概念和关系。
        参数：
        - path（必填）：要列出顶级源代码定义的目录路径（相对于当前工作目录{{ current_project }}）。
        用法：
        <list_code_definition_names>
        <path>Directory path here</path>
        </list_code_definition_names>

        ask_followup_question（提出后续问题）
        描述：向用户提出问题以收集完成任务所需的额外信息。当遇到歧义、需要澄清或需要更多细节以有效推进时使用此工具。它通过与用户直接沟通实现交互式问题解决，应明智使用，以在收集必要信息和避免过多来回沟通之间取得平衡。
        参数：
        - question（必填）：要问用户的问题，应清晰、具体，针对所需信息。
        - options（可选）：用户可选择的 2-5 个选项的数组，每个选项应为描述可能答案的字符串。并非总是需要提供选项，但在许多情况下有助于避免用户手动输入响应。重要提示：切勿包含切换到 Act 模式的选项，因为这需要用户自行手动操作（如有需要）。
        用法：
        <ask_followup_question>
        <question>Your question here</question>
        <options>
        Array of options here (optional), e.g. ["Option 1", "Option 2", "Option 3"]
        </options>
        </ask_followup_question>

        ## attempt_completion（尝试完成任务）
        描述：每次工具使用后，用户会回复该工具使用的结果，即是否成功以及失败原因（如有）。一旦收到工具使用结果并确认任务完成，使用此工具向用户展示工作成果。可选地，你可以提供一个 CLI 命令来展示工作成果。用户可能会提供反馈，你可据此进行改进并再次尝试。
        重要提示：在确认用户已确认之前的工具使用成功之前，不得使用此工具。否则将导致代码损坏和系统故障。在使用此工具之前，必须在<thinking></thinking>标签中自问是否已从用户处确认之前的工具使用成功。如果没有，则不要使用此工具。
        参数：
        - result（必填）：任务的结果，应以最终形式表述，无需用户进一步输入，不得在结果结尾提出问题或提供进一步帮助。
        - command（可选）：用于向用户演示结果的 CLI 命令。例如，使用open index.html显示创建的网站，或使用open localhost:3000显示本地运行的开发服务器，但不要使用像echo或cat这样仅打印文本的命令。该命令应适用于当前操作系统，且需正确格式化，不得包含任何有害指令。
        用法：
        <attempt_completion>
        <result>
        Your final result description here
        </result>
        <command>Command to demonstrate result (optional)</command>
        </attempt_completion>

        # 工具使用示例

        ## 示例 1：请求执行命令
        <execute_command>
        <command>npm run dev</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        ## 示例 2：请求创建新文件
        <write_to_file>
        <path>src/frontend-config.json</path>
        <content>
        {
        "apiEndpoint": "https://api.example.com",
        "theme": {
            "primaryColor": "#007bff",
            "secondaryColor": "#6c757d",
            "fontFamily": "Arial, sans-serif"
        },
        "features": {
            "darkMode": true,
            "notifications": true,
            "analytics": false
        },
        "version": "1.0.0"
        }
        </content>
        </write_to_file>

        ## 示例 3：请求对文件进行有针对性的编辑
        <replace_in_file>
        <path>src/components/App.tsx</path>
        <diff>
        <<<<<<< SEARCH
        import React from 'react';
        =======
        import React, { useState } from 'react';
        >>>>>>> REPLACE

        <<<<<<< SEARCH
        function handleSubmit() {
        saveData();
        setLoading(false);
        }

        =======
        >>>>>>> REPLACE

        <<<<<<< SEARCH
        return (
        <div>
        =======
        function handleSubmit() {
        saveData();
        setLoading(false);
        }

        return (
        <div>
        >>>>>>> REPLACE
        </diff>
        </replace_in_file>

        # 工具使用指南
        0. 始终以全面搜索和探索开始：在进行任何代码更改之前，使用搜索工具（list_files、grep 命令）充分了解代码库的结构、现有模式和依赖关系，这有助于防止错误并确保你的更改符合项目约定。
        1. 在<thinking>标签中，评估你已有的信息和继续完成任务所需的信息。
        2. 根据任务和工具描述选择最合适的工具，评估是否需要其他信息来推进，并确定可用工具中哪个最适合收集这些信息。例如，使用 list_files 工具比在终端中运行类似ls的命令更有效。关键是要思考每个可用工具，并使用最适合任务当前步骤的工具。
        3. 如果需要多个操作，每条消息使用一个工具，以迭代方式完成任务，每个工具的使用都基于前一个工具的使用结果，切勿假设任何工具使用的结果，每个步骤都必须以前一步骤的结果为依据。
        4. 使用为每个工具指定的 XML 格式来制定工具使用方式。
        5. 每次工具使用后，用户会回复该工具使用的结果，该结果将为你提供继续任务或做出进一步决策所需的信息，可能包括：
            * 工具是否成功的信息，以及失败原因（如有）。
            * 可能因更改而产生的 linter 错误，你需要解决这些错误。
            * 对更改做出反应的新终端输出，你可能需要考虑或采取行动。
            * 与工具使用相关的任何其他相关反馈或信息。
        6. 每次工具使用后务必等待用户确认，切勿在未获得用户对结果的明确确认前假设工具使用成功。

        务必逐步推进，在每次工具使用后等待用户的消息再继续任务，这种方法使你能够：
        1. 确认每个步骤成功后再继续。
        2. 立即解决出现的任何问题或错误。
        3. 根据新信息或意外结果调整方法。
        4. 确保每个操作正确建立在前一个操作的基础上。

        通过等待并仔细考虑用户在每次工具使用后的回复，你可以做出相应反应，并就是否继续任务做出明智决策，这种迭代过程有助于确保工作的整体成功和准确性。

        ===

        文件搜索

        **这是你的核心方法** - 以下先搜索的方法并非可选，而是进行可靠代码工作的必要条件。每个代码任务都应遵循这种系统的探索模式。
        本指南为 AI 代理和开发人员提供了一种有效搜索、理解和修改代码库的系统方法，强调彻底的预编码调查和后编码验证，以确保可靠和可维护的更改。
        该方法将多个搜索工具（grep、list_files、read_file）与结构化工作流程相结合，以最大限度地减少代码错误，确保全面理解，系统地验证更改，并遵循已建立的项目模式。

        # list_files（列出文件）
        ## 目的：
        - 发现项目结构并了解目录组织；
        - 在深入研究之前获取可用文件和文件夹的概述。
        ## 使用时机：
        - 初始项目探索以了解代码库布局；
        - 识别关键目录，如src/、lib/、components/、utils/；
        - 定位配置文件，如package.json、tsconfig.json、Makefile；
        - 在使用更有针对性的搜索工具之前。
        ## 优点：
        - 快速提供项目概述，不会带来过多细节；
        - 帮助规划在特定目录中的目标搜索；
        - 不熟悉代码库时的必要第一步。

        # grep（Shell 命令）
        ## 目的：
        - 在多个文件中查找确切的文本匹配和模式；
        - 执行输出开销最小的精确搜索；
        - 验证代码更改并确认实现。

        ## 使用时机：
        - 预编码上下文收集：查找符号、函数、导入和使用模式。
        - 后编码验证：确认更改已正确应用，且没有过时的引用残留。
        - 模式分析：了解编码约定和现有实现。

        ## 关键命令模式：
        - 预编码上下文示例：
        <execute_command>
        <command>grep -l "className" src/ | head -5</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -rc "import.*React" src/ | grep -v ":0"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -Rn "function.*MyFunction\|const.*MyFunction" . | head -10</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -R --exclude-dir={node_modules,dist,build,.git} "TODO" .</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 后编码验证示例：

        <execute_command>
        <command>ls -la newfile.js 2>/dev/null && echo "File created" || echo "File not found"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -Rn "oldName" . || echo "✓ No stale references found"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -c "newName" src/*.js | grep -v ":0" || echo "⚠ New references not found"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -Rn "import.*newModule\|export.*newFunction" . | wc -l</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        ## 输出优化技巧：
        - 使用-l仅获取文件名。
        - 使用-c仅获取计数。
        - 使用| head -N限制行数。
        - 使用| wc -l获取总数。
        - 使用2>/dev/null抑制错误。
        - 与|| echo结合使用以显示清晰的状态消息。

        # search_files（备用）

        ## 目的：
        - 当无法使用 grep 命令时的替代搜索方法；
        - 用于在代码库中进行更广泛、不太精确的搜索的语义搜索功能；
        - 作为 grep 的补充，用于全面的代码发现。

        ## 使用时机：
        - 当 shell 访问受限或 grep 不可用时；
        - 需要在代码库中进行更广泛、不太精确的搜索时；
        - 作为 grep 的补充，用于全面的代码发现。

        # read_file（读取文件）

        ## 目的：
        - 详细检查完整的文件内容；
        - 理解上下文、模式和实现细节。

        ## 使用时机：
        - 通过 list_files 或 grep 确定目标文件后；
        - 了解函数签名、接口和契约时；
        - 分析使用模式和项目约定时；
        - 进行更改前需要详细检查代码时。

        ## 重要注意事项：
        - 在缩小目标文件范围后策略性地使用；
        - 进行代码修改前了解上下文的必要步骤；
        - 有助于识别依赖关系和潜在的副作用。

        # 选择正确的搜索策略
        - 首先使用 list_files了解项目结构。
        - 需要查找特定内容时使用 grep。
        - 需要检查特定文件的详细信息时使用 read_file。
        - 结合多种方法以全面理解。

        ## 默认工作流程：
        - list_files → 了解结构。
        - grep → 查找特定模式 / 符号。
        - read_file → 检查细节。
        - 实施更改。
        - grep → 验证更改。

        # 综合工作流程

        ## 阶段 1：项目发现与分析

        **项目结构概述**
        <execute_command>
        <command>ls -la</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 使用 list_files 工具了解目录结构。
        - 识别关键目录：src/、lib/、components/、utils/。
        - 查找配置文件：package.json、tsconfig.json、Makefile。

        **技术栈识别**
        <execute_command>
        <command>grep -E "(import|require|from).*['\"]" src/ | head -20</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 检查软件包依赖项和导入。
        - 识别框架、库和编码模式。
        - 了解项目约定（命名、文件组织）。

        ## 阶段 2：上下文代码调查

        **符号和模式搜索**
        <execute_command>
        <command>grep -Rn "targetFunction|targetClass" . --exclude-dir={node_modules,dist}</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        **使用模式分析**
        - 使用 read_file 详细检查关键文件。
        - 了解函数签名、接口和契约。
        - 检查错误处理模式和边缘情况。

        **依赖关系映射**
        <execute_command>
        <command>grep -Rn "import.*targetModule" . | grep -v test</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        ## 阶段 3：实施计划

        **影响评估**
        - 识别所有需要修改的文件。
        - 规划向后兼容性注意事项。
        - 考虑潜在的副作用。

        **测试策略**
        <execute_command>
        <command>find . -name "*test*" -o -name "*spec*" | head -10</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 查找现有的测试以供参考。
        - 必要时规划新的测试用例。

        ## 阶段 4：代码实现

        更多细节请参考 “文件编辑” 部分。

        ## 阶段 5：全面验证

        **文件系统验证**
        <execute_command>
        <command>ls -la newfile.* 2>/dev/null || echo "Expected new files not found"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        **代码集成验证**
        <execute_command>
        <command>grep -Rn "oldSymbol" . --exclude-dir={node_modules,dist} || echo "✓ No stale references"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -Rn "oldSymbol" . --exclude-dir={node_modules,dist} || echo "✓ No stale references"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        **功能验证**
        <execute_command>
        <command>npm run lint 2>/dev/null || echo "Linting not configured"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>npm test 2>/dev/null || echo "Testing not configured"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>npm run build 2>/dev/null || echo "Build not configured"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        **文档和注释**
        - 验证新函数 / 类是否有适当的文档。
        - 检查复杂逻辑是否有解释性注释。
        - 确保 README 或其他文档在需要时已更新。

        ## 阶段 6：质量保证

        **性能考虑**
        - 检查潜在的性能影响。
        - 验证内存使用模式。
        - 考虑可伸缩性影响。

        **安全审查**
        - 查找潜在的安全漏洞。
        - 验证输入验证和清理。
        - 检查适当的错误处理。

        **最终集成检查**
        <execute_command>
        <command>grep -Rn "TODO\|FIXME\|XXX" . --exclude-dir={node_modules,dist} | wc -l</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        # 最佳实践

        - 迭代方法：不要试图一次性理解所有内容，逐步积累知识。
        - 文档优先：在深入研究代码之前，阅读现有的文档、注释和 README 文件。
        - 小步骤：进行增量更改并验证每个步骤。
        - 做好回滚准备：始终知道如何撤销更改（如果出现问题）。
        - 尽早测试：在开发过程中频繁运行测试，而不仅仅是在最后。
        - 模式一致性：遵循已建立的项目模式，而不是引入新的模式。

        通过遵循这种全面的方法，你可以确保对所有代码更改的全面理解、可靠实现和稳健验证。

        =====

        文件编辑 EDITING FILES

        在应用以下编辑技术之前，请确保你已按照 “文件搜索” 方法充分了解代码库的上下文。
        你可以使用两个工具来处理文件：write_to_file和replace_in_file。了解它们的角色并为工作选择合适的工具将有助于确保高效和准确的修改。

        # write_to_file（写入文件）

        ## 目的：
        - 创建新文件或覆盖现有文件的全部内容。

        ## 使用时机：
        - 初始文件创建，如搭建新项目时；
        - 覆盖大型样板文件，需要一次性替换全部内容时；
        - 当更改的复杂性或数量使 replace_in_file 难以处理或容易出错时；
        - 当需要完全重构文件的内容或更改其基本组织时。

        ## 重要注意事项：
        - 使用 write_to_file 需要提供文件的完整最终内容；
        - 如果只需要对现有文件进行小的更改，考虑使用 replace_in_file，以避免不必要地重写整个文件；
        - 虽然 write_to_file 不应是你的默认选择，但在情况确实需要时不要犹豫使用它。

        # replace_in_file（替换文件内容）

        ## 目的：
        - 对现有文件的特定部分进行有针对性的编辑，而不覆盖整个文件。

        ## 使用时机：
        - 进行小的、局部的更改，如更新几行代码、函数实现、更改变量名、修改文本部分等；
        - 有针对性的改进，只需要更改文件内容的特定部分；
        - 特别适用于长文件，其中大部分内容将保持不变。

        ## 优点：
        - 对于较小的编辑更高效，因为不需要提供整个文件内容；
        - 减少覆盖大型文件时可能出现的错误机会。

        # 选择合适的工具
        - 大多数更改默认使用 replace_in_file，它是更安全、更精确的选择，可最大限度地减少潜在问题。
        - 使用 write_to_file的情况：
            * 创建新文件。
            * 更改非常广泛，使用 replace_in_file 会更复杂或更危险。
            * 需要完全重组或重构文件。
            * 文件相对较小，更改影响其大部分内容。
            * 生成样板文件或模板文件。

        # 自动格式化注意事项
        - 使用 write_to_file 或 replace_in_file 后，用户的编辑器可能会自动格式化文件。
        - 这种自动格式化可能会修改文件内容，例如：
            * 将单行拆分为多行。
            * 调整缩进以匹配项目样式（如 2 个空格、4 个空格或制表符）。
            * 将单引号转换为双引号（或根据项目首选项反之亦然）。
            * 组织导入（如排序、按类型分组）。
            * 在对象和数组中添加 / 删除尾随逗号。
            * 强制一致的大括号样式（如同一行或新行）。
            * 标准化分号用法（根据样式添加或删除）。
            * write_to_file 和 replace_in_file 工具响应将包含自动格式化后的文件最终状态。
            * 将此最终状态用作任何后续编辑的参考点，这在为 replace_in_file 制作 SEARCH 块时尤其重要，因为需要内容与文件中的内容完全匹配。

        # 工作流程提示
        1. 编辑前，评估更改的范围并决定使用哪个工具。
        2. 对于有针对性的编辑，应用带有精心制作的 SEARCH/REPLACE 块的 replace_in_file。如果需要多次更改，可以在单个 replace_in_file 调用中堆叠多个 SEARCH/REPLACE 块。
        3. 对于重大修改或初始文件创建，依赖 write_to_file。
        4. 一旦使用 write_to_file 或 replace_in_file 编辑了文件，系统将为你提供修改后文件的最终状态。将此更新后的内容用作任何后续 SEARCH/REPLACE 操作的参考点，因为它反映了任何自动格式化或用户应用的更改。

        通过谨慎选择 write_to_file 和 replace_in_file，你可以使文件编辑过程更流畅、更安全、更高效。

        =====

        软件包上下文信息 PACKAGE CONTEXT INFORMATION

        # 理解目录上下文

        ## 目的：
        - 项目中的每个目录（尤其是源代码目录）都有隐式的上下文信息，包括最近的更改、重要文件及其用途。

        ## 访问目录上下文：
        - 使用list_package_info工具查看特定目录的此信息；
        - 不要使用其他工具（如 list_files）查看此专门的上下文信息。

        ## 使用时机：
        - 需要了解目录中最近发生的更改时；
        - 需要深入了解目录的目的和组织时；
        - 在使用其他工具进行详细文件探索之前。

        ## 示例：
        <list_package_info>
        <path>src/some/directory</path>
        </list_package_info>

        # 好处

        - 快速识别可能与你的任务相关的最近修改的文件。
        - 提供目录内容和目的的高级理解。
        - 帮助确定使用 read_file、shell 命令或 list_code_definition_names 等工具详细检查哪些文件的优先级。

        =====

        # 功能 CAPABILITIES

        - 先搜索和理解：你的主要优势在于在进行更改之前系统地探索和理解代码库。使用 list_files、execute_command（grep）来映射项目结构、识别模式和理解依赖关系，这种先探索的方法对于可靠的代码修改至关重要。
        - 你可以使用允许你在用户的计算机上执行 CLI 命令、列出文件、查看源代码定义、正则表达式搜索、读取和编辑文件以及提出后续问题的工具。这些工具可帮助你有效地完成广泛的任务，如编写代码、对现有文件进行编辑或改进、了解项目的当前状态、执行系统操作等。
        - 当用户最初给你一个任务时，环境详细信息中将包含当前工作目录 {{current_project}} 中所有文件路径的递归列表。这提供了项目文件结构的概述，从目录 / 文件名（开发人员如何概念化和组织他们的代码）和文件扩展名（使用的语言）中提供关键见解，这也可以指导关于进一步探索哪些文件的决策。如果你需要进一步探索当前工作目录之外的目录，如桌面，你可以使用 list_files 工具。如果为 recursive 参数传递 'true'，它将递归列出文件，否则，它将列出顶级文件，这更适合通用目录，如桌面，你不一定需要嵌套结构。
        - 你可以使用 shell_command (grep) 在指定目录的文件中执行正则表达式搜索，输出包含周围行的富含上下文的结果，这对于理解代码模式、查找特定实现或识别需要重构的区域特别有用。
        - 你可以使用 list_code_definition_names 工具获取指定目录顶级所有文件的源代码定义概述，这在需要了解更广泛的上下文和某些代码部分之间的关系时特别有用。你可能需要多次调用此工具来了解与任务相关的代码库的各个部分。例如，当被要求进行编辑或改进时，你可以分析初始环境详细信息中的文件结构以获取项目概述，然后使用 list_code_definition_names 使用位于相关目录中的文件的源代码定义来获取进一步的见解，然后使用 read_file 检查相关文件的内容，分析代码并提出改进建议或进行必要的编辑，然后使用 replace_in_file 工具实施更改。如果你重构了可能影响代码库其他部分的代码，你可以使用 shell 命令 (grep) 来确保根据需要更新其他文件。
        - 你可以使用 execute_command 工具在用户的计算机上运行命令，只要你认为这有助于完成用户的任务。当你需要执行 CLI 命令时，你必须清楚地解释命令的作用。相对于创建可执行脚本，优先执行复杂的 CLI 命令，因为它们更灵活且易于运行。允许交互式和长时间运行的命令，因为命令在用户的 VSCode 终端中运行。用户可能会在后台保持命令运行，你会一路收到它们的状态更新。你执行的每个命令都在新的终端实例中运行。

        =====

        # 规则 RULES

        - 你当前的工作目录是：{{current_project}}
        - 编辑前必须搜索：在编辑任何文件之前，你必须首先搜索以了解其上下文、依赖关系和使用模式。使用 list_files 或 grep 命令查找相关代码、导入和引用。
        - 通过搜索验证：进行更改后，使用 list_files 或 grep 命令验证是否没有过时的引用残留，并且新代码是否与现有模式正确集成。
        - 你不能cd到不同的目录来完成任务，你只能在{{ current_project }}中操作，因此在使用需要路径的工具时，请确保传递正确的 'path' 参数。
        - 不要使用 ~ 字符或 $HOME 来引用主目录。
        - 在使用 execute_command 工具之前，你必须首先考虑提供的系统信息上下文，以了解用户的环境，并调整你的命令以确保它们与用户的系统兼容。你还必须考虑是否需要在当前工作目录 {{current_project}} 之外的特定目录中执行命令，如果是这样，需在命令前加上cd到该目录 && 然后执行命令（作为一个命令，因为你只能在 {{current_project}} 中操作）。例如，如果你需要在 {{current_project}} 之外的项目中运行npm install，你需要在前面加上cd，即此命令的伪代码为cd (项目路径) && (命令，在这种情况下为npm install)。
        - 使用 shell 命令工具（grep）时，仔细设计正则表达式模式以平衡特异性和灵活性。根据用户的任务，你可以使用它来查找代码模式、注释、待办事项、函数定义或项目中的任何基于文本的信息。结果包括上下文，因此分析周围的代码以更好地理解匹配项。将 shell 命令工具 (grep) 与其他工具结合使用以进行更全面的分析。例如，使用它查找特定的代码模式，然后使用 read_file 检查有趣匹配项的完整上下文，然后再使用 replace_in_file 进行明智的更改。
        - 创建新项目（如应用程序、网站或任何软件项目）时，除非用户另有说明，否则将所有新文件组织在专用项目目录中。创建文件时使用适当的文件路径，因为 write_to_file 工具会自动创建任何必要的目录。根据项目的特定类型，逻辑地构建项目结构，遵循最佳实践。除非另有说明，新项目应无需额外设置即可轻松运行，例如大多数项目可以使用 HTML、CSS 和 JavaScript 构建 - 你可以在浏览器中打开。
        - 确定适当的结构和要包含的文件时，一定要考虑项目的类型（如 Python、JavaScript、Web 应用程序）。还可以考虑哪些文件可能与完成任务最相关，例如查看项目的清单文件将帮助你了解项目的依赖关系，你可以将其纳入你编写的任何代码中。
        - 对代码进行更改时，始终考虑代码使用的上下文。确保你的更改与现有代码库兼容，并遵循项目的编码标准和最佳实践。
        - 当你想修改文件时，直接使用 replace_in_file 或 write_to_file 工具进行所需的更改，无需在使用工具前显示更改。
        - 不要询问不必要的信息。使用提供的工具高效有效地完成用户的请求。完成任务后，必须使用 attempt_completion 工具向用户展示结果。用户可能会提供反馈，你可以利用反馈进行改进并再次尝试。
        - 你只能使用 ask_followup_question 工具向用户提问。仅当需要额外的细节来完成任务时使用此工具，并且一定要提出清晰简洁的问题，帮助你推进任务。但是，如果你可以使用可用工具避免向用户提问，你应该这样做。例如，如果用户提到一个可能在桌面等外部目录中的文件，你应该使用 list_files 工具列出桌面中的文件，并检查用户提到的文件是否在其中，而不是要求用户自己提供文件路径。
        - 执行命令时，如果没有看到预期的输出，假设终端成功执行了命令并继续执行任务。用户的终端可能无法正确流式传输输出。如果你绝对需要查看实际的终端输出，请使用 ask_followup_question 工具请求用户将其复制并粘贴回给你。
        - 用户可能会在其消息中直接提供文件的内容，在这种情况下，你不应使用 read_file 工具再次获取文件内容，因为你已经拥有它。
        - 你的目标是尝试完成用户的任务，而不是进行来回对话。
        - 切勿以 “Great”、“Certainly”、“Okay”、“Sure” 等词开头你的消息，你的回复不应是对话式的，而应直接切中要点。例如，你不应说 “Great, I've updated the CSS”，而应说 “I've updated the CSS”。重要的是你在消息中要清晰和专业。
        - 当呈现图像时，利用你的视觉能力彻底检查它们并提取有意义的信息。在完成用户的任务时，将这些见解纳入你的思维过程。
        - 在每条用户消息的末尾，你将自动收到 environment_details。此信息不是由用户自己编写的，而是自动生成的，以提供有关项目结构和环境的潜在相关上下文。虽然此信息对于理解项目上下文可能很有价值，但不要将其视为用户请求或响应的直接部分。使用它来为你的操作和决策提供信息，但不要假设用户明确询问或提及此信息，除非他们在消息中明确这样做。使用 environment_details 时，清楚地解释你的操作，以确保用户理解，因为他们可能不知道这些细节。
        - 执行命令前，检查 environment_details 中的 “Actively Running Terminals” 部分。如果存在，考虑这些活动进程可能如何影响你的任务。例如，如果已经在运行本地开发服务器，你无需再次启动它。如果未列出活动终端，正常继续执行命令。
        - 使用 replace_in_file 工具时，你必须在 SEARCH 块中包含完整的行，而不是部分行。系统需要精确的行匹配，无法匹配部分行。例如，如果你想匹配包含 “const x = 5;” 的行，你的 SEARCH 块必须包含整行，而不仅仅是 “x = 5” 或其他片段。
        - 使用 replace_in_file 工具时，如果使用多个 SEARCH/REPLACE 块，请按它们在文件中出现的顺序列出。例如，如果需要对第 10 行和第 50 行进行更改，首先包含第 10 行的 SEARCH/REPLACE 块，然后是第 50 行的 SEARCH/REPLACE 块。
        - 至关重要的是，你要在每次工具使用后等待用户的响应，以确认工具使用成功。例如，如果要求制作待办事项应用程序，你将创建一个文件，等待用户响应它已成功创建，然后在需要时创建另一个文件，等待用户响应它已成功创建，等等。
        - 要显示 LaTeX 公式，使用单个美元符号包裹行内公式，如$E=mc^2$，使用双美元符号包裹块级公式，如$$\frac{d}{dx}e^x = e^x$$。
        - 要包含流程图或图表，你可以使用 Mermaid 语法。
        - 如果你遇到一些未知或不熟悉的概念或术语，或者用户在提问，你可以尝试使用适当的 MCP 或 RAG 服务来获取信息。


        =====

        {% if extra_docs %}
        用户提供的规则或文档 RULES OR  DOCUMENTS PROVIDED BY USER
        以下规则由用户提供，你必须严格遵守。
        <user_rule_or_document_files>
        {% for key, value in extra_docs.items() %}
        <user_rule_or_document_file>
        ##File: {{ key }}
        {{ value }}
        </user_rule_or_document_file>
        {% endfor %}
        </user_rule_or_document_files>
        确保你始终通过使用 read_file 工具根据用户的具体要求获取 index.md 中列出的相关 RULE 文件来开始你的任务。
        {% endif %}

        =====

        {% if file_paths_str %}

        用户提到的文件 FILES MENTIONED BY USER

        以下是用户提到的文件或目录。
        确保你始终通过使用 read_file 工具获取文件的内容或使用 list_files 工具列出提到的目录中包含的文件来开始你的任务。
        如果是目录，请使用 list_files 查看它包含哪些文件，并根据需要使用 read_file 读取文件。如果是文件，请使用 read_file 读取文件。

        <files>
        {{file_paths_str}}
        </files>
        {% endif %}

        =====

        系统信息 SYSTEM INFORMATION

        操作系统：{{os_distribution}}
        默认 Shell：{{shell_type}}
        主目录：{{home_dir}}
        当前工作目录：{{current_project}}

        ====

        目标 OBJECTIVE

        你以迭代方式完成给定任务，将其分解为清晰的步骤并系统地完成它们。

        1. 分析用户的任务并设定明确、可实现的目标以完成它，按逻辑顺序对这些目标进行优先排序。
        2. 按顺序处理这些目标，根据需要一次使用一个可用工具。每个目标应对应你解决问题过程中的一个不同步骤。你会在进行过程中了解已完成的工作和剩余的工作。
        3. 记住，你拥有广泛的能力，可以根据需要以强大和巧妙的方式使用各种工具来完成每个目标。在调用工具之前，在<thinking></thinking>标签中进行一些分析。首先，分析环境详细信息中提供的文件结构，以获取上下文和有效推进的见解。然后，思考哪个提供的工具是完成用户任务最相关的工具。接下来，仔细检查相关工具的每个所需参数，并确定用户是否已直接提供或给出足够的信息来推断一个值。在决定参数是否可以推断时，仔细考虑所有上下文，看看它是否支持特定的值。如果所有必填参数都存在或可以合理推断，关闭思考标签并继续使用工具。但是，如果缺少必填参数的值，不要调用工具（甚至不要使用填充符填充缺失的参数），而是使用 ask_followup_question 工具要求用户提供缺失的参数。如果未提供可选参数的信息，不要询问。
        4. 完成用户的任务后，你必须使用 attempt_completion 工具向用户展示任务的结果。你也可以提供一个 CLI 命令来展示你的任务结果；这在 Web 开发任务中特别有用，你可以运行例如open index.html来显示你构建的网站。
        5. 用户可能会提供反馈，你可以利用反馈进行改进并再次尝试。但不要进行无意义的来回对话，即不要在回复结尾提出问题或提供进一步帮助。
        6. 按顺序处理这些目标，始终以使用可用工具进行全面搜索和探索开始。对于任何与代码相关的任务，首先使用 list_files 了解结构，然后使用命令 (grep) 查找相关模式，并在进行更改前使用 read_file 检查上下文。
        """
        env_info = detect_env()
        shell_type = "bash"
        if not env_info.has_bash:
            shell_type = "cmd/powershell"
        file_paths_str = "\n".join([file_source.module_name for file_source in self.files.sources])
        # extra_docs = get_required_and_index_rules()
        return {
            "current_project": os.path.abspath(self.args.source_dir),
            "home_dir": env_info.home_dir,
            "os_distribution": env_info.os_name,
            "shell_type": shell_type,
            "extra_docs": "",
            "file_paths_str": file_paths_str
        }

    @staticmethod
    def _reconstruct_tool_xml(tool: BaseTool) -> str:
        """
        Reconstructs the XML representation of a tool call from its Pydantic model.
        """
        tool_tag = next((tag for tag, model in TOOL_MODEL_MAP.items() if isinstance(tool, model)), None)
        if not tool_tag:
            printer.print_text(f"找不到工具类型 {type(tool).__name__} 对应的标签名", style="red")
            return f"<error>Could not find tag for tool {type(tool).__name__}</error>"

        xml_parts = [f"<{tool_tag}>"]
        for field_name, field_value in tool.model_dump(exclude_none=True).items():
            # 根据类型格式化值，确保XML安全性
            if isinstance(field_value, bool):
                value_str = str(field_value).lower()
            elif isinstance(field_value, (list, dict)):
                # 目前对列表/字典使用简单字符串表示
                # 如果需要且提示/LLM支持，可考虑在标签内使用JSON
                # 对结构化数据使用JSON
                value_str = json.dumps(field_value, ensure_ascii=False)
            else:
                value_str = str(field_value)

            # 对值内容进行转义
            escaped_value = xml.sax.saxutils.escape(value_str)

            # 处理多行内容（如'content'或'diff'）- 确保保留换行符
            if '\n' in value_str:
                # 如果内容跨越多行，在闭合标签前添加换行符以提高可读性
                xml_parts.append(
                    f"<{field_name}>\n{escaped_value}\n</{field_name}>")
            else:
                xml_parts.append(
                    f"<{field_name}>{escaped_value}</{field_name}>")
        xml_parts.append(f"</{tool_tag}>")
        # 使用换行符连接以提高可读性，与提示示例保持一致
        return "\n".join(xml_parts)

    def analyze(
            self, request: AgenticEditRequest
    ) -> Generator[Union[LLMOutputEvent, LLMThinkingEvent, ToolCallEvent, ToolResultEvent, CompletionEvent, ErrorEvent,
                         WindowLengthChangeEvent, TokenUsageEvent, PlanModeRespondEvent] | None, None, None]:

        system_prompt = self._analyze.prompt(request)
        printer.print_key_value(
            {"长度(tokens)": f"{len(system_prompt)}"}, title="系统提示词"
        )

        conversations = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.user_input}
        ]

        self.current_conversations = conversations

        # 计算初始对话窗口长度并触发事件
        conversation_str = json.dumps(conversations, ensure_ascii=False)
        current_tokens = len(conversation_str)  # 暂时使用len
        yield WindowLengthChangeEvent(tokens_used=current_tokens)

        iteration_count = 0
        tool_executed = False
        should_yield_completion_event = False
        completion_event = None

        while True:
            iteration_count += 1
            tool_executed = False
            last_message = conversations[-1]
            printer.print_key_value(
                {"当前": f"第 {iteration_count} 轮", "历史会话长度": f"{len(conversations)}"}, title="LLM 交互循环"
            )

            if last_message["role"] == "assistant":
                # printer.print_text(f"上一条消息来自 assistant，跳过LLM交互循环", style="green")
                if should_yield_completion_event:
                    if completion_event is None:
                        yield CompletionEvent(completion=AttemptCompletionTool(
                            result=last_message["content"],
                            command=""
                        ), completion_xml="")
                    else:
                        yield completion_event
                break

            assistant_buffer = ""

            # 实际请求大模型
            llm_response_gen = stream_chat_with_continue(
                llm=self.llm,
                conversations=conversations,
                llm_config={},  # Placeholder for future LLM configs
                args=self.args
            )

            parsed_events = self.stream_and_parse_llm_response(llm_response_gen)

            event_count = 0
            mark_event_should_finish = False
            for event in parsed_events:
                event_count += 1

                if mark_event_should_finish:
                    if isinstance(event, TokenUsageEvent):
                        yield event
                    continue

                if isinstance(event, (LLMOutputEvent, LLMThinkingEvent)):
                    assistant_buffer += event.text
                    # printer.print_text(f"当前助手缓冲区累计字符数：{len(assistant_buffer)}", style="green")
                    yield event  # Yield text/thinking immediately for display

                elif isinstance(event, ToolCallEvent):
                    tool_executed = True
                    tool_obj = event.tool
                    tool_name = type(tool_obj).__name__
                    tool_xml = event.tool_xml  # Already reconstructed by parser

                    # Append assistant's thoughts and the tool call to history
                    printer.print_panel(content=f"tool_xml \n{tool_xml}", title=f"🛠️ 工具触发: {tool_name}", center=True)

                    # 记录当前对话的token数量
                    conversations.append({
                        "role": "assistant",
                        "content": assistant_buffer + tool_xml
                    })
                    assistant_buffer = ""  # Reset buffer after tool call

                    # 计算当前对话的总 token 数量并触发事件
                    current_conversation_str = json.dumps(conversations, ensure_ascii=False)
                    total_tokens = self.count_tokens(current_conversation_str)
                    yield WindowLengthChangeEvent(tokens_used=total_tokens)

                    yield event  # Yield the ToolCallEvent for display

                    # Handle AttemptCompletion separately as it ends the loop
                    if isinstance(tool_obj, AttemptCompletionTool):
                        printer.print_panel(content=f"完成结果: {tool_obj.result[:50]}...",
                                            title="AttemptCompletionTool，正在结束会话", center=True)
                        completion_event = CompletionEvent(completion=tool_obj, completion_xml=tool_xml)
                        # save_formatted_log(self.args.source_dir, json.dumps(conversations, ensure_ascii=False),
                        #                    "agentic_conversation")
                        mark_event_should_finish = True
                        should_yield_completion_event = True
                        continue

                    if isinstance(tool_obj, PlanModeRespondTool):
                        printer.print_panel(content=f"Plan 模式响应内容: {tool_obj.response[:50]}...",
                                            title="PlanModeRespondTool，正在结束会话", center=True)
                        yield PlanModeRespondEvent(completion=tool_obj, completion_xml=tool_xml)
                        # save_formatted_log(self.args.source_dir, json.dumps(conversations, ensure_ascii=False),
                        #                    "agentic_conversation")
                        mark_event_should_finish = True
                        continue

                    # Resolve the tool
                    resolver_cls = TOOL_RESOLVER_MAP.get(type(tool_obj))
                    if not resolver_cls:
                        tool_result = ToolResult(
                            success=False, message="错误：工具解析器未实现.", content=None)
                        result_event = ToolResultEvent(tool_name=type(tool_obj).__name__, result=tool_result)
                        error_xml = (f"<tool_result tool_name='{type(tool_obj).__name__}' success='false'>"
                                     f"<message>Error: Tool resolver not implemented.</message>"
                                     f"<content></content></tool_result>")
                    else:
                        try:
                            resolver = resolver_cls(agent=self, tool=tool_obj, args=self.args)
                            tool_result: ToolResult = resolver.resolve()
                            result_event = ToolResultEvent(tool_name=type(tool_obj).__name__, result=tool_result)

                            # Prepare XML for conversation history
                            escaped_message = xml.sax.saxutils.escape(tool_result.message)
                            content_str = str(
                                tool_result.content) if tool_result.content is not None else ""
                            escaped_content = xml.sax.saxutils.escape(
                                content_str)
                            error_xml = (
                                f"<tool_result tool_name='{type(tool_obj).__name__}' success='{str(tool_result.success).lower()}'>"
                                f"<message>{escaped_message}</message>"
                                f"<content>{escaped_content}</content>"
                                f"</tool_result>"
                            )
                        except Exception as e:
                            error_message = f"Critical Error during tool execution: {e}"
                            tool_result = ToolResult(success=False, message=error_message, content=None)
                            result_event = ToolResultEvent(tool_name=type(tool_obj).__name__, result=tool_result)
                            escaped_error = xml.sax.saxutils.escape(error_message)
                            error_xml = (f"<tool_result tool_name='{type(tool_obj).__name__}' success='false'>"
                                         f"<message>{escaped_error}</message>"
                                         f"<content></content></tool_result>")

                    yield result_event  # Yield the ToolResultEvent for display

                    # 添加工具结果到对话历史
                    conversations.append({
                        "role": "user",  # Simulating the user providing the tool result
                        "content": error_xml
                    })

                    # 计算当前对话的总 token 数量并触发事件
                    current_conversation_str = json.dumps(conversations, ensure_ascii=False)
                    total_tokens = self.count_tokens(current_conversation_str)
                    yield WindowLengthChangeEvent(tokens_used=total_tokens)

                    # 一次交互只能有一次工具，剩下的其实就没有用了，但是如果不让流式处理完，我们就无法获取服务端
                    # 返回的token消耗和计费，所以通过此标记来完成进入空转，直到流式走完，获取到最后的token消耗和计费
                    mark_event_should_finish = True

                elif isinstance(event, ErrorEvent):
                    yield event  # Pass through errors
                    # Optionally stop the process on parsing errors
                    # logger.error("Stopping analyze loop due to parsing error.")
                    # return
                elif isinstance(event, TokenUsageEvent):
                    yield event

            if not tool_executed:
                # No tool executed in this LLM response cycle
                printer.print_text("LLM响应完成, 未执行任何工具", style="yellow")
                if assistant_buffer:
                    printer.print_text(f"将 Assistant Buffer 内容写入会话历史（字符数：{len(assistant_buffer)}）")

                    last_message = conversations[-1]
                    if last_message["role"] != "assistant":
                        printer.print_text("添加新的 Assistant 消息", style="green")
                        conversations.append({"role": "assistant", "content": assistant_buffer})
                    elif last_message["role"] == "assistant":
                        printer.print_text("追加已存在的 Assistant 消息")
                        last_message["content"] += assistant_buffer

                    # 计算当前对话的总 token 数量并触发事件
                    current_conversation_str = json.dumps(conversations, ensure_ascii=False)
                    total_tokens = self.count_tokens(current_conversation_str)
                    yield WindowLengthChangeEvent(tokens_used=total_tokens)

                # 添加系统提示，要求LLM必须使用工具或明确结束，而不是直接退出
                printer.print_text("正在添加系统提示: 请使用工具或尝试直接生成结果", style="green")

                conversations.append({
                    "role": "user",
                    "content": "NOTE: You must use an appropriate tool (such as read_file, write_to_file, "
                               "execute_command, etc.) or explicitly complete the task (using attempt_completion). Do "
                               "not provide text responses without taking concrete actions. Please select a suitable "
                               "tool to continue based on the user's task."
                })

                # 计算当前对话的总 token 数量并触发事件
                current_conversation_str = json.dumps(conversations, ensure_ascii=False)
                total_tokens = self.count_tokens(current_conversation_str)
                yield WindowLengthChangeEvent(tokens_used=total_tokens)
                # 继续循环，让 LLM 再思考，而不是 break
                printer.print_text("持续运行 LLM 交互循环（保持不中断）", style="green")
                continue

        printer.print_text(f"AgenticEdit 分析循环已完成，共执行 {iteration_count} 次迭代.")
        save_formatted_log(self.args.source_dir, json.dumps(conversations, ensure_ascii=False), "agentic_conversation")

    def stream_and_parse_llm_response(
            self, generator: Generator[Tuple[str, Any], None, None]
    ) -> Generator[Union[LLMOutputEvent, LLMThinkingEvent, ToolCallEvent, ErrorEvent, TokenUsageEvent], None, None]:
        buffer = ""
        in_tool_block = False
        in_thinking_block = False
        current_tool_tag = None
        tool_start_pattern = re.compile(r"<(?!thinking\b)([a-zA-Z0-9_]+)>")  # Matches tool tags
        thinking_start_tag = "<thinking>"
        thinking_end_tag = "</thinking>"

        def parse_tool_xml(tool_xml: str, tool_tag: str) -> Optional[BaseTool]:
            """ Agent工具 XML字符串 解析器 """
            params = {}
            try:
                # 在<tool_tag>和</tool_tag>之间查找内容
                inner_xml_match = re.search(rf"<{tool_tag}>(.*?)</{tool_tag}>", tool_xml, re.DOTALL)
                if not inner_xml_match:
                    printer.print_text(f"无法在<{tool_tag}>...</{tool_tag}>标签内找到内容", style="red")
                    return None
                inner_xml = inner_xml_match.group(1).strip()

                # 在 tool_tag 内部内容中查找 <param>value</param> 参数键值对
                pattern = re.compile(r"<([a-zA-Z0-9_]+)>(.*?)</\1>", re.DOTALL)
                for m in pattern.finditer(inner_xml):
                    key = m.group(1)
                    # 基础的反转义处理（如果使用复杂值可能需要更健壮的反转义）
                    val = xml.sax.saxutils.unescape(m.group(2))
                    params[key] = val

                tool_cls = TOOL_MODEL_MAP.get(tool_tag)
                if tool_cls:
                    # 特别处理 requires_approval 的布尔值转换
                    if 'requires_approval' in params:
                        params['requires_approval'] = params['requires_approval'].lower() == 'true'
                    # 特别处理 ask_followup_question_tool 的JSON解析
                    if tool_tag == 'ask_followup_question' and 'options' in params:
                        try:
                            params['options'] = json.loads(params['options'])
                        except json.JSONDecodeError:
                            printer.print_text(f"ask_followup_question_tool 参数JSON解码失败: {params['options']}",
                                               style="red")
                            # 保持为字符串还是处理错误？目前先保持为字符串
                            pass
                    if tool_tag == 'plan_mode_respond' and 'options' in params:
                        try:
                            params['options'] = json.loads(params['options'])
                        except json.JSONDecodeError:
                            printer.print_text(f"plan_mode_respond_tool 参数JSON解码失败: {params['options']}",
                                               style="red")
                    # 处理 list_files 工具的递归参数
                    if tool_tag == 'list_files' and 'recursive' in params:
                        params['recursive'] = params['recursive'].lower() == 'true'
                    return tool_cls(**params)
                else:
                    printer.print_text(f"未找到标签对应的工具类: {tool_tag}", style="red")
                    return None
            except Exception as e:
                printer.print_text(f"解析工具XML <{tool_tag}> 失败: {e}\nXML内容:\n{tool_xml}", style="red")
                return None

        last_metadata = None
        for content_chunk, metadata in generator:
            if not content_chunk:
                last_metadata = metadata
                continue

            last_metadata = metadata
            buffer += content_chunk

            while True:
                # Check for transitions: thinking -> text, tool -> text, text -> thinking, text -> tool
                found_event = False

                # 1. Check for </thinking> if inside thinking block
                if in_thinking_block:
                    end_think_pos = buffer.find(thinking_end_tag)
                    if end_think_pos != -1:
                        thinking_content = buffer[:end_think_pos]
                        yield LLMThinkingEvent(text=thinking_content)
                        buffer = buffer[end_think_pos + len(thinking_end_tag):]
                        in_thinking_block = False
                        found_event = True
                        continue  # Restart loop with updated buffer/state
                    else:
                        # Need more data to close thinking block
                        break

                # 2. Check for </tool_tag> if inside tool block
                elif in_tool_block:
                    end_tag = f"</{current_tool_tag}>"
                    end_tool_pos = buffer.find(end_tag)
                    if end_tool_pos != -1:
                        tool_block_end_index = end_tool_pos + len(end_tag)
                        tool_xml = buffer[:tool_block_end_index]
                        tool_obj = parse_tool_xml(tool_xml, current_tool_tag)

                        if tool_obj:
                            # Reconstruct the XML accurately here AFTER successful parsing
                            # This ensures the XML yielded matches what was parsed.
                            reconstructed_xml = self._reconstruct_tool_xml(tool_obj)
                            if reconstructed_xml.startswith("<error>"):
                                yield ErrorEvent(message=f"Failed to reconstruct XML for tool {current_tool_tag}")
                            else:
                                yield ToolCallEvent(tool=tool_obj, tool_xml=reconstructed_xml)
                        else:
                            yield ErrorEvent(message=f"Failed to parse tool: <{current_tool_tag}>")
                            # Optionally yield the raw XML as plain text?
                            # yield LLMOutputEvent(text=tool_xml)

                        buffer = buffer[tool_block_end_index:]
                        in_tool_block = False
                        current_tool_tag = None
                        found_event = True
                        continue  # Restart loop
                    else:
                        # Need more data to close tool block
                        break

                # 3. Check for <thinking> or <tool_tag> if in plain text state
                else:
                    start_think_pos = buffer.find(thinking_start_tag)
                    tool_match = tool_start_pattern.search(buffer)
                    start_tool_pos = tool_match.start() if tool_match else -1
                    tool_name = tool_match.group(1) if tool_match else None

                    # Determine which tag comes first (if any)
                    first_tag_pos = -1
                    is_thinking = False
                    is_tool = False

                    if start_think_pos != -1 and (start_tool_pos == -1 or start_think_pos < start_tool_pos):
                        first_tag_pos = start_think_pos
                        is_thinking = True
                    elif start_tool_pos != -1 and (start_think_pos == -1 or start_tool_pos < start_think_pos):
                        # Check if it's a known tool
                        if tool_name in TOOL_MODEL_MAP:
                            first_tag_pos = start_tool_pos
                            is_tool = True
                        else:
                            # Unknown tag, treat as text for now, let buffer grow
                            pass

                    if first_tag_pos != -1:  # Found either <thinking> or a known <tool>
                        # Yield preceding text if any
                        preceding_text = buffer[:first_tag_pos]
                        if preceding_text:
                            yield LLMOutputEvent(text=preceding_text)

                        # Transition state
                        if is_thinking:
                            buffer = buffer[first_tag_pos + len(thinking_start_tag):]
                            in_thinking_block = True
                        elif is_tool:
                            # Keep the starting tag
                            buffer = buffer[first_tag_pos:]
                            in_tool_block = True
                            current_tool_tag = tool_name

                        found_event = True
                        continue  # Restart loop
                    else:
                        # No tags found, or only unknown tags found. Need more data or end of stream.
                        # Yield text chunk but keep some buffer for potential tag start
                        # Keep last 100 chars
                        split_point = max(0, len(buffer) - 1024)
                        text_to_yield = buffer[:split_point]
                        if text_to_yield:
                            yield LLMOutputEvent(text=text_to_yield)
                            buffer = buffer[split_point:]
                        break  # Need more data
                # If no event was processed in this iteration, break inner loop
                if not found_event:
                    break

        # After generator exhausted, yield any remaining content
        if in_thinking_block:
            # Unterminated thinking block
            yield ErrorEvent(message="Stream ended with unterminated <thinking> block.")
            if buffer:
                # Yield remaining as thinking
                yield LLMThinkingEvent(text=buffer)
        elif in_tool_block:
            # Unterminated tool block
            yield ErrorEvent(message=f"Stream ended with unterminated <{current_tool_tag}> block.")
            if buffer:
                yield LLMOutputEvent(text=buffer)  # Yield remaining as text
        elif buffer:
            # Yield remaining plain text
            yield LLMOutputEvent(text=buffer)

        # 这个要放在最后，防止其他关联的多个事件的信息中断
        yield TokenUsageEvent(usage=last_metadata)

    def apply_pre_changes(self):
        if not self.args.skip_commit:
            try:
                commit_message = commit_changes(self.args.source_dir, f"auto_coder_nano_agentic_edit")
                if commit_message:
                    printer.print_text(f"Commit 成功", style="green")
            except Exception as err:
                import traceback
                traceback.print_exc()
                printer.print_text(f"Commit 失败: {err}", style="red")
                return

    def apply_changes(self):
        """ Apply all tracked file changes to the original project directory. """
        changes = get_uncommitted_changes(self.args.source_dir)

        if changes != "No uncommitted changes found.":
            if not self.args.skip_commit:
                try:
                    commit_message = commit_changes(
                        self.args.source_dir, f"{self.args.query}\nauto_coder_nano_agentic_edit",
                    )
                    if commit_message:
                        printer.print_panel(content=f"Commit 成功", title="Commit 信息", center=True)
                except Exception as err:
                    import traceback
                    traceback.print_exc()
                    printer.print_panel(content=f"Commit 失败: {err}", title="Commit 信息", center=True)
        else:
            printer.print_panel(content=f"未进行任何更改", title="Commit 信息", center=True)

    def run_in_terminal(self, request: AgenticEditRequest):
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))

        printer.print_key_value(
            items={"项目名": f"{project_name}", "用户目标": f"{request.user_input}"}, title="Agentic Edit 开始运行"
        )

        # 用于累计TokenUsageEvent数据
        accumulated_token_usage = {
            "model_name": "",
            "input_tokens": 0,
            "output_tokens": 0,
        }

        try:
            self.apply_changes()  # 在开始 Agentic Edit 之前先提交变更
            event_stream = self.analyze(request)
            for event in event_stream:
                if isinstance(event, TokenUsageEvent):
                    last_meta: SingleOutputMeta = event.usage

                    # 累计token使用情况
                    accumulated_token_usage["model_name"] = self.args.chat_model
                    accumulated_token_usage["input_tokens"] += last_meta.input_tokens_count
                    accumulated_token_usage["output_tokens"] += last_meta.generated_tokens_count

                    printer.print_key_value(accumulated_token_usage)

                elif isinstance(event, WindowLengthChangeEvent):
                    # 显示当前会话的token数量
                    printer.print_panel(
                        content=f"当前会话总 tokens: {event.tokens_used}", title="Window Length Change", center=True
                    )

                elif isinstance(event, LLMThinkingEvent):
                    # Render thinking within a less prominent style, maybe grey?
                    printer.print_panel(content=f"{event.text}", title="LLM Thinking", center=True)

                elif isinstance(event, LLMOutputEvent):
                    # Print regular LLM output, potentially as markdown if needed later
                    printer.print_panel(
                        content=f"{event.text}", title="LLM Output", center=True
                    )

                elif isinstance(event, ToolCallEvent):
                    # Skip displaying AttemptCompletionTool's tool call
                    if isinstance(event.tool, AttemptCompletionTool):
                        continue  # Do not display AttemptCompletionTool tool call

                    tool_name = type(event.tool).__name__
                    # Use the new internationalized display function
                    display_content = get_tool_display_message(event.tool)
                    printer.print_panel(content=display_content, title=f"🛠️ 工具调用: {tool_name}", center=True)

                elif isinstance(event, ToolResultEvent):
                    # Skip displaying AttemptCompletionTool's result
                    if event.tool_name == "AttemptCompletionTool":
                        continue  # Do not display AttemptCompletionTool result
                    if event.tool_name == "PlanModeRespondTool":
                        continue

                    result = event.result
                    title = f"✅ 工具返回: {event.tool_name}" if result.success else f"❌ 工具返回: {event.tool_name}"
                    border_style = "green" if result.success else "red"
                    base_content = f"状态: {'成功' if result.success else '失败'}\n"
                    base_content += f"信息: {result.message}\n"

                    def _format_content(_content):
                        if len(_content) > 200:
                            return f"{_content[:100]}\n...\n{_content[-100:]}"
                        else:
                            return _content

                    # Prepare panel for base info first
                    panel_content = [base_content]
                    # syntax_content = None
                    content_str = ""
                    lexer = "python"  # Default guess

                    if result.content is not None:
                        try:
                            if isinstance(result.content, (dict, list)):
                                content_str = json.dumps(result.content, indent=2, ensure_ascii=False)
                                # syntax_content = Syntax(content_str, "json", theme="default", line_numbers=False)
                            elif isinstance(result.content, str) and (
                                    '\n' in result.content or result.content.strip().startswith('<')):
                                # Heuristic for code or XML/HTML
                                if event.tool_name == "ReadFileTool" and isinstance(event.result.message, str):
                                    # Try to guess lexer from file extension in message
                                    if ".py" in event.result.message:
                                        lexer = "python"
                                    elif ".js" in event.result.message:
                                        lexer = "javascript"
                                    elif ".ts" in event.result.message:
                                        lexer = "typescript"
                                    elif ".html" in event.result.message:
                                        lexer = "html"
                                    elif ".css" in event.result.message:
                                        lexer = "css"
                                    elif ".json" in event.result.message:
                                        lexer = "json"
                                    elif ".xml" in event.result.message:
                                        lexer = "xml"
                                    elif ".md" in event.result.message:
                                        lexer = "markdown"
                                    else:
                                        lexer = "text"  # Fallback lexer
                                elif event.tool_name == "ExecuteCommandTool":
                                    lexer = "shell"
                                else:
                                    lexer = "text"

                                content_str = str(result.content)
                                # syntax_content = Syntax(
                                #     _format_content(result.content), lexer, theme="default", line_numbers=True
                                # )
                            else:
                                content_str = str(result.content)
                                # Append simple string content directly
                                panel_content.append(_format_content(content_str))

                        except Exception as e:
                            printer.print_text(f"Error formatting tool result content: {e}", style="yellow")
                            panel_content.append(
                                # Fallback
                                _format_content(str(result.content)))

                    # Print the base info panel
                    printer.print_panel(
                        content="\n".join(panel_content), title=title, border_style=border_style, center=True)
                    # Print syntax highlighted content separately if it exists
                    if content_str:
                        printer.print_code(
                            code=content_str, lexer=lexer, theme="monokai", line_numbers=True, panel=True)

                elif isinstance(event, PlanModeRespondEvent):
                    printer.print_panel(
                        content=Markdown(event.completion.response),
                        title="🏁 任务完成", center=True
                    )

                elif isinstance(event, CompletionEvent):
                    # 在这里完成实际合并
                    try:
                        self.apply_changes()
                    except Exception as e:
                        printer.print_text(f"Error merging shadow changes to project: {e}", style="red")

                    printer.print_panel(
                        content=Markdown(event.completion.result),
                        title="🏁 任务完成", center=True
                    )
                    if event.completion.command:
                        printer.print_text(f"Suggested command:{event.completion.command}", style="green")

                elif isinstance(event, ErrorEvent):
                    printer.print_panel(
                        content=f"Error: {event.message}",
                        title="🔥 任务失败", center=True
                    )

                time.sleep(0.5)  # Small delay for better visual flow

            # 在处理完所有事件后打印累计的token使用情况
            printer.print_key_value(accumulated_token_usage)

        except Exception as err:
            # 在处理异常时也打印累计的token使用情况
            if accumulated_token_usage["input_tokens"] > 0:
                printer.print_key_value(accumulated_token_usage)
            printer.print_panel(content=f"FATAL ERROR: {err}", title="🔥 Agentic Edit 运行错误", center=True)
            raise err
        finally:
            printer.print_text("Agentic Edit 结束", style="green")
