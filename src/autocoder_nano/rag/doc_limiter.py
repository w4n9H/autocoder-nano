import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Dict

from autocoder_nano.core import AutoLLM
from autocoder_nano.core import prompt, extract_code
from autocoder_nano.actypes import SourceCode, AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


class TokenLimiter:
    def __init__(
        self, count_tokens: Callable[[str], int], full_text_limit: int, segment_limit: int, buff_limit: int,
        llm: AutoLLM, args: AutoCoderArgs, disable_segment_reorder: bool,
    ):
        self.count_tokens = count_tokens
        self.full_text_limit = full_text_limit
        self.segment_limit = segment_limit
        self.buff_limit = buff_limit
        self.llm = llm
        self.args = args
        self.first_round_full_docs = []
        self.second_round_extracted_docs = []
        self.sencond_round_time = 0
        self.disable_segment_reorder = disable_segment_reorder

    @prompt()
    def extract_relevance_range_from_docs_with_conversation(
            self, conversations: List[Dict[str, str]], documents: List[str]
    ) -> str:
        """
        根据提供的文档和对话历史提取相关信息范围。

        输入:
        1. 文档内容:
        {% for doc in documents %}
        {{ doc }}
        {% endfor %}

        2. 对话历史:
        {% for msg in conversations %}
        <{{ msg.role }}>: {{ msg.content }}
        {% endfor %}

        任务:
        1. 分析最后一个用户问题及其上下文。
        2. 在文档中找出与问题相关的一个或多个重要信息段。
        3. 对每个相关信息段，确定其起始行号(start_line)和结束行号(end_line)。
        4. 信息段数量不超过4个。

        输出要求:
        1. 返回一个JSON数组，每个元素包含"start_line"和"end_line"。
        2. start_line和end_line必须是整数，表示文档中的行号。
        3. 行号从1开始计数。
        4. 如果没有相关信息，返回空数组[]。

        输出格式:
        严格的JSON数组，不包含其他文字或解释。

        示例:
        1.  文档：
            1 这是这篇动物科普文。
            2 大象是陆地上最大的动物之一。
            3 它们生活在非洲和亚洲。
            问题：大象生活在哪里？
            返回：[{"start_line": 2, "end_line": 3}]

        2.  文档：
            1 地球是太阳系第三行星，
            2 有海洋、沙漠，温度适宜，
            3 是已知唯一有生命的星球。
            4 太阳则是太阳系的唯一恒心。
            问题：地球的特点是什么？
            返回：[{"start_line": 1, "end_line": 3}]

        3.  文档：
            1 苹果富含维生素。
            2 香蕉含有大量钾元素。
            问题：橙子的特点是什么？
            返回：[]
        """

    def limit_tokens(
            self, relevant_docs: List[SourceCode], conversations: List[Dict[str, str]], index_filter_workers: int,
    ) -> List[SourceCode]:
        final_relevant_docs = []
        token_count = 0
        doc_num_count = 0

        reorder_relevant_docs = []

        # 文档分段（单个文档过大）和重排序逻辑
        # 1. 背景：在检索过程中，许多文档被切割成多个段落（segments）
        # 2. 问题：这些segments在召回时因为是按相关分做了排序可能是乱序的，不符合原文顺序，会强化大模型的幻觉。
        # 3. 目标：重新排序这些segments，确保来自同一文档的segments保持连续且按正确顺序排列。
        # 4. 实现方案：
        #    a) 方案一（保留位置）：统一文档的不同segments 根据chunk_index 来置换位置
        #    b) 方案二（当前实现）：遍历文档，发现某文档的segment A，立即查找该文档的所有其他segments，
        #       对它们进行排序，并将排序后多个segments插入到当前的segment A 位置中。
        # TODO:
        #     1. 未来根据参数决定是否开启重排以及重排的策略
        if not self.disable_segment_reorder:
            num_count = 0
            for doc in relevant_docs:
                num_count += 1
                reorder_relevant_docs.append(doc)
                if "original_doc" in doc.metadata and "chunk_index" in doc.metadata:
                    original_doc_name = doc.metadata["original_doc"]

                    temp_docs = []
                    for temp_doc in relevant_docs[num_count:]:
                        if "original_doc" in temp_doc.metadata and "chunk_index" in temp_doc.metadata:
                            if temp_doc.metadata["original_doc"] == original_doc_name:
                                if temp_doc not in reorder_relevant_docs:
                                    temp_docs.append(temp_doc)

                    temp_docs.sort(key=lambda x: x.metadata["chunk_index"])
                    reorder_relevant_docs.extend(temp_docs)
        else:
            reorder_relevant_docs = relevant_docs

        # 非窗口分区实现
        for doc in reorder_relevant_docs:
            doc_tokens = self.count_tokens(doc.source_code)
            doc_num_count += 1
            if token_count + doc_tokens <= self.full_text_limit + self.segment_limit:
                final_relevant_docs.append(doc)
                token_count += doc_tokens
            else:
                break

        # 如果窗口无法放下所有的相关文档，则需要分区
        if len(final_relevant_docs) < len(reorder_relevant_docs):
            printer.print_text(f"窗口无法放下所有的相关文档, 开始分区处理", style="yellow")
            # 先填充full_text分区
            token_count = 0
            new_token_limit = self.full_text_limit
            doc_num_count = 0
            for doc in reorder_relevant_docs:
                doc_tokens = self.count_tokens(doc.source_code)
                doc_num_count += 1
                if token_count + doc_tokens <= new_token_limit:
                    self.first_round_full_docs.append(doc)
                    token_count += doc_tokens
                else:
                    break

            if len(self.first_round_full_docs) > 0:
                remaining_tokens = (self.full_text_limit + self.segment_limit - token_count)
            else:
                printer.print_text("整个文本区域为空，这可能是由于单个文档过长导致的", style="yellow")
                remaining_tokens = self.full_text_limit + self.segment_limit

            # 继续填充segment分区
            sencond_round_start_time = time.time()
            remaining_docs = reorder_relevant_docs[len(self.first_round_full_docs):]
            printer.print_key_value(
                items={"首轮文档数": f"{len(self.first_round_full_docs)}", "剩余文档数": f"{len(remaining_docs)}"},
                title="第一轮 DocLimit"
            )

            self.llm.setup_default_model_name(self.args.chunk_model)
            with ThreadPoolExecutor(max_workers=index_filter_workers or 5) as executor:
                future_to_doc = {
                    executor.submit(self.process_range_doc, doc, conversations): doc
                    for doc in remaining_docs
                }

                for future in as_completed(future_to_doc):
                    doc = future_to_doc[future]
                    try:
                        result = future.result()
                        if result and remaining_tokens > 0:
                            self.second_round_extracted_docs.append(result)
                            tokens = result.tokens
                            if tokens > 0:
                                remaining_tokens -= tokens
                            else:
                                printer.print_text(f"文档 {doc.module_name} 的标记数量为 0 或负数", style="yellow")
                    except Exception as exc:
                        printer.print_text(f"处理文档 {doc.module_name} 时发生异常: {exc}", style="red")

            final_relevant_docs = (self.first_round_full_docs + self.second_round_extracted_docs)
            self.sencond_round_time = time.time() - sencond_round_start_time
            printer.print_key_value(
                items={
                    "第二轮文档数": f"{self.second_round_extracted_docs}",
                    "处理耗时": f"{self.sencond_round_time:.2f} 秒"},
                title="第二轮 DocLimit"
            )

        return final_relevant_docs

    def process_range_doc(
            self, doc: SourceCode, conversations: List[Dict[str, str]], max_retries=3
    ) -> SourceCode | None:
        for attempt in range(max_retries):
            content = ""
            try:
                source_code_with_line_number = ""
                source_code_lines = doc.source_code.split("\n")
                for idx, line in enumerate(source_code_lines):
                    source_code_with_line_number += f"{idx + 1} {line}\n"

                llm = self.llm

                extracted_info = (
                    self.extract_relevance_range_from_docs_with_conversation
                    .with_llm(llm)
                    .run(conversations, [source_code_with_line_number])
                )
                json_str = extract_code(extracted_info.output)[0][1]
                json_objs = json.loads(json_str)

                for json_obj in json_objs:
                    start_line = json_obj["start_line"] - 1
                    end_line = json_obj["end_line"]
                    chunk = "\n".join(source_code_lines[start_line:end_line])
                    content += chunk + "\n"

                return SourceCode(
                    module_name=doc.module_name,
                    source_code=content.strip(),
                    tokens=self.count_tokens(content),
                    metadata={
                        "original_doc": doc.module_name,
                        "chunk_ranges": json_objs,
                    },
                )
            except Exception as e:
                if attempt < max_retries - 1:
                    printer.print_text(f"处理文档 {doc.module_name} 时出错，正在重试(尝试次数:{attempt + 1})错误：{str(e)}",
                                       style="yellow")
                else:
                    printer.print_text(f"在 {max_retries} 次尝试后仍未能处理文档 {doc.module_name}：{str(e)}",
                                       style="red")
                    return SourceCode(
                        module_name=doc.module_name, source_code="", tokens=0
                    )