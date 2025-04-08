import json
import os
import statistics
import time
import traceback
from typing import Optional, Dict, Any, Generator, List

import pathspec
from loguru import logger
from openai import OpenAI
from rich.console import Console
from rich.table import Table
from tokenizers import Tokenizer

from autocoder_nano.llm_client import AutoLLM
from autocoder_nano.llm_prompt import prompt
from autocoder_nano.llm_types import SourceCode, AutoCoderArgs, FilterDoc, VariableHolder
from autocoder_nano.rag.doc_filter import DocFilter
from autocoder_nano.rag.doc_limiter import TokenLimiter
from autocoder_nano.rag.doc_retriever import LocalDocumentRetriever
from autocoder_nano.rag.token_counter import TokenCounter, RemoteTokenCounter


def get_event_file_path(request_id: str, base_path: str = "events") -> str:
    return f"{base_path}/{request_id}.jsonl"


class LongContextRAG:
    def __init__(self, llm: AutoLLM, args: AutoCoderArgs, path: str, tokenizer_path: Optional[str] = None,) -> None:
        self.llm = llm
        self.args = args
        self.path = path

        # 基础配置
        self.relevant_score = self.args.rag_doc_filter_relevance or 5
        self.token_limit = self.args.rag_context_window_limit or 120000
        self.full_text_ratio = self.args.full_text_ratio
        self.segment_ratio = self.args.segment_ratio
        self.buff_ratio = 1 - self.full_text_ratio - self.segment_ratio
        if self.buff_ratio < 0:
            raise ValueError("full_text_ratio 和 segment_ratio 的总和必须小于或等于 1.0")
        self.full_text_limit = int(self.args.rag_context_window_limit * self.full_text_ratio)
        self.segment_limit = int(self.args.rag_context_window_limit * self.segment_ratio)
        self.buff_limit = int(self.args.rag_context_window_limit * self.buff_ratio)

        # 分词相关
        self.tokenizer = None
        self.tokenizer_path = tokenizer_path
        if self.tokenizer_path:
            VariableHolder.TOKENIZER_PATH = self.tokenizer_path
            VariableHolder.TOKENIZER_MODEL = Tokenizer.from_file(self.tokenizer_path)
            self.tokenizer = TokenCounter(self.tokenizer_path)
        else:
            if llm.get_sub_client("deepseek_tokenizer"):
                tokenizer_llm = AutoLLM()
                tokenizer_llm.setup_default_model_name("deepseek_tokenizer")
                self.tokenizer = RemoteTokenCounter(tokenizer_llm)

        # 设置忽略文件后缀
        self.ignore_spec = self._load_ignore_file()
        self.required_exts = (
            [ext.strip() for ext in self.args.required_exts.split(",")]
            if self.args.required_exts
            else []
        )

        # 监控模式
        self.monitor_mode = self.args.monitor_mode or False
        self.enable_hybrid_index = self.args.enable_hybrid_index
        logger.info(f"监控模式: {self.monitor_mode}")

        # 设置 Client
        if args.rag_url and args.rag_url.startswith("http://"):
            if not args.rag_token:
                raise ValueError("您当前处于客户端模式，请提供 RAG token。例如：rag_token: your_token_here")
            if not args.rag_url.endswith("/v1"):
                args.rag_url = args.rag_url.rstrip("/") + "/v1"
            self.client = OpenAI(api_key=args.rag_token, base_url=args.rag_url)
        else:
            self.client = None
            # if not pure client mode, then the path should be provided
            if not self.path and args.rag_url and not args.rag_url.startswith("http://"):
                self.path = args.rag_url
            if not self.path:
                raise ValueError("请提供本地文件系统中文档的路径。")

        retriever_class = self._get_document_retriever_class()
        self.document_retriever = retriever_class(
            self.llm,
            self.args,
            self.path,
            self.ignore_spec,
            self.required_exts,
            False,
            self.monitor_mode,
            # 确保全文区至少能放下一个文件
            single_file_token_limit=self.full_text_limit - 100,
            disable_auto_window=self.args.disable_auto_window,
            enable_hybrid_index=self.args.enable_hybrid_index
        )

        # 文本过滤初始化
        self.doc_filter = DocFilter(
            self.llm, self.args, on_ray=False, path=self.path
        )

        doc_num = 0
        token_num = 0
        token_counts = []
        for doc in self._retrieve_documents():
            doc_num += 1
            doc_tokens = doc.tokens
            token_num += doc_tokens
            token_counts.append(doc_tokens)
        avg_tokens = statistics.mean(token_counts) if token_counts else 0
        median_tokens = statistics.median(token_counts) if token_counts else 0

        logger.info("RAG 配置:")
        logger.info(f"  文档总数: {doc_num}")
        logger.info(f"  总 Token 数: {token_num}")
        logger.info(f"  分词器路径: {self.tokenizer_path}")
        logger.info(f"  相关性分数: {self.relevant_score}")
        logger.info(f"  Token 限制: {self.token_limit}")
        logger.info(f"  全文限制: {self.full_text_limit}")
        logger.info(f"  段落限制: {self.segment_limit}")
        logger.info(f"  缓冲限制: {self.buff_limit}")
        logger.info(f"  最大文档 Token 数: {max(token_counts) if token_counts else 0}")
        logger.info(f"  最小文档 Token 数: {min(token_counts) if token_counts else 0}")
        logger.info(f"  平均文档 Token 数: {avg_tokens:.2f}")
        logger.info(f"  文档 Token 数中位数: {median_tokens:.2f}")

    def count_tokens(self, text: str) -> int:
        if self.tokenizer is None:
            return -1
        return self.tokenizer.count_tokens(text)

    @prompt()
    def extract_relevance_info_from_docs_with_conversation(
            self, conversations: List[Dict[str, str]], documents: List[str]
    ) -> str:
        """
        使用以下文档和对话历史来提取相关信息。

        文档：
        <documents>
        {% for doc in documents %}
        {{ doc }}
        {% endfor %}
        </documents>

        对话历史：
        <conversations>
        {% for msg in conversations %}
        [{{ msg.role }}]:
        {{ msg.content }}

        {% endfor %}
        </conversations>

        请根据提供的文档内容、用户对话历史以及最后一个问题，提取并总结文档中与问题相关的重要信息。
        如果文档中没有相关信息，请回复"该文档中没有与问题相关的信息"。
        提取的信息尽量保持和原文中的一样，并且只输出这些信息。
        """

    @prompt()
    def _answer_question(
            self, query: str, relevant_docs: List[str]
    ) -> Generator[str, None, None]:
        """
        文档：
        <documents>
        {% for doc in relevant_docs %}
        {{ doc }}
        {% endfor %}
        </documents>

        使用以上文档来回答用户的问题。回答要求：

        1. 严格基于文档内容回答
        - 如果文档提供的信息无法回答问题,请明确回复:"抱歉,文档中没有足够的信息来回答这个问题。"
        - 不要添加、推测或扩展文档未提及的信息

        2. 格式如 ![image](./path.png) 的 Markdown 图片处理
        - 根据Markdown 图片前后文本内容推测改图片与问题的相关性，有相关性则在回答中输出该Markdown图片路径
        - 根据相关图片在文档中的位置，自然融入答复内容,保持上下文连贯
        - 完整保留原始图片路径,不省略任何部分

        3. 回答格式要求
        - 使用markdown格式提升可读性

        问题：{{ query }}
        """

    def _retrieve_documents(self, options: Optional[Dict[str, Any]] = None) -> Generator[SourceCode, None, None]:
        return self.document_retriever.retrieve_documents(options=options)

    @staticmethod
    def _get_document_retriever_class():
        """Get the document retriever class based on configuration."""
        # Default to LocalDocumentRetriever if not specified
        return LocalDocumentRetriever

    def _load_ignore_file(self):
        serveignore_path = os.path.join(self.path, ".serveignore")
        gitignore_path = os.path.join(self.path, ".gitignore")

        if os.path.exists(serveignore_path):
            with open(serveignore_path, "r") as ignore_file:
                return pathspec.PathSpec.from_lines("gitwildmatch", ignore_file)
        elif os.path.exists(gitignore_path):
            with open(gitignore_path, "r") as ignore_file:
                return pathspec.PathSpec.from_lines("gitwildmatch", ignore_file)
        return None

    def build(self):
        pass

    def search(self, query: str) -> List[SourceCode]:
        target_query = query
        only_contexts = False
        if self.args.enable_rag_search and isinstance(self.args.enable_rag_search, str):
            target_query = self.args.enable_rag_search
        elif self.args.enable_rag_context and isinstance(self.args.enable_rag_context, str):
            target_query = self.args.enable_rag_context
            only_contexts = True
        elif self.args.enable_rag_context:
            only_contexts = True

        logger.info("正在从 RAG 中搜索.....")
        logger.info(f"查询内容: {target_query[0:100]}... only_contexts: {only_contexts}")

        if self.client:  # 设置的 http:// 即 url 类型的 rag
            new_query = json.dumps(
                {"query": target_query, "only_contexts": only_contexts},
                ensure_ascii=False,
            )
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": new_query}],
                model=self.args.model,
                max_tokens=self.args.rag_params_max_tokens,
            )
            v = response.choices[0].message.content
            if not only_contexts:
                return [SourceCode(module_name=f"RAG:{target_query}", source_code=v)]

            json_lines = [json.loads(line) for line in v.split("\n") if line.strip()]
            return [SourceCode.model_validate(json_line) for json_line in json_lines]
        else:  # 设置的本地 path 类型的 rag
            if only_contexts:
                return [
                    doc.source_code
                    for doc in self._filter_docs(
                        [{"role": "user", "content": target_query}]
                    )
                ]
            else:
                v, contexts = self.stream_chat_oai(
                    conversations=[{"role": "user", "content": target_query}]
                )
                url = ",".join(contexts)
                return [SourceCode(module_name=f"RAG:{url}", source_code="".join(v))]

    def _filter_docs(self, conversations: List[Dict[str, str]]) -> List[FilterDoc]:
        query = conversations[-1]["content"]
        documents = self._retrieve_documents(options={"query": query})
        return self.doc_filter.filter_docs(
            conversations=conversations, documents=[d for d in documents]
        )

    def stream_chat_oai(self, conversations, model: Optional[str] = None):
        try:
            return self._stream_chat_oai(conversations, model=model)
        except Exception as e:
            logger.error(f"Error in stream_chat_oai: {str(e)}")
            traceback.print_exc()
            return ["出现错误，请稍后再试。"], []

    def _stream_chat_oai(self, conversations, model: Optional[str] = None):
        if self.client:
            model = model or self.args.model
            response = self.client.chat.completions.create(
                model=model,
                messages=conversations,
                stream=True,
                max_tokens=self.args.rag_params_max_tokens
            )

            def response_generator(_response):
                for chunk in _response:
                    if chunk.choices[0].delta.content is not None:
                        yield chunk.choices[0].delta.content

            return response_generator(response), []
        else:
            query = conversations[-1]["content"]
            context = []
            only_contexts = False
            try:
                v = json.loads(query)
                if "only_contexts" in v:
                    query = v["query"]
                    only_contexts = v["only_contexts"]
                    conversations[-1]["content"] = query
            except json.JSONDecodeError:
                pass

            logger.info(f"Query: {query} only_contexts: {only_contexts}")
            start_time = time.time()
            relevant_docs: List[FilterDoc] = self._filter_docs(conversations)
            filter_time = time.time() - start_time

            # 过滤 relevant_docs，仅包含 is_relevant=True 的文档
            highly_relevant_docs = [
                doc for doc in relevant_docs if doc.relevance.is_relevant
            ]

            if highly_relevant_docs:
                relevant_docs = highly_relevant_docs
                logger.info(f"找到 {len(relevant_docs)} 个高度相关的文档")
            logger.info(f"过滤时间: {filter_time:.2f} 秒，过滤出 {len(relevant_docs)} 个文档")

            if only_contexts:  # 仅返回相关文档原文
                final_docs = []
                for doc in relevant_docs:
                    final_docs.append(doc.model_dump())
                return [json.dumps(final_docs, ensure_ascii=False)], []

            if not relevant_docs:
                return ["没有找到相关的文档来回答这个问题。"], []

            context = [doc.source_code.module_name for doc in relevant_docs]

            # 将 FilterDoc 转化为 SourceCode 方便后续的逻辑继续做处理
            relevant_docs_source: List[SourceCode] = [doc.source_code for doc in relevant_docs]

            console = Console()

            # Create a table for the query information
            query_table = Table(title="查询信息", show_header=False)
            query_table.add_row("查询", query)
            query_table.add_row("相关文档", str(len(relevant_docs)))

            # Add relevant docs information
            relevant_docs_info = []
            for doc in relevant_docs_source:
                info = f"- {doc.module_name.replace(self.path, '', 1)}"
                if "original_docs" in doc.metadata:
                    original_docs = ", ".join(
                        [
                            doc.replace(self.path, "", 1)
                            for doc in doc.metadata["original_docs"]
                        ]
                    )
                    info += f" (Original docs: {original_docs})"
                relevant_docs_info.append(info)

            relevant_docs_info = "\n".join(relevant_docs_info)
            query_table.add_row("相关文档列表", relevant_docs_info)

            first_round_full_docs = []
            second_round_extracted_docs = []
            sencond_round_time = 0

            if self.tokenizer is not None:
                token_limiter = TokenLimiter(
                    count_tokens=self.count_tokens,
                    full_text_limit=self.full_text_limit,
                    segment_limit=self.segment_limit,
                    buff_limit=self.buff_limit,
                    llm=self.llm,
                    disable_segment_reorder=self.args.disable_segment_reorder,
                )
                final_relevant_docs = token_limiter.limit_tokens(
                    relevant_docs=relevant_docs_source,
                    conversations=conversations,
                    index_filter_workers=self.args.index_filter_workers or 5,
                )
                first_round_full_docs = token_limiter.first_round_full_docs
                second_round_extracted_docs = token_limiter.second_round_extracted_docs
                sencond_round_time = token_limiter.sencond_round_time

                relevant_docs_source = final_relevant_docs
            else:
                relevant_docs_source = relevant_docs_source[: self.args.index_filter_file_num]

            logger.info(f"最终发送到模型的数量: {len(relevant_docs_source)}")

            query_table.add_row("仅上下文", str(only_contexts))
            query_table.add_row("过滤时间", f"{filter_time:.2f} 秒")
            query_table.add_row("最终相关文档", str(len(relevant_docs_source)))
            query_table.add_row("第一轮完整文档", str(len(first_round_full_docs)))
            query_table.add_row("第二轮提取文档", str(len(second_round_extracted_docs)))
            query_table.add_row("第二轮时间", f"{sencond_round_time:.2f} 秒")

            # Add relevant docs information
            final_relevant_docs_info = []
            for doc in relevant_docs_source:
                info = f"- {doc.module_name.replace(self.path, '', 1)}"
                if "original_docs" in doc.metadata:
                    original_docs = ", ".join(
                        [
                            doc.replace(self.path, "", 1)
                            for doc in doc.metadata["original_docs"]
                        ]
                    )
                    info += f" (Original docs: {original_docs})"
                if "chunk_ranges" in doc.metadata:
                    chunk_ranges = json.dumps(
                        doc.metadata["chunk_ranges"], ensure_ascii=False
                    )
                    info += f" (Chunk ranges: {chunk_ranges})"
                final_relevant_docs_info.append(info)

            final_relevant_docs_info = "\n".join(final_relevant_docs_info)
            query_table.add_row("最终相关文档列表", final_relevant_docs_info)

            console.print(query_table)

            request_tokens = sum([doc.tokens for doc in relevant_docs_source])
            self.llm.setup_default_model_name("qa_model")
            qa_model = self.llm
            logger.info(f"开始发送到模型 qa_model，使用 {request_tokens} 个 token")

            new_conversations = conversations[:-1] + [
                {
                    "role": "user",
                    "content": self._answer_question.prompt(
                        query=query,
                        relevant_docs=[doc.source_code for doc in relevant_docs_source],
                    ),
                }
            ]

            chunks = qa_model.stream_chat_ai(
                conversations=new_conversations
            )

            return ((chunk.choices[0].delta.content for chunk in chunks
                    if chunk.choices and chunk.choices[0].delta.content),
                    context)

    def search_step1(self, conversations):
        """ 文件检索步骤, 混合索引将使用duckdb """
        start_time = time.time()
        query = conversations[-1]["content"]
        source_list = []
        documents = self._retrieve_documents(options={"query": query})
        for d in documents:
            source_list.append(d)
        end_time = time.time() - start_time
        return source_list, end_time

    def search_step2(self, conversations, source_list):
        """ 文件过滤步骤 """
        start_time = time.time()
        relevant_docs: List[FilterDoc] = self.doc_filter.filter_docs(
            conversations=conversations, documents=source_list
        )
        # 过滤 relevant_docs，仅包含 is_relevant=True 的文档
        highly_relevant_docs = [
            doc for doc in relevant_docs if doc.relevance.is_relevant
        ]
        if highly_relevant_docs:
            relevant_docs = highly_relevant_docs
        end_time = time.time() - start_time
        return relevant_docs, end_time

    def search_step3(self, conversations, relevant_docs: List[FilterDoc]):
        """ 文件合并,最终发送到模型的文档数量 """
        start_time = time.time()
        # 将 FilterDoc 转化为 SourceCode 方便后续的逻辑继续做处理
        relevant_docs_source: List[SourceCode] = [doc.source_code for doc in relevant_docs]

        if self.tokenizer is not None:
            token_limiter = TokenLimiter(
                count_tokens=self.count_tokens,
                full_text_limit=self.full_text_limit,
                segment_limit=self.segment_limit,
                buff_limit=self.buff_limit,
                llm=self.llm,
                disable_segment_reorder=self.args.disable_segment_reorder,
            )
            final_relevant_docs = token_limiter.limit_tokens(
                relevant_docs=relevant_docs_source,
                conversations=conversations,
                index_filter_workers=self.args.index_filter_workers or 5,
            )

            relevant_docs_source = final_relevant_docs
        else:
            relevant_docs_source = relevant_docs_source[: self.args.index_filter_file_num]

        end_time = time.time() - start_time
        return relevant_docs_source, end_time

    def search_step4(self, query, conversations, relevant_docs_source):
        """ 最终提问阶段 """
        self.llm.setup_default_model_name("qa_model")
        qa_model = self.llm

        new_conversations = conversations[:-1] + [
            {
                "role": "user",
                "content": self._answer_question.prompt(
                    query=query,
                    relevant_docs=[doc.source_code for doc in relevant_docs_source],
                ),
            }
        ]

        chunks = qa_model.stream_chat_ai(
            conversations=new_conversations
        )

        return ((chunk.choices[0].delta.content for chunk in chunks
                 if chunk.choices and chunk.choices[0].delta.content),
                "")