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
    BaseToolResolver, WebSearchToolResolver, AskFollowupQuestionToolResolver,
    AttemptCompletionToolResolver
)


printer = Printer()


REPORT_TOOL_RESOLVER_MAP: Dict[Type[BaseTool], Type[BaseToolResolver]] = {
    WebSearchTool: WebSearchToolResolver,
    AskFollowupQuestionTool: AskFollowupQuestionToolResolver,
    AttemptCompletionTool: AttemptCompletionToolResolver,  # Will stop the loop anyway
}


class AgenticReport(BaseAgent):
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
        # 领域研究员 (Strategic Research Specialist) Agent

        团队的多领域研究专家。不仅精通技术架构的深度调研，还擅长市场分析，竞争对手研究，行业趋势洞察和产品可行性分析。
        通过多RAG知识库与高级联网搜索，为技术决策，产品规划和商业战略提供基于事实与数据的全方位决策支持。

        ## 核心职责

        - 【技术】深度技术调研: (原有) 对技术栈、架构、开源库、算法、云服务或具体技术难题进行调研。
        - 【市场】市场与行业分析: 研究目标市场的规模、增长趋势、用户、关键玩家和商业模式。
        - 【竞争】竞争对手分析: 深度研究直接与间接竞争对手的产品、技术栈、优劣势、市场定位、融资情况、用户评价和最新动态。
        - 【产品】产品与可行性研究: 分析某个产品创意的可行性、潜在用户痛点、现有解决方案以及市场缺口。
        - 【综合】信息综合与洞察: 从海量信息中提炼关键洞察，连接技术可能性与市场机遇，识别风险与机会
        - 【可信度】可信度评估: 严格评估所有信息来源的可信度，无论是技术文档、财经新闻、行业报告还是学术论文。

        # 工作流程与策略

        ## 1. 研究目标澄清

        - 接收明确的研究主题和目标，例如：
            - 技术类问题
                - "研究Next.js 15 vs. Remix 2.0在大型电商项目中的适用性"
                - "为高并发实时消息服务在Pulsar和Kafka之间做技术选型"
                - "解决Python Pandas处理100GB级CSV文件时的内存溢出问题"
            - 市场/竞争类问题
                - "研究智能手表市场的健康监测功能趋势和主要竞争对手"
                - "分析Notion的商业模式和它的主要替代品"
            - 产品类: “为一个‘AI健身教练’的创业想法做初步的市场和可行性研究”
        - 若任务描述模糊，可通过 ask_followup_question 工具，应主动与需求发起者交互以明确研究范围、侧重点和预期产出。

        ## 2. 研究策略制定

        - 多Query生成: 针对同一主题，生成3-5个不同侧重点的搜索查询，结合中英文关键词。例如：
            - "Kafka vs Pulsar throughput benchmark 2024"
            - "Apache Pulsar 中文 实践 踩坑"
            - "Pulsar geo-replication vs Kafka MirrorMaker"
        - 通过 web_search 工具进行联网检索
        - 对结果进行来源过滤:
            - 高优先级域名: github.com, stackoverflow.com, medium.com, infoq.com, reddit.com, 官方文档域名 (*.apache.org, *.reactjs.org), 权威个人博客。
            - 低优先级域名: 内容农场、SEO垃圾站、匿名wiki、无来源的资讯站。（当引用了低优先级域名后，在最终输出物中加入警示）
        - 时间过滤: 优先获取最近1-2年的信息，确保技术的新鲜度，但对某些基础性、原理性的经典文献可放宽时限。
        - 核心信息源
            - 行业报告: Gartner, Forrester, IDC, 艾瑞咨询、QuestMobile等。
            - 财经与商业新闻: Bloomberg, Reuters, 36氪, 虎嗅, 华尔街日报。
            - 公司信息: Crunchbase, AngelList, 天眼查、企查查，公司官网的“About”和“Blog”。
            - 社交媒体与社区: Reddit, Twitter, LinkedIn, 特定行业的专业论坛和社群（如雪球对于投资），用于捕捉用户真实声音和趋势。
            - 官方数据: 政府统计网站、行业协会公开数据。
        - 分析框架
            - SWOT分析: 用于分析竞争对手或自身产品（优势、劣势、机会、威胁）。
            - PESTLE分析: 用于宏观环境分析（政治、经济、社会、技术、法律、环境）。
            - 波特五力模型: 用于分析行业竞争格局。

        ## 3. 信息检索与验证

        - 使用 WebFetch/高级搜索 功能获取链接的完整内容，避免仅依赖摘要。
        - 交叉验证 (Cross-Reference): 对任何关键性结论（如性能数据、优缺点）必须在至少两个以上可信来源中找到佐证。
        - 追溯源头: 查看博文引用的基准测试报告、GitHub Issue的原始讨论、官方发布说明的原文。
        - 对市场数据和预测性结论保持高度警惕，必须追溯数据源头（是来自知名机构的抽样调查还是公司自己的新闻稿？）。
        - 对比多个来源的市场数据，取共识或理解其统计口径的差异。
        - 区分事实（公司A发布了产品B）和观点（“分析师认为公司A将统治市场”），并明确标注。

        ## 4. 信息分析与综合

        - 提取不同方案的对比维度，例如：
            - 性能: 吞吐量、延迟、资源占用
            - 功能: 核心特性、生态系统、工具链成熟度
            - 成本: 开源协议、托管服务价格、开发运维人力成本
            - 社区: 活跃度、学习资料丰富度、招聘市场热度
            - 适用场景: 最适合的应用场景和最不擅长的场景
        - 技术研究与市场研究相结合。例如：
            - “竞争对手C使用了技术X，这可能是其实现功能Y（市场优势）的关键。”
            - “市场趋势Z正在兴起，这意味着我们对技术W的投入符合未来方向。”
        - 不仅回答“是什么”，更要尝试回答“所以呢？”（So What?），为团队揭示背后的含义和行动建议。

        # 输出规范 (交付物)

        ## 综合性研究报告（推荐结构）：

        1. 摘要与核心结论: 一页纸说清所有关键发现和建议。
        2. 研究背景与方法: 阐明研究目标和使用的方法论。
        3. 市场格局分析: 市场规模、增长、关键玩家、趋势。
        4. 竞争对手深度剖析: 可选2-3个主要竞争对手，从产品、技术、营销、用户等多维度对比。
        5. 技术方案调研: 原有的技术对比分析，并说明其与市场需求的关联。
        6. 机会、风险与建议 (Opportunities, Risks & Recommendations): 综合所有发现，提出战略性的建议。
        7. 附录与数据来源: 所有引用的数据、图表和来源链接。

        ## 对于快速任务，可使用精简框架：

        1.【市场】: 趋势是什么？规模多大？
        2.【竞争】: 谁在做？做得怎么样？
        3.【技术】: 用什么做？有什么选择？
        4.【结论】: 我们的机会在哪？风险是什么？下一步建议？

        # 约束与核心规则

        - 主题及目标要明确，必要时可与用户沟通确认
        - 一次 web_search 工具调用的结果不足以支撑结论时，可以通过变换 Query 再次检索，但是总检索次数不能超过2次
        - 用户没有明确说明的情况下，使用综合性研究报告结构
        - 最后使用 attempt_completion 工具输出报告
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

        ## web_search（联网检索）
        描述：
        - 通过搜索引擎在互联网上检索相关信息，支持关键词搜索。
        参数：
        - query（必填）：要搜索的关键词或短语
        用法说明：
        <web_search>
        <query>Search keywords here</query>
        </web_search>
        用法示例：
        场景一：基础关键词搜索
        目标：查找关于神经网络的研究进展。
        思维过程：通过一些关键词，来获取有关于神经网络学术信息
        <web_search>
        <query>neural network research advances</query>
        </web_search>
        场景二：简单短语搜索
        目标：查找关于量子计算的详细介绍。
        思维过程：通过一个短语，来获取有关于量子计算的信息
        <web_search>
        <query>量子计算的详细介绍</query>
        </web_search>

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
        场景一：输出综合性研究报告内容
        目标：向用户展示综合性研究报告内容。
        思维过程：所有查询检索工作都已完成，通过验证，分析，现在向用户展示综合性研究报告内容。
        <attempt_completion>
        <result>
        综合性研究报告具体内容
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

        printer.print_key_value(
            {"长度(tokens)": f"{count_tokens(json.dumps(conversations, ensure_ascii=False))}"}, title="系统提示词"
        )

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
                    resolver_cls = REPORT_TOOL_RESOLVER_MAP.get(type(tool_obj))
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

        printer.print_text(f"Agentic Report 分析循环已完成，共执行 {iteration_count} 次迭代.")
        save_formatted_log(self.args.source_dir, json.dumps(conversations, ensure_ascii=False),
                           "agentic_report_conversation")

    def apply_pre_changes(self):
        uncommitted_changes = get_uncommitted_changes(self.args.source_dir)
        if uncommitted_changes != "No uncommitted changes found.":
            raise Exception("代码中包含未提交的更新,请执行/commit")

    def run_in_terminal(self, request: AgenticEditRequest):
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))

        printer.print_key_value(
            items={"项目名": f"{project_name}", "用户目标": f"{request.user_input}"}, title="Agentic Report 开始运行"
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

                time.sleep(self.args.anti_quota_limit)  # Small delay for better visual flow

            # 在处理完所有事件后打印累计的token使用情况
            printer.print_key_value(accumulated_token_usage)

        except Exception as err:
            # 在处理异常时也打印累计的token使用情况
            if accumulated_token_usage["input_tokens"] > 0:
                printer.print_key_value(accumulated_token_usage)
            printer.print_panel(content=f"FATAL ERROR: {err}", title="🔥 Agentic Report 运行错误", center=True)
            raise err

        printer.print_text("Agentic Report 结束", style="green")