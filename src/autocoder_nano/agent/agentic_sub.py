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
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.utils.color_utils import *

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

    def _reinforce_guidelines(self, interval=5):
        """ 每N轮对话强化指导原则 """
        if len(self.current_conversations) % interval == 0:
            printer.print_text(f"SubAgent 强化工具使用规则(间隔{interval})", style=COLOR_SYSTEM)
            self.current_conversations.append(
                {"role": "user", "content": self.prompt_manager.load_prompt_file(self.agent_type, "tools")}
            )

    def _build_system_prompt(self) -> List[Dict[str, Any]]:
        """ 构建初始对话消息 """
        system_prompt = [
            {"role": "system", "content": self.prompt_manager.load_prompt_file(self.agent_type, "system")},
            {"role": "system", "content": self.prompt_manager.load_prompt_file(self.agent_type, "tools")},
            {"role": "system", "content": self.prompt_manager.prompt_sysinfo.prompt()}
        ]

        printer.print_text(f"📝 SubAgent 系统提示词长度(token): {self._count_conversations_tokens(system_prompt)}",
                           style=COLOR_TOKEN_USAGE)

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
            printer.print_text(f"🔄 SubAgent 当前为第{iteration_count}轮对话", style=COLOR_ITERATION)

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
                    printer.print_text(f"🛠️ SubAgent 触发工具: {tool_name}", style=COLOR_TOOL_CALL)

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
                        printer.print_text(
                            f"SubAgent 正在结束会话, 完成结果: {tool_obj.result[:50]}...", style=COLOR_COMPLETION
                        )
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
                        printer.print_text(f"SubAgent LLM Response 流以未闭合的标签块结束, 即将强化记忆",
                                           style=COLOR_ERROR)
                        self.current_conversations.append(
                            {"role": "user",
                             "content": "使用工具时需要包含 开始和结束标签, 缺失结束标签会导致工具调用失败"}
                        )
                    yield event
                elif isinstance(event, TokenUsageEvent):
                    yield event

            if not tool_executed:
                printer.print_text("SubAgent LLM 响应完成, 未执行任何工具, 将 Assistant Buffer 内容写入会话历史",
                                   style=COLOR_WARNING)
                if assistant_buffer:
                    last_message = self.current_conversations[-1]
                    if last_message["role"] != "assistant":
                        self.current_conversations.append({"role": "assistant", "content": assistant_buffer})
                    elif last_message["role"] == "assistant":
                        last_message["content"] += assistant_buffer

                    yield WindowLengthChangeEvent(
                        tokens_used=self._count_conversations_tokens(self.current_conversations))

                # 添加系统提示，要求LLM必须使用工具或明确结束，而不是直接退出
                printer.print_text("💡 SubAgent 正在添加系统提示: 请使用工具或尝试直接生成结果", style=COLOR_SYSTEM)

                self.current_conversations.append({
                    "role": "user",
                    "content": "注意：您必须使用适当的工具或使用 attempt_completion明确完成任务,"
                               "不要在不采取具体行动的情况下提供文本回复。请根据用户的任务选择合适的工具继续操作."
                })
                yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(self.current_conversations))
                # 继续循环，让 LLM 再思考，而不是 break
                printer.print_text("🔄 SubAgent 持续运行 LLM 交互循环（保持不中断）", style=COLOR_ITERATION)
                continue

        printer.print_text(f"✅ SubAgent [{self.agent_type.title()}] 分析循环已完成，共执行 {iteration_count} 次迭代.",
                           style=COLOR_ITERATION)

    def run_subagent(self, request: AgenticEditRequest):
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))

        printer.print_text(f"🚀 SubAgent [{self.agent_type.title()}] 开始运行, 项目名: {project_name}, "
                           f"用户目标: {request.user_input[:50]}...",
                           style=COLOR_SYSTEM)
        completion_text = ""
        completion_status = False
        try:
            self._apply_pre_changes()  # 在开始 Agentic 之前先判断是否有未提交变更,有变更则直接退出
            event_stream = self.analyze(request)
            for event in event_stream:
                if isinstance(event, TokenUsageEvent):
                    last_meta: SingleOutputMeta = event.usage
                    printer.print_text(f"📝 SubAgent Token 使用: "
                                       f"Input({last_meta.input_tokens_count})/"
                                       f"Output({last_meta.generated_tokens_count})",
                                       style=COLOR_TOKEN_USAGE)
                elif isinstance(event, WindowLengthChangeEvent):
                    printer.print_text(f"📝 SubAgent 当前 Token 总用量: {event.tokens_used}", style=COLOR_TOKEN_USAGE)
                elif isinstance(event, LLMThinkingEvent):
                    # 以不太显眼的样式（比如灰色）呈现思考内容
                    printer.print_panel(
                        content=Text(f"{event.text}", style=COLOR_LLM_THINKING),
                        title="💭 SubAgent LLM Thinking",
                        border_style=COLOR_PANEL_INFO,
                        center=True)
                elif isinstance(event, LLMOutputEvent):
                    printer.print_panel(
                        content=Text(f"{event.text}", style=COLOR_LLM_OUTPUT),
                        title="💬 SubAgent LLM Output",
                        border_style=COLOR_PANEL_INFO,
                        center=True)
                elif isinstance(event, ToolCallEvent):
                    printer.print_text(f"️🛠️ SubAgent 工具调用: {type(event.tool).__name__}, "
                                       f"{self.get_tool_display_message(event.tool)}",
                                       style=COLOR_TOOL_CALL)
                elif isinstance(event, ToolResultEvent):
                    result = event.result
                    printer.print_text(
                        f"{'✅' if result.success else '❌'} SubAgent 工具返回: {event.tool_name}, "
                        f"状态: {'成功' if result.success else '失败'}, 信息: {result.message}",
                        style=COLOR_TOOL_CALL
                    )
                elif isinstance(event, CompletionEvent):
                    self._apply_changes(request)  # 在这里完成实际合并
                    # 保存完成结果用于返回
                    completion_text = event.completion.result
                    completion_status = True
                    printer.print_panel(
                        content=Markdown(event.completion.result),
                        border_style=COLOR_PANEL_SUCCESS,
                        title="🏁 任务完成", center=True
                    )
                    if event.completion.command:
                        printer.print_text(f"SubAgent 建议命令: {event.completion.command}", style=COLOR_DEBUG)
                    printer.print_text(f"SubAgent {self.agent_type.title()} 结束", style=COLOR_AGENT_END)
                elif isinstance(event, ErrorEvent):
                    printer.print_panel(
                        content=f"错误: {event.message}",
                        border_style=COLOR_PANEL_ERROR,
                        title="🔥 SubAgent 任务失败", center=True
                    )

                time.sleep(self.args.anti_quota_limit)

                # 如果已经获得完成结果，可以提前结束事件处理
                if completion_text:
                    break
        except Exception as err:
            printer.print_panel(
                content=f"FATAL ERROR: {err}",
                title=f"🔥 SubAgent {self.agent_type.title()} 执行失败",
                border_style=COLOR_PANEL_ERROR,
                center=True)
            completion_text = f"SubAgent {self.agent_type.title()} 执行失败: {str(err)}"

        return completion_status, completion_text
