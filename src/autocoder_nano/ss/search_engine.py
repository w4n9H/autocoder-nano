import hashlib
import random
from time import sleep, time
from types import TracebackType
from urllib.parse import quote

from bs4 import BeautifulSoup

from autocoder_nano.tools.http_tools import RetrySession


class BingSearch(RetrySession):
    def __init__(
            self,
            headers: dict[str, str] | None = None,
            proxy: str | None = None,
            proxies: dict[str, str] | str | None = None,  # deprecated
            timeout: int | None = 10,
    ) -> None:
        super().__init__()
        self.headers = headers if headers else {}
        self.headers["Referer"] = "https://www.bing.com/"
        self.timeout = timeout
        self.sleep_timestamp = 0.0
        self.cvid = self._random_md5()

    def __enter__(self) -> RetrySession:
        return self

    def __exit__(
            self,
            exc_type: type[BaseException] | None = None,
            exc_val: BaseException | None = None,
            exc_tb: TracebackType | None = None,
    ) -> None:
        pass

    @staticmethod
    def _random_md5():
        random_data = str(random.random()).encode()
        return hashlib.md5(random_data).hexdigest().upper()

    def _sleep(self, sleeptime: float = 0.75) -> None:
        """Sleep between API requests."""
        delay = 0.0 if not self.sleep_timestamp else 0.0 if time() - self.sleep_timestamp >= 20 else sleeptime
        self.sleep_timestamp = time()
        sleep(delay)

    def _send(self, keywords: str, en_search: int = 0, page: int = 0) -> str:
        _url = f"https://www.bing.com/search?q={quote(keywords)}"
        _url += "&sp=-1"  # 排序方式,-1 表示默认排序（相关性）
        _url += "&sc=13-6"  # 结果筛选范围,可能表示结果类型或来源范围（如网页、视频、图片等）
        _url += "&qs=n"  # 查询模式,n 表示普通模式（无特殊筛选）,其他值可能触发即时答案或快捷搜索
        _url += f"&cvid={self.cvid}"  # 会话唯一标识符
        _url += f"&first={1 + page * 10}"

        if en_search > 0:
            _url += f"&ensearch={en_search}"

        _url += "&FORM=PERE"

        # params = {"q": keywords}
        #
        # if page == 0:
        #     params.update({"first": 1})
        # elif page > 0:
        #     params.update({"first": page * 10})
        #
        # if en_search > 0:
        #     params.update({"ensearch": en_search})
        # respon = self.session.get(url=f"https://www.bing.com/search?", params=params)
        print(_url)
        respon = self.session.get(url=_url)
        return respon.text

    @staticmethod
    def _parse(content):
        results = []
        # 使用 BeautifulSoup 解析 HTML
        soup = BeautifulSoup(content, "html.parser")
        li_b_algo = soup.find_all("li", class_="b_algo")
        for li in li_b_algo:
            title = li.find("h2").text
            link = li.find("a")["href"]
            description = li.find("div", class_="b_caption").text.strip()
            results.append(
                {
                    "title": title,
                    "url": link,
                    "desc": description
                }
            )
        return results

    def search(self, keywords: str, sn: int = 1, en_search: int = 0):
        assert keywords, "keywords is mandatory"

        results = []
        for n in range(sn):
            resp_content = self._send(keywords, en_search=en_search, page=n)
            parsers = self._parse(resp_content)
            results.extend(parsers)
            self._sleep(sleeptime=3)

        return results


if __name__ == '__main__':
    bing = BingSearch()
    r = bing.search("小米+su7", sn=3, en_search=0)
    for i in r:
        print(i)