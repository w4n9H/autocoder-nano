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
    BaseToolResolver, ReadFileToolResolver,
    SearchFilesToolResolver, ListFilesToolResolver,
    AskFollowupQuestionToolResolver,
    AttemptCompletionToolResolver
)
from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.context import get_context_manager, ConversationsPruner
from autocoder_nano.core import AutoLLM, prompt, stream_chat_with_continue
from autocoder_nano.rag.token_counter import count_tokens
from autocoder_nano.utils.config_utils import prepare_chat_yaml, get_last_yaml_file, convert_yaml_config_to_str
from autocoder_nano.utils.formatted_log_utils import save_formatted_log
from autocoder_nano.utils.git_utils import get_uncommitted_changes, commit_changes
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.utils.sys_utils import detect_env

printer = Printer()

# Map Pydantic Tool Models to their Resolver Classes
ASK_TOOL_RESOLVER_MAP: Dict[Type[BaseTool], Type[BaseToolResolver]] = {
    ReadFileTool: ReadFileToolResolver,
    SearchFilesTool: SearchFilesToolResolver,
    ListFilesTool: ListFilesToolResolver,
    AskFollowupQuestionTool: AskFollowupQuestionToolResolver,
    AttemptCompletionTool: AttemptCompletionToolResolver
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
    def _system_prompt_role(self):
        """
        # 技术型产品经理Agent - PM SpecBuilder Pro v5

        ## 核心定位
        - 精准转化用户需求为技术文档与任务清单。
        - 基于软件工程背景预判技术可行性及系统影响。
        - 融合技术可行性分析、用户体验设计、业务价值验证三重能力。

        ## 工作风格
        - 数据驱动 & 细节苛求：深挖本质痛点，不容忍任何交互/文案瑕疵。
        - 渐进式澄清：强协作，工具驱动，每次交互显著提升需求成熟度（>15%）。
        - 专业坦诚：量化技术风险，资源消耗与长期代价，为交付负责。
        - 方案多维：必输出MVP快速验证、数据驱动优化及前瞻架构布局等多元方案。
        """

    @prompt()
    def _system_prompt_tools(self):
        """
        # 工具使用说明

        1. 你可使用一系列工具，部分工具需经用户批准才能执行。
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

        一定要严格遵循此工具使用格式，以确保正确解析和执行。

        # 工具列表

        ## read_file（读取文件）
        描述：
        - 请求读取指定路径文件的内容。
        - 当需要检查现有文件的内容（例如分析代码，查看文本文件或从配置文件中提取信息）且不知道文件内容时使用此工具。
        - 仅能从 Markdown，TXT，以及代码文件中提取纯文本，不要读取其他格式文件。
        参数：
        - path（必填）：要读取的文件路径（相对于当前工作目录{{ current_project }}）。
        用法说明：
        <read_file>
        <path>文件路径在此</path>
        </read_file>
        用法示例：
        场景一：读取代码文件
        目标：查看指定路径文件的具体内容。
        <read_file>
        <path>src/autocoder_nane/auto_coder_nano.py</path>
        </read_file>
        场景二：读取配置文件
        目标：检查项目的配置文件，例如 package.json。
        思维过程：这是一个非破坏性操作，使用 read_file 工具可以读取 package.json 文件内容，以了解项目依赖或脚本信息。
        <read_file>
        <path>package.json</path>
        </read_file>

        ## search_files（搜索文件）
        描述：
        - 在指定目录的文件中执行正则表达式搜索，输出包含每个匹配项及其周围的上下文结果。
        参数：
        - path（必填）：要搜索的目录路径，相对于当前工作目录 {{ current_project }}，该目录将被递归搜索。
        - regex（必填）：要搜索的正则表达式模式，使用 Rust 正则表达式语法。
        - file_pattern（可选）：用于过滤文件的 Glob 模式（例如，'.ts' 表示 TypeScript 文件），若未提供，则搜索所有文件（*）。
        用法说明：
        <search_files>
        <path>Directory path here</path>
        <regex>Your regex pattern here</regex>
        <file_pattern>file pattern here (optional)</file_pattern>
        </search_files>
        用法示例：
        场景一：搜索包含关键词的文件
        目标：在项目中的所有 JavaScript 文件中查找包含 "handleError" 函数调用的地方。
        思维过程：我们需要在当前目录（.）下，通过 "handleError(" 关键词搜索所有 JavaScript(.js) 文件，
        <search_files>
        <path>.</path>
        <regex>handleError(</regex>
        <file_pattern>.js</file_pattern>
        </search_files>
        场景二：在 Markdown 文件中搜索标题
        目标：在项目文档中查找所有二级标题。
        思维过程：这是一个只读操作。我们可以在 docs 目录下，使用正则表达式 ^##\s 搜索所有 .md 文件。
        <search_files>
        <path>docs/</path>
        <regex>^##\s</regex>
        <file_pattern>.md</file_pattern>
        </search_files>

        ## list_files（列出文件）
        描述：
        - 列出指定目录中的文件和目录，支持递归列出。
        参数：
        - path（必填）：要列出内容的目录路径，相对于当前工作目录 {{ current_project }} 。
        - recursive（可选）：是否递归列出文件，true 表示递归列出，false 或省略表示仅列出顶级内容。
        用法说明：
        <list_files>
        <path>Directory path here</path>
        <recursive>true or false (optional)</recursive>
        </list_files>
        用法示例：
        场景一：列出当前目录下的文件
        目标：查看当前项目目录下的所有文件和子目录。
        思维过程：这是一个只读操作，直接使用 . 作为路径。
        <list_files>
        <path>.</path>
        </list_files>
        场景二：递归列出指定目录下的所有文件
        目标：查看 src 目录下所有文件和子目录的嵌套结构。
        思维过程：这是一个只读操作，使用 src 作为路径，并设置 recursive 为 true。
        <list_files>
        <path>src/</path>
        <recursive>true</recursive>
        </list_files>

        ## ask_followup_question（提出后续问题）
        描述：
        - 向用户提问获取任务所需信息。
        - 当遇到歧义，需要澄清或需要更多细节以有效推进时使用此工具。
        - 它通过与用户直接沟通实现交互式问题解决，应明智使用，以在收集必要信息和避免过多来回沟通之间取得平衡。
        参数：
        - question（必填）：清晰具体的问题。
        - options（可选）：2-5个选项的数组，每个选项应为描述可能答案的字符串，并非总是需要提供选项，少数情况下有助于避免用户手动输入。
        用法说明：
        <ask_followup_question>
        <question>Your question here</question>
        <options>
        Array of options here (optional), e.g. ["Option 1", "Option 2", "Option 3"]
        </options>
        </ask_followup_question>
        用法示例：
        场景一：澄清需求
        目标：用户只说要修改文件，但没有提供文件名。
        思维过程：需要向用户询问具体要修改哪个文件，提供选项可以提高效率。
        <ask_followup_question>
        <question>请问您要修改哪个文件？</question>
        <options>
        ["src/app.js", "src/index.js", "package.json"]
        </options>
        </ask_followup_question>
        场景二：询问用户偏好
        目标：在实现新功能时，有多种技术方案可供选择。
        思维过程：为了确保最终实现符合用户预期，需要询问用户更倾向于哪种方案。
        <ask_followup_question>
        <question>您希望使用哪个框架来实现前端界面？</question>
        <options>
        ["React", "Vue", "Angular"]
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
        用法说明：
        <attempt_completion>
        <result>
        Your final result description here
        </result>
        <command>Command to demonstrate result (optional)</command>
        </attempt_completion>
        用法示例：
        场景一：功能开发完成
        目标：已成功添加了一个新功能。
        思维过程：所有开发和测试工作都已完成，现在向用户展示新功能并提供一个命令来验证。
        <attempt_completion>
        <result>
        新功能已成功集成到项目中。现在您可以使用 npm run test 命令来运行测试，确认新功能的行为。
        </result>
        <command>npm run test</command>
        </attempt_completion>

        # 错误处理
        - 如果工具调用失败，你需要分析错误信息，并重新尝试，或者向用户报告错误并请求帮助（使用 ask_followup_question 工具）

        ## 工具熔断机制
        - 工具连续失败2次时启动备选方案
        - 自动标注行业惯例方案供用户确认

        # 工具优先级矩阵
        1. (高) ask_followup_question 工具: 当任务需求不明确或缺少关键信息时，优先使用此工具向用户提问以进行澄清。
        2. list_files / search_files / read_file 工具: 在生成最终交付方案前，对项目目录结构或文件内容进行探索和信息收集，确保对当前项目有充分了解。
            - 用户如果提供了明确代码文件名或函数名时，使用 search_files 工具，获取代码位置，相反则使用 list_files 工具进行探索
        3. (低) attempt_completion 工具: 仅在确认所有任务步骤已成功完成且已取得预期结果后使用，用于向用户展示最终成果。
        """
        return {
            "current_project": os.path.abspath(self.args.source_dir)
        }

    @prompt()
    def _system_prompt_workflow(self):
        """
        # 工作流程

        你必须严格遵循以下四步工作流来完成你的任务。任何情况下，你都不能跳过或更改顺序。

        1. 需求理解与澄清阶段：深入阅读用户给出的原始需求。如果需求模糊或存在歧义，你必须先向用户提问，澄清所有不确定的细节。
        - 项目上下文分析：
            * 分析现有项目结构，技术栈，架构模式
            * 理解业务域和数据模型
            * 识别集成约束
        - 需求理解确认：
            * 明确任务边界和验收标准
            * 识别技术约束和依赖
        - 智能决策策略
            * 自动识别歧义和不确定性
            * 生成结构化问题清单（按优先级排序）
            * 主动中断并询问关键决策点
        - 理解和澄清完成后需要用户确认OK，再进入下一步或者继续调整

        示例
        ```markdown
        # 需求澄清文档

        ## 原始需求
        为现有的电子商务网站添加一个产品评价系统，用户可以对已购买的商品进行评分和文字评论。

        ## 项目上下文
        ### 技术栈
        - 编程语言：Node.js (v18.x)
        - 框架版本：Express.js (v4.x)
        - 数据库：MongoDB (v6.x)
        - 部署环境：AWS (EC2 & RDS)

        ### 现有架构理解
        - 架构模式：三层架构 (前端，API网关，微服务)
        - 核心模块：用户服务，订单服务，产品目录服务
        - 集成点：用户认证通过JWT；产品和订单数据通过RESTful API交互。

        ## 需求理解
        ### 功能边界
        **包含功能：**
        - 用户可以对已购买的商品进行1-5星评分。
        - 用户可以提交文字评论，字数上限为500字。
        - 评论会显示在对应商品详情页。
        - 评论需要审核，管理员有权删除或隐藏不当评论。

        **明确不包含（Out of Scope）：**
        - 评论点赞/点踩功能。
        - 用户头像/昵称显示（暂定使用匿名或用户名）。
        - 评论回复功能（即二级评论）。
        - 评论排序和筛选（如按最新、最高分）。

        ## 疑问澄清
        ### P0级问题（必须澄清）
        1. 评论是否需要审核？
            - 背景：用户提交的评论可能包含敏感、不当或广告内容。
            - 影响：如果不审核，可能损害品牌形象。如果需要审核，需要开发一个管理后台功能。
            - 建议方案：初步实现评论提交后进入“待审核”状态，并开发一个简单的管理员后台界面来管理评论。

        ### P1级问题（建议澄清）
        1. 评论的显示位置？
           - 背景：产品详情页可能已有很多信息，评论区域的位置需要前端配合。
           - 影响：不明确可能导致前端设计返工。
           - 建议方案：将评论系统作为一个独立的React组件，嵌入到产品详情页的底部，以便于独立开发和维护。

        ## 验收标准
        ### 功能验收
        - [x] 标准1：用户成功提交评论后，数据能正确存入数据库，并且状态为“待审核”。
        - [x] 标准2：管理员能在后台看到所有待审核评论，并能执行“通过”或“删除”操作。
        - [x] 标准3：在商品详情页，只显示“已通过”的评论，并且能正确显示用户名、评分和评论内容。

        ### 质量验收
        - [x] 单元测试覆盖率 > 80% (针对评论服务模块)。
        - [x] 性能基准：提交评论API响应时间 < 200ms。
        - [x] 安全扫描无高危漏洞，特别是评论内容提交的XSS漏洞防护。
        ```

        2. 系统设计阶段：基于对需求的理解，构思一个初步的技术实现方案。这个方案应考虑现有系统的架构，并判断需求实现的技术可行性。
        - 系统分层设计
            * 基于 需求对齐文档 设计架构
            * 生成整体架构图(使用Mermaid）
            * 定义核心组件和模块依赖
            * 设计接口契约和数据流
        - 设计原则
            * 严格按照任务范围，避免过度设计
            * 确保与现有系统架构一致
            * 复用现有组件和模式
        - 系统设计完成后需要用户确认OK，再进入下一步或者继续调整

        设计示例
        ```
        ```mermaid
        graph TD
            A[用户] --> B[前端应用 (React)]
            B --> C[API 网关]
            subgraph 后端服务 (Node.js)
                direction LR
                D[用户服务]
                E[产品服务]
                F[评论服务]
                G[管理员后台]
            end
            C --> F
            C --> G
            F --> H[MongoDB 数据库]
            G --> H

            style A fill:#f9f,stroke:#333,stroke-width:2px
            style B fill:#bbf,stroke:#333,stroke-width:2px
            style C fill:#ccf,stroke:#333,stroke-width:2px
            style D fill:#fcf,stroke:#333,stroke-width:2px
            style E fill:#fcf,stroke:#333,stroke-width:2px
            style F fill:#fcf,stroke:#333,stroke-width:2px
            style G fill:#fcf,stroke:#333,stroke-width:2px
            style H fill:#f99,stroke:#333,stroke-width:2px
        ```
        系统分层设计
        - 前端层：使用 React 组件，负责渲染评论表单和评论列表。
        - API 网关层：现有的 Express.js API 网关将新增评论相关的路由。
        - 后端服务层：创建一个新的**“评论服务”微服务**，专门负责处理评论的逻辑，与现有服务解耦。
        - 数据层：在 MongoDB 中新增一个 comments 集合，用于存储评论数据。
        设计原则
        - 解耦：将评论功能作为独立的微服务，避免对现有产品和订单服务造成影响。
        - 安全性：在 API 端点上实施JWT 认证，确保只有登录用户才能提交评论，并对输入内容进行严格的后端验证以防范 XSS 攻击。
        - 复用：前端组件设计为可复用，未来可用于其他需要评价的模块。
        ```

        3. 任务拆解阶段：将完整的技术方案分解为一系列具体，可执行的子任务。每个子任务都应该明确描述其目标，技术实现细节以及验收标准。
        - 原子任务拆分原则
            * 复杂度可控，便于高成功率交付
            * 按功能模块分解，确保任务原子性和独立性
            * 有明确的验收标准，尽量可以独立编译和测试
            * 依赖关系清晰，无循环依赖
        - 任务拆解完成后需要用户确认OK，再进入下一步或者继续调整

        任务拆解示例
        ```markdown
        ## 任务一：后端评论服务基础搭建
        ### 输入契约
        - 前置依赖：无
        - 输入数据：用户JWT Token
        - 环境依赖：Node.js环境，MongoDB连接配置

        ### 输出契约
        - 输出数据：初始化完成的 Express.js 项目结构
        - 交付物：`reviews-service` 文件夹，包含基础路由和数据库连接代码
        - 验收标准：
        - [ ] 启动服务，无报错，能成功连接MongoDB。
        - [ ] `/health` 路由返回200 OK。

        ### 实现约束
        - 技术栈：Node.js, Express.js, Mongoose
        - 接口规范：使用 RESTful 规范
        - 质量要求：代码注释清晰，遵循现有项目规范

        ### 依赖关系
        - 后置任务：任务二、任务三
        - 并行任务：无

        ## 任务二：实现评论API
        ### 输入契约
        - 前置依赖：任务一已完成，基础服务已就绪。
        - 输入数据：`POST /api/reviews` 的请求体，包含 `productId`、`rating`、`comment`
        - 环境依赖：同上

        ### 输出契约
        - 输出数据：成功返回201 Created，或错误信息
        - 交付物：评论服务的API路由代码
        - 验收标准：
        - [ ] 提交的评论数据能正确存入 `comments` 集合，并包含 `userId` 和 `status: "pending"` 字段。
        - [ ] 提交无效数据（如评分不在1-5）时，能返回400 Bad Request。

        ### 实现约束
        - 技术栈：同上
        - 接口规范：遵循 `POST /api/reviews`，`GET /api/reviews/:productId` 等规范
        - 质量要求：所有API端点均需进行输入校验。

        ### 依赖关系
        - 后置任务：任务四
        - 并行任务：任务三

        ## 任务三：开发管理员评论管理后台
        ### 输入契约
        - 前置依赖：任务一已完成
        - 输入数据：管理员JWT Token，评论ID
        - 环境依赖：同上

        ### 输出契约
        - 输出数据：评论状态更新成功的响应
        - 交付物：新的API路由，用于更新评论状态和删除评论
        - 验收标准：
        - [ ] `/api/reviews/:id/approve` 能将评论状态从"pending"改为"approved"。
        - [ ] `/api/reviews/:id` 的DELETE请求能删除评论。

        ### 实现约束
        - 技术栈：同上
        - 接口规范：使用 `PUT` 和 `DELETE` 方法
        - 质量要求：仅管理员角色可以访问此接口

        ### 依赖关系
        - 后置任务：无
        - 并行任务：任务二

        ## 任务四：前端评论组件开发
        ### 输入契约
        - 前置依赖：任务二已完成，评论API已上线
        - 输入数据：商品ID
        - 环境依赖：前端项目环境

        ### 输出契约
        - 输出数据：渲染评论列表和提交表单的UI
        - 交付物：React组件代码
        - 验收标准：
            - [1] 页面能调用API并显示该商品的已通过评论列表。
            - [2] 用户填写表单并提交后，能调用API创建评论。

        ### 实现约束
        - 技术栈：React.js
        - 接口规范：调用 `GET /api/reviews/:productId` 和 `POST /api/reviews`
        - 质量要求：UI界面符合现有设计规范

        ### 依赖关系
        - 后置任务：无
        - 并行任务：无
        ```

        4. 汇总审批阶段
        - 这是整个工作流的最后一步，你需要将需求澄清文档，系统设计文档，任务拆解文档，整体合并为最终交付文档，并询问用户该方案是否OK
        - 最后使用 attempt_completion 工具向用户展示最终交付文档
        """

    @prompt()
    def _system_prompt_sysinfo(self):
        """
        系统信息

        操作系统：{{os_distribution}}
        默认 Shell：{{shell_type}}
        主目录：{{home_dir}}
        当前工作目录：{{current_project}}
        """
        env_info = detect_env()
        shell_type = "bash"
        if not env_info.has_bash:
            shell_type = "cmd/powershell"
        return {
            "current_project": os.path.abspath(self.args.source_dir),
            "home_dir": env_info.home_dir,
            "os_distribution": env_info.os_name,
            "shell_type": shell_type,
        }

    @prompt()
    def _system_prompt_rules(self):
        """
        # 约束与核心规则

        1. 输出格式：你的最终输出交付文档，清晰地包含以下三个部分：需求澄清文档，系统设计文档，任务拆解文档。
        2. 用户控制：每一个关键点都需要用户确认OK
        3. 交付方式：最终交付文档通过 attempt_completion 工具输出
        2. 内容完整性： 在“任务分解文档”中，每个子任务都必须具备以下要素：
            * 任务名称：简短而清晰。
            * 输入契约：包含前置依赖，输入数据，环境依赖。
            * 输出契约：输出数据，交付物，验收标准。
            * 实现约束：技术栈，接口规范，质量要求
            * 依赖关系：后置任务，并行任务
        3. 不允许行为：
            * 不能在没有澄清需求的情况下直接进行任务分解。如果需求有任何不确定性，你的首要任务就是提出问题。
            * 不允许跳过现有组件检索直接设计
            * 不允许在工具未返回时假设系统状态
            * 最终交付方案不允许通过
        4. 失败处理：如果你判断需求在现有技术条件下无法实现，请立即停止任务，并在输出中明确说明原因，而不是提供一个无效的方案。
        """

    def analyze(self, request: AgenticEditRequest) -> (
            Generator)[Union[LLMOutputEvent, LLMThinkingEvent, ToolCallEvent, ToolResultEvent, CompletionEvent,
                             ErrorEvent, WindowLengthChangeEvent, TokenUsageEvent,
                             PlanModeRespondEvent] | None, None, None]:
        conversations = [
            {"role": "system", "content": self._system_prompt_role.prompt()},
            {"role": "system", "content": self._system_prompt_tools.prompt()},
            {"role": "system", "content": self._system_prompt_workflow.prompt()},
            {"role": "system", "content": self._system_prompt_sysinfo.prompt()},
            {"role": "system", "content": self._system_prompt_rules.prompt()}
        ]

        printer.print_text(f"📝 系统提示词长度(token): {count_tokens(json.dumps(conversations, ensure_ascii=False))}",
                           style="green")

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
                printer.print_text(f"📂 恢复对话，已有 {len(current_conversation['messages'])} 条现有消息", style="green")
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
        current_tokens = count_tokens(conversation_str)
        yield WindowLengthChangeEvent(tokens_used=current_tokens)

        iteration_count = 0
        tool_executed = False
        should_yield_completion_event = False
        completion_event = None

        while True:
            iteration_count += 1
            if iteration_count % 20 == 0:
                conversations.append({"role": "user", "content": self._system_prompt_rules.prompt()})  # 强化规则记忆
            tool_executed = False
            last_message = conversations[-1]
            printer.print_text(f"🔄 当前为第 {iteration_count} 轮对话, 历史会话长度(Context):{len(conversations)}",
                               style="green")

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
                printer.print_text("💡 正在添加系统提示: 请使用工具或尝试直接生成结果", style="green")

                conversations.append({
                    "role": "user",
                    "content": "注意：您必须使用适当的工具或明确完成任务（使用 attempt_completion）。"
                               "不要在不采取具体行动的情况下提供文本回复。请根据用户的任务选择合适的工具继续操作。"
                })
                self.conversation_manager.append_message_to_current(
                    role="user",
                    content="注意：您必须使用适当的工具或明确完成任务（使用 attempt_completion）。"
                            "不要在不采取具体行动的情况下提供文本回复。请根据用户的任务选择合适的工具继续操作。",
                    metadata={})

                # 计算当前对话的总 token 数量并触发事件
                current_conversation_str = json.dumps(conversations, ensure_ascii=False)
                total_tokens = count_tokens(current_conversation_str)
                yield WindowLengthChangeEvent(tokens_used=total_tokens)
                # 继续循环，让 LLM 再思考，而不是 break
                printer.print_text("🔄 持续运行 LLM 交互循环（保持不中断）", style="green")
                continue

        printer.print_text(f"✅ AgenticEdit 分析循环已完成，共执行 {iteration_count} 次迭代.")
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
                        printer.print_text(f"Commit 成功", style="green")
                except Exception as err:
                    import traceback
                    traceback.print_exc()
                    printer.print_text(f"Commit 失败: {err}", style="red")
        else:
            printer.print_text(f"文件未进行任何更改, 无需 Commit", style="yellow")

    def run_in_terminal(self, request: AgenticEditRequest):
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))

        printer.print_text(f"🚀 Agentic Ask 开始运行, 项目名: {project_name}, 用户目标: {request.user_input}")

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

                    printer.print_text(f"📝 Token 使用: "
                                       f"Input({last_meta.input_tokens_count})/"
                                       f"Output({last_meta.generated_tokens_count})",
                                       style="green")

                elif isinstance(event, WindowLengthChangeEvent):
                    printer.print_text(f"📝 当前 Token 总用量: {event.tokens_used}", style="green")

                elif isinstance(event, LLMThinkingEvent):
                    # 以不太显眼的样式（比如灰色）呈现思考内容
                    think_text = f"[grey]{event.text}[/grey]"
                    printer.print_panel(content=think_text, title="💭 LLM Thinking", center=True)

                elif isinstance(event, LLMOutputEvent):
                    printer.print_panel(content=f"{event.text}", title="💬 LLM Output", center=True)

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
                            return f"{_content[:200]}\n\n\n......\n\n\n{_content[-200:]}"
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
