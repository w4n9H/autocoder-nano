import hashlib
import json
import re
import os
import xml.sax.saxutils
from importlib import resources

from rich.markdown import Markdown
from rich.text import Text

from autocoder_nano.actypes import AutoCoderArgs, SingleOutputMeta
from autocoder_nano.core import AutoLLM, prompt
from autocoder_nano.rag.token_counter import count_tokens
from autocoder_nano.rules import get_rules_context
from autocoder_nano.utils.config_utils import prepare_chat_yaml, get_last_yaml_file, convert_yaml_config_to_str
from autocoder_nano.utils.git_utils import get_uncommitted_changes, commit_changes
from autocoder_nano.utils.printer_utils import (
    Printer, COLOR_ERROR, COLOR_SUCCESS, COLOR_WARNING, COLOR_INFO, COLOR_SYSTEM)
from autocoder_nano.agent.agent_define import get_subagent_define
from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.agent.agentic_edit_tools import *
from autocoder_nano.utils.sys_utils import detect_env

printer = Printer()


TOOL_RESOLVER_MAP: Dict[Type[BaseTool], Type[BaseToolResolver]] = {
    ExecuteCommandTool: ExecuteCommandToolResolver,
    ReadFileTool: ReadFileToolResolver,
    WriteToFileTool: WriteToFileToolResolver,
    ReplaceInFileTool: ReplaceInFileToolResolver,
    SearchFilesTool: SearchFilesToolResolver,
    ListFilesTool: ListFilesToolResolver,
    AskFollowupQuestionTool: AskFollowupQuestionToolResolver,
    AttemptCompletionTool: AttemptCompletionToolResolver,  # Will stop the loop anyway
    TodoReadTool: TodoReadToolResolver,
    TodoWriteTool: TodoWriteToolResolver,
    WebSearchTool: WebSearchToolResolver,
    ACModWriteTool: ACModWriteToolResolver,
    ACModSearchTool: ACModSearchToolResolver,
    CallSubAgentTool: CallSubAgentToolResolver,
    UseRAGTool: UseRAGToolResolver
}


class BaseAgent:

    def __init__(self, args: AutoCoderArgs, llm: AutoLLM):
        self.args = args
        self.llm = llm
        # self.conversation_manager = get_context_manager()
        # self.tool_resolver_map = {}  # 子类填充具体工具实现

        # main agent printer prefix
        self.mapp = "* (main:agent) "

    @staticmethod
    def get_tool_display_message(tool: BaseTool) -> str:
        """ 生成一个用户友好的, 国际化的工具调用字符串表示 """
        if isinstance(tool, ReadFileTool):
            context = f"读取文件：{tool.path}"
        elif isinstance(tool, WriteToFileTool):
            context = f"写入文件: {tool.path}"
        elif isinstance(tool, ReplaceInFileTool):
            context = f"变更文件: {tool.path}"
        elif isinstance(tool, ExecuteCommandTool):
            context = f"执行命令: {tool.command} (是否审批: {tool.requires_approval})"
        elif isinstance(tool, ListFilesTool):
            context = f"列出目录: {tool.path} ({'递归' if tool.recursive else '顶层'})"
        elif isinstance(tool, SearchFilesTool):
            context = f"搜索文件: {tool.path}, 文件模式: {tool.file_pattern}, 正则表达式：{tool.regex}"
        elif isinstance(tool, AskFollowupQuestionTool):
            options_text_zh = ""
            if tool.options and isinstance(tool.options, list):
                options_text_zh = "\n".join(
                    [f"- {opt}" for opt in tool.options])  # Assuming options are simple enough not to need translation
            context = f"模型提问: {tool.question}, 选项：{options_text_zh}"
        elif isinstance(tool, WebSearchTool):
            context = f"联网搜索: {tool.query}"
        elif isinstance(tool, RecordMemoryTool):
            context = f"记录记忆: {tool.content[:50]}"
        elif isinstance(tool, RecallMemoryTool):
            context = f"检索记忆: {tool.query}"
        elif isinstance(tool, ACModWriteTool):
            context = f"ACMod 记录: {tool.content[:50]}"
        elif isinstance(tool, ACModSearchTool):
            context = f"ACMod 检索: {tool.query}"
        elif isinstance(tool, CallSubAgentTool):
            context = f"子代理调用: {tool.agent_type}"
        elif isinstance(tool, UseRAGTool):
            context = f"RAG检索: {tool.query}"
        else:
            context = ""

        return context

    def _parse_tool_xml(self, tool_xml: str, tool_tag: str) -> Optional[BaseTool]:
        """ Agent工具 XML字符串 解析器 """
        params = {}
        try:
            # 在<tool_tag>和</tool_tag>之间查找内容
            inner_xml_match = re.search(rf"<{tool_tag}>(.*?)</{tool_tag}>", tool_xml, re.DOTALL)
            if not inner_xml_match:
                printer.print_text(f"无法在<{tool_tag}>...</{tool_tag}>标签内找到内容",
                                   style=COLOR_ERROR, prefix=self.mapp)
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
                                           style=COLOR_ERROR, prefix=self.mapp)
                        # 保持为字符串还是处理错误？目前先保持为字符串
                        pass
                if tool_tag == 'plan_mode_respond' and 'options' in params:
                    try:
                        params['options'] = json.loads(params['options'])
                    except json.JSONDecodeError:
                        printer.print_text(f"plan_mode_respond_tool 参数JSON解码失败: {params['options']}",
                                           style=COLOR_ERROR, prefix=self.mapp)
                # 处理 list_files 工具的递归参数
                if tool_tag == 'list_files' and 'recursive' in params:
                    params['recursive'] = params['recursive'].lower() == 'true'
                return tool_cls(**params)
            else:
                printer.print_text(f"未找到标签对应的工具类: {tool_tag}", style=COLOR_ERROR, prefix=self.mapp)
                return None
        except Exception as e:
            printer.print_text(f"解析工具XML <{tool_tag}> 失败: {e}\nXML内容:\n{tool_xml}",
                               style=COLOR_ERROR, prefix=self.mapp)
            return None

    def _reconstruct_tool_xml(self, tool: BaseTool) -> str:
        """ Reconstructs the XML representation of a tool call from its Pydantic model. """
        tool_tag = next((tag for tag, model in TOOL_MODEL_MAP.items() if isinstance(tool, model)), None)
        if not tool_tag:
            printer.print_text(f"找不到工具类型 {type(tool).__name__} 对应的标签名", style=COLOR_ERROR, prefix=self.mapp)
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

    def stream_and_parse_llm_response(self, generator):
        """ LLM响应解析器 """
        buffer = ""
        in_tool_block = False
        in_thinking_block = False
        current_tool_tag = None
        valid_tool_tags = set(TOOL_MODEL_MAP.keys())
        tool_start_pattern = re.compile(r"<(" + "|".join(valid_tool_tags) + r")>")
        # tool_start_pattern = re.compile(r"<(?!thinking\b)([a-zA-Z0-9_]+)>")  # Matches tool tags
        thinking_start_tag = "<thinking>"
        thinking_end_tag = "</thinking>"

        last_metadata = None
        for content_chunk, metadata in generator:
            if not content_chunk:
                last_metadata = metadata
                continue

            last_metadata = metadata
            buffer += content_chunk

            while True:  # 循环处理缓冲区直到无法解析完整事件
                # 检查状态转换：思考->文本，工具->文本，文本->思考，文本->工具
                found_event = False

                # 1. 如果在思考块中，检查</thinking>
                if in_thinking_block:
                    end_think_pos = buffer.find(thinking_end_tag)
                    if end_think_pos != -1:
                        thinking_content = buffer[:end_think_pos]
                        yield LLMThinkingEvent(text=thinking_content)
                        buffer = buffer[end_think_pos + len(thinking_end_tag):]
                        in_thinking_block = False
                        found_event = True
                        continue  # 用更新后的缓冲区/状态重新开始循环
                    else:
                        break  # 需要更多数据来关闭思考块

                # 2. 如果在工具块中，检查</tool_tag>
                elif in_tool_block:
                    end_tag = f"</{current_tool_tag}>"
                    end_tool_pos = buffer.find(end_tag)
                    if end_tool_pos != -1:
                        tool_block_end_index = end_tool_pos + len(end_tag)
                        tool_xml = buffer[:tool_block_end_index]
                        tool_obj = self._parse_tool_xml(tool_xml, current_tool_tag)

                        if tool_obj:
                            # 成功解析后精确重建XML, 确保生成的XML与解析内容匹配
                            reconstructed_xml = self._reconstruct_tool_xml(tool_obj)
                            if reconstructed_xml.startswith("<error>"):
                                yield ErrorEvent(message=f"Failed to reconstruct XML for tool {current_tool_tag}")
                            else:
                                yield ToolCallEvent(tool=tool_obj, tool_xml=reconstructed_xml)
                        else:
                            # yield ErrorEvent(message=f"Failed to parse tool: <{current_tool_tag}>")
                            # 可选：将原始XML作为纯文本输出？
                            # yield LLMOutputEvent(text=tool_xml)
                            yield LLMOutputEvent(text=f"Failed to parse tool: <{current_tool_tag}> {tool_xml}")

                        buffer = buffer[tool_block_end_index:]
                        in_tool_block = False
                        current_tool_tag = None
                        found_event = True
                        continue  # 重新开始循环
                    else:
                        break  # 需要更多数据来关闭工具块

                # 3. 如果在纯文本状态，检查<thinking>或<tool_tag>
                else:
                    start_think_pos = buffer.find(thinking_start_tag)
                    tool_match = tool_start_pattern.search(buffer)
                    start_tool_pos = tool_match.start() if tool_match else -1
                    tool_name = tool_match.group(1) if tool_match else None

                    # 确定哪个标签先出现（如果有）
                    first_tag_pos = -1
                    is_thinking = False
                    is_tool = False

                    if start_think_pos != -1 and (start_tool_pos == -1 or start_think_pos < start_tool_pos):
                        first_tag_pos = start_think_pos
                        is_thinking = True
                    elif start_tool_pos != -1 and (start_think_pos == -1 or start_tool_pos < start_think_pos):
                        if tool_name in TOOL_MODEL_MAP:  # 检查是否是已知工具
                            first_tag_pos = start_tool_pos
                            is_tool = True
                        else:
                            pass  # 未知标签，暂时视为文本，让缓冲区继续累积

                    if first_tag_pos != -1:  # 找到<thinking>或已知<tool>
                        # 如果有前置文本则输出
                        preceding_text = buffer[:first_tag_pos]
                        if preceding_text:
                            yield LLMOutputEvent(text=preceding_text)

                        # 状态转换
                        if is_thinking:
                            buffer = buffer[first_tag_pos + len(thinking_start_tag):]
                            in_thinking_block = True
                        elif is_tool:
                            # 保留开始标签
                            buffer = buffer[first_tag_pos:]
                            in_tool_block = True
                            current_tool_tag = tool_name

                        found_event = True
                        continue  # 重新开始循环
                    else:
                        # 未找到标签，或只找到未知标签. 需要更多数据或流结束。
                        # 输出文本块但保留部分缓冲区以防标签开始, 保留最后128个字符
                        # split_point = max(0, len(buffer) - 4096)
                        # text_to_yield = buffer[:split_point]
                        # if text_to_yield:
                        #     yield LLMOutputEvent(text=text_to_yield)
                        #     buffer = buffer[split_point:]
                        # break  # 需要更多数据
                        if len(buffer) > 2048:
                            split_point = len(buffer) - 512  # 减少保留的缓冲区大小
                            # 寻找最近的换行符
                            newline_pos = buffer.rfind('\n', 0, split_point)
                            if newline_pos > split_point - 200:  # 如果换行符距离截断点不太远
                                split_point = newline_pos + 1

                            text_to_yield = buffer[:split_point]
                            if text_to_yield:
                                yield LLMOutputEvent(text=text_to_yield)
                                buffer = buffer[split_point:]
                            break  # 需要更多数据
                        else:
                            break  # buffer较小，不进行截断
                # 如果本轮未处理事件，跳出内层循环
                if not found_event:
                    break

        # 生成器耗尽后，输出剩余内容
        if in_thinking_block:
            # 未终止的思考块
            yield ErrorEvent(message="Stream ended with unterminated <thinking> block.")
            if buffer:
                # 将剩余内容作为思考输出
                yield LLMThinkingEvent(text=buffer)
        elif in_tool_block:
            # 未终止的工具块
            yield ErrorEvent(message=f"Stream ended with unterminated <{current_tool_tag}> block.")
            if buffer:
                yield LLMOutputEvent(text=buffer)  # 将剩余内容作为文本输出
        elif buffer:
            # 输出剩余纯文本
            yield LLMOutputEvent(text=buffer)

        # 这个要放在最后，防止其他关联的多个事件的信息中断
        yield TokenUsageEvent(usage=last_metadata)

    def _apply_pre_changes(self):
        uncommitted_changes = get_uncommitted_changes(self.args.source_dir)
        if uncommitted_changes != "No uncommitted changes found.":
            raise Exception("代码中包含未提交的更新,请执行/commit")

    def _apply_changes(self, request: AgenticEditRequest):
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
                        self.args.source_dir, f"auto_coder_nano_{latest_yaml_file}_{md5}",
                    )
                    if commit_message:
                        printer.print_text(f"Commit 成功", style=COLOR_SUCCESS, prefix=self.mapp)
                except Exception as err:
                    import traceback
                    traceback.print_exc()
                    printer.print_text(f"Commit 失败: {err}", style=COLOR_ERROR, prefix=self.mapp)
        else:
            printer.print_text(f"文件未进行任何更改, 无需 Commit", style=COLOR_WARNING, prefix=self.mapp)

    @staticmethod
    def _count_conversations_tokens(conversations: list):
        return count_tokens(json.dumps(conversations, ensure_ascii=False))

    def _handle_token_usage_event(self, event, accumulated_token_usage):
        """处理token使用事件"""
        last_meta: SingleOutputMeta = event.usage

        # 累计token使用情况
        accumulated_token_usage["model_name"] = self.args.chat_model
        accumulated_token_usage["input_tokens"] += last_meta.input_tokens_count
        accumulated_token_usage["output_tokens"] += last_meta.generated_tokens_count

        printer.print_text(f"Token 使用: "
                           f"Input({last_meta.input_tokens_count})/"
                           f"Output({last_meta.generated_tokens_count})",
                           style=COLOR_INFO, prefix=self.mapp)

    def _handle_tool_call_event(self, event):
        """处理工具调用事件"""
        # 跳过显示AttemptCompletionTool的工具调用
        if isinstance(event.tool, AttemptCompletionTool):
            return

        tool_name = type(event.tool).__name__
        display_content = self.get_tool_display_message(event.tool)
        printer.print_text(
            Text.assemble(
                (f"{tool_name}: ", COLOR_SYSTEM),
                (f"{display_content}", COLOR_INFO)
            ),
            prefix=self.mapp
        )

    def _handle_tool_result_event(self, event):
        """处理工具结果事件"""
        if event.tool_name in ["AttemptCompletionTool", "PlanModeRespondTool"]:
            return

        result = event.result
        # if result.success:
        #     title = f"工具返回: {event.tool_name}"
        # else:
        #     title = f"工具返回: {event.tool_name}"
        # base_content = f"状态: {'成功' if result.success else '失败'}, 信息: {result.message}"

        # 打印基础信息面板
        # printer.print_text(f"{title}, {base_content}", style=COLOR_INFO, prefix=self.mapp)
        printer.print_text(
            Text.assemble(
                (f"{event.tool_name} Result: ", COLOR_SYSTEM),
                (f"{result.message}", COLOR_SUCCESS if result.success else COLOR_ERROR)
            ),
            prefix=self.mapp
        )

        if event.tool_name in ["TodoReadTool", "TodoWriteTool"]:
            printer.print_panel(
                content=Markdown(result.content),
                title="Todo List",
                border_style=COLOR_INFO,
                center=True)

        # 不在展示具体的代码，以展示 Agent 操作为主
        # content_str = self._format_tool_result_content(result.content)
        # lexer = self._determine_content_lexer(event.tool_name, result.message)
        # if content_str:
        #     printer.print_code(
        #         code=content_str, lexer=lexer, theme="monokai", line_numbers=True, panel=True)

    def _format_tool_result_content(self, result_content, max_len: int = 500):
        """格式化工具返回的内容"""

        def _format_content(_content):
            if len(_content) > max_len:
                return f"{_content[:200]}\n\n\n......\n\n\n{_content[-200:]}"
            else:
                return _content

        content_str = ""
        if result_content is not None:
            try:
                if isinstance(result_content, (dict, list)):
                    content_str = _format_content(json.dumps(result_content, indent=2, ensure_ascii=False))
                elif isinstance(result_content, str) and (
                        '\n' in result_content or result_content.strip().startswith('<')):
                    content_str = _format_content(str(result_content))
                else:
                    content_str = str(result_content)
            except Exception as e:
                printer.print_text(f"Error formatting tool result content: {e}", style=COLOR_WARNING, prefix=self.mapp)
                content_str = _format_content(str(result_content))

        return content_str

    @staticmethod
    def _determine_content_lexer(tool_name, result_message):
        """根据工具类型和内容确定语法高亮器"""
        if tool_name == "ReadFileTool" and isinstance(result_message, str):
            # Try to guess lexer from file extension in message
            if ".py" in result_message:
                lexer = "python"
            elif ".js" in result_message:
                lexer = "javascript"
            elif ".ts" in result_message:
                lexer = "typescript"
            elif ".html" in result_message:
                lexer = "html"
            elif ".css" in result_message:
                lexer = "css"
            elif ".json" in result_message:
                lexer = "json"
            elif ".xml" in result_message:
                lexer = "xml"
            elif ".md" in result_message:
                lexer = "markdown"
            else:
                lexer = "text"  # Fallback lexer
        elif tool_name == "ExecuteCommandTool":
            lexer = "shell"
        else:
            lexer = "text"

        return lexer

    def _delete_old_todo_file(self):
        todo_file = os.path.join(self.args.source_dir, ".auto-coder", "todos", "current_session.json")
        if os.path.exists(todo_file):
            printer.print_text(f"TodoList 文件已清理", style=COLOR_INFO, prefix=self.mapp)
            os.remove(todo_file)


class ToolResolverFactory:
    """工具解析器工厂"""

    def __init__(self):
        self._resolvers: Dict[Type[BaseTool], Type[BaseToolResolver]] = {}

    def register_resolver(self, tool_type: Type[BaseTool], resolver_class: Type[BaseToolResolver]) -> None:
        """
        注册工具解析器
        Args:
            tool_type: 工具类型
            resolver_class: 解析器类
        """
        if not issubclass(resolver_class, BaseToolResolver):
            raise ValueError(f"Resolver class {resolver_class} must be a subclass of BaseToolResolver")

        self._resolvers[tool_type] = resolver_class
        # printer.print_text(f"✅ 注册工具解析器: {tool_type.__name__} -> {resolver_class.__name__}", style="green")

    def register_dynamic_resolver(self, agent_type):
        subagent = get_subagent_define()
        if agent_type not in subagent:
            raise Exception(f"未内置该[{agent_type}] Agent 类型")

        tool_list = subagent[agent_type]["tools"]

        for tool in tool_list:
            _tool_type = TOOL_MODEL_MAP[tool]
            _resolver_class = TOOL_RESOLVER_MAP[_tool_type]

            self.register_resolver(_tool_type, _resolver_class)
        printer.print_text(f"已注册 Agent Tool Resolver {len(tool_list)} 个", style=COLOR_INFO)

    def get_resolvers(self):
        return self._resolvers

    def get_resolver(self, tool_type: Type[BaseTool]):
        if not self.has_resolver(tool_type):
            raise Exception(f"{tool_type} 工具类型不存在")
        return self._resolvers[tool_type]

    def has_resolver(self, tool_type: Type[BaseTool]) -> bool:
        """检查是否有指定工具类型的解析器"""
        return tool_type in self._resolvers

    def get_registered_tools(self) -> list:
        """获取所有已注册的工具类型"""
        return list(self._resolvers.keys())

    def get_registered_size(self) -> int:
        """获取所有已注册的工具类型"""
        return len(self._resolvers.keys())

    def clear_instances(self) -> None:
        """清除所有解析器实例"""
        self._resolvers.clear()
        printer.print_text("已清除所有工具解析器实例", style=COLOR_WARNING)


class PromptManager:
    """ 提示词管理器 - 集中管理所有提示词模板 """

    def __init__(self, args):
        self.args = args
        self.prompts_dirs = resources.files("autocoder_nano").joinpath("agent/prompt").__str__()

        if not os.path.exists(self.prompts_dirs):
            raise Exception(f"{self.prompts_dirs} 提示词目录不存在")

    def load_prompt_file(self, agent_type, prompt_type) -> str:
        _prompt_file_name = f"{agent_type}_{prompt_type}_prompt.md"
        _prompt_file_path = os.path.join(self.prompts_dirs, _prompt_file_name)

        if not os.path.exists(_prompt_file_path):
            raise Exception(f"{_prompt_file_path} 提示词文件不存在")

        with open(_prompt_file_path, 'r') as fp:
            prompt_str = fp.read()
        return prompt_str

    @prompt()
    def prompt_sysinfo(self):
        """
        # 系统信息

        操作系统：{{os_distribution}}
        默认 Shell：{{shell_type}}
        主目录：{{home_dir}}
        当前工作目录：{{current_project}}

        {% if rules_context %}
        # RULES
        {{ rules_context }}
        {% endif %}
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
            "rules_context": get_rules_context(self.args.source_dir)
        }

    @staticmethod
    def subagent_info(used_subagent: list[str]) -> str:
        subagent_use_info = "## SubAgent 类型\n"
        subagent_define = get_subagent_define()
        for sub in used_subagent:
            if sub in subagent_define:
                subagent = subagent_define[sub]
                subagent_use_info += f"### {sub.title()}\n{subagent['description']}\n{subagent['call']}\n\n"
        return subagent_use_info