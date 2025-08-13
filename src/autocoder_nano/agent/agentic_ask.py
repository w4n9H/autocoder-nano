import hashlib
import json
import os
import time
import xml.sax.saxutils
from copy import deepcopy
from typing import Generator, Union

from rich.markdown import Markdown

from autocoder_nano.actypes import AutoCoderArgs, SourceCodeList, SingleOutputMeta
from autocoder_nano.agent.agent_base import BaseAgent
from autocoder_nano.agent.agentic_edit_tools import (  # Import specific resolvers
    BaseToolResolver,
    ExecuteCommandToolResolver, ReadFileToolResolver,
    SearchFilesToolResolver, ListFilesToolResolver,
    ListCodeDefinitionNamesToolResolver, AskFollowupQuestionToolResolver,
    AttemptCompletionToolResolver, PlanModeRespondToolResolver,
    RecordMemoryToolResolver, RecallMemoryToolResolver
)
from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.context import get_context_manager, ConversationsPruner
from autocoder_nano.core import AutoLLM, prompt, stream_chat_with_continue
from autocoder_nano.rag.token_counter import count_tokens
from autocoder_nano.utils.config_utils import prepare_chat_yaml, get_last_yaml_file, convert_yaml_config_to_str
from autocoder_nano.utils.formatted_log_utils import save_formatted_log
from autocoder_nano.utils.git_utils import get_uncommitted_changes, commit_changes
from autocoder_nano.utils.printer_utils import Printer

printer = Printer()

# Map Pydantic Tool Models to their Resolver Classes
ASK_TOOL_RESOLVER_MAP: Dict[Type[BaseTool], Type[BaseToolResolver]] = {
    ExecuteCommandTool: ExecuteCommandToolResolver,
    ReadFileTool: ReadFileToolResolver,
    SearchFilesTool: SearchFilesToolResolver,
    ListFilesTool: ListFilesToolResolver,
    ListCodeDefinitionNamesTool: ListCodeDefinitionNamesToolResolver,
    AskFollowupQuestionTool: AskFollowupQuestionToolResolver,
    AttemptCompletionTool: AttemptCompletionToolResolver,  # Will stop the loop anyway
    PlanModeRespondTool: PlanModeRespondToolResolver,
    RecordMemoryTool: RecordMemoryToolResolver,
    RecallMemoryTool: RecallMemoryToolResolver
}


class AgenticAsk(BaseAgent):
    def __init__(
            self, args: AutoCoderArgs, llm: AutoLLM, files: SourceCodeList, history_conversation: List[Dict[str, Any]],
            conversation_config: Optional[AgenticEditConversationConfig] = None
    ):
        super().__init__(args, llm)
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

    @prompt()
    def _analyze(self, request: AgenticEditRequest):
        """
        # 技术型产品经理Agent - PM SpecBuilder Pro

        ## 核心定位
        - 三重能力：技术可行性分析 × 用户体验设计 × 业务价值验证
        - 工作模式：工具驱动的渐进式需求澄清（强交互式）
        - 核心指标：每次交互提升需求成熟度≥15%

        =====
        # 交互协议

        ## 第一步：需求原子化解构

        1. 解析用户原始需求
        2. 使用工具分析项目
        3. 自动识别：
           - 核心功能模块（≥3个关键组件）
           - 技术风险点（高/中/低）
           - 业务模糊项

        ## 第二步：三维深度追问（每次≤3问）

        1. 业务维度
        - 价值闭环：此功能如何提升核心指标？
        - 成功指标：如何量化效果？（例：DAU提升15%）

        2. 技术维度
        - 系统集成：需对接哪些现有模块？
        - 性能边界：预期峰值QPS/数据量级？

        3. 体验维度
        - 异常处理：在极端场景如何处理？
        - 交互反馈：哪些操作需视觉反馈？

        ## 第三步：动态原型构建

        ```markdown
        ## 需求原型 v0.[迭代号]
        ### 功能骨架
        | 模块        | 技术方案               | 依赖资源       | 成本系数 |
        |------------|-----------------------|---------------|---------|
        | 模块A       | 核心技术路径           | 关键依赖        |    1    |
        | 模块B       | 核心技术路径           | 关键依赖        |    4    |

        ### 待验证清单
        1. [技术决策] 问题描述 → 影响说明
        2. [体验缺陷] 问题描述 → 影响说明
        3. [业务规则] 问题描述 → 影响说明
        ```

        ## 第四步：技术债务评估

        每次响应必须包含：
        - 技术债务增量：+[0.1-0.5]年
        - 复用推荐：[组件名]@[路径] 匹配度[XX%]

        =====
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
        - query（必填）：你检索笔记的提问，检索笔记时可以使用多个关键词（关键词可以根据任务需求自由发散），且必须使用空格分割关键词
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

        # 工具使用指南
        1. 开始提问前务必进行全面搜索和探索，
            * 用搜索工具（list_files，execute_command + grep 命令）了解代码库结构，模式和依赖
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
        - 提问前探查上下文进行需求结构：定位符号、函数、导入、使用模式
        - 模式分析：理解编码规范与现有实现

        ## 关键命令模式：
        - 提问前探查上下文示例：
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
        - 分析核心功能模块，主要技术风险，业务矛盾点

        =====
        # 工具使用策略

        ## 各阶段工具调用

        1. 需求解构阶段：

        - 使用笔记检索历史需求
        <recall_memory>
        <query>相关历史需求分析(空格切分关键词)</query>
        </recall_memory>

        - 判断项目类型
        <execute_command>
        <command>find src/ -type f | awk -F. '!/\./ {print "no"} /\./ {print $NF}' | sort | uniq -c | sort -nr | head -10</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 了解项目结构
        <execute_command>
        <command>ls -la</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        - 查询关键函数
        <execute_command>
        <command>grep -Rn --exclude-dir={.auto-coder,.git} "*FunctionName" . | head -10</command>
        <requires_approval>false</requires_approval>
        </execute_command>

        注意：
        在收到用户需求后，你可以使用所有读取工具来分析这个项目，基于你对项目的了解，拆解用户的需求，同时不停的和用户交互，询问项目相关的问题
        最终目标是得到一个高度完整的方案

        2. 技术维度追问：

        - 代码库检索验证技术方案
        <search_files>
        <path>src/</path>
        <regex>关键技术关键词</regex>
        <file_pattern>.js|.ts|.py</file_pattern>
        </search_files>

        3. 高成本方案验证：

        - 执行可行性测试命令
        <execute_command>
        <command>基准测试命令</command>
        <requires_approval>true</requires_approval>
        </execute_command>

        ## 工具熔断机制

        - 工具连续失败2次时启动备选方案
        - 自动标注行业惯例方案供用户确认

        ## 规格书生成流程

        1. 生成方案后, 执行业务闭环确认：
        <ask_followup_question>
        <question>请确认业务规则完整性</question>
        </ask_followup_question>

        3. 生成详细方案并保存为笔记：
        <record_memory>
        <content>最终需求规格文档</content>
        </record_memory>

        =====
        # 约束规则

        ## 绝对禁止
        - 未使用工具验证高成本(成本系数≥4)方案
        - 跳过现有组件检索直接设计
        - 在工具未返回时假设系统状态
        - 禁止修改文件，禁止修改文件，禁止修改文件，重要的事情说三遍
        - 仅需要生成方案并由确认即可

        ## 必须执行
        - 技术方案必须附带验证命令原型
        - 复用匹配度<60%时标注高风险
        - 每次响应更新原型版本号(v0.1→v0.2→...)

        =====
        # 关键机制

        1. 渐进式澄清：
            - 需求原型从v0.1开始迭代
            - 每轮聚焦解决1个高风险项

        2. 技术红绿灯：
            - 架构冲突 → 立即停止
            - 成本系数≥3 → 需用户确认
            - 方案可行 → 自动推进
            - 需求较为简单 → 自动推进

        3. 成本感知系统：
            - 成本系数：1(微调)-5(架构改造)
            - 高成本方案必须预验证

        =====

        ## 示例交互
        用户：需要实现实时协作编辑功能

        Agent：
        <recall_memory>
        <query>历史文档协作功能方案</query>
        </recall_memory>

        （用户返回历史记录后）

        需求解构：
        - 核心模块：操作转换(OT)、实时同步、冲突解决
        - 高风险点：OT算法实现（技术风险-高）

        技术维度追问：
        1. 是否复用现有OT模块？
        2. 预期同时编辑用户量级？
        3. 需支持离线编辑同步吗？

        当前原型 v0.1：
        | 模块        | 技术方案               | 成本系数 |
        |-------------|------------------------|----------|
        | 操作转换    | JSON diff-patch        | 4    |
        | 实时同步    | WebSocket+消息队列     | 3     |

        技术评估：
        - 复用检查：OTUtils@/src/lib/utils 匹配度40% → 高风险
        - 验证命令：`负载测试 --users=100`
        ```
        """

    def analyze(self, request: AgenticEditRequest) -> (
            Generator)[Union[LLMOutputEvent, LLMThinkingEvent, ToolCallEvent, ToolResultEvent, CompletionEvent,
                             ErrorEvent, WindowLengthChangeEvent, TokenUsageEvent,
                             PlanModeRespondEvent] | None, None, None]:
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
                    resolver_cls = ASK_TOOL_RESOLVER_MAP.get(type(tool_obj))
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
                    yield event
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

        printer.print_text(f"AgenticAsk 分析循环已完成，共执行 {iteration_count} 次迭代.")
        save_formatted_log(self.args.source_dir, json.dumps(conversations, ensure_ascii=False),
                           "agentic_ask_conversation")

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
            items={"项目名": f"{project_name}", "用户目标": f"{request.user_input}"}, title="Agentic Ask 开始运行"
        )

        # 用于累计TokenUsageEvent数据
        accumulated_token_usage = {
            "model_name": "",
            "input_tokens": 0,
            "output_tokens": 0,
        }

        try:
            self.apply_pre_changes()  # 在开始 Agentic Ask 之前先判断是否有未提交变更,有变更则直接退出
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
                    # 不显示 AttemptCompletionTool 结果
                    if isinstance(event.tool, AttemptCompletionTool):
                        continue

                    # Ask Agentic RecordMemoryTool 结果需要保存
                    if isinstance(event.tool, RecordMemoryTool):
                        ask_file = os.path.join(self.args.source_dir, ".auto-coder", "ask.txt")
                        with open(os.path.join(ask_file), "w") as f:
                            f.write(event.tool.content)

                    tool_name = type(event.tool).__name__
                    # Use the new internationalized display function
                    display_content = self.get_tool_display_message(event.tool)
                    printer.print_panel(content=display_content, title=f"🛠️ 工具调用: {tool_name}", center=True)

                elif isinstance(event, ToolResultEvent):
                    # 不显示 AttemptCompletionTool 和 PlanModeRespondTool 结果
                    if event.tool_name == "AttemptCompletionTool":
                        continue
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
                    # Ask 模式不会对代码进行变更,故放弃合并
                    # try:
                    #     self.apply_changes(request)
                    # except Exception as e:
                    #     printer.print_text(f"Error merging shadow changes to project: {e}", style="red")

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
            printer.print_panel(content=f"FATAL ERROR: {err}", title="🔥 Agentic Ask 运行错误", center=True)
            raise err
        finally:
            printer.print_text("Agentic Ask 结束", style="green")
