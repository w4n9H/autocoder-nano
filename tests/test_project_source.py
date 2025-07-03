import os
from pathlib import Path

from autocoder_nano.project import project_source
from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs


def project_source_test():
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

    s = project_source(source_llm=llm, args=args)

    for i in s:
        print(i.module_name)


if __name__ == '__main__':
    project_source_test()

