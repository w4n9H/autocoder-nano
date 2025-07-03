import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict

from autocoder_nano.core import AutoLLM
from autocoder_nano.core import prompt
from autocoder_nano.actypes import DocRelevance, SourceCode, FilterDoc, TaskTiming, AutoCoderArgs
from autocoder_nano.rag.doc_config import RagConfigManager
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


def parse_relevance(text: Optional[str]) -> Optional[DocRelevance]:
    if text is None:
        return None
    pattern = r"(yes|no)/(\d+)"
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        is_relevant = match.group(1).lower() == "yes"
        relevant_score = int(match.group(2))
        return DocRelevance(is_relevant=is_relevant, relevant_score=relevant_score)

    return None


@prompt()
def _check_relevance_with_conversation(
        conversations: List[Dict[str, str]], documents: List[str], filter_config: Optional[str] = None
) -> str:
    """
    使用以下文档和对话历史来回答问题。如果文档中没有相关信息，请说"我没有足够的信息来回答这个问题"。

    文档：
    <documents>
    {% for doc in documents %}
    {{ doc }}
    {% endfor %}
    </documents>

    对话历史：
    <conversations>
    {% for msg in conversations %}
    <{{ msg.role }}>: {{ msg.content }}
    {% endfor %}
    </conversations>

    {% if filter_config %}
    一些提示：
    {{ filter_config }}
    {% endif %}

    请结合提供的文档以及用户对话历史，判断提供的文档是不是能和用户的最后一个问题相关。
    如果该文档提供的知识能够和用户的问题相关，那么请回复"yes/<relevant>" 否则回复"no/<relevant>"。
    其中， <relevant> 是你认为文档中和问题的相关度，0-10之间的数字，数字越大表示相关度越高。
    """


class DocFilter:
    def __init__(
        self, llm: AutoLLM, args: AutoCoderArgs, on_ray: bool = False, path: Optional[str] = None,
    ):
        self.llm = llm
        self.args = args
        self.relevant_score = self.args.rag_doc_filter_relevance
        self.on_ray = on_ray
        self.path = path

    def filter_docs(self, conversations: List[Dict[str, str]], documents: List[SourceCode]) -> List[FilterDoc]:
        return self.filter_docs_with_threads(conversations, documents)

    def filter_docs_with_threads(
            self, conversations: List[Dict[str, str]], documents: List[SourceCode]
    ) -> List[FilterDoc]:
        rag_manager = RagConfigManager(path=self.path)
        rag_config = rag_manager.load_config()
        documents = list(documents)
        self.llm.setup_default_model_name(self.args.recall_model)
        with ThreadPoolExecutor(max_workers=self.args.index_filter_workers or 5) as executor:
            future_to_doc = {}
            for doc in documents:
                submit_time = time.time()

                def _run(_conversations, docs):
                    _submit_time_1 = time.time()
                    try:
                        llm = self.llm

                        _v = (
                            _check_relevance_with_conversation.with_llm(llm)
                            .run(
                                conversations=_conversations,
                                documents=docs,
                                filter_config=rag_config.filter_config,
                            )
                        )
                    except Exception as _err:
                        printer.print_text(f"Error in _check_relevance_with_conversation: {str(_err)}", style="red")
                        return None, _submit_time_1, time.time()

                    _end_time_2 = time.time()
                    return _v, _submit_time_1, _end_time_2

                m = executor.submit(
                    _run,
                    conversations,
                    [f"##File: {doc.module_name}\n{doc.source_code}"],
                )
                future_to_doc[m] = (doc, submit_time)

        relevant_docs = []
        for future in as_completed(list(future_to_doc.keys())):
            try:
                doc, submit_time = future_to_doc[future]
                end_time = time.time()
                v, submit_time_1, end_time_2 = future.result()
                task_timing = TaskTiming(
                    submit_time=submit_time,
                    end_time=end_time,
                    duration=end_time - submit_time,
                    real_start_time=submit_time_1,
                    real_end_time=end_time_2,
                    real_duration=end_time_2 - submit_time_1,
                )

                relevance = parse_relevance(v.output)
                printer.print_key_value(
                    items={
                        "文件": f"{doc.module_name}",
                        "相关性": f"{'相关' if relevance and relevance.is_relevant else '不相关'}",
                        "分数": f"{relevance.relevant_score if relevance else 'N/A'}",
                        "分数阈值": f"{self.relevant_score}",
                        "原始响应": f"{v}",
                        "总耗时": f"{task_timing.duration:.2f} 秒",
                        "实际耗时": f"{task_timing.real_duration:.2f} 秒",
                        "队列等待时间": f"{(task_timing.real_start_time - task_timing.submit_time):.2f} 秒"
                    },
                    title="文档过滤进度"
                )
                if relevance and relevance.relevant_score >= self.relevant_score:
                    relevant_docs.append(
                        FilterDoc(
                            source_code=doc,
                            relevance=relevance,
                            task_timing=task_timing,
                        )
                    )
            except Exception as exc:
                try:
                    doc, submit_time = future_to_doc[future]
                    printer.print_text(f"文档过滤时生成异常（文档：{doc.module_name}）：{exc}", style="red")
                except Exception as err:
                    printer.print_text(f"文档过滤时生成异常：{err}", style="red")

        # Sort relevant_docs by relevance score in descending order
        relevant_docs.sort(key=lambda x: x.relevance.relevant_score, reverse=True)
        return relevant_docs