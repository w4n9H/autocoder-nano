import json
import os
import time
import xml.sax.saxutils
from copy import deepcopy
from typing import Generator, Union

from rich.text import Text

from autocoder_nano.agent.agent_base import BaseAgent, ToolResolverFactory, PromptManager
from autocoder_nano.context import get_context_manager, ConversationsPruner
from rich.markdown import Markdown

from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.core import AutoLLM, stream_chat_with_continue, prompt
from autocoder_nano.actypes import AutoCoderArgs, SourceCodeList
from autocoder_nano.utils.formatted_log_utils import save_formatted_log
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.utils.color_utils import *

printer = Printer()


class AgenticRuntime(BaseAgent):
    def __init__(
            self, args: AutoCoderArgs, llm: AutoLLM, agent_type: str, files: SourceCodeList,
            history_conversation: List[Dict[str, Any]],
            conversation_config: Optional[AgenticEditConversationConfig] = None
    ):
        super().__init__(args, llm)
        self.agent_type = agent_type
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

        # Tools 管理
        self.tool_resolver_factory = ToolResolverFactory()
        self.tool_resolver_factory.register_dynamic_resolver(self.agent_type)

        # prompt 管理
        self.prompt_manager = PromptManager(args=self.args)

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

    def _reinforce_guidelines(self, conversations, interval=5):
        """ 每N轮对话强化指导原则 """
        if len(conversations) % interval == 0:
            printer.print_text(f"强化工具使用规则(间隔{interval})", style=COLOR_SYSTEM)
            conversations.append(
                {"role": "user", "content": self.prompt_manager.load_prompt_file(self.agent_type, "tools")}
            )

    def _build_system_prompt(self) -> List[Dict[str, Any]]:
        """ 构建初始对话消息 """
        system_prompt = [
            {"role": "system", "content": self.prompt_manager.load_prompt_file(self.agent_type, "system")},
            {"role": "system", "content": self.prompt_manager.load_prompt_file(self.agent_type, "tools")},
            {"role": "system", "content": self.prompt_manager.prompt_sysinfo.prompt()}
        ]

        printer.print_text(f"📝 系统提示词长度(token): {self._count_conversations_tokens(system_prompt)}",
                           style=COLOR_TOKEN_USAGE)

        return system_prompt

    def _add_resumed_conversation(self, conversations: list):
        """添加恢复的对话内容"""
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
                printer.print_text(f"📂 恢复对话，已有 {len(current_conversation['messages'])} 条现有消息",
                                   style=COLOR_SUCCESS)

    def analyze(self, request: AgenticEditRequest) -> Generator[Union[LLMOutputEvent, LLMThinkingEvent, ToolCallEvent, ToolResultEvent, CompletionEvent, ErrorEvent, WindowLengthChangeEvent, TokenUsageEvent, PlanModeRespondEvent] | None, None, None]:
        conversations = self._build_system_prompt()
        # 添加恢复的对话内容
        self._add_resumed_conversation(conversations)

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

        yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(conversations))

        iteration_count = 0
        tool_executed = False
        should_yield_completion_event = False
        completion_event = None

        while True:
            self._reinforce_guidelines(conversations=conversations, interval=8)
            iteration_count += 1
            tool_executed = False
            last_message = conversations[-1]
            printer.print_text(f"🔄 当前为第 {iteration_count} 轮对话, 历史会话长度(Context):{len(conversations)}",
                               style=COLOR_ITERATION)

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

            llm_response_gen = stream_chat_with_continue(  # 实际请求大模型
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

                    # printer.print_panel(content=f"tool_xml \n{tool_xml}", title=f"🛠️ 工具触发: {tool_name}",
                    #                     center=True)
                    printer.print_text(f"🛠️ 工具触发: {tool_name}", style=COLOR_TOOL_CALL)

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

                    yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(conversations))
                    yield event  # Yield the ToolCallEvent for display

                    # Handle AttemptCompletion separately as it ends the loop
                    if isinstance(tool_obj, AttemptCompletionTool):
                        printer.print_text(f"正在结束会话, 完成结果: {tool_obj.result[:50]}...", style=COLOR_COMPLETION)
                        completion_event = CompletionEvent(completion=tool_obj, completion_xml=tool_xml)
                        mark_event_should_finish = True
                        should_yield_completion_event = True
                        continue

                    # Resolve the tool
                    resolver_cls = self.tool_resolver_factory.get_resolver(type(tool_obj))
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
                    conversations.append({
                        "role": "user",  # Simulating the user providing the tool result
                        "content": error_xml
                    })
                    self.conversation_manager.append_message_to_current(
                        role="user",
                        content=error_xml,
                        metadata={})

                    yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(conversations))

                    # 一次交互只能有一次工具，剩下的其实就没有用了，但是如果不让流式处理完，我们就无法获取服务端
                    # 返回的token消耗和计费，所以通过此标记来完成进入空转，直到流式走完，获取到最后的token消耗和计费
                    mark_event_should_finish = True

                elif isinstance(event, ErrorEvent):
                    if event.message.startswith("Stream ended with unterminated"):
                        printer.print_text(f"流以未闭合的标签块结束, 即将强化记忆", style=COLOR_ERROR)
                        conversations.append(
                            {"role": "user", "content": "使用工具时需要包含 开始和结束标签, 缺失结束标签会导致工具调用失败"}
                        )
                    yield event
                elif isinstance(event, TokenUsageEvent):
                    yield event

            if not tool_executed:
                # No tool executed in this LLM response cycle
                printer.print_text("LLM响应完成, 未执行任何工具", style=COLOR_WARNING)
                if assistant_buffer:
                    printer.print_text(f"将 Assistant Buffer 内容写入会话历史（字符数：{len(assistant_buffer)}）")

                    last_message = conversations[-1]
                    if last_message["role"] != "assistant":
                        printer.print_text("添加新的 Assistant 消息", style=COLOR_SYSTEM)
                        conversations.append({"role": "assistant", "content": assistant_buffer})
                        self.conversation_manager.append_message_to_current(
                            role="assistant", content=assistant_buffer, metadata={})
                    elif last_message["role"] == "assistant":
                        printer.print_text("追加已存在的 Assistant 消息", style=COLOR_SYSTEM)
                        last_message["content"] += assistant_buffer

                    yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(conversations))

                # 添加系统提示，要求LLM必须使用工具或明确结束，而不是直接退出
                printer.print_text("💡 正在添加系统提示: 请使用工具或尝试直接生成结果", style=COLOR_SYSTEM)

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

                yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(conversations))
                # 继续循环，让 LLM 再思考，而不是 break
                printer.print_text("🔄 持续运行 LLM 交互循环（保持不中断）", style=COLOR_ITERATION)
                continue

        printer.print_text(f"✅ Agentic {self.agent_type} 分析循环已完成，共执行 {iteration_count} 次迭代.", style=COLOR_ITERATION)
        save_formatted_log(self.args.source_dir, json.dumps(conversations, ensure_ascii=False), "agentic_conversation")

    def run_in_terminal(self, request: AgenticEditRequest):
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))

        printer.print_text(f"🚀 Agentic {self.agent_type} 开始运行, 项目名: {project_name}, "
                           f"用户目标: {request.user_input.strip()}",
                           style=COLOR_SYSTEM)

        # 用于累计TokenUsageEvent数据
        accumulated_token_usage = {
            "model_name": "",
            "input_tokens": 0,
            "output_tokens": 0,
        }

        try:
            self._apply_pre_changes()  # 在开始 Agentic 之前先判断是否有未提交变更,有变更则直接退出
            event_stream = self.analyze(request)
            for event in event_stream:
                if isinstance(event, TokenUsageEvent):
                    self._handle_token_usage_event(event, accumulated_token_usage)
                elif isinstance(event, WindowLengthChangeEvent):
                    printer.print_text(f"📝 当前 Token 总用量: {event.tokens_used}", style=COLOR_TOKEN_USAGE)
                elif isinstance(event, LLMThinkingEvent):
                    # 以不太显眼的样式（比如灰色）呈现思考内容
                    printer.print_panel(
                        content=Text(f"{event.text}", style=COLOR_LLM_THINKING),
                        title="💭 LLM Thinking",
                        border_style=COLOR_PANEL_INFO,
                        center=True)
                elif isinstance(event, LLMOutputEvent):
                    printer.print_panel(
                        content=Text(f"{event.text}", style=COLOR_LLM_OUTPUT),
                        title="💬 LLM Output",
                        border_style=COLOR_PANEL_INFO,
                        center=True)
                elif isinstance(event, ToolCallEvent):
                    self._handle_tool_call_event(event)
                elif isinstance(event, ToolResultEvent):
                    self._handle_tool_result_event(event)
                elif isinstance(event, CompletionEvent):
                    try:
                        self._apply_changes(request)  # 在这里完成实际合并
                    except Exception as e:
                        printer.print_text(f"合并变更失败: {e}", style=COLOR_ERROR)

                    printer.print_panel(
                        content=Markdown(event.completion.result),
                        border_style=COLOR_PANEL_SUCCESS,
                        title="🏁 任务完成", center=True
                    )
                    if event.completion.command:
                        printer.print_text(f"建议命令: {event.completion.command}", style=COLOR_DEBUG)
                elif isinstance(event, ErrorEvent):
                    printer.print_panel(
                        content=f"Error: {event.message}",
                        border_style=COLOR_PANEL_ERROR,
                        title="🔥 任务失败", center=True
                    )

                time.sleep(self.args.anti_quota_limit)
        except Exception as err:
            # 在处理异常时也打印累计的token使用情况
            if accumulated_token_usage["input_tokens"] > 0:
                printer.print_key_value(accumulated_token_usage)
            printer.print_panel(
                content=f"FATAL ERROR: {err}",
                title=f"🔥 Agentic {self.agent_type} 运行错误",
                border_style=COLOR_PANEL_ERROR,
                center=True)
            raise err
        finally:
            printer.print_text(f"Agentic {self.agent_type} 结束", style=COLOR_AGENT_END)