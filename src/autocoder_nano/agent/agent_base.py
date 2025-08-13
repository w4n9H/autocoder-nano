import json
import re
import xml.sax.saxutils

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.core import AutoLLM, format_str_jinja2
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.agent.agentic_edit_types import *


printer = Printer()


TOOL_DISPLAY_MESSAGES: Dict[Type[BaseTool], Dict[str, str]] = {
    ReadFileTool: {
        "zh": "AutoCoder Nano 想要读取此文件：\n {{ path }}"
    },
    WriteToFileTool: {
        "zh": (
            "AutoCoder Nano 想要写入此文件：\n{{ path }} \n\n内容片段：\n{{ content_snippet }} {{ ellipsis }} "
        )
    },
    ReplaceInFileTool: {
        "zh": (
            "AutoCoder Nano 想要替换此文件中的内容：\n{{ path }} \n\n差异片段：\n{{ diff_snippet }}{{ ellipsis }}"
        )
    },
    ExecuteCommandTool: {
        "zh": (
            "AutoCoder Nano 想要执行此命令：\n{{ command }}\n(需要批准：{{ requires_approval }})"
        )
    },
    ListFilesTool: {
        "zh": (
            "AutoCoder Nano 想要列出此目录中的文件：\n{{ path }} {{ recursive_text }}"
        )
    },
    SearchFilesTool: {
        "zh": (
            "AutoCoder Nano 想要在此目录中搜索文件：\n{{ path }}\n文件模式: {{ file_pattern }}\n正则表达式：{{ regex }}"
        )
    },
    ListCodeDefinitionNamesTool: {
        "zh": "AutoCoder Nano 想要列出此路径中的定义：\n{{ path }}"
    },
    AskFollowupQuestionTool: {
        "zh": (
            "AutoCoder Nano 正在提问：\n{{ question }}\n{{ options_text }}"
        )
    },
    RecordMemoryTool: {
        "zh": (
            "AutoCoder Nano 正在记录笔记：\n{{ content }}"
        )
    },
    RecallMemoryTool: {
        "zh": (
            "AutoCoder Nano 正在检索笔记, 提问：\n{{ query }}"
        )
    }
}


class BaseAgent:

    def __init__(self, args: AutoCoderArgs, llm: AutoLLM):
        self.args = args
        self.llm = llm
        # self.conversation_manager = get_context_manager()
        # self.tool_resolver_map = {}  # 子类填充具体工具实现

    @staticmethod
    def get_tool_display_message(tool: BaseTool, lang="zh") -> str:
        """ 生成一个用户友好的, 国际化的工具调用字符串表示 """
        tool_type = type(tool)

        if tool_type not in TOOL_DISPLAY_MESSAGES:  # Fallback for unknown tools
            return f"Unknown tool type: {tool_type.__name__}\nData: {tool.model_dump_json(indent=2)}"

        templates = TOOL_DISPLAY_MESSAGES[tool_type]
        template = templates.get(lang, templates.get("en", "Tool display template not found"))  # Fallback to English

        if isinstance(tool, ReadFileTool):
            context = {"path": tool.path}
        elif isinstance(tool, WriteToFileTool):
            snippet = tool.content[:150]
            context = {
                "path": tool.path, "content_snippet": snippet, "ellipsis": '...' if len(tool.content) > 150 else ''
            }
        elif isinstance(tool, ReplaceInFileTool):
            snippet = tool.diff
            context = {
                "path": tool.path, "diff_snippet": snippet, "ellipsis": ''
            }
        elif isinstance(tool, ExecuteCommandTool):
            context = {"command": tool.command, "requires_approval": tool.requires_approval}
        elif isinstance(tool, ListFilesTool):
            context = {"path": tool.path, "recursive_text": '（递归）' if tool.recursive else '（顶层）'}
        elif isinstance(tool, SearchFilesTool):
            context = {
                "path": tool.path, "file_pattern": tool.file_pattern or '*', "regex": tool.regex
            }
        elif isinstance(tool, ListCodeDefinitionNamesTool):
            context = {"path": tool.path}
        elif isinstance(tool, AskFollowupQuestionTool):
            options_text_zh = ""
            if tool.options:
                options_list_zh = "\n".join(
                    [f"- {opt}" for opt in tool.options])  # Assuming options are simple enough not to need translation
                options_text_zh = f"选项：\n{options_list_zh}"
            context = {
                "question": tool.question, "options_text": options_text_zh
            }
        elif isinstance(tool, RecordMemoryTool):
            context = {"content": tool.content}
        elif isinstance(tool, RecallMemoryTool):
            context = {"query": tool.query}
        else:
            context = tool.model_dump()  # Generic context for tools not specifically handled above

        try:
            return format_str_jinja2(template, **context)
        except Exception as e:
            return f"Error formatting display for {tool_type.__name__}: {e}\nTemplate: {template}\nContext: {context}"

    @staticmethod
    def _parse_tool_xml(tool_xml: str, tool_tag: str) -> Optional[BaseTool]:
        """ Agent工具 XML字符串 解析器 """
        params = {}
        try:
            # 在<tool_tag>和</tool_tag>之间查找内容
            inner_xml_match = re.search(rf"<{tool_tag}>(.*?)</{tool_tag}>", tool_xml, re.DOTALL)
            if not inner_xml_match:
                printer.print_text(f"无法在<{tool_tag}>...</{tool_tag}>标签内找到内容", style="red")
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
                                           style="red")
                        # 保持为字符串还是处理错误？目前先保持为字符串
                        pass
                if tool_tag == 'plan_mode_respond' and 'options' in params:
                    try:
                        params['options'] = json.loads(params['options'])
                    except json.JSONDecodeError:
                        printer.print_text(f"plan_mode_respond_tool 参数JSON解码失败: {params['options']}",
                                           style="red")
                # 处理 list_files 工具的递归参数
                if tool_tag == 'list_files' and 'recursive' in params:
                    params['recursive'] = params['recursive'].lower() == 'true'
                return tool_cls(**params)
            else:
                printer.print_text(f"未找到标签对应的工具类: {tool_tag}", style="red")
                return None
        except Exception as e:
            printer.print_text(f"解析工具XML <{tool_tag}> 失败: {e}\nXML内容:\n{tool_xml}", style="red")
            return None

    @staticmethod
    def _reconstruct_tool_xml(tool: BaseTool) -> str:
        """ Reconstructs the XML representation of a tool call from its Pydantic model. """
        tool_tag = next((tag for tag, model in TOOL_MODEL_MAP.items() if isinstance(tool, model)), None)
        if not tool_tag:
            printer.print_text(f"找不到工具类型 {type(tool).__name__} 对应的标签名", style="red")
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

    # def run(self, request) -> Generator:
    #     raise NotImplementedError