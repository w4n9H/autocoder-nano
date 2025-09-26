from copy import deepcopy
import json
import re
from typing import List, Tuple, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel

from autocoder_nano.actypes import SourceCode, VerifyFileRelevance, AutoCoderArgs
from autocoder_nano.core import prompt, extract_code, AutoLLM
from autocoder_nano.rag.token_counter import count_tokens
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.utils.color_utils import *


printer = Printer()


class ContentPruner:

    def __init__(self, args: AutoCoderArgs, llm: AutoLLM, max_tokens: int):
        self.args = args
        self.llm = llm
        self.llm.setup_default_model_name(self.args.chat_model)
        self.max_tokens = max_tokens

    @staticmethod
    def _split_content_with_sliding_window(content: str, window_size=100, overlap=20) -> List[Tuple[int, int, str]]:
        """使用滑动窗口分割大文件内容，返回包含行号信息的文本块
        Args:
            content: 要分割的文件内容
            window_size: 每个窗口包含的行数
            overlap: 相邻窗口的重叠行数
        Returns:
            List[Tuple[int, int, str]]: 返回元组列表，每个元组包含:
                - 起始行号(从1开始)，在原始文件的绝对行号
                - 结束行号，在原始文件的绝对行号
                - 带行号的内容文本
        """
        # 按行分割内容
        lines = content.splitlines()
        chunks = []
        start = 0

        while start < len(lines):
            # 计算当前窗口的结束位置
            end = min(start + window_size, len(lines))

            # 计算实际的起始位置(考虑重叠)
            actual_start = max(0, start - overlap)

            # 提取当前窗口的行
            chunk_lines = lines[actual_start:end]

            # 为每一行添加行号
            # 行号从actual_start+1开始，保持与原文件的绝对行号一致
            chunk_content = "\n".join([
                f"{i + 1} {line}" for i, line in enumerate(chunk_lines, start=actual_start)
            ])

            # 保存分块信息：(起始行号, 结束行号, 带行号的内容)
            # 行号从1开始计数
            chunks.append((actual_start + 1, end, chunk_content))

            # 移动到下一个窗口的起始位置
            # 减去overlap确保窗口重叠
            start += (window_size - overlap)

        return chunks

    def _delete_overflow_files(self, file_sources: List[SourceCode]) -> List[SourceCode]:
        """ 直接删除超出 token 限制的文件 """
        total_tokens = 0
        selected_files = []
        # token_count = 0

        for file_source in file_sources:
            try:
                token_count = file_source.tokens
                if token_count <= 0:  # 空文件 or 异常文件
                    # token_count = 0
                    token_count = count_tokens(file_source.source_code)

                if total_tokens + token_count <= self.max_tokens:
                    total_tokens += token_count
                    selected_files.append(file_source)
                else:
                    break
            except Exception as e:
                printer.print_text(f"Failed to read file {file_source.module_name}: {e}", style=COLOR_ERROR)
                selected_files.append(file_source)

        return selected_files

    @prompt()
    def extract_code_snippets(
            self, conversations: List[Dict[str, str]], content: str, is_partial_content: bool = False
    ) -> str:
        """
        根据提供的代码文件和对话历史提取相关代码片段。

        处理示例：
        <examples>
        1.  代码文件：
        <code_file>
            1 def add(a, b):
            2     return a + b
            3 def sub(a, b):
            4     return a - b
        </code_file>
        <conversation_history>
            <user>: 如何实现加法？
        </conversation_history>

        输出：
        ```json
        [
            {"start_line": 1, "end_line": 2}
        ]
        ```

        2.  代码文件：
            1 class User:
            2     def __init__(self, name):
            3         self.name = name
            4     def greet(self):
            5         return f"Hello, {self.name}"
        </code_file>
        <conversation_history>
            <user>: 如何创建一个User对象？
        </conversation_history>

        输出：
        ```json
        [
            {"start_line": 1, "end_line": 3}
        ]
        ```

        3.  代码文件：
        <code_file>
            1 def foo():
            2     pass
        </code_file>
        <conversation_history>
            <user>: 如何实现减法？
        </conversation_history>

        输出：
        ```json
        []
        ```
        </examples>

        输入:
        1. 代码文件内容:
        <code_file>
        {{ content }}
        </code_file>

        <% if is_partial_content: %>
        <partial_content_process_note>
        当前处理的是文件的局部内容（行号{start_line}-{end_line}），
        请仅基于当前可见内容判断相关性，返回标注的行号区间。
        </partial_content_process_note>
        <% endif %>

        2. 对话历史:
        <conversation_history>
        {% for msg in conversations %}
        <{{ msg.role }}>: {{ msg.content }}
        {% endfor %}
        </conversation_history>

        任务:
        1. 分析最后一个用户问题及其上下文。
        2. 在代码文件中找出与问题相关的一个或多个重要代码段。
        3. 对每个相关代码段，确定其起始行号(start_line)和结束行号(end_line)。
        4. 代码段数量不超过4个。

        输出要求:
        1. 返回一个JSON数组，每个元素包含"start_line"和"end_line"。
        2. start_line和end_line必须是整数，表示代码文件中的行号。
        3. 行号从1开始计数。
        4. 如果没有相关代码段，返回空数组[]。

        输出格式:
        严格的JSON数组，不包含其他文字或解释。

        ```json
        [
            {"start_line": 第一个代码段的起始行号, "end_line": 第一个代码段的结束行号},
            {"start_line": 第二个代码段的起始行号, "end_line": 第二个代码段的结束行号}
        ]
        ```
        """

    def _extract_code_snippets(
            self, file_sources: List[SourceCode], conversations: List[Dict[str, str]]
    ) -> List[SourceCode]:
        """ 抽取关键代码片段策略 """
        token_count = 0
        selected_files = []
        full_file_tokens = int(self.max_tokens * 0.8)

        total_input_tokens = sum(f.tokens for f in file_sources)
        printer.print_text(
            f"🚀 开始代码片段抽取处理，共 {len(file_sources)} 个文件，总token数: {total_input_tokens}", style=COLOR_DEBUG
        )
        printer.print_text(
            f"📋 处理策略: 完整文件优先阈值={full_file_tokens}, 最大token限制={self.max_tokens}", style=COLOR_DEBUG
        )

        for file_source in file_sources:
            try:
                # 完整文件优先
                tokens = file_source.tokens
                if token_count + tokens <= full_file_tokens:
                    selected_files.append(SourceCode(
                        module_name=file_source.module_name, source_code=file_source.source_code, tokens=tokens))
                    token_count += tokens
                    printer.print_text(
                        f"✅ 文件 {file_source.module_name} 完整保留 (token数: {tokens}，当前总token数: {token_count})",
                        style=COLOR_DEBUG
                    )
                    continue

                # 如果单个文件太大，那么先按滑动窗口分割，然后对窗口抽取代码片段
                if tokens > self.max_tokens:
                    chunks = self._split_content_with_sliding_window(
                        file_source.source_code,
                        self.args.context_prune_sliding_window_size,
                        self.args.context_prune_sliding_window_overlap
                    )
                    printer.print_text(
                        f"📊 文件 {file_source.module_name} 通过滑动窗口分割为 {len(chunks)} 个chunks", style=COLOR_DEBUG)

                    all_snippets = []
                    chunk_with_results = 0
                    for chunk_idx, (chunk_start, chunk_end, chunk_content) in enumerate(chunks):
                        printer.print_text(
                            f"🔍 处理chunk {chunk_idx + 1}/{len(chunks)} (行号: {chunk_start}-{chunk_end})",
                            style=COLOR_DEBUG)
                        extracted = self.extract_code_snippets.with_llm(self.llm).run(
                            conversations=conversations,
                            content=chunk_content,
                            is_partial_content=True
                        )
                        if extracted.output:
                            json_str = extract_code(extracted.output)[0][1]
                            snippets = json.loads(json_str)

                            if snippets:  # 有抽取结果
                                chunk_with_results += 1
                                printer.print_text(
                                    f"✅ chunk {chunk_idx + 1} 抽取到 {len(snippets)} 个代码片段: {snippets}", style=COLOR_DEBUG)
                                # 获取到的本来就是在原始文件里的绝对行号
                                # 后续在构建代码片段内容时，会为了适配数组操作修改行号，这里无需处理
                                adjusted_snippets = [{
                                    "start_line": snippet["start_line"],
                                    "end_line": snippet["end_line"]
                                } for snippet in snippets]
                                all_snippets.extend(adjusted_snippets)
                            else:
                                printer.print_text(f"❌ chunk {chunk_idx + 1} 未抽取到相关代码片段", style=COLOR_ERROR)
                        else:
                            printer.print_text(f"❌ chunk {chunk_idx + 1} 抽取失败，未返回结果", style=COLOR_ERROR)
                    printer.print_text(
                        f"📈 滑动窗口处理完成: {chunk_with_results}/{len(chunks)} 个chunks有抽取结果，共收集到 {len(all_snippets)} 个代码片段",
                        style=COLOR_DEBUG
                    )

                    merged_snippets = self._merge_overlapping_snippets(all_snippets)

                    printer.print_text(f"🔄 合并重叠片段: {len(all_snippets)} -> {len(merged_snippets)} 个片段",
                                       style=COLOR_DEBUG)
                    # if merged_snippets:
                    #     self.printer.print_str_in_terminal(f"    合并后的片段: {merged_snippets}")

                    # 只有当有代码片段时才处理
                    if merged_snippets:
                        content_snippets = self._build_snippet_content(
                            file_source.module_name, file_source.source_code, merged_snippets)
                        snippet_tokens = count_tokens(content_snippets)

                        if token_count + snippet_tokens <= self.max_tokens:
                            selected_files.append(SourceCode(
                                module_name=file_source.module_name, source_code=content_snippets,
                                tokens=snippet_tokens))
                            token_count += snippet_tokens
                            printer.print_text(f"✅ 文件 {file_source.module_name} 滑动窗口处理成功，最终抽取到结果", style=COLOR_DEBUG)
                            continue
                        else:
                            printer.print_text(
                                f"❌ 文件 {file_source.module_name} 滑动窗口处理后token数超限"
                                f" ({token_count + snippet_tokens} > {self.max_tokens})，停止处理",
                                style=COLOR_ERROR
                            )
                            break
                    else:
                        printer.print_text(
                            f"⏭️ 文件 {file_source.module_name} 滑动窗口处理后无相关代码片段，跳过处理", style=COLOR_WARNING)
                        continue

                # 抽取关键片段
                lines = file_source.source_code.splitlines()
                new_content = ""

                # 将文件内容按行编号
                for index, line in enumerate(lines):
                    new_content += f"{index + 1} {line}\n"

                printer.print_text(f"🔍 开始对文件 {file_source.module_name} 进行整体代码片段抽取 (共 {len(lines)} 行)",
                                   style=COLOR_DEBUG)

                extracted = self.extract_code_snippets.with_llm(self.llm).run(
                    conversations=conversations,
                    content=new_content
                )

                # 构建代码片段内容
                if extracted.output:
                    json_str = extract_code(extracted.output)[0][1]
                    snippets = json.loads(json_str)

                    if snippets:
                        printer.print_text(f"✅ 抽取到 {len(snippets)} 个代码片段: {snippets}", style=COLOR_DEBUG)
                    else:
                        printer.print_text(f"❌ 未抽取到相关代码片段", style=COLOR_ERROR)

                    # 只有当有代码片段时才处理
                    if snippets:
                        content_snippets = self._build_snippet_content(
                            file_source.module_name, file_source.source_code, snippets)
                        snippet_tokens = count_tokens(content_snippets)
                        if token_count + snippet_tokens <= self.max_tokens:
                            selected_files.append(SourceCode(module_name=file_source.module_name,
                                                             source_code=content_snippets,
                                                             tokens=snippet_tokens))
                            token_count += snippet_tokens
                            printer.print_text(f"✅ 文件 {file_source.module_name} 整体抽取成功，最终抽取到结果", style=COLOR_DEBUG)
                        else:
                            printer.print_text(
                                f"❌ 文件 {file_source.module_name} 整体抽取后token数超限"
                                f" ({token_count + snippet_tokens} > {self.max_tokens})，停止处理",
                                style=COLOR_ERROR)
                            break
                    else:
                        # 没有相关代码片段，跳过这个文件
                        printer.print_text(f"⏭️ 文件 {file_source.module_name} 无相关代码片段，跳过处理", style=COLOR_WARNING)
                else:
                    printer.print_text(f"❌ 文件 {file_source.module_name} 整体抽取失败，未返回结果", style=COLOR_ERROR)

            except Exception as e:
                printer.print_text(f"❌ 文件 {file_source.module_name} 处理异常: {e}", style=COLOR_ERROR)
                continue

        total_input_tokens = sum(f.tokens for f in file_sources)
        final_tokens = sum(f.tokens for f in selected_files)
        complete_files = 0
        snippet_files = 0
        for i, file_source in enumerate(file_sources):
            if i < len(selected_files):
                if selected_files[i].source_code == file_source.source_code:
                    complete_files += 1
                else:
                    snippet_files += 1

        printer.print_text(f"🎯 代码片段抽取处理完成", style=COLOR_DEBUG)
        printer.print_text(f"📊 处理结果统计:", style=COLOR_DEBUG)
        printer.print_key_value(
            items={
                "输入文件数": f"{len(file_sources)} 个",
                "输入token数": f"{total_input_tokens}",
                "输出文件数": f"{len(selected_files)} 个",
                "输出token数": f"{final_tokens}",
                "Token压缩率": f"{((total_input_tokens - final_tokens) / total_input_tokens * 100):.1f}%",
                "完整保留文件": f"{complete_files} 个",
                "片段抽取文件": f"{snippet_files} 个",
                "跳过处理文件": f"{len(file_sources) - len(selected_files)} 个"
            }
        )
        return selected_files

    @staticmethod
    def _merge_overlapping_snippets(snippets: List[dict]) -> List[dict]:
        if not snippets:
            return []

        # 按起始行排序
        sorted_snippets = sorted(snippets, key=lambda x: x["start_line"])

        merged = [sorted_snippets[0]]
        for current in sorted_snippets[1:]:
            last = merged[-1]
            if current["start_line"] <= last["end_line"] + 1:  # 允许1行间隔
                # 合并区间
                merged[-1] = {
                    "start_line": min(last["start_line"], current["start_line"]),
                    "end_line": max(last["end_line"], current["end_line"])
                }
            else:
                merged.append(current)

        return merged

    @staticmethod
    def _build_snippet_content(file_path: str, full_content: str, snippets: List[dict]) -> str:
        """构建包含代码片段的文件内容"""
        lines = full_content.splitlines()
        header = f"Snippets:\n"

        content = []
        for snippet in snippets:
            start = max(0, snippet["start_line"] - 1)
            end = min(len(lines), snippet["end_line"])
            content.append(
                f"# Lines {start + 1}-{end} ({snippet.get('reason', '')})")
            content.extend(lines[start:end])

        return header + "\n".join(content)

    def prune(
            self, file_sources: List[SourceCode], conversations: List[Dict[str, str]], strategy: str = "score"
    ) -> List[SourceCode]:
        """
        处理超出 token 限制的文件
        :param file_sources: 要处理的文件
        :param conversations: 对话上下文（用于提取策略）
        :param strategy: 处理策略 (delete/extract/score)
            * `score`：通过对话分析对文件进行相关性评分，保留分数最高的文件
            * `delete`：简单地从列表开始移除文件，直到满足 token 限制
            * `extract`：基于用户对话内容智能提取每个文件中的关键代码片段，是处理大文件的推荐方式
        """
        file_paths = [file_source.module_name for file_source in file_sources]
        total_tokens, sources = self._count_tokens(file_sources=file_sources)
        if total_tokens <= self.max_tokens:
            return sources

        if strategy == "score":
            return self._score_and_filter_files(sources, conversations)
        if strategy == "delete":
            return self._delete_overflow_files(sources)
        elif strategy == "extract":
            return self._extract_code_snippets(sources, conversations)
        else:
            raise ValueError(f"无效策略: {strategy}. 可选值: delete/extract/score")

    @staticmethod
    def _count_tokens(file_sources: List[SourceCode]) -> Tuple[int, List[SourceCode]]:
        """计算文件总token数"""
        total_tokens = 0
        sources = []
        for file_source in file_sources:
            try:
                if file_source.tokens > 0:
                    tokens = file_source.tokens
                    total_tokens += file_source.tokens
                else:
                    tokens = count_tokens(file_source.source_code)
                    total_tokens += tokens

                sources.append(SourceCode(module_name=file_source.module_name,
                                          source_code=file_source.source_code, tokens=tokens))

            except Exception as e:
                printer.print_text(f"Failed to count tokens for {file_source.module_name}: {e}", style=COLOR_ERROR)
                sources.append(SourceCode(module_name=file_source.module_name,
                                          source_code=file_source.source_code, tokens=0))
        return total_tokens, sources

    @prompt()
    def verify_file_relevance(self, file_content: str, conversations: List[Dict[str, str]]) -> str:
        """
        请验证下面的文件内容是否与用户对话相关:

        文件内容:
        {{ file_content }}

        历史对话:
        <conversation_history>
        {% for msg in conversations %}
        <{{ msg.role }}>: {{ msg.content }}
        {% endfor %}
        </conversation_history>

        相关是指，需要依赖这个文件提供上下文，或者需要修改这个文件才能解决用户的问题。
        请给出相应的可能性分数：0-10，并结合用户问题，理由控制在50字以内。格式如下:

        ```json
        {
            "relevant_score": 0-10,
            "reason": "这是相关的原因（不超过10个中文字符）..."
        }
        ```
        """

    def _score_and_filter_files(
            self, file_sources: List[SourceCode], conversations: List[Dict[str, str]]
    ) -> List[SourceCode]:
        """根据文件相关性评分过滤文件，直到token数大于max_tokens 停止追加"""
        selected_files = []
        total_tokens = 0
        scored_files = []

        def _score_file(file_source: SourceCode) -> dict:
            try:
                score_result = self.verify_file_relevance.with_llm(self.llm).with_return_type(VerifyFileRelevance).run(
                    file_content=file_source.source_code,
                    conversations=conversations
                )
                print(score_result)
                return {
                    "file_path": file_source.module_name,
                    "score": score_result.relevant_score,
                    "tokens": file_source.tokens,
                    "content": file_source.source_code
                }
            except Exception as e:
                printer.print_text(f"Failed to score file {file_source.module_name}: {e}")
                return {}

        # 使用线程池并行打分
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(_score_file, file_source) for file_source in file_sources]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    scored_files.append(result)

        # 第二步：按分数从高到低排序
        scored_files.sort(key=lambda x: x["score"], reverse=True)

        # 第三步：从高分开始过滤，直到token数大于max_tokens 停止追加
        for file_info in scored_files:
            if total_tokens + file_info["tokens"] <= self.max_tokens:
                selected_files.append(SourceCode(
                    module_name=file_info["file_path"],
                    source_code=file_info["content"],
                    tokens=file_info["tokens"]
                ))
                total_tokens += file_info["tokens"]
            else:
                break

        return selected_files


class PruneStrategy(BaseModel):
    name: str
    description: str
    config: Dict[str, Any] = {"safe_zone_tokens": 0}


class ConversationsPruner:
    def __init__(self, args: AutoCoderArgs, llm: AutoLLM):
        self.args = args
        self.llm = llm
        self.llm.setup_default_model_name(self.args.chat_model)
        self.replacement_message = ("This message has been cleared. If you still want to get this information, "
                                    "you can call the tool again to retrieve it.")
        self.strategies = {
            "tool_output_cleanup": PruneStrategy(
                name="tool_output_cleanup",
                description="占位裁剪策略, 通过用占位消息替换内容来清理工具输出结果",
                config={"safe_zone_tokens": self.args.conversation_prune_safe_zone_tokens}
            ),
            "summarize": PruneStrategy(
                name="summarize",
                description="摘要裁剪策略, 对早期对话进行分组摘要, 保留关键信息",
                config={"safe_zone_tokens": self.args.conversation_prune_safe_zone_tokens,
                        "group_size": self.args.conversation_prune_group_size}
            ),
            "truncate": PruneStrategy(
                name="truncate",
                description="截断裁剪策略, 分组截断最早的部分对话",
                config={"safe_zone_tokens": self.args.conversation_prune_safe_zone_tokens,
                        "group_size": self.args.conversation_prune_group_size}
            ),
            "hybrid": PruneStrategy(
                name="hybrid",
                description="混合裁剪策略, 根据对话列表情况, 组合使用不同策略",
                config={"safe_zone_tokens": self.args.conversation_prune_safe_zone_tokens,
                        "group_size": self.args.conversation_prune_group_size}
            )
        }

    @staticmethod
    def _split_system_messages(history_conversation):
        """ 快速将 conversation 列表切分为 system 和 user+assistant 两个列表 """
        split_index = next(
            (i for i, msg in enumerate(history_conversation) if msg["role"] != "system"),
            len(history_conversation)  # 如果全是system消息，则返回整个长度
        )
        return history_conversation[:split_index], history_conversation[split_index:]

    def get_available_strategies(self) -> List[Dict[str, Any]]:
        """ 获取所有可用策略 """
        return [strategy.model_dump() for strategy in self.strategies.values()]

    def prune_conversations(
            self, conversations: List[Dict[str, Any]], strategy_name: str = "tool_output_cleanup"
    ) -> List[Dict[str, Any]]:
        """
        根据策略修剪对话
        Args:
            conversations: 原始对话列表
            strategy_name: 策略名称
        Returns:
            修剪后的对话列表
        """
        safe_zone_tokens = self.args.conversation_prune_safe_zone_tokens
        current_tokens = count_tokens(json.dumps(conversations, ensure_ascii=False))

        if current_tokens <= safe_zone_tokens:
            return conversations

        strategy = self.strategies.get(self.args.conversation_prune_strategy, self.strategies["tool_output_cleanup"])

        if strategy.name == "tool_output_cleanup":
            return self._tool_output_cleanup_prune(conversations, strategy.config)
        elif strategy.name == "summarize":
            return self._summarize_prune(conversations, strategy.config)
        elif strategy.name == "truncate":
            return self._truncate_prune(conversations, strategy.config)
        elif strategy.name == "hybrid":
            return self._hybrid_prune(conversations, strategy.config)
        else:
            printer.print_text(f"未知策略：{strategy_name}，已默认使用占位策略", style=COLOR_WARNING)
            return self._tool_output_cleanup_prune(conversations, strategy.config)

    def _hybrid_prune(self, conversations: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """ 混合裁剪策略 """
        safe_zone_tokens = config.get("safe_zone_tokens", 50 * 1024)
        group_size = config.get("group_size", 4)
        current_tokens = count_tokens(json.dumps(conversations, ensure_ascii=False))

        # 混合裁剪策略
        # 1. 如果会话长度<10,还超过safe_zone_tokens,说明单个会话超大,此时如果使用占位和截断将导致重要信息丢失,故采用摘要策略
        # 2. 如果会话长度处于 11 - 50 之间,说明这是一个刚运行不久的agent,以考虑直接使用占位策略
        # 3. 如果会话长度处于 51 - 100 之间,说明这个agent已经运行了比较久或者是跑了多轮的agent,通过使用占位和摘要结合使用
        # 4. 如果会话长度 >100,说明这是一个运行了超长时间的agent,通过使用占位,摘要和截断结合使用

        if len(conversations) <= 10:  # 摘要
            return self._summarize_prune(conversations,
                                         config={
                                             "safe_zone_tokens": self.args.conversation_prune_safe_zone_tokens,
                                             "group_size": 2  # 使用独立的config
                                         })
        elif 11 <= len(conversations) <= 50:  # 占位
            return self._tool_output_cleanup_prune(conversations, config=config)
        elif 51 <= len(conversations) <= 100:  # 摘要+占位
            summarized = self._summarize_prune(conversations,
                                               config={
                                                   "safe_zone_tokens": int(current_tokens * 0.8),
                                                   "group_size": self.args.conversation_prune_group_size
                                               })
            summarized_tokens = count_tokens(json.dumps(summarized, ensure_ascii=False))
            if summarized_tokens > self.args.conversation_prune_safe_zone_tokens:
                return self._tool_output_cleanup_prune(summarized, config=config)
            return summarized
        else:  # 截断+摘要+占位
            truncated = self._truncate_prune(conversations,
                                             config={
                                                 "safe_zone_tokens": int(current_tokens * 0.8),
                                                 "group_size": self.args.conversation_prune_group_size
                                             })
            truncated_tokens = count_tokens(json.dumps(truncated, ensure_ascii=False))
            if truncated_tokens > self.args.conversation_prune_safe_zone_tokens:
                summarized = self._summarize_prune(truncated,
                                                   config={
                                                       "safe_zone_tokens": int(truncated_tokens * 0.8),
                                                       "group_size": self.args.conversation_prune_group_size
                                                   })
                summarized_tokens = count_tokens(json.dumps(summarized, ensure_ascii=False))
                if summarized_tokens > self.args.conversation_prune_safe_zone_tokens:
                    return self._tool_output_cleanup_prune(summarized, config=config)
                return summarized
            return truncated

    def _truncate_prune(self, conversations: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """截断式剪枝"""
        safe_zone_tokens = config.get("safe_zone_tokens", 50 * 1024)
        group_size = config.get("group_size", 4)
        processed_conversations = conversations.copy()

        system_conversations, other_conversations = self._split_system_messages(processed_conversations)

        init_tokens = count_tokens(json.dumps(system_conversations + other_conversations, ensure_ascii=False))
        printer.print_text(f"[截断裁剪策略]对话: {len(system_conversations + other_conversations)} 条, "
                           f"Token计数: {init_tokens}",
                           style=COLOR_DEBUG)
        while True:
            current_tokens = count_tokens(json.dumps(system_conversations + other_conversations, ensure_ascii=False))
            if current_tokens <= safe_zone_tokens:
                printer.print_text(f"Token计数（{current_tokens}）已在安全区（{safe_zone_tokens}）内，停止裁剪",
                                   style=COLOR_DEBUG)
                break

            # 如果剩余对话不足一组，直接返回系统提示词列表
            if len(other_conversations) <= group_size:
                return system_conversations

            # 移除最早的一组对话
            other_conversations = other_conversations[group_size:]

        final_tokens = count_tokens(json.dumps(system_conversations + other_conversations, ensure_ascii=False))
        printer.print_text(f"[截断裁剪策略]清理完成, Token计数：{init_tokens} → {final_tokens}", style=COLOR_DEBUG)

        return system_conversations + other_conversations

    def _summarize_prune(self, conversations: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """ 摘要式剪枝 """
        safe_zone_tokens = config.get("safe_zone_tokens", 50 * 1024)
        group_size = config.get("group_size", 4)
        processed_conversations = conversations.copy()

        system_conversations, other_conversations = self._split_system_messages(processed_conversations)

        init_tokens = count_tokens(json.dumps(system_conversations + other_conversations, ensure_ascii=False))
        printer.print_text(f"[摘要裁剪策略]对话: {len(system_conversations + other_conversations)} 条, "
                           f"Token计数: {init_tokens}",
                           style=COLOR_DEBUG)
        while True:
            current_tokens = count_tokens(json.dumps(system_conversations + other_conversations, ensure_ascii=False))
            if current_tokens <= safe_zone_tokens:
                printer.print_text(f"Token计数（{current_tokens}）已在安全区（{safe_zone_tokens}）内，停止裁剪",
                                   style=COLOR_DEBUG)
                break

            # 找到要处理的对话组
            early_conversations = other_conversations[:group_size]
            recent_conversations = other_conversations[group_size:]

            if not early_conversations:
                break

            # 生成当前组的摘要
            group_summary = self._generate_summary.with_llm(self.llm).run(
                conversations=early_conversations[-group_size:]
            )

            # 更新对话历史
            other_conversations = [
                                       {"role": "user", "content": f"历史对话摘要：\n{group_summary.output}"},
                                       {"role": "assistant", "content": f"收到"}
                                   ] + recent_conversations

        final_tokens = count_tokens(json.dumps(system_conversations + other_conversations, ensure_ascii=False))
        printer.print_text(f"[摘要裁剪策略]清理完成, Token计数：{init_tokens} → {final_tokens}", style=COLOR_DEBUG)
        return system_conversations + other_conversations

    @prompt()
    def _generate_summary(self, conversations: List[Dict[str, Any]]) -> str:
        """
        请用中文将以下对话浓缩为要点, 保留关键决策和技术细节, 浓缩要点字数要求为原文的 30% 左右：

        <history_conversations>
        {{conversations}}
        </history_conversations>
        """

    def _tool_output_cleanup_prune(self, conversations: List[Dict[str, Any]], config: Dict[str, Any]
                                   ) -> List[Dict[str, Any]]:
        """
        通过用占位消息替换内容来清理工具输出结果
        该方法执行以下操作：
        1. 识别工具结果消息（角色为'user'且内容包含'<tool_result'的消息）
        2. 从首个工具输出开始依次清理
        3. 当token计数进入安全区时停止处理
        """
        safe_zone_tokens = config.get("safe_zone_tokens", 50 * 1024)
        processed_conversations = conversations.copy()

        # 查找所有工具结果消息的索引
        tool_result_indices = []
        for i, conv in enumerate(processed_conversations):
            if conv.get("role") == "user" and isinstance(conv.get("content"), str) and self._is_tool_result_message(conv.get("content", "")):
                tool_result_indices.append(i)

        printer.print_text(f"[占位裁剪策略]发现 {len(tool_result_indices)} 条可能需要清理的工具结果消息", style=COLOR_DEBUG)

        # 依次清理工具输出，从首个输出开始
        init_tokens = count_tokens(json.dumps(processed_conversations, ensure_ascii=False))
        for tool_index in tool_result_indices:
            current_tokens = count_tokens(json.dumps(processed_conversations, ensure_ascii=False))

            if current_tokens <= safe_zone_tokens:
                printer.print_text(f"Token计数（{current_tokens}）已在安全区（{safe_zone_tokens}）内，停止裁剪", style=COLOR_DEBUG)
                break

            # 提取工具名称以生成更具体的替换消息
            tool_name = self._extract_tool_name(processed_conversations[tool_index]["content"])
            if tool_name in ["RecordMemoryTool"]:
                printer.print_text(f"[占位裁剪策略]已跳过清理索引[{tool_index}]的工具结果({tool_name})")
            else:
                replacement_content = self._generate_replacement_message(tool_name)

                # 替换内容
                original_content = processed_conversations[tool_index]["content"]
                processed_conversations[tool_index]["content"] = replacement_content

                printer.print_text(
                    f"[占位裁剪策略]已清理索引[{tool_index}]的工具结果({tool_name}),字符数从 {len(original_content)} 减少到 {len(replacement_content)}",
                    style=COLOR_DEBUG
                )

        final_tokens = count_tokens(json.dumps(processed_conversations, ensure_ascii=False))
        printer.print_text(f"[占位裁剪策略]清理完成。Token计数：{init_tokens} → {final_tokens}", style=COLOR_DEBUG)

        return processed_conversations

    @staticmethod
    def _is_tool_result_message(content: str) -> bool:
        """
        检查消息内容是否包含工具结果 XML 格式
        Args:
            content: 待检查的消息内容
        Returns:
            若内容包含工具结果格式则返回 True
        """
        return "<tool_result" in content and "tool_name=" in content

    @staticmethod
    def _extract_tool_name(content: str) -> str:
        """
        从工具结果 XML 内容中解析工具名称
        Args:
            content: 工具结果 XML 内容
        Returns:
            工具名称，若未找到则返回 'unknown'
        """
        # Pattern to match: <tool_result tool_name='...' or <tool_result tool_name="..."
        pattern = r"<tool_result[^>]*tool_name=['\"]([^'\"]+)['\"]"
        match = re.search(pattern, content)
        if match:
            return match.group(1)
        return "unknown"

    def _generate_replacement_message(self, tool_name: str) -> str:
        """
        生成清理后的工具结果替换消息
        Args:
            tool_name: 被调用工具的名称
        Returns:
            替换消息字符串
        """
        if tool_name and tool_name != "unknown":
            return (f"<tool_result tool_name='{tool_name}' success='true'>"
                    f"<message>Content cleared to save tokens</message>"
                    f"<content>{self.replacement_message}</content>"
                    f"</tool_result>")
        else:
            return (f"<tool_result success='true'><message>[Content cleared to save tokens, you can call the tool "
                    f"again to get the tool result.]</message><"
                    f"content>{self.replacement_message}</content></tool_result>")

    def get_cleanup_statistics(self, original_conversations: List[Dict[str, Any]],
                               pruned_conversations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        获取清理过程的统计信息
        Args:
            original_conversations: 原始对话列表
            pruned_conversations: 清理后的对话列表
        Returns:
            包含清理统计信息的字典
        """
        original_tokens = count_tokens(json.dumps(original_conversations, ensure_ascii=False))
        pruned_tokens = count_tokens(json.dumps(pruned_conversations, ensure_ascii=False))

        cleaned_count = 0
        for orig, pruned in zip(original_conversations, pruned_conversations):
            if (orig.get("role") == "user" and
                    self._is_tool_result_message(orig.get("content", "")) and
                    orig.get("content") != pruned.get("content")):
                cleaned_count += 1

        return {
            "original_tokens": original_tokens,
            "pruned_tokens": pruned_tokens,
            "tokens_saved": original_tokens - pruned_tokens,
            "compression_ratio": f"{(1 - pruned_tokens / original_tokens) * 100:.1f}%" if original_tokens > 0 else "0.0%",
            "tool_results_cleaned": cleaned_count,
            "total_messages": len(original_conversations)
        }
