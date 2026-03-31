import json
import os
import time
import xml.sax.saxutils
from copy import deepcopy
from typing import Generator, Union
from datetime import datetime

from autocoder_nano.agent.agent_base import BaseAgent, ToolResolverFactory, PromptManager
from autocoder_nano.agent.agentic_skills import SkillRegistry
from autocoder_nano.context import get_context_manager, ConversationsPruner
from rich.markdown import Markdown

from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.core import AutoLLM, stream_chat_with_continue, prompt
from autocoder_nano.actypes import AutoCoderArgs, SourceCodeList
from autocoder_nano.utils.formatted_log_utils import save_formatted_log
from autocoder_nano.utils.printer_utils import (
    Printer, COLOR_SYSTEM, COLOR_SUCCESS, COLOR_WARNING, COLOR_ERROR, COLOR_INFO)

printer = Printer()


class AgenticRuntime(BaseAgent):
    def __init__(
            self, args: AutoCoderArgs, llm: AutoLLM,
            agent_define: dict,
            files: SourceCodeList,
            history_conversation: List[Dict[str, Any]],
            conversation_config: Optional[AgenticEditConversationConfig] = None
    ):
        super().__init__(args, llm)
        self.agent_define = agent_define
        self.agent_type = self.get_keys_by_type('main')[0]
        self.subagents = self.get_keys_by_type('sub')
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
        self.tool_resolver_factory = ToolResolverFactory(self.agent_define)
        self.tool_resolver_factory.register_dynamic_resolver(self.agent_type)

        # prompt 管理
        self.prompt_manager = PromptManager(args=self.args, agent_define=self.agent_define)

        if self.conversation_config.action == "new":
            conversation_id = self.conversation_manager.create_conversation(
                name=self.conversation_config.query or "New Conversation",
                description=self.conversation_config.query or "New Conversation")
            self.conversation_manager.set_current_conversation(conversation_id)
        if self.conversation_config.action == "resume" and self.conversation_config.conversation_id:
            self.conversation_manager.set_current_conversation(self.conversation_config.conversation_id)

    def get_keys_by_type(self, target_type):
        result = []
        for key, value in self.agent_define.items():
            # 检查当前项是否包含type字段且等于目标type
            if isinstance(value, dict) and value.get("type") == target_type:
                result.append(key)
        return result

    def _reinforce_guidelines(self, conversations, interval=5):
        """ 每N轮对话强化指导原则 """
        if len(conversations) % interval == 0:
            printer.print_text(f"强化工具使用规则(间隔{interval})", style=COLOR_SYSTEM, prefix=self.mapp)
            conversations.append(
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

        ## 工具使用格式

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

        ## 工具列表

        {guides}

        ## 错误处理
        
        - 如果工具调用失败，你需要分析错误信息，并重新尝试，或者向用户报告错误并请求帮助

        ## 工具熔断机制
        
        - 工具连续失败3次时启动备选方案或直接结束任务
        - 自动标注行业惯例方案供用户确认
        
        ## 工具调用规范
        
        - 调用前必须在 <think></think> 内分析：
            * 分析系统环境及目录结构
            * 根据目标选择合适工具
            * 必填参数检查（用户提供或可推断，否则用 `ask_followup_question` 询问）
        - 当所有必填参数齐备或可明确推断后，才关闭思考标签并调用工具

        ## 工具使用指南
        
        1. 开始任务前务必进行全面搜索和探索
        2. 在 <think> 标签中评估已有和继续完成任务所需信息
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
        return self.prompt_manager.system_prompt(self.agent_type)

    def _get_subagent_prompt(self) -> str:
        return self.prompt_manager.subagent_prompt(self.subagents)

    def _get_skills_pompt(self) -> str:
        _registry = SkillRegistry(args=self.args)
        _registry.scan_skills()
        return _registry.get_skills_summary()

    def _get_sysinfo_prompt(self) -> str:
        return self.prompt_manager.sysinfo_prompt.prompt()

    def _build_system_prompt(self) -> List[Dict[str, Any]]:
        """ 构建初始对话消息 """
        _system_prompt = (
            f""
            f"{self._get_system_prompt()}\n"
            f"----------\n"
            f"{self._get_subagent_prompt()}\n"
            f"----------\n"
            f"{self._get_tools_prompt()}\n"
            f"----------\n"
            f"{self._get_skills_pompt() if self.tool_resolver_factory.has_resolver(CallSkillsTool) else ''}\n"
            f"----------\n"
            f"{self._get_sysinfo_prompt()}")
        system_prompt = [
            {"role": "system", "content": _system_prompt}
        ]

        printer.print_text(f"系统提示词长度(token): {self._count_conversations_tokens(system_prompt)}",
                           style=COLOR_INFO, prefix=self.mapp)

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
                printer.print_text(f"恢复对话，已有 {len(current_conversation['messages'])} 条现有消息",
                                   style=COLOR_SUCCESS, prefix=self.mapp)

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
            "role": "user",
            "content": f"{request.user_input} \n Current Time:{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
            printer.print_text(f"当前为第 {iteration_count} 轮对话, 历史会话长度(Context):{len(conversations)}",
                               style=COLOR_INFO, prefix=self.mapp)

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

                    # 不在展示工具触发, 仅展示后面的调用部分
                    # printer.print_panel(content=f"tool_xml \n{tool_xml}", title=f"🛠️ 工具触发: {tool_name}",
                    #                     center=True)
                    # printer.print_text(f"🛠️ 工具触发: {tool_name}", style=COLOR_TOOL_CALL)

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
                        printer.print_text(f"正在准备结束会话 ...", style=COLOR_INFO, prefix=self.mapp)
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
                        printer.print_text(f"流以未闭合的标签块结束, 即将强化记忆", style=COLOR_ERROR, prefix=self.mapp)
                        conversations.append(
                            {"role": "user", "content": "使用工具时需要包含 开始和结束标签, 缺失结束标签会导致工具调用失败"}
                        )
                    yield event
                elif isinstance(event, TokenUsageEvent):
                    yield event

            if not tool_executed:
                # No tool executed in this LLM response cycle
                printer.print_text("LLM响应完成, 未执行任何工具", style=COLOR_WARNING, prefix=self.mapp)
                if assistant_buffer:
                    printer.print_text(f"将 Assistant Buffer 内容写入会话历史（字符数：{len(assistant_buffer)}）",
                                       style=COLOR_INFO, prefix=self.mapp)

                    last_message = conversations[-1]
                    if last_message["role"] != "assistant":
                        printer.print_text("添加新的 Assistant 消息", style=COLOR_INFO, prefix=self.mapp)
                        conversations.append({"role": "assistant", "content": assistant_buffer})
                        self.conversation_manager.append_message_to_current(
                            role="assistant", content=assistant_buffer, metadata={})
                    elif last_message["role"] == "assistant":
                        printer.print_text("追加已存在的 Assistant 消息", style=COLOR_INFO, prefix=self.mapp)
                        last_message["content"] += assistant_buffer

                    yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(conversations))

                # 添加系统提示，要求LLM必须使用工具或明确结束，而不是直接退出
                printer.print_text("正在添加系统提示: 请使用工具或尝试直接生成结果", style=COLOR_INFO, prefix=self.mapp)

                conversations.append({
                    "role": "user",
                    "content": "注意：如果你当前的任务已经完成并且已无后续待办，请使用 attempt_completion 工具完成任务"
                })
                self.conversation_manager.append_message_to_current(
                    role="user",
                    content="注意：如果你当前的任务已经完成并且已无后续待办，请使用 attempt_completion 工具完成任务",
                    metadata={})

                yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(conversations))
                # 继续循环，让 LLM 再思考，而不是 break
                printer.print_text("持续运行 LLM 交互循环（保持不中断）", style=COLOR_INFO, prefix=self.mapp)
                continue

        printer.print_text(f"Agentic {self.agent_type} 分析循环已完成，共执行 {iteration_count} 次迭代.",
                           style=COLOR_INFO, prefix=self.mapp)
        save_formatted_log(self.args.source_dir, json.dumps(conversations, ensure_ascii=False), "agentic_conversation")

    def run_in_terminal(self, request: AgenticEditRequest):
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))

        printer.print_text(f"Agentic {self.agent_type} 开始运行, 项目名: {project_name}, "
                           f"用户目标: {request.user_input.strip()}",
                           style=COLOR_SYSTEM, prefix=self.mapp)

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
                    pass
                    # printer.print_text(f"当前 Token 总用量: {event.tokens_used}", style=COLOR_INFO, prefix=self.mapp)
                elif isinstance(event, LLMThinkingEvent):
                    # 以不太显眼的样式（比如灰色）呈现思考内容
                    # printer.print_panel(
                    #     content=Text(f"{event.text}", style=COLOR_INFO, justify="left"),
                    #     title="LLM Thinking",
                    #     border_style=COLOR_INFO,
                    #     center=True)
                    printer.print_text(f"LLM Thinking: ", style=COLOR_SYSTEM, prefix=self.mapp)
                    printer.print_llm_output(f"{event.text}")
                elif isinstance(event, LLMOutputEvent):
                    # printer.print_panel(
                    #     content=Text(f"{event.text}", style=COLOR_INFO, justify="left"),
                    #     title="LLM Output",
                    #     border_style=COLOR_INFO,
                    #     center=True)
                    printer.print_text(f"LLM Output: ", style=COLOR_SYSTEM, prefix=self.mapp)
                    printer.print_llm_output(f"{event.text}")
                elif isinstance(event, ToolCallEvent):
                    self._handle_tool_call_event(event)
                elif isinstance(event, ToolResultEvent):
                    self._handle_tool_result_event(event)
                elif isinstance(event, CompletionEvent):
                    try:
                        self._apply_changes(request)  # 在这里完成实际合并
                    except Exception as e:
                        printer.print_text(f"合并变更失败: {e}", style=COLOR_ERROR, prefix=self.mapp)

                    printer.print_panel(
                        content=Markdown(event.completion.result),
                        border_style=COLOR_SUCCESS,
                        title="任务完成", center=True
                    )
                    if event.completion.command:
                        printer.print_text(f"建议命令: {event.completion.command}", style=COLOR_INFO, prefix=self.mapp)
                elif isinstance(event, ErrorEvent):
                    printer.print_panel(
                        content=f"Error: {event.message}",
                        border_style=COLOR_ERROR,
                        title="任务失败", center=True
                    )

                time.sleep(self.args.anti_quota_limit)
        except Exception as err:
            # 在处理异常时也打印累计的token使用情况
            if accumulated_token_usage["input_tokens"] > 0:
                printer.print_key_value(accumulated_token_usage)
            printer.print_panel(
                content=f"FATAL ERROR: {err}",
                title=f"Agentic {self.agent_type} 运行错误",
                border_style=COLOR_ERROR,
                center=True)
            raise err
        finally:
            self._delete_old_todo_file()
            printer.print_text(f"Agentic {self.agent_type} 结束", style=COLOR_SUCCESS, prefix=self.mapp)

    def run_in_web(self, request: AgenticEditRequest):
        from autocoder_nano.core.queue import sqlite_queue
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))

        try:
            # self._apply_pre_changes()  # web模式下，在开始 Agentic 之前不再判断是否有未提交变更
            event_stream = self.analyze(request)
            for event in event_stream:
                if isinstance(event, TokenUsageEvent):
                    pass
                elif isinstance(event, LLMThinkingEvent):
                    thinking_steps = [f"{event.text}"]
                    sqlite_queue.insert_agent_response(
                        self.args.web_queue_db_path,
                        self.args.web_client_id,
                        self.args.web_message_id,
                        "thinking", thinking_steps)
                elif isinstance(event, LLMOutputEvent):
                    output_steps = [f"{event.text}"]
                    sqlite_queue.insert_agent_response(
                        self.args.web_queue_db_path,
                        self.args.web_client_id,
                        self.args.web_message_id,
                        "output", output_steps)
                elif isinstance(event, ToolCallEvent):
                    tool_name = type(event.tool).__name__
                    tool_call = {
                        "name": f"{tool_name}",
                        "params": f"{event.tool_xml}",
                        "status": "",
                        "result": ""
                    }
                    sqlite_queue.insert_agent_response(
                        self.args.web_queue_db_path,
                        self.args.web_client_id,
                        self.args.web_message_id,
                        "tool_call", tool_call)
                elif isinstance(event, ToolResultEvent):
                    tool_name = event.tool_name
                    result = event.result
                    tool_result = {
                        "name": f"{tool_name}",
                        "params": f"{result.message}",
                        "status": f"{'success' if result.success else 'error'}",
                        "result": f"{result.content if result.content else ''}"
                    }
                    sqlite_queue.insert_agent_response(
                        self.args.web_queue_db_path,
                        self.args.web_client_id,
                        self.args.web_message_id,
                        "tool_result", tool_result)
                elif isinstance(event, CompletionEvent):
                    try:
                        self.args.skip_commit = True  # 临时设置参数
                        self._apply_changes(request)  # 在这里完成实际变更
                    except Exception as e:
                        printer.print_text(f"合并变更失败: {e}", style=COLOR_ERROR, prefix=self.mapp)

                    final_reply = [f"{event.completion.result}"]
                    sqlite_queue.insert_agent_response(
                        self.args.web_queue_db_path,
                        self.args.web_client_id,
                        self.args.web_message_id,
                        "final", final_reply)
                elif isinstance(event, ErrorEvent):
                    if event.message != "Stream ended with unterminated <think> block.":
                        error_message = [f"{event.message}"]
                        sqlite_queue.insert_agent_response(
                            self.args.web_queue_db_path,
                            self.args.web_client_id,
                            self.args.web_message_id,
                            "error", error_message)
                time.sleep(self.args.anti_quota_limit)
        except Exception as err:
            error_message = [f"{err}"]
            sqlite_queue.insert_agent_response(
                self.args.web_queue_db_path,
                self.args.web_client_id,
                self.args.web_message_id,
                "error", error_message)
        finally:
            self._delete_old_todo_file()