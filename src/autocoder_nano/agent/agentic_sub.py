import os
import time
import xml.sax.saxutils
from copy import deepcopy
from typing import Generator, Union

from rich.text import Text

from autocoder_nano.agent.agent_base import BaseAgent, ToolResolverFactory, PromptManager
from autocoder_nano.context import ConversationsPruner
from rich.markdown import Markdown

from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.core import AutoLLM, stream_chat_with_continue, prompt
from autocoder_nano.actypes import AutoCoderArgs, SourceCodeList, SingleOutputMeta
from autocoder_nano.utils.printer_utils import (
    Printer, COLOR_SYSTEM, COLOR_INFO, COLOR_SUCCESS, COLOR_ERROR)

printer = Printer()


class SubAgents(BaseAgent):
    def __init__(
            self, args: AutoCoderArgs, llm: AutoLLM, agent_type: str, files: SourceCodeList,
            history_conversation: List[Dict[str, Any]]
    ):
        super().__init__(args, llm)
        self.agent_type = agent_type
        self.files = files
        self.history_conversation = history_conversation
        self.current_conversations = []

        # Agentic 对话修剪器
        self.agentic_pruner = ConversationsPruner(args=args, llm=self.llm)

        # Tools 管理
        self.tool_resolver_factory = ToolResolverFactory()
        self.tool_resolver_factory.register_dynamic_resolver(self.agent_type)

        # prompt 管理
        self.prompt_manager = PromptManager(args=self.args)

        # subagent printer prefix
        self.spp = f"* (sub:{self.agent_type}) "

    def _reinforce_guidelines(self, interval=5):
        """ 每N轮对话强化指导原则 """
        if len(self.current_conversations) % interval == 0:
            printer.print_text(f"强化工具使用规则(间隔{interval})", style=COLOR_SYSTEM, prefix=self.spp)
            self.current_conversations.append(
                {"role": "user", "content": self._get_tools_prompt()}
            )

    def _get_tools_prompt(self) -> str:
        if self.tool_resolver_factory.get_registered_size() <= 0:
            raise Exception(f"未注册任何工具")
        guides = ""
        resolvers = self.tool_resolver_factory.get_resolvers()
        for t, resolver_cls in resolvers.items():
            resolver = resolver_cls(agent=self, tool=t, args=self.args)
            tool_guide: str = resolver.guide()
            guides += f"{tool_guide}\n\n"
        return f"""
        # 工具使用说明

        1. 你可使用一系列工具，部分工具需经用户批准才能执行。
        2. 每条消息中仅能使用一个工具，用户回复中会包含该工具的执行结果。
        3. 你要借助工具逐步完成给定任务，每个工具的使用都需依据前一个工具的使用结果。
        4. 使用工具时需要包含 开始和结束标签, 缺失结束标签会导致工具调用失败
        
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
        
        {guides}
        
        # 错误处理
        - 如果工具调用失败，你需要分析错误信息，并重新尝试，或者向用户报告错误并请求帮助
        
        # 工具熔断机制
        - 工具连续失败3次时启动备选方案或直接结束任务
        - 自动标注行业惯例方案供用户确认
        
        # 工具调用规范
        - 调用前必须在 <thinking></thinking> 内分析：
            * 分析系统环境及目录结构
            * 根据目标选择合适工具
            * 必填参数检查（用户提供或可推断，否则用 `ask_followup_question` 询问）
        - 当所有必填参数齐备或可明确推断后，才关闭思考标签并调用工具
        
        # 工具使用指南
        1. 开始任务前务必进行全面搜索和探索
        2. 在 <thinking> 标签中评估已有和继续完成任务所需信息
        3. 根据任务选择合适工具，思考是否需其他信息来推进，以及用哪个工具收集
        4. 逐步执行，禁止预判：
            * 单次仅使用一个工具
            * 后续操作必须基于前次结果
            * 严禁假设任何工具的执行结果
        5. 按工具指定的 XML 格式使用
        6. 重视用户反馈，某些时候，工具使用后，用户会回复为你提供继续任务或做出进一步决策所需的信息，可能包括：
            * 工具是否成功的信息
            * 触发的 Linter 错误（需修复）
            * 相关终端输出
            * 其他关键信息
        """

    def _get_system_prompt(self) -> str:
        return self.prompt_manager.load_prompt_file(self.agent_type, "system")

    def _build_system_prompt(self) -> List[Dict[str, Any]]:
        """ 构建初始对话消息 """
        system_prompt = [
            {"role": "system", "content": self._get_system_prompt()},
            {"role": "system", "content": self._get_tools_prompt()},
            {"role": "system", "content": self.prompt_manager.prompt_sysinfo.prompt()}
        ]

        printer.print_text(f"系统提示词长度(token): {self._count_conversations_tokens(system_prompt)}",
                           style=COLOR_INFO, prefix=self.spp)

        return system_prompt

    def analyze(self, request: AgenticEditRequest) -> Generator[Union[Any] | None, None, None]:
        self.current_conversations.extend(self._build_system_prompt())
        self.current_conversations.append({"role": "user", "content": request.user_input})

        yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(self.current_conversations))

        iteration_count = 0
        tool_executed = False
        should_yield_completion_event = False
        completion_event = None

        while True:
            self._reinforce_guidelines(interval=10)
            iteration_count += 1
            tool_executed = False
            last_message = self.current_conversations[-1]
            printer.print_text(f"当前为第{iteration_count}轮对话", style=COLOR_INFO, prefix=self.spp)

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

            llm_response_gen = stream_chat_with_continue(
                llm=self.llm,
                conversations=self.agentic_pruner.prune_conversations(deepcopy(self.current_conversations)),
                llm_config={},  # Placeholder for future LLM configs
                args=self.args
            )

            parsed_events = self.stream_and_parse_llm_response(llm_response_gen)

            mark_event_should_finish = False
            for event in parsed_events:
                if mark_event_should_finish:
                    if isinstance(event, TokenUsageEvent):
                        yield event
                    continue

                if isinstance(event, (LLMOutputEvent, LLMThinkingEvent)):
                    assistant_buffer += event.text
                    yield event

                elif isinstance(event, ToolCallEvent):
                    tool_executed = True
                    tool_obj = event.tool
                    tool_name = type(tool_obj).__name__
                    tool_xml = event.tool_xml
                    # 不在展示工具触发, 仅展示后面的调用部分
                    # printer.print_text(f"🛠️ SubAgent 触发工具: {tool_name}", style=COLOR_TOOL_CALL)

                    # 记录当前对话的token数量
                    self.current_conversations.append({
                        "role": "assistant",
                        "content": assistant_buffer + tool_xml
                    })
                    assistant_buffer = ""  # Reset buffer after tool call

                    yield WindowLengthChangeEvent(
                        tokens_used=self._count_conversations_tokens(self.current_conversations))
                    yield event  # Yield the ToolCallEvent for display

                    if isinstance(tool_obj, AttemptCompletionTool):
                        printer.print_text(f"正在准备结束会话 ...", style=COLOR_INFO, prefix=self.spp)
                        completion_event = CompletionEvent(completion=tool_obj, completion_xml=tool_xml)
                        mark_event_should_finish = True
                        should_yield_completion_event = True
                        continue

                    resolver_cls = self.tool_resolver_factory.get_resolver(type(tool_obj))
                    if not resolver_cls:
                        tool_result = ToolResult(success=False, message="错误：工具解析器未实现.", content=None)
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
                            content_str = str(tool_result.content) if tool_result.content is not None else ""
                            escaped_content = xml.sax.saxutils.escape(content_str)
                            error_xml = (
                                f"<tool_result tool_name='{type(tool_obj).__name__}' "
                                f"success='{str(tool_result.success).lower()}'>"
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
                    self.current_conversations.append({
                        "role": "user",
                        "content": error_xml
                    })

                    yield WindowLengthChangeEvent(
                        tokens_used=self._count_conversations_tokens(self.current_conversations))

                    # 一次交互只能有一次工具，剩下的其实就没有用了，但是如果不让流式处理完，我们就无法获取服务端
                    # 返回的token消耗和计费，所以通过此标记来完成进入空转，直到流式走完，获取到最后的token消耗和计费
                    mark_event_should_finish = True

                elif isinstance(event, ErrorEvent):
                    if event.message.startswith("Stream ended with unterminated"):
                        printer.print_text(f"LLM Response 流以未闭合的标签块结束, 即将强化记忆",
                                           style=COLOR_ERROR, prefix=self.spp)
                        self.current_conversations.append(
                            {"role": "user",
                             "content": "使用工具时需要包含 开始和结束标签, 缺失结束标签会导致工具调用失败"}
                        )
                    yield event
                elif isinstance(event, TokenUsageEvent):
                    yield event

            if not tool_executed:
                # printer.print_text("LLM 响应完成, 未执行任何工具, 将 Assistant Buffer 内容写入会话历史",
                #                    style=COLOR_WARNING, prefix=self.spp)
                if assistant_buffer:
                    last_message = self.current_conversations[-1]
                    if last_message["role"] != "assistant":
                        self.current_conversations.append({"role": "assistant", "content": assistant_buffer})
                    elif last_message["role"] == "assistant":
                        last_message["content"] += assistant_buffer

                    yield WindowLengthChangeEvent(
                        tokens_used=self._count_conversations_tokens(self.current_conversations))

                # 添加系统提示，要求LLM必须使用工具或明确结束，而不是直接退出
                # printer.print_text("正在添加系统提示: 请使用工具或尝试直接生成结果", style=COLOR_INFO, prefix=self.spp)

                self.current_conversations.append({
                    "role": "user",
                    "content": "注意：您必须使用适当的工具或使用 attempt_completion明确完成任务,"
                               "不要在不采取具体行动的情况下提供文本回复。请根据用户的任务选择合适的工具继续操作."
                })
                yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(self.current_conversations))
                # 继续循环，让 LLM 再思考，而不是 break
                # printer.print_text("🔄 SubAgent 持续运行 LLM 交互循环（保持不中断）", style=COLOR_ITERATION)
                continue

        printer.print_text(f"分析循环已完成，共执行 {iteration_count} 次迭代.", style=COLOR_SUCCESS, prefix=self.spp)

    def run_subagent(self, request: AgenticEditRequest):
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))

        printer.print_text(f"开始运行, 项目名: {project_name}, 用户目标: {request.user_input[:50]}...",
                           style=COLOR_SYSTEM, prefix=self.spp)
        completion_text = ""
        completion_status = False
        try:
            self._apply_pre_changes()  # 在开始 Agentic 之前先判断是否有未提交变更,有变更则直接退出
            event_stream = self.analyze(request)
            for event in event_stream:
                if isinstance(event, TokenUsageEvent):
                    last_meta: SingleOutputMeta = event.usage
                    printer.print_text(
                        Text.assemble(
                            ("Token 使用: ", COLOR_SYSTEM),
                            (f"Input({last_meta.input_tokens_count})", COLOR_INFO),
                            (f"/", COLOR_SYSTEM),
                            (f"Output({last_meta.generated_tokens_count})", COLOR_INFO)
                        ),
                        prefix=self.spp
                    )
                elif isinstance(event, WindowLengthChangeEvent):
                    pass
                    # printer.print_text(f"当前 Token 总用量: {event.tokens_used}", style=COLOR_INFO, prefix=self.spp)
                elif isinstance(event, LLMThinkingEvent):
                    # 以不太显眼的样式（比如灰色）呈现思考内容
                    printer.print_text(f"LLM Thinking: ", style=COLOR_SYSTEM, prefix=self.spp)
                    printer.print_llm_output(f"{event.text}")
                elif isinstance(event, LLMOutputEvent):
                    printer.print_text(f"LLM Output: ", style=COLOR_SYSTEM, prefix=self.spp)
                    printer.print_llm_output(f"{event.text}")
                elif isinstance(event, ToolCallEvent):
                    printer.print_text(
                        Text.assemble(
                            (f"{type(event.tool).__name__}: ", COLOR_SYSTEM),
                            (f"{self.get_tool_display_message(event.tool)}", COLOR_INFO)
                        ),
                        prefix=self.spp
                    )
                elif isinstance(event, ToolResultEvent):
                    result = event.result
                    printer.print_text(
                        Text.assemble(
                            (f"{event.tool_name} Result: ", COLOR_SYSTEM),
                            (f"{result.message}", COLOR_SUCCESS if result.success else COLOR_ERROR)
                        ),
                        prefix=self.spp
                    )
                elif isinstance(event, CompletionEvent):
                    self._apply_changes(request)  # 在这里完成实际合并
                    # 保存完成结果用于返回
                    completion_text = event.completion.result
                    completion_status = True
                    if event.completion.command:
                        printer.print_text(f"建议命令: {event.completion.command}", style=COLOR_INFO, prefix=self.spp)
                    printer.print_text(f"任务完成", style=COLOR_SUCCESS, prefix=self.spp)
                    printer.print_llm_output(f"{completion_text}")
                elif isinstance(event, ErrorEvent):
                    printer.print_text(f"任务失败", style=COLOR_ERROR, prefix=self.spp)
                    printer.print_llm_output(f"{event.message}")

                time.sleep(self.args.anti_quota_limit)

                # 如果已经获得完成结果，可以提前结束事件处理
                if completion_text:
                    break
        except Exception as err:
            printer.print_text(f"SubAgent 执行失败", style=COLOR_ERROR, prefix=self.spp)
            printer.print_llm_output(f"{err}")
            completion_text = f"SubAgent {self.agent_type.title()} 执行失败: {str(err)}"

        return completion_status, completion_text
