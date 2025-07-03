import os

from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.index import index_build, index_build_and_filter


def index_build_test():
    project_root = os.getcwd()
    print(project_root)

    llm = AutoLLM()
    llm.setup_sub_client(
        client_name="ark-deepseek-v3",
        api_key="",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model_name="deepseek-v3-250324"
    )

    args = AutoCoderArgs()
    args.project_type = "py"
    args.source_dir = project_root
    args.target_file = os.path.join(project_root, "output.txt")
    args.model_max_input_length = 100000
    args.chat_model = "ark-deepseek-v3"
    args.exclude_files = [
        "regex://.*/src/*."
    ]

    index_build(llm=llm, args=args)


def index_build_and_filter_test():
    project_root = os.getcwd()
    print(project_root)

    llm = AutoLLM()
    llm.setup_sub_client(
        client_name="ark-deepseek-v3",
        api_key="",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model_name="deepseek-v3-250324"
    )

    args = AutoCoderArgs()
    args.query = "哪几个是测试脚本"
    args.project_type = "py"
    args.source_dir = project_root
    args.target_file = os.path.join(project_root, "output.txt")
    args.model_max_input_length = 100000
    args.chat_model = "ark-deepseek-v3"
    args.skip_build_index = False
    args.skip_filter_index = False
    args.index_filter_level = 1
    args.exclude_files = [
        "regex://.*/src/*."
    ]

    index_build_and_filter(llm=llm, args=args)


if __name__ == '__main__':
    index_build_test()
    index_build_and_filter_test()