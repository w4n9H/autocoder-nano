from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs, SourceCode
from autocoder_nano.project.pyproject import PyProject
from autocoder_nano.project.suffixproject import SuffixProject
from autocoder_nano.project.tsproject import TSProject


def project_source(source_llm: AutoLLM, args: AutoCoderArgs) -> list[SourceCode]:
    if args.project_type == "py":
        pp = PyProject(llm=source_llm, args=args)
    elif args.project_type == "ts":
        pp = TSProject(llm=source_llm, args=args)
    else:
        pp = SuffixProject(llm=source_llm, args=args)
    pp.run()
    return pp.sources


__all__ = ["PyProject", "SuffixProject", "TSProject", "project_source"]