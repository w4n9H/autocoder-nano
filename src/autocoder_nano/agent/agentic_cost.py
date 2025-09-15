import json
import os
import time
from copy import deepcopy
import xml.sax.saxutils
from typing import List, Dict, Any, Optional, Generator, Union

from rich.markdown import Markdown

from autocoder_nano.actypes import AutoCoderArgs, SourceCodeList, SingleOutputMeta
from autocoder_nano.agent.agent_base import BaseAgent
from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.context import get_context_manager, ConversationsPruner
from autocoder_nano.core import AutoLLM, prompt, stream_chat_with_continue
from autocoder_nano.rag.token_counter import count_tokens
from autocoder_nano.utils.formatted_log_utils import save_formatted_log
from autocoder_nano.utils.git_utils import get_uncommitted_changes
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.agent.agentic_edit_tools import (  # Import specific resolvers
    BaseToolResolver,
    SearchFilesToolResolver, ListFilesToolResolver,
    AttemptCompletionToolResolver
)


printer = Printer()


COST_TOOL_RESOLVER_MAP: Dict[Type[BaseTool], Type[BaseToolResolver]] = {
    SearchFilesTool: SearchFilesToolResolver,
    ListFilesTool: ListFilesToolResolver,
    AttemptCompletionTool: AttemptCompletionToolResolver,  # Will stop the loop anyway
}


class AgenticCost(BaseAgent):
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

    @prompt()
    def _system_prompt_role(self):
        """
        # 技术经济分析师 Agent

        ## 核心身份与职责

        你是技术经济分析师，你的核心使命是在项目启动初期，快速评估用户需求的综合难度与成本，并为老板和CTO提供下一步行动的决策依据与最优资源分配方案。
        你不是代码执行者，而是决策前的“计算器”和“导航仪”，确保整个多智能体系统以最高性价比的方式启动和运行。

        # Multi-Agent系统全角色说明

        - 技术经济分析师 agent_cost：对整个需求做初步的难度判断，快速评估用户需求的综合难度与成本，提供下一步行动的决策依据。
        - 领域研究员 agent_report：通过多rag与联网搜索结合的DeepResearch，用于深度研究某个技术架构，技术难题。
        - 产品经理 agent_ask：针对用户需求，做需求澄清，系统设计以及任务拆解，生成最终交付文档
        - 研发工程师 agent_edit：编写基础设施，前端及后端的相关代码

        # 核心目标

        你的所有分析都必须围绕以下四个关键决策点展开：

        - 难度判断：初步判断该需求的描述清晰度和技术实现难度（低/中/高/极高）
        - 研究必要性：决定是否需触发 agent_report (技术研究员) 进行深度研究
        - 澄清必要性：决定是否需触发 agent_ask (产品经理) 与用户进行需求澄清

        # 工作流与决策逻辑

        收到用户需求后，你需要执行以下分析流程：

        ## 第一步：需求复杂度分析

        - 分析需求的技术范围（是否涉及前后端，基础设施，复杂算法）
            - 通过 list_files 工具递归列出项目目录，初步进行以下判断
                - 项目基本规模（文件数），目录结构，使用何种编程语言（代码文件后缀）
                - 项目类型：前端项目，后端项目，Cli 工具脚本
        - 分析需求的明确性（需求描述是否清晰，无歧义，有明确的输入输出）
            - 需求是否带上了明确的代码文件名，函数名，类名，以及改动点是否明确
            - 需求中是否带有明确的 "优化" "提升速度" 等对性能有要求的字眼
            - 需求中是否明确出现了使用某技术栈进行任务的字眼
            - 需求中是否明确提出了研究某种事物
        - 分析需求的依赖项（是否需要外部API，特殊数据库，特定许可）

        ## 第二步：做出关键决策

        - 需求涉及未知技术栈，未验证的算法，极高的性能要求，课题的研究【需深度研究】-> 建议调用 agent_report
        - 需求描述模糊，存在歧义，缺少关键细节（如UI样式，业务规则，边界条件），【需需求澄清】-> 建议调用 agent_ask

        # 最终输出格式

        ```json
        {
            "difficulty": "中",
            "need_research": false,
            "need_ask": true,
            "decision_rationale": "需求业务逻辑清晰，但缺少对并发用户数的明确要求，建议由agent_ask先行澄清。核心交易模块难度较高，建议使用GPT-4o编写以确保质量。"
        }
        ```

        - difficulty：可选值: "低", "中", "高", "极高"
        - need_research： 布尔值: true / false
        - need_ask：布尔值: true / false
        - decision_rationale：原因说明，在20字以内

        # 约束与核心规则

        - 果断明确：你的决策必须是非黑即白的（true/false），不允许使用 “可能”，“也许” 等模糊词汇。
        - 效率优先：你的分析应在最短时间内完成，进行初步判断，本身不应消耗过多Token成本。
        - 最后使用 attempt_completion 工具输出 json 结果
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
        {
            "difficulty": "中",
            "need_research": false,
            "need_ask": true,
            "decision_rationale": "需求业务逻辑清晰，但缺少对并发用户数的明确要求，建议由agent_ask先行澄清。核心交易模块难度较高，建议使用GPT-4o编写以确保质量。"
        }
        </result>
        </attempt_completion>

        # 错误处理
        - 如果工具调用失败，你需要分析错误信息，并重新尝试，或者向用户报告错误并请求帮助（使用 ask_followup_question 工具）

        ## 工具熔断机制
        - 工具连续失败2次时启动备选方案
        - 自动标注行业惯例方案供用户确认
        """

    def analyze(self, request: AgenticEditRequest) -> (
            Generator)[Union[LLMOutputEvent, LLMThinkingEvent, ToolCallEvent, ToolResultEvent, CompletionEvent,
                             ErrorEvent, WindowLengthChangeEvent, TokenUsageEvent,
                             PlanModeRespondEvent] | None, None, None]:
        conversations = [
            {"role": "system", "content": self._system_prompt_role.prompt()},
            {"role": "system", "content": self._system_prompt_tools.prompt()}
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
                    resolver_cls = COST_TOOL_RESOLVER_MAP.get(type(tool_obj))
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
                           "agentic_cost_conversation")

    def apply_pre_changes(self):
        uncommitted_changes = get_uncommitted_changes(self.args.source_dir)
        if uncommitted_changes != "No uncommitted changes found.":
            raise Exception("代码中包含未提交的更新,请执行/commit")

    def run_in_terminal(self, request: AgenticEditRequest) -> str:
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))

        printer.print_text(f"🚀 Agentic Cost 开始运行, 项目名: {project_name}, 用户目标: {request.user_input}")

        # 用于累计TokenUsageEvent数据
        accumulated_token_usage = {
            "model_name": "",
            "input_tokens": 0,
            "output_tokens": 0,
        }

        cost_result = "{}"

        try:
            self.apply_pre_changes()  # 在开始 Agentic Cost 之前先判断是否有未提交变更,有变更则直接退出
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
                    cost_result = event.completion.result

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

                time.sleep(self.args.anti_quota_limit)  # Small delay for better visual flow

            # 在处理完所有事件后打印累计的token使用情况
            printer.print_key_value(accumulated_token_usage)

        except Exception as err:
            # 在处理异常时也打印累计的token使用情况
            if accumulated_token_usage["input_tokens"] > 0:
                printer.print_key_value(accumulated_token_usage)
            printer.print_panel(content=f"FATAL ERROR: {err}", title="🔥 Agentic Cost 运行错误", center=True)
            raise err

        printer.print_text("Agentic Cost 结束", style="green")
        return cost_result