import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from autocoder_nano.utils.printer_utils import Printer

printer = Printer()


class RetrySession:
    def __init__(
            self,
            total_retries=5,
            connect_retries=3,
            read_retries=2,
            redirect_retries=3,
            status_forcelist=(500, 502, 503, 504),
            backoff_factor=1,
            raise_on_status=False):
        self.retry_strategy = Retry(
            total=total_retries,                 # 总共重试 5 次
            connect=connect_retries,             # 连接错误时重试 3 次
            read=read_retries,                   # 读取错误时重试 2 次
            redirect=redirect_retries,           # 重定向时最多重试 3 次
            status_forcelist=status_forcelist,   # 对于这些 HTTP 状态码强制重试
            backoff_factor=backoff_factor,       # 等待时间因子：指数递增，如 1s, 2s, 4s...
            raise_on_status=raise_on_status      # 达到最大重试次数后不抛异常
        )
        self.session = requests.Session()
        self.mount_adapters()

    def mount_adapters(self):
        http_adapter = HTTPAdapter(max_retries=self.retry_strategy)
        self.session.mount('https://', http_adapter)
        self.session.mount('http://', http_adapter)

    def request(self, method, url, **kwargs):
        try:
            _response = self.session.request(method, url, **kwargs)
            _response.raise_for_status()  # 如果响应状态码不是2xx，抛出HTTPError
            return _response
        except requests.exceptions.RetryError as e:
            printer.print_text(f"达到最大重试次数，重试失败: {e}", style="red")
        except requests.exceptions.RequestException as e:
            printer.print_text(f"请求失败: {e}", style="red")
        return None

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, data=None, json=None, **kwargs):
        return self.request('POST', url, data=data, json=json, **kwargs)

    def put(self, url, data=None, **kwargs):
        return self.request('PUT', url, data=data, **kwargs)

    def delete(self, url, **kwargs):
        return self.request('DELETE', url, **kwargs)


def metaso_search_api(
        query: str = None,
        scope: str = "webpage",  # 搜索范围：网页
        size: str = "10",
        include_summary: bool = False,  # 通过网页的摘要信息进行召回增强
        include_raw_content: bool = False,  # 抓取所有来源网页原文
        concise_snippet: bool = False,  # 返回精简的原文匹配信息
        metaso_key: str = None,
        metaso_url: str = "https://metaso.cn/api/v1/search"
) -> list[dict]:
    if not metaso_key:
        raise Exception(f"请输入 API KEY")

    rs = RetrySession()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {metaso_key}"
    }
    payload = {
        "q": query,
        "scope": scope,
        "size": size,
        "includeSummary": include_summary,
        "includeRawContent": include_raw_content,
        "conciseSnippet": concise_snippet,
    }
    try:
        rlist = []
        response = rs.post(url=metaso_url, headers=headers, json=payload)
        metaso_json = response.json()
        if isinstance(metaso_json["webpages"], list) and len(metaso_json["webpages"]):
            for w in metaso_json["webpages"]:
                rlist.append(
                    {
                        "date": w.get("date", ""),
                        "link": w.get("link", ""),
                        "summary": w.get("summary", ""),
                        "content": w.get("content", "")
                    }
                )
        return rlist
    except Exception as e:
        raise Exception(f"{e}")


def metaso_reader_api(
        url: str = None,
        metaso_key: str = None,
        metaso_url: str = "https://metaso.cn/api/v1/reader"
) -> str:
    if not metaso_key:
        raise Exception(f"请输入 API KEY")

    rs = RetrySession()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {metaso_key}"
    }
    payload = {
        "url": url
    }
    try:
        response = rs.post(url=metaso_url, headers=headers, json=payload)
        return response.json().get("markdown", "")
    except Exception as e:
        raise Exception(f"{e}")


def bocha_search_api(
        query: str = None,
        freshness: str = "noLimit",  # 搜索指定时间范围内的网页 oneDay oneWeek oneMonth oneYear
        summary: bool = True,  # 是否显示文本摘要
        include: str = "",  # 指定搜索的网站范围。多个域名使用|或,分隔，最多不能超过20个
        exclude: str = "",  # 排除搜索的网站范围。多个域名使用|或,分隔，最多不能超过20个
        count: int = 10,  # 返回结果的条数（实际返回结果数量可能会小于count指定的数量），可填范围1-50，默认10
        bocha_key: str = None,
        bocha_url: str = "https://api.bochaai.com/v1/web-search"
):
    if not bocha_key:
        raise

    rs = RetrySession()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {bocha_key}"
    }
    payload = {
        "query": query,
        "freshness": freshness,
        "summary": summary,
        "include": include,
        "exclude": exclude,
        "count": count,
    }
    try:
        rlist = []
        response = rs.post(url=bocha_url, headers=headers, json=payload)
        bocha_json = response.json()
        if isinstance(bocha_json["data"], dict):
            if isinstance(bocha_json["data"]["webPages"], dict):
                for m in bocha_json["data"]["webPages"]["value"]:
                    rlist.append(
                        {
                            "date": m.get("dateLastCrawled", ""),
                            "link": m.get("url", ""),
                            "summary": m.get("summary", ""),
                            "content": m.get("content", "")
                        }
                    )
        return rlist
    except Exception as e:
        raise Exception(f"{e}")