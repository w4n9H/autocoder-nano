import typing
from typing import Union, Optional

from jinja2 import Template

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.agent.agentic_edit_tools import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import WebSearchTool, ToolResult
from autocoder_nano.utils.http_utils import metaso_search_api, bocha_search_api, metaso_reader_api
from autocoder_nano.utils.printer_utils import Printer

printer = Printer()

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


# 定义Jinja2模板
SEARCH_RESULTS_TEMPLATE = Template("""
Web搜索结果 (共{{ results|length }}条):

{% for result in results %}
## 结果 {{ loop.index }}
- 日期: {{ result.get('date', '未知日期') }}
- 链接: {{ result.link }}
- 摘要: {{ result.get('summary', '无摘要') }}
{% if result.get('content') %}
- 内容: {{ result.content }}
{% endif %}
{% endfor %}
""")


class WebSearchToolResolver(BaseToolResolver):
    def __init__(
            self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
            tool: WebSearchTool, args: AutoCoderArgs
    ):
        super().__init__(agent, tool, args)
        self.tool: WebSearchTool = tool
        # self.args = args

    def request_search_api(self, query: str):
        # 从多个渠道获取摘要及 url list
        url_list = []
        if self.agent.args.search_metaso_key and self.agent.args.search_metaso_key.startswith("mk-"):
            url_list.extend(
                metaso_search_api(
                    query=query,
                    size=str(self.agent.args.search_size),
                    include_summary=True,
                    include_raw_content=True,
                    metaso_key=self.agent.args.search_metaso_key
                )
            )

        if self.agent.args.search_bocha_key and self.agent.args.search_bocha_key.startswith("sk-"):
            url_list.extend(
                bocha_search_api(
                    query=query,
                    summary=True,
                    count=self.agent.args.search_size,
                    bocha_key=self.agent.args.search_bocha_key
                )
            )

        # 补充正文
        for u in url_list:
            if len(u.get("content", "")) < 10:
                u["content"] = metaso_reader_api(
                    url=u["link"], metaso_key=self.agent.args.search_metaso_key
                )

        return url_list

    def resolve(self) -> ToolResult:
        """
        [
            {
                "date": w.get("date", ""),
                "link": w.get("link", ""),
                "summary": w.get("summary", ""),
                "content": w.get("content", "")
            }
        ]
        """
        query = self.tool.query

        try:
            url_list = self.request_search_api(query=query)
            messgae = f"查询内容: {query}, 共查询出 {len(url_list)} 条内容。"
            # 使用Jinja2模板格式化结果
            content = SEARCH_RESULTS_TEMPLATE.render(results=url_list)
            return ToolResult(success=True, message=messgae, content=content)
        except Exception as e:
            return ToolResult(success=False,
                              message=f"{str(e)}")

    def guide(self) -> str:
        doc = """
        ## web_search（联网检索）
        描述：
        - 通过搜索引擎在互联网上检索相关信息，支持关键词搜索。
        参数：
        - query（必填）：要搜索的关键词或短语
        用法说明：
        <web_search>
        <query>Search keywords here</query>
        </web_search>
        用法示例：
        场景一：基础关键词搜索
        目标：查找关于神经网络的研究进展。
        思维过程：通过一些关键词，来获取有关于神经网络学术信息
        <web_search>
        <query>neural network research advances</query>
        </web_search>
        场景二：简单短语搜索
        目标：查找关于量子计算的详细介绍。
        思维过程：通过一个短语，来获取有关于量子计算的信息
        <web_search>
        <query>量子计算的详细介绍</query>
        </web_search>
        """
        return doc