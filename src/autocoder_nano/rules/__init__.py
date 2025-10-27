import os
import uuid

from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs, SourceCodeList, SourceCode
from autocoder_nano.rules.rules_learn import AutoRulesLearn
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


# def rules_from_commit_changes(commit_id: str, llm: AutoLLM, args: AutoCoderArgs):
#     rules_dir_path = os.path.join(args.source_dir, ".auto-coder", "autocoderrules")
#     auto_learn = AutoRulesLearn(llm=llm, args=args)
#
#     try:
#         result = auto_learn.analyze_commit_changes(commit_id=commit_id, conversations=[])
#         rules_file = os.path.join(rules_dir_path, f"rules-commit-{uuid.uuid4()}.md")
#         with open(rules_file, "w", encoding="utf-8") as f:
#             f.write(result)
#         printer.print_text(f"代码变更[{commit_id}]生成 Rules 成功", style="green")
#     except Exception as e:
#         printer.print_text(f"代码变更[{commit_id}]生成 Rules 失败: {e}", style="red")


def rules_from_active_files(files: list[str], llm: AutoLLM, args: AutoCoderArgs):
    rule_path = os.path.join(args.source_dir, ".auto-coder", "RULES.md")
    auto_learn = AutoRulesLearn(llm=llm, args=args)

    sources = SourceCodeList([])
    # 写入已有内容
    if os.path.exists(rule_path):
        with open(rule_path, "r", encoding="utf-8") as old_rule_fp:
            sources.sources.append(SourceCode(module_name="以下是历史Rules, 你需要与新Rules, 合并更新",
                                              source_code=old_rule_fp.read()))
    # 追加活跃文件
    for file in files:
        try:
            with open(file, "r", encoding="utf-8") as f:
                source_code = f.read()
                sources.sources.append(SourceCode(module_name=file, source_code=source_code))
        except Exception as e:
            printer.print_text(f"读取文件生成 Rules 失败: {e}", style="yellow")
            continue

    try:
        result = auto_learn.analyze_modules(sources=sources, conversations=[])
        with open(rule_path, "w", encoding="utf-8") as f:
            f.write(result)
        printer.print_text(f"活跃文件[Files:{len(files)}]生成 Rules 成功", style="green")
    except Exception as e:
        printer.print_text(f"活跃文件生成 Rules 失败: {e}", style="red")


def get_rules_context(project_root):
    rule_path = os.path.join(project_root, ".auto-coder", "RULES.md")
    printer.print_text("已开启 Rules 模式", style="green")
    context = ""
    if os.path.exists(rule_path):
        context += f"下面是我们对部分代码进行深入分析,提取具有通用价值的功能模式和设计模式,可在其他需求中复用的Rules\n"
        context += "你在编写代码时可以参考以下Rules\n"
        context += "<rules>\n"
        with open(rule_path, "r") as fp:
            context += f"{fp.read()}\n"
        context += "</rules>\n"
    return context


__all__ = ["get_rules_context", "rules_from_active_files"]