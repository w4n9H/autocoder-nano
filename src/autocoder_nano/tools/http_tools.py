import json
from loguru import logger

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry


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
            logger.error(f"达到最大重试次数，重试失败: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
        return None

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, data=None, json=None, **kwargs):
        return self.request('POST', url, data=data, json=json, **kwargs)

    def put(self, url, data=None, **kwargs):
        return self.request('PUT', url, data=data, **kwargs)

    def delete(self, url, **kwargs):
        return self.request('DELETE', url, **kwargs)


class DeepSeekChat_(RetrySession):
    def __init__(self, api_key):
        super().__init__()
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com/chat/completions"  # 假设这是DeepSeek的API URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def send_message(self, message):
        payload = {
            "model": "deepseek-chat",
            "stream": False,
            "messages": [
                {"role": "user", "content": "{}".format(message)}
            ]
        }
        response = self.session.post(self.base_url, headers=self.headers, data=json.dumps(payload))
        print(response.text)
        if response.status_code == 200:
            return response.json().get("response", "No response received.")
        else:
            return f"Error: {response.status_code} - {response.text}"