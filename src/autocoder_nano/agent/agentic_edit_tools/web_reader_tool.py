import typing
from typing import Union, Optional

from jinja2 import Template

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.agent.agentic_edit_tools import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import WebReaderTool, ToolResult
from autocoder_nano.utils.http_utils import metaso_search_api, bocha_search_api, metaso_reader_api
from autocoder_nano.utils.printer_utils import Printer

printer = Printer()

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


class WebReaderToolResolver(BaseToolResolver):
    def __init__(
            self, agent: Optional[Union['AgenticRuntime', 'SubAgents']],
            tool: WebReaderTool, args: AutoCoderArgs
    ):
        super().__init__(agent, tool, args)
        self.tool: WebReaderTool = tool

    def request_reader_api(self, url: str) -> str:
        # 从多个渠道获取摘要及 url list
        content = metaso_reader_api(
            url, metaso_key=self.agent.args.search_metaso_key
        )
        return content

    def resolve(self) -> ToolResult:
        url = self.tool.url

        try:
            content = self.request_reader_api(url=url)
            messgae = f"查询页面: {url}"
            return ToolResult(success=True, message=messgae, content=content)
        except Exception as e:
            return ToolResult(success=False,
                              message=f"{str(e)}")

    def guide(self) -> str:
        doc = """
        ## web_reader（获取指定网页url的内容）
        描述：
        - 通过搜索引擎在互联网上检索相关信息，支持关键词搜索。
        参数：
        - url（必填）：你想要获取内容的网页url
        用法说明：
        <web_reader>
        <url>合法的网页url</url>
        </web_reader>
        用法示例：
        场景一：获取某url的正文内容
        目标：获取微信公众号某篇文章的内容。
        <web_reader>
        <url>https://mp.weixin.qq.com/s/frYHrzJiSdbdIx4AlTg7jw</url>
        </web_reader>
        """
        return doc