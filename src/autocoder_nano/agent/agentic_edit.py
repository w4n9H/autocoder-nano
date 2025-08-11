import hashlib
import json
import os
import re
import time
import xml.sax.saxutils
from copy import deepcopy
# from importlib import resources
from typing import Generator, Union, Tuple

from autocoder_nano.agent.agent_base import BaseAgent
from autocoder_nano.context import get_context_manager, ConversationsPruner
from autocoder_nano.rag.token_counter import count_tokens
from rich.markdown import Markdown
# from tokenizers import Tokenizer

from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.utils.config_utils import prepare_chat_yaml, get_last_yaml_file, convert_yaml_config_to_str
from autocoder_nano.utils.git_utils import commit_changes, get_uncommitted_changes
from autocoder_nano.core import AutoLLM, stream_chat_with_continue
from autocoder_nano.core import prompt, format_str_jinja2
from autocoder_nano.actypes import AutoCoderArgs, SourceCodeList, SingleOutputMeta
from autocoder_nano.utils.sys_utils import detect_env
from autocoder_nano.utils.formatted_log_utils import save_formatted_log
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.agent.agentic_edit_tools import (  # Import specific resolvers
    BaseToolResolver,
    ExecuteCommandToolResolver, ReadFileToolResolver, WriteToFileToolResolver,
    ReplaceInFileToolResolver, SearchFilesToolResolver, ListFilesToolResolver,
    ListCodeDefinitionNamesToolResolver, AskFollowupQuestionToolResolver,
    AttemptCompletionToolResolver, PlanModeRespondToolResolver, ListPackageInfoToolResolver,
    RecordMemoryToolResolver, RecallMemoryToolResolver
)

printer = Printer()


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
    PlanModeRespondTool: PlanModeRespondToolResolver,
    RecordMemoryTool: RecordMemoryToolResolver,
    RecallMemoryTool: RecallMemoryToolResolver
}


class AgenticEdit(BaseAgent):
    def __init__(
            self, args: AutoCoderArgs, llm: AutoLLM, files: SourceCodeList, history_conversation: List[Dict[str, Any]],
            conversation_config: Optional[AgenticEditConversationConfig] = None
    ):
        super().__init__(args, llm)
        # self.args = args
        # self.llm = llm
        self.files = files
        self.history_conversation = history_conversation
        self.current_conversations = []
        self.shadow_manager = None
        self.file_changes: Dict[str, FileChangeEntry] = {}

        # 对话管理器
        self.conversation_config = conversation_config
        self.conversation_manager = get_context_manager()

        # Agentic 对话修剪器
        self.agentic_pruner = ConversationsPruner(args=args, llm=self.llm)

        if self.conversation_config.action == "new":
            conversation_id = self.conversation_manager.create_conversation(
                name=self.conversation_config.query or "New Conversation",
                description=self.conversation_config.query or "New Conversation")
            self.conversation_manager.set_current_conversation(conversation_id)
        if self.conversation_config.action == "resume" and self.conversation_config.conversation_id:
            self.conversation_manager.set_current_conversation(self.conversation_config.conversation_id)

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

    # noinspection PyUnresolvedReferences
    @prompt()
    def _analyze(self, request: AgenticEditRequest):
        """
        你是一位技术精湛的软件工程师，在众多编程语言，框架，设计模式和最佳实践方面拥有渊博知识。

        ====
        # 工具使用说明

        1. 你可使用一系列工具，且需经用户批准才能执行。
        2. 每条消息中仅能使用一个工具，用户回复中会包含该工具的执行结果。
        3. 你要借助工具逐步完成给定任务，每个工具的使用都需依据前一个工具的使用结果。

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
        描述：
        - 用于在系统上执行 CLI 命令，根据用户操作系统调整命令，并解释命令作用，
        - 对于命令链，使用适合用户操作系统及shell类型的链式语法，相较于创建可执行脚本，优先执行复杂的 CLI 命令，因为它们更灵活且易于运行。
        - 命令将在当前工作目录{{current_project}}中执行。
        参数：
        - command（必填）：要执行的 CLI 命令。该命令应适用于当前操作系统，且需正确格式化，不得包含任何有害指令。
        - requires_approval（必填）：
            * 布尔值，此命令表示在用户启用自动批准模式的情况下是否还需要明确的用户批准。
            * 对于可能产生影响的操作，如安装/卸载软件包，删除/覆盖文件，系统配置更改，网络操作或任何可能产生影响的命令，设置为 'true'。
            * 对于安全操作，如读取文件/目录、运行开发服务器、构建项目和其他非破坏性操作，设置为 'false'。
        用法：
        <execute_command>
        <command>需要运行的命令</command>
        <requires_approval>true 或 false</requires_approval>
        </execute_command>

        ## list_package_info（列出软件包信息）
        描述：
        - 请求检索有关源代码包的信息，如最近的更改或文档摘要，以更好地理解代码上下文。它接受一个目录路径（相对于当前项目的绝对或相对路径）。
        参数：
        - path（必填）：源代码包目录路径。
        用法：
        <list_package_info>
        <path>相对或绝对的软件包路径</path>
        </list_package_info>

        ## read_file（读取文件）
        描述：
        - 请求读取指定路径文件的内容。
        - 当需要检查现有文件的内容（例如分析代码，查看文本文件或从配置文件中提取信息）且不知道文件内容时使用此工具。
        - 仅能从 Markdown，TXT，以及代码文件中提取纯文本，可能不适用于其他类型的文件。
        参数：
        - path（必填）：要读取的文件路径（相对于当前工作目录{{ current_project }}）。
        用法：
        <read_file>
        <path>文件路径在此</path>
        </read_file>

        ## write_to_file（写入文件）
        描述：将内容写入指定路径文件，文件存在则覆盖，不存在则创建，会自动创建所需目录。
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
        描述：
        - 请求使用定义对文件特定部分进行精确更改的 SEARCH/REPLACE 块来替换现有文件中的部分内容。
        - 此工具应用于需要对文件特定部分进行有针对性更改的情况。
        参数：
        - path（必填）：要修改的文件路径，相对于当前工作目录 {{ current_project }} 。
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
        描述：
        - 在指定目录的文件中执行正则表达式搜索，输出包含每个匹配项及其周围的上下文结果。
        参数：
        - path（必填）：要搜索的目录路径，相对于当前工作目录 {{ current_project }}，该目录将被递归搜索。
        - regex（必填）：要搜索的正则表达式模式，使用 Rust 正则表达式语法。
        - file_pattern（可选）：用于过滤文件的 Glob 模式（例如，'.ts' 表示 TypeScript 文件），若未提供，则搜索所有文件（*）。
        用法：
        <search_files>
        <path>Directory path here</path>
        <regex>Your regex pattern here</regex>
        <file_pattern>file pattern here (optional)</file_pattern>
        </search_files>

        ## list_files（列出文件）
        描述：
        - 列出指定目录中的文件和目录，支持递归列出。
        参数：
        - path（必填）：要列出内容的目录路径，相对于当前工作目录 {{ current_project }} 。
        - recursive（可选）：是否递归列出文件，true 表示递归列出，false 或省略表示仅列出顶级内容。
        用法：
        <list_files>
        <path>Directory path here</path>
        <recursive>true or false (optional)</recursive>
        </list_files>

        ## list_code_definition_names（列出代码定义名称）
        描述：
        - 请求列出指定目录顶级源文件中的定义名称（类，函数，方法等）。
        参数：
        - path（必填）：要列出顶级源代码定义的目录路径（相对于当前工作目录{{ current_project }}）。
        用法：
        <list_code_definition_names>
        <path>Directory path here</path>
        </list_code_definition_names>

        ## record_memory (记录笔记/记忆)
        描述：
        - 笔记系统，用于存储任务需求分析过程及结果，任务待办列表，代码自描述文档（AC Module）和任务执行经验总结
        参数：
        - content（必填）：你的笔记正文, 笔记的具体用法下文会告知
        用法：
        <record_memory>
        <content>Notebook Content</content>
        </record_memory>

        ## recall_memory (检索笔记/记忆)
        描述：
        - 检索笔记系统中的信息
        参数：
        - query（必填）：你检索笔记的提问
        用法：
        <recall_memory>
        <query>Recall Notebook Query</query>
        </recall_memory>

        ask_followup_question（提出后续问题）
        描述：
        - 向用户提问获取任务所需信息。
        - 当遇到歧义，需要澄清或需要更多细节以有效推进时使用此工具。
        - 它通过与用户直接沟通实现交互式问题解决，应明智使用，以在收集必要信息和避免过多来回沟通之间取得平衡。
        参数：
        - question（必填）：清晰具体的问题。
        - options（可选）：2-5个选项的数组，每个选项应为描述可能答案的字符串，并非总是需要提供选项，少数情况下有助于避免用户手动输入。
        用法：
        <ask_followup_question>
        <question>Your question here</question>
        <options>
        Array of options here (optional), e.g. ["Option 1", "Option 2", "Option 3"]
        </options>
        </ask_followup_question>

        ## attempt_completion（尝试完成任务）
        描述：
        - 每次工具使用后，用户会回复该工具使用的结果，即是否成功以及失败原因（如有）。
        - 一旦收到工具使用结果并确认任务完成，使用此工具向用户展示工作成果。
        - 可选地，你可以提供一个 CLI 命令来展示工作成果。用户可能会提供反馈，你可据此进行改进并再次尝试。
        重要提示：
        - 在确认用户已确认之前的工具使用成功之前，不得使用此工具。否则将导致代码损坏和系统故障。
        - 在使用此工具之前，必须在<thinking></thinking>标签中自问是否已从用户处确认之前的工具使用成功。如果没有，则不要使用此工具。
        参数：
        - result（必填）：任务的结果，应以最终形式表述，无需用户进一步输入，不得在结果结尾提出问题或提供进一步帮助。
        - command（可选）：用于向用户演示结果的 CLI 命令。
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
        1. 开始任务前务必进行全面搜索和探索，
            * 用搜索工具（list_files，grep 命令）了解代码库结构，模式和依赖
            * 使用笔记检索工具查询历史需求分析过程及结果，任务待办列表，代码自描述文档（AC Module）和任务执行经验总结。
        2. 在 <thinking> 标签中评估已有和继续完成任务所需信息
        3. 根据任务选择合适工具，思考是否需其他信息来推进，以及用哪个工具收集。
            * 例如，list_files 工具比在 execute_command 工具中使用 ls 的命令更高效。
        4. 逐步执行，禁止预判：
            * 单次仅使用一个工具
            * 后续操作必须基于前次结果
            * 严禁假设任何工具的执行结果
        4. 按工具指定的 XML 格式使用
        5. 重视用户反馈，某些时候，工具使用后，用户会回复为你提供继续任务或做出进一步决策所需的信息，可能包括：
            * 工具是否成功的信息
            * 触发的 Linter 错误（需修复）
            * 相关终端输出
            * 其他关键信息

        =====

        文件搜索 (核心方法)

        搜索优先是进行可靠代码工作的强制要求。所有代码任务必须遵循此系统的探索模式。
        本指南为AI代理和开发人员提供了一种有效搜索，理解和修改代码库的系统方法，强调变更前充分探查与变更后系统验证，确保修改可靠且可维护。

        该方法结合多种工具 (grep, list_files, read_file) 与结构化流程，旨在：
        - 最大限度地减少代码错误
        - 确保全面理解
        - 系统化验证变更
        - 遵循项目既定模式

        # list_files（列出文件）
        ## 目的：
        - 探查项目结构，理解目录组织。
        - 获取文件/文件夹概览
        ## 使用时机：
        - 初始探索：了解代码库布局
        - 定位关键目录：如 src/, lib/, components/, utils/
        - 查找配置文件：如 package.json, tsconfig.json, Makefile
        - 使用精准搜索工具前
        ## 优点：
        - 快速获取项目概览，避免信息过载
        - 辅助规划精准搜索范围
        - 理解陌生代码库的必备首步

        # grep（Shell 命令）
        ## 目的：
        - 跨文件查找精确文本匹配与模式。
        - 执行输出开销最小的精确搜索。
        - 验证代码更改并确认实现。

        ## 使用时机：
        - 编码前探查上下文：定位符号、函数、导入、使用模式
        - 编码后验证：确认更改已正确应用，消除残留引用。
        - 模式分析：理解编码规范与现有实现

        ## 关键命令模式：
        - 编码前探查上下文示例：
        <execute_command>
        <command>grep -l "className" src/ | head -5</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -rc "import.*React" src/ | grep -v ":0"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -Rn "function.*MyFunction | const.*MyFunction" . | head -10</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -R --exclude-dir={node_modules,dist,build,.git} "TODO" .</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 编码后验证变更示例：

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
        <command>grep -Rn "import.*newModule | export.*newFunction" . | wc -l</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        ## 输出优化技巧：
        - 使用 -l 仅获取文件名。
        - 使用 -c 仅获取计数。
        - 使用 | head -N 限制行数。
        - 使用 | wc -l 获取总数。
        - 使用 2>/dev/null 抑制错误。
        - 与 || echo 结合使用以显示清晰的状态消息。

        ## 关于 grep 命令 --exclude-dir 参数额外说明
        - 一定要放入 .git,.auto-coder 这两个目录进行排除，示例 --exclude-dir={.git,.auto-coder}
        - 然后根据项目类型进行其他目录的排除，以避免检索出无用内容

        # search_files（备选搜索）

        ## 目的：
        - 当 grep 不可用时作为备选方案。
        - 提供更广泛但不太精确的语义搜索能力，查找相关代码。
        - 作为 grep 的补充，用于全面的代码发现。

        ## 使用时机：
        - Shell 访问受限或 grep 不可用。
        - 需要在代码库中进行更广泛、精度要求较低的搜索时。
        - 作为 grep 的补充，用于全面的代码发现。

        # read_file（读取文件）

        ## 目的：
        - 详细检查完整的文件内容。
        - 深入理解上下文，模式与实现细节。

        ## 使用时机：
        - 通过 list_files 或 grep 定位目标文件后。
        - 需要理解函数签名，接口或约定时。
        - 分析使用模式和项目规范时。
        - 在修改代码前需进行详细检查时

        ## 重要提示：
        - 精准定位后使用：在缩小目标文件范围后使用。
        - 修改前必备：代码修改前理解上下文至关重要。
        - 识别关联影响：帮助识别依赖关系和潜在副作用

        # 选择正确的搜索策略
        - 首先使用 list_files了解项目结构。
        - 需要查找特定内容时使用 grep。
        - 需要检查特定文件的详细信息时使用 read_file。
        - 组合使用：综合运用以获得全面理解。

        ## 默认工作流程：
        - list_files → 了解结构。
        - grep → 查找特定模式/符号。
        - read_file → 检查细节。
        - 实施更改。
        - grep → 验证更改。

        =====

        # 综合工作流程

        ## 阶段1：项目探索与分析

        ### 项目结构概述

        <execute_command>
        <command>ls -la</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 使用 list_files 工具了解目录结构。
        - 定位关键目录：src/, lib/, components/, utils/
        - 查找配置文件：package.json, tsconfig.json, Makefile

        ### 检索笔记，获取记忆

        <recall_memory>
        <query>package.json main.py coder.py 与需求有关联的词语</query>
        </recall_memory>

        - 了解项目结构后，结合任务需求，思考检索关键词，如代码文件名称，文档名称，以及与需求相关的关键词
        - 关键词之间必须使用空格分割
        - 最多尝试检索2次，无结果则默认无长期记忆
        - 注意：如果同一个代码文件出现多个AC模块，或者类似的需求出现了多次总结，以最新日期为准

        ### 技术栈识别

        <execute_command>
        <command>grep -E "(import|require|from).*['\"]" src/ | head -20</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 检查包依赖与导入关系。
        - 识别框架，库及编码模式。
        - 理解项目规范（命名/文件组织）。

        ## 阶段2：代码上下文探查

        ### 符号与模式搜索

        <execute_command>
        <command>grep -Rn "targetFunction|targetClass" . --exclude-dir={node_modules,dist}</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        ### 使用模式分析

        <read_file>
        <path>src/autocoder_nano/main.py</path>
        </read_file>

        - 使用 read_file 详细检查关键文件。
        - 理解函数签名，接口与约定。
        - 检查错误处理与边界情况。

        ### 依赖关系映射

        <execute_command>
        <command>grep -Rn "import.*targetModule" . | grep -v test</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        ### 记录 AC Module

        <record_memory>
        <content>AC Module 内容</content>
        </record_memory>

        - 在完成代码上下文探查后，务必使用 AC Module 的记录笔记
        - 尽量以目录为模块进行记录，也可以对少量关键代码文件进行记录

        ## 阶段3：实施规划

        ### 影响评估

        - 识别所有需要修改的文件。
        - 规划向后兼容性注意事项。
        - 评估潜在副作用。

        ### 测试策略

        <execute_command>
        <command>find . -name "*test*" -o -name "*spec*" | head -10</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 定位现有测试作为参考。
        - 必要时规划新的测试用例。

        ## 阶段4：代码实现

        更多细节请参考 “文件编辑” 部分。

        ## 阶段 5：全面验证

        ### 文件系统验证

        <execute_command>
        <command>ls -la newfile.* 2>/dev/null || echo "Expected new files not found"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        ### 代码集成验证

        <execute_command>
        <command>grep -Rn "oldSymbol" . --exclude-dir={node_modules,dist} || echo "✓ No stale references"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        <execute_command>
        <command>grep -Rn "oldSymbol" . --exclude-dir={node_modules,dist} || echo "✓ No stale references"</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        ### 功能验证

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

        ### 文档和注释

        - 验证新函数 / 类是否有适当的文档。
        - 检查复杂逻辑是否有解释性注释。
        - 确保 README 或其他文档在需要时已更新。

        ## 阶段6：质量保证

        ### 性能考虑

        - 检查潜在的性能影响。
        - 验证内存使用模式。
        - 评估可扩展性影响。

        ### 安全审查

        - 查找潜在的安全漏洞。
        - 验证输入验证和清理。
        - 检查错误/异常处理完备性。

        ### 记录工作总结

        <record_memory>
        <content>任务完成工作总结</content>
        </record_memory>

        - 工作总结内容包括：
            * 任务需求分析过程及结果（任务待办列表）
            * 本次任务的经验总结

        ### 最终集成检查

        <execute_command>
        <command>grep -Rn "TODO | FIXME | XXX" . --exclude-dir={node_modules,dist} | wc -l</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        =====

        # 最佳实践

        - 迭代推进：避免一次性理解所有内容，逐步构建认知。
        - 文档/笔记优先：深入研究代码前先阅读现有文档，注释和README，检索历史笔记内容。
        - 小步实施：增量修改并逐步骤验证。
        - 回滚准备：始终预设问题发生时的撤销方案。
        - 及早测试：开发中频繁运行测试，而非仅最终阶段测试。
        - 模式一致：遵循项目既有模式，避免引入新范式

        遵循此完整流程，可确保：
        - 全面理解代码变更
        - 可靠实施修改内容
        - 稳健验证最终结果

        =====

        文件编辑 EDITING FILES

        前置要求：执行编辑前，必须已完成"文件搜索"流程，充分理解代码库上下文。
        提供两种编辑工具：write_to_file (全文件写入) 与 replace_in_file (局部替换)。根据场景选择合适工具是保证修改效率与准确性的关键。

        # write_to_file（全文件写入）

        ## 目的：
        - 创建新文件 或 完全覆盖现有文件内容。

        ## 使用时机：
        - 初始化创建文件（如脚手架项目）。
        - 覆盖大型样板文件。
        - 修改量过大导致使用 replace_in_file 局部替换不切实际时。
        - 当需要完全重构文件的内容时。

        ## 重要提示：
        - 使用 write_to_file 需要提供文件的完整最终内容。
        - 如果只需要对现有文件进行小的更改，考虑使用 replace_in_file，以避免不必要地重写整个文件。
        - 虽然 write_to_file 不应是你的默认选择，但在情况确实需要时不要犹豫使用它。

        # replace_in_file（局部替换）

        ## 目的：
        - 精准修改文件局部内容，避免全文件覆盖。

        ## 使用时机：
        - 小范围修改：更新单行，函数实现，变量名等。
        - 长文件中仅需改动特定部分时。
        - 目标明确的针对性改进。

        ## 优点：
        - 高效：无需提供完整文件内容。
        - 安全：降低大文件覆盖的风险。

        # 文件编辑工具选择原则

        - 大多数更改默认使用 replace_in_file，它是更安全、更精确的选择，可最大限度地减少潜在问题。
        - 使用 write_to_file 的情况：
            * 创建新文件。
            * 更改非常广泛，使用 replace_in_file 会更复杂或更危险。
            * 需要完全重组或重构文件。
            * 文件相对较小，更改影响其大部分内容。
            * 生成样板文件或模板文件。

        # 自动格式化注意事项

        - 使用 write_to_file 或 replace_in_file 后，可能触发编辑器自动格式化。
        - 这种自动格式化可能会修改文件内容，例如：
            * 将单行拆分为多行。
            * 调整缩进以匹配项目样式（如2个空格，4个空格或制表符）。
            * 将单引号转换为双引号（或根据项目首选项反之亦然）。
            * 组织导入（如排序，按类型分组）。
            * 在对象和数组中添加/删除尾随逗号。
            * 强制一致的大括号样式（如同一行或新行）。
            * 标准化分号用法（根据样式添加或删除）。
            * write_to_file 和 replace_in_file 工具响应将包含自动格式化后的文件最终状态。
            * 将此最终状态用作任何后续编辑的参考点，这在为 replace_in_file 制作 SEARCH 块时尤其重要，因为需要内容与文件中的内容完全匹配。

        # 工作流程提示

        1. 预判范围：根据修改量选择工具
        2. 精准替换：单次 replace_in_file 可叠加多个SEARCH/REPLACE块
        3. 彻底重写：重大变更时使用 write_to_file
        4. 版本同步：以工具返回的终态文件为后续操作基准

        合理选择工具，使文件编辑更流畅，安全，高效。

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

        笔记系统 Notebook

        ## 目的：
        - 用于存储任务需求分析过程及结果，任务待办列表
        - 保存阅读代码后产生的 AC Module
        - 保存任务执行完毕后, 记录任务执行经验总结
        - 用于解决 agentic 无法保存长期记忆的问题

        ## 笔记记录时机：
        - 任务需求分析完毕后
        - 阅读代码文件后，分析并记录 AC Module
        - 完成需求后，进行相关的工作总结, 比如需求完成情况, 完成该需求的经验总结

        ## 笔记检索时机：
        - 接收到需求并获取项目结构后, 即可开始检索笔记
          - 检索以前是否有完成过类似的任务，可以查看以前的工作总结
          - 阅读代码前，检索以前是否分析过该代码，可以查看分析结果
          - 注意：如果同一个代码文件出现多个AC模块，或者类似的需求出现了多次总结，以最新日期为准

        ## 强制使用要求

        你必须在以下时机使用笔记系统，否则将无法高效完成任务：

        - 任务开始：使用 recall_memory 检索与当前任务相关的历史笔记，包括需求分析，AC模块，经验总结等。
        - 阅读代码后：对每个阅读过的代码文件，生成AC模块并记录（使用 record_memory）。
        - 任务完成：使用 record_memory 记录任务完成情况和工作总结。

        ## 笔记检索技巧：
        - 因为笔记的存储，英文部分是大小写敏感的，当你在构思查询语句时，可以多尝试几次，比如
          - 查询 "agent" 无结果时，可以试试 "Agent" 。这种情况尝试最多2次无论是否有结果都必须要进行下一步

        ### 示例1：任务开始时检索笔记

        <recall_memory>
        <query>登录 登录功能 登陆页面 login </query>
        </recall_memory>

        - 检索关于实现登录功能的需求分析，AC模块，经验总结

        ### 示例2：阅读代码后记录AC模块

        假设你阅读了 `src/auth/login.js` 文件，并生成了该文件的AC模块描述：

        <record_memory>
        <content>
        ...（src/auth/login.js AC模块内容）...
        </content>
        </record_memory>

        ### 示例3：任务完成后记录工作总结

        <record_memory>
        <content>
        任务：实现登录功能
        需求分析过程及结果：...
        完成情况：成功实现了基于JWT的登录功能，包括前端表单和后端验证。
        经验总结：在实现过程中，发现需要处理XSS攻击，已在前端输入过滤和后端验证中增加安全措施。
        </content>
        </record_memory>

        =====

        # AC Module（AC 模块）

        别名：AC Module，AC模块，代码自描述文件，以上三个关键词时，都表示为同一个意思

        ## 何为 AC Module？

        -  AC Module是一种全新的模块化组织方式，专为AI时代设计。
        - 提供完整功能， 语言无关，可作为API使用的独立单元。
        - 特性：自包含，接口明确，文档完备。

        ### 以AI为中心的设计思想

        传统模块化主要考虑人类开发者的需求，而 AC Module 首先考虑的是：如何让AI更好地理解和使用这个模块？

        - 每个 AC Module 都有完整的代码自描述内容。
        - 所有信息都集中在一个描述文件中。
        - 使用 AI友好的 Markdown 格式进行存储。
        - 严格控制 Token 数量，确保在模型窗口内。

        ### 语言无关的模块定义

        AC Module 不依赖特定的编程语言或框架：
        - 一个 AC Module = 功能实现 + 完整文档 + 使用示例 + 测试验证
        - 无论是Python、JavaScript、Go还是Rust，AC Module 的组织方式都是一致的。

        ### 自包含的文档化模块

        每个 AC Module 都是一个自包含的知识单元，包含：

        - 功能描述和使用场景
        - 完整的API文档
        - 详细的使用示例
        - 依赖关系说明
        - 测试和验证方法

        ## 标准化的模块结构

        每个 AC Module 都遵循统一的文档结构：

        ````markdown
        # [模块名称]
        [一句话功能描述]

        ## Directory Structure
        [标准化的目录结构说明]

        ## Quick Start
        ### Basic Usage
        [完整的使用示例代码]

        ### Helper Functions
        [辅助函数说明]

        ### Configuration Management
        [配置管理说明]

        ## Core Components
        ### 1. [主要类名] Main Class
        **Core Features:**
        - [特性1]: [详细描述]
        - [特性2]: [详细描述]

        **Main Methods:**
        - `method1()`: [方法功能和参数描述]
        - `method2()`: [方法功能和参数描述]

        ## Mermaid File Dependency Graph
        [依赖关系的可视化图表]

        ## Dependency Relationships
        [与其他AC模块的依赖关系列表]

        ## Commands to Verify Module Functionality
        [可执行的验证命令]
        ```

        ## 使用场景

        - 避免重复：实现新功能前检查现有  AC Module
        - 架构理解：通过 AC Module 掌握整体项目结构
        - 变更评估：修改文件时确认所在 AC Module 及影响范围

        ## 快速入门

        ### 基础使用

        ``python
        # 依赖导入
        from [模块路径] import [主类], [工具类]

        # 1. 配置初始化
        [具体配置代码示例]

        # 2. 核心功能调用
        [主类使用方法示例]

        # 3. 基础调用
        [基础调用代码示例]
        ```

        ### 工具函数集

        [详细说明模块提供的辅助函数]

        ### 配置管理规范

        [配置项说明及管理方法论]

        ## 核心组件

        ### 1. [主类名] Main Class
        [YOU SHOULD KEEP THIS PART AS SIMPLIFIED AS POSSIBLE]

        核心能力：

        - [能力1]：[技术细节]
        - [能力2]：[技术细节]

        关键方法：

        - [方法1](参数)：[功能描述+参数说明]
        - [方法2](参数)：[功能描述+参数说明]

        ### 2. [模块] 架构设计

        [实现原理与设计细节解析]

        ## Mermaid 依赖图谱

        [模块内部依赖说明]

        ```mermaid
        graph TB
            %% 核心组件定义
            [主组件][主组件<br/>功能描述]
            [子组件][子组件<br/>功能描述]

            %% 依赖关系
            [主组件] --> [子组件]

            %% 样式规范
            classDef coreClass fill:#e1f5fe,stroke:#0277bd,stroke-width:2px
            classDef subClass fill:#f3e5f5,stroke:#7b1fa2,stroke-width:1px

            class [主组件] coreClass
            class [子组件1] subClass
        ```

        [示例如下]

        ```mermaid
        graph TB
            FileMonitor[FileMonitor<br/>文件系统监控核心类]
            Watchfiles[watchfiles<br/>文件系统监控库]
            Pathspec[pathspec<br/>路径模式匹配库]

            FileMonitor --> Watchfiles
            FileMonitor --> Pathspec
        ```

        ## 功能验证指令

        [可执行的测试/运行命令]

        ```
        node --experimental-transform-types ./a/b/c.ts
        ```

        或者：

        ```
        pytest path/to/your/module/tests -v
        ```

        =====

        # 核心能力

        ## 先探索后修改（基本原则）

        核心优势在于系统化代码库探查能力：

        - 优先使用 list_files、execute_command（grep）映射项目结构。
        - 识别代码模式与依赖关系
        - 确保可靠变更的必经流程

        ## 长期记忆与知识复用

        - 通过笔记系统，你可以记录和检索历史任务的经验和代码分析结果，避免重复工作。
        - 在任务开始时，通过检索笔记，可以快速获取相关任务的解决方案和注意事项。
        - 在代码分析过程中，记录AC模块可以帮助你构建项目的知识库，便于后续任务使用。

        ## 多工具协同体系

        支持通过工具链完成全周期任务：

        - 探查工具：执行CLI命令，文件列表，源码定义解析
        - 搜索工具：正则匹配跨文件搜索
        - 编辑工具：文件读写/替换
        - 交互工具：用户追问确认

        ## 环境智能感知

        - 任务启动时自动获取 {{ current_project }} 全文件递归列表
        - 文件结构洞察：
            * 目录/文件名 → 项目组织逻辑
            * 文件扩展名 → 技术栈标识
        - 定向探查：
            * 使用 list_files 探索外部目录
            * recursive=true：递归获取嵌套结构
            * recursive=false：快速扫描顶层（如桌面目录）

        ## 深度代码分析能力

        - 上下文搜索：
            * execute_command（grep） 输出富含上下文的结果
            * 适用场景：理解代码模式，查找特定实现，识别需要重构的区域
        - 定义拓扑分析：
            * list_code_definition_names 提取目录顶层源码定义
            * 关键价值：理清代码模块间关系
            * 需多次调用构建完整认知图谱

        ## 标准工作流示例

        ```mermaid
        graph LR
        A[初始环境分析] --> B[源码定义解析]
        B --> C[文件精读]
        C --> D[变更设计]
        D --> E[replace_in_file执行]
        E --> F[grep全局验证]
        ```

        ## CLI命令执行规范

        - 随时触发：execute_command 支持任意合法命令
        - 强制说明：必须解释每条命令的作用
        - 最佳实践：
            * 首选复杂CLI命令而非脚本
            * 允许交互式/长时运行命令
            * 每个命令在新终端实例运行
        - 状态同步：后台运行命令状态实时更新

        =====

        # 核心规则

        ## 工作目录

        - 当前工作目录：{{current_project}}
        - 禁止操作：
            * [!] 不可使用 cd 切换目录
            * [!] 不可使用 ~ 或 $HOME 指代家目录

        ## 强制搜索规范

        - 编辑前必须搜索：任何文件编辑前必须通过 list_files / execute_command（grep） 探查上下文依赖，使用模式，关联引用
        - 修改后必验证：变更后必须通过搜索工具验证确认代码有无残留引用，新代码是否与现有模式正确集成

        ## 强制笔记规则

        - 任务开始时，必须使用 recall_memory 检索是否有相关任务的需求分析过程，AC模块信息，以及任务经验总结。
            * 检索笔记时可以使用多个关键词（关键词可以根据任务需求自由发散），且必须使用空格分割关键词
            * 注意：如果同一个代码文件出现多个AC模块，或者类似的需求出现了多次总结，以最新日期为准
        - 在阅读代码文件后，必须使用 record_memory 记录生成的AC模块（代码自描述文档）。
        - 任务完成后，必须使用 record_memory 记录任务完成情况和工作总结。
        - 如果未按上述规则使用笔记系统，将导致任务消耗更多的 tokens。

        ## CLI命令执行铁律

        - 环境适配：
            * 执行前必须分析 SYSTEM INFORMATION
            * 确保命令兼容用户系统
        - 跨目录操作：
            * cd 目标路径 && 执行命令
        - 输出处理：
            * 未见到预期输出时默认执行成功
            * 需原始输出时用 ask_followup_question 申请

        ## 文件操作准则

        - 新建项目：
            * 创建专属项目目录（除非用户指定）
            * 自动生成必要父目录
            * 默认构建可直接运行的HTML/CSS/JS应用
        - 修改文件：
            * 直接使用 replace_in_file/write_to_file
            * 无需前置展示变更
        - 替换规范：
            * [!]SEARCH块必须包含整行内容
            * [!]多替换块按文件行序排列

        ## 用户交互规范

        - 问题最小化：
            * 优先用工具替代提问
            * 必须提问时使用 ask_followup_question
            * 问题需精准简洁
        - 完成标识：
            * 任务完成必须调用attempt_completion
            * 结果展示禁止包含问题或继续对话请求
        - 表达禁令：
            * 禁止"Great/Certainly"等闲聊开头
            * 必须直接技术表述（例："CSS已更新"）

        ## 环境信息处理

        - environment_details 自动附加于用户消息后
        - 性质认知：
            * 非用户主动提供
            * 仅作背景参考
        - 终端状态检查：
            * 执行命令前检查 "Actively Running Terminals"
            * 避免重复启动已运行服务

        ## 高级能力规范

        - 公式展示：
            * 行内公式：$E=mc^2$
            * 块级公式：$$\frac{d}{dx}e^x = e^x$$
        - 图表嵌入：
            * 使用Mermaid语法生成流程图/图表
        - 知识盲区：
            * 可以询问用户，或者调用MCP/RAG服务获取未知概念信息

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

        目标

        你需迭代式完成任务：将任务拆解为清晰步骤，并有序执行。

        执行步骤：

        1. 分析任务，设定目标：解析用户任务，设定明确可行的子目标，并按逻辑排序优先级。
        2. 按序执行目标：
            - 依序完成各目标（每个目标对应一个解决步骤）。
            - 执行中会获知进度（已完成/待完成）。
            - 每个目标步骤中，至多使用一个工具。
        3. 工具调用规范：
            - 调用工具前，必须在 <thinking></thinking> 标签内分析：
                a. 分析 environment_details 提供的文件结构，获取上下文。
                b. 判断哪个工具最适合当前目标。
                c. 严格检查工具必填参数：
                    * 用户是否直接提供？
                    * 否可根据上下文明确推断出参数值？
                    * 若任一必填参数缺失或无法推断：禁止调用工具，立即使用 ask_followup_question 工具向用户询问缺失信息。
                d. 可选参数未提供时，无需询问。
            - 仅当所有必填参数齐备或可明确推断后，才关闭思考标签并调用工具。
        4. 任务完成与展示：
            - 任务完成后，必须使用 attempt_completion 工具向用户展示结果。
            - 可附带相关 CLI 命令（如 open index.html）直观呈现成果（尤其适用于网页开发）。
        5. 处理反馈：
            - 用户反馈可用于改进和重试。
            - 避免无意义的来回对话，回应结尾禁止提问或主动提供进一步帮助。
        6. 核心执行原则：
            - 务必从全面搜索与探索开始！
            - 对代码相关任务：
                a. 先用 list_files 了解结构。
                b. 再用 execute_command（grep） 搜索关键模式。
                c. 最后用 read_file 细读上下文。
            - 完成以上探索后，方可进行修改。
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
            "file_paths_str": file_paths_str
        }

    def analyze(
            self, request: AgenticEditRequest
    ) -> Generator[Union[LLMOutputEvent, LLMThinkingEvent, ToolCallEvent, ToolResultEvent, CompletionEvent, ErrorEvent,
                         WindowLengthChangeEvent, TokenUsageEvent, PlanModeRespondEvent] | None, None, None]:

        system_prompt = self._analyze.prompt(request)
        printer.print_key_value(
            {"长度(tokens)": f"{len(system_prompt)}"}, title="系统提示词"
        )

        conversations = [
            {"role": "system", "content": system_prompt}
        ]

        if self.conversation_config.action == "resume":
            current_conversation = self.conversation_manager.get_current_conversation()
            # 如果继续的是当前的对话，将其消息加入到 conversations 中
            if current_conversation and current_conversation.get('messages'):
                for message in current_conversation['messages']:
                    # 确保消息格式正确（包含 role 和 content 字段）
                    if isinstance(message, dict) and 'role' in message and 'content' in message:
                        conversations.append({
                            "role": message['role'],
                            "content": message['content']
                        })
                printer.print_text(f"恢复对话，已有 {len(current_conversation['messages'])} 条现有消息", style="green")
        if self.conversation_manager.get_current_conversation_id() is None:
            conv_id = self.conversation_manager.create_conversation(name=self.conversation_config.query,
                                                                    description=self.conversation_config.query)
            self.conversation_manager.set_current_conversation(conv_id)

        self.conversation_manager.set_current_conversation(self.conversation_manager.get_current_conversation_id())

        conversations.append({
            "role": "user", "content": request.user_input
        })

        self.conversation_manager.append_message_to_current(
            role="user",
            content=request.user_input,
            metadata={})

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
                conversations=self.agentic_pruner.prune_conversations(deepcopy(conversations)),
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
                    printer.print_panel(content=f"tool_xml \n{tool_xml}", title=f"🛠️ 工具触发: {tool_name}",
                                        center=True)

                    # 记录当前对话的token数量
                    conversations.append({
                        "role": "assistant",
                        "content": assistant_buffer + tool_xml
                    })
                    self.conversation_manager.append_message_to_current(
                        role="assistant",
                        content=assistant_buffer + tool_xml,
                        metadata={})
                    assistant_buffer = ""  # Reset buffer after tool call

                    # 计算当前对话的总 token 数量并触发事件
                    current_conversation_str = json.dumps(conversations, ensure_ascii=False)
                    total_tokens = count_tokens(current_conversation_str)
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
                    self.conversation_manager.append_message_to_current(
                        role="user",
                        content=error_xml,
                        metadata={})

                    # 计算当前对话的总 token 数量并触发事件
                    current_conversation_str = json.dumps(conversations, ensure_ascii=False)
                    total_tokens = count_tokens(current_conversation_str)
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
                        self.conversation_manager.append_message_to_current(
                            role="assistant", content=assistant_buffer, metadata={})
                    elif last_message["role"] == "assistant":
                        printer.print_text("追加已存在的 Assistant 消息")
                        last_message["content"] += assistant_buffer

                    # 计算当前对话的总 token 数量并触发事件
                    current_conversation_str = json.dumps(conversations, ensure_ascii=False)
                    total_tokens = count_tokens(current_conversation_str)
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
                self.conversation_manager.append_message_to_current(
                    role="user",
                    content="NOTE: You must use an appropriate tool (such as read_file, write_to_file, "
                            "execute_command, etc.) or explicitly complete the task (using attempt_completion). Do "
                            "not provide text responses without taking concrete actions. Please select a suitable "
                            "tool to continue based on the user's task.",
                    metadata={})

                # 计算当前对话的总 token 数量并触发事件
                current_conversation_str = json.dumps(conversations, ensure_ascii=False)
                total_tokens = count_tokens(current_conversation_str)
                yield WindowLengthChangeEvent(tokens_used=total_tokens)
                # 继续循环，让 LLM 再思考，而不是 break
                printer.print_text("持续运行 LLM 交互循环（保持不中断）", style="green")
                continue

        printer.print_text(f"AgenticEdit 分析循环已完成，共执行 {iteration_count} 次迭代.")
        save_formatted_log(self.args.source_dir, json.dumps(conversations, ensure_ascii=False), "agentic_conversation")

    def apply_pre_changes(self):
        uncommitted_changes = get_uncommitted_changes(self.args.source_dir)
        if uncommitted_changes != "No uncommitted changes found.":
            raise Exception("代码中包含未提交的更新,请执行/commit")

    def apply_changes(self, request: AgenticEditRequest):
        """ Apply all tracked file changes to the original project directory. """
        changes = get_uncommitted_changes(self.args.source_dir)

        if changes != "No uncommitted changes found.":
            # if not self.args.skip_commit:
            # 有变更才进行下一步操作
            prepare_chat_yaml(self.args.source_dir)  # 复制上一个序号的 yaml 文件, 生成一个新的聊天 yaml 文件

            latest_yaml_file = get_last_yaml_file(self.args.source_dir)

            if latest_yaml_file:
                yaml_config = {
                    "include_file": ["./base/base.yml"],
                    "skip_build_index": self.args.skip_build_index,
                    "skip_confirm": self.args.skip_confirm,
                    "chat_model": self.args.chat_model,
                    "code_model": self.args.code_model,
                    "auto_merge": self.args.auto_merge,
                    "context": "",
                    "query": request.user_input,
                    "urls": [],
                    "file": latest_yaml_file
                }
                yaml_content = convert_yaml_config_to_str(yaml_config=yaml_config)
                execute_file = os.path.join(self.args.source_dir, "actions", latest_yaml_file)
                with open(os.path.join(execute_file), "w") as f:
                    f.write(yaml_content)

                md5 = hashlib.md5(yaml_content.encode("utf-8")).hexdigest()

                try:
                    commit_message = commit_changes(
                        self.args.source_dir, f"auto_coder_{latest_yaml_file}_{md5}",
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
            self.apply_pre_changes()  # 在开始 Agentic Edit 之前先判断是否有未提交变更,有变更则直接退出
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
                    display_content = self.get_tool_display_message(event.tool)
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
                        if len(_content) > 500:
                            return f"{_content[:200]}\n......\n{_content[-200:]}"
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
                                content_str = _format_content(json.dumps(result.content, indent=2, ensure_ascii=False))
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

                                content_str = _format_content(str(result.content))
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
                        self.apply_changes(request)
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
