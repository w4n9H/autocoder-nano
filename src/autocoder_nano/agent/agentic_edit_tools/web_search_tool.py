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
            self, agent: Optional[Union['AgenticRuntime']],
            tool: WebSearchTool, args: AutoCoderArgs
    ):
        super().__init__(agent, tool, args)
        self.tool: WebSearchTool = tool
        self.args = args

    def request_search_api(self, query: str):
        # 从多个渠道获取摘要及 url list
        url_list = []
        if self.args.search_metaso_key and self.args.search_metaso_key.startswith("mk-"):
            url_list.extend(
                metaso_search_api(
                    query=query,
                    size=str(self.args.search_size),
                    include_summary=True,
                    include_raw_content=True,
                    metaso_key=self.args.search_metaso_key
                )
            )

        if self.args.search_bocha_key and self.args.search_bocha_key.startswith("sk-"):
            url_list.extend(
                bocha_search_api(
                    query=query,
                    summary=True,
                    count=self.args.search_size,
                    bocha_key=self.args.search_bocha_key
                )
            )

        # 补充正文
        for u in url_list:
            if len(u.get("content", "")) < 10:
                u["content"] = metaso_reader_api(
                    url=u["link"], metaso_key=self.args.search_metaso_key
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