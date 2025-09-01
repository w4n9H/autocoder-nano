from autocoder_nano.utils.http_utils import metaso_search_api, bocha_search_api, metaso_reader_api
import pprint


def metaso_search_api_test():
    r = metaso_search_api(
        query="小米yu7",
        metaso_key="",
        include_raw_content=True,
        include_summary=True
    )
    pprint.pprint(r)


def metaso_reader_api_test():
    r = metaso_reader_api(
        url="https://www.163.com/news/article/K56809DQ000189FH.html",
        metaso_key=""
    )
    pprint.pprint(r)


def bocha_search_api_test():
    r = bocha_search_api(
        query="小米yu7",
        bocha_key="",
        count=20
    )
    pprint.pprint(r)


if __name__ == '__main__':
    metaso_reader_api_test()