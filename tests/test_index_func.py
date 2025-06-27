import os

from autocoder_nano.llm_client import AutoLLM
from autocoder_nano.llm_types import AutoCoderArgs


def index_build_test():
    project_root = os.getcwd()
    print(project_root)

    llm = AutoLLM()
    args = AutoCoderArgs()
    args.project_type = "py"
    args.source_dir = project_root
    args.target_file = os.path.join(project_root, "output.txt")
    args.exclude_files = [
        "regex://.*/src/*."
    ]


def index_build_and_filter_test():
    pass


if __name__ == '__main__':
    index_build_test()
    index_build_and_filter_test()