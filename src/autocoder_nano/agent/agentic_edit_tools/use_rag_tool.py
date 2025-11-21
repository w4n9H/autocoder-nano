import typing
from typing import Optional, Union

from autocoder_nano.rag.doc_entry import RAGFactory
from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import UseRAGTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


printer = Printer()


class UseRAGToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
                 tool: UseRAGTool, args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: UseRAGTool = tool  # For type hinting

    def resolve(self) -> ToolResult:
        query = self.tool.query
        try:
            rag_factory = RAGFactory()
            rag = rag_factory.get_rag(llm=self.agent.llm, args=self.agent.args, path=self.agent.args.rag_url)
            contexts = rag.search(query=query)
            messgae = f"检索内容: {query}, 检索目录 {self.agent.args.rag_url}"
            return ToolResult(success=True, message=messgae, content=contexts)
        except Exception as e:
            return ToolResult(success=False,
                              message=f"{str(e)}")

    def guide(self) -> str:
        doc = """
        ## use_rag_tool（调用RAG检索）
        描述：
        - RAG全称检索增强生成（Retrieval-Augmented Generation）
        - 通过本地RAG服务发起信息查询请求，支持关键词/短语搜索。
        参数：
        - query（必填）：要搜索的关键词或短语
        用法说明：
        <use_rag_tool>
        <query>在此处填写查询内容</query>
        </use_rag_tool>
        用法示例：
        场景一：基础关键词搜索
        目标：查找关于神经网络的研究进展。
        思维过程：通过一些关键词，来获取有关于神经网络学术信息
        <use_rag_tool>
        <query>neural network research advances</query>
        </use_rag_tool>
        场景二：简单短语搜索
        目标：查找关于t_table数据表的详细介绍。
        思维过程：通过一个短语，来获取有关于一个MySQL数据表的信息
        <use_rag_tool>
        <query>查询t_table数据表详细介绍</query>
        </use_rag_tool>
        """
        return doc