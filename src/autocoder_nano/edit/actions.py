import time

# from loguru import logger

from autocoder_nano.edit.code.generate_editblock import CodeAutoGenerateEditBlock
from autocoder_nano.edit.code.merge_editblock import CodeAutoMergeEditBlock
from autocoder_nano.index.entry import build_index_and_filter_files
from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.project import PyProject, SuffixProject
from autocoder_nano.rag.token_counter import count_tokens
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


class BaseAction:
    @staticmethod
    def _get_content_length(content: str) -> int:
        return count_tokens(content)


class ActionPyProject(BaseAction):
    def __init__(self, args: AutoCoderArgs, llm: AutoLLM) -> None:
        self.args = args
        self.llm = llm
        self.pp = None

    def run(self):
        if self.args.project_type != "py":
            return False
        pp = PyProject(llm=self.llm, args=self.args)
        self.pp = pp
        pp.run()
        source_code = pp.output()
        if self.llm:
            source_code = build_index_and_filter_files(args=self.args, llm=self.llm, sources=pp.sources)
        self.process_content(source_code)
        return True

    def process_content(self, content: str):
        # args = self.args
        if self.args.execute and self.llm:
            content_length = self._get_content_length(content)
            if content_length > self.args.conversation_prune_safe_zone_tokens:
                printer.print_text(
                    f"发送给模型的内容长度为 {content_length} 个 token(可能收集了过多文件),"
                    f"已超过最大输入长度限制 {self.args.conversation_prune_safe_zone_tokens}.",
                    style="yellow"
                )

        if self.args.execute:
            printer.print_text("正在自动生成代码...", style="green")
            start_time = time.time()
            # diff, strict_diff, editblock 是代码自动生成或合并的不同策略, 通常用于处理代码的变更或生成
            # diff 模式,基于差异生成代码,生成最小的变更集,适用于局部优化,代码重构
            # strict_diff 模式,严格验证差异,确保生成的代码符合规则,适用于代码审查,自动化测试
            # editblock 模式,基于编辑块生成代码，支持较大范围的修改,适用于代码重构,功能扩展
            if self.args.auto_merge == "editblock":
                generate = CodeAutoGenerateEditBlock(args=self.args, llm=self.llm, action=self)
            else:
                generate = None

            if self.args.enable_multi_round_generate:
                generate_result = generate.multi_round_run(query=self.args.query, source_content=content)
            else:
                generate_result = generate.single_round_run(query=self.args.query, source_content=content)
            printer.print_text(f"代码生成完毕，耗时 {time.time() - start_time:.2f} 秒", style="green")

            if self.args.auto_merge:
                printer.print_text("正在自动合并代码...", style="green")
                if self.args.auto_merge == "editblock":
                    code_merge = CodeAutoMergeEditBlock(args=self.args, llm=self.llm)
                    merge_result = code_merge.merge_code(generate_result=generate_result)
                else:
                    merge_result = None

                content = merge_result.contents[0]
            else:
                content = generate_result.contents[0]

            with open(self.args.target_file, "w") as file:
                file.write(content)


class ActionSuffixProject(BaseAction):
    def __init__(self, args: AutoCoderArgs, llm: AutoLLM) -> None:
        self.args = args
        self.llm = llm
        self.pp = None

    def run(self):
        pp = SuffixProject(llm=self.llm, args=self.args)
        self.pp = pp
        pp.run()
        source_code = pp.output()
        if self.llm:
            source_code = build_index_and_filter_files(args=self.args, llm=self.llm, sources=pp.sources)
        self.process_content(source_code)

    def process_content(self, content: str):
        if self.args.execute and self.llm:
            content_length = self._get_content_length(content)
            if content_length > self.args.conversation_prune_safe_zone_tokens:
                printer.print_text(
                    f"发送给模型的内容长度为 {content_length} 个 token(可能收集了过多文件),"
                    f"已超过最大输入长度限制 {self.args.conversation_prune_safe_zone_tokens}.",
                    style="yellow"
                )

        if self.args.execute:
            printer.print_text("正在自动生成代码...", style="green")
            start_time = time.time()
            # diff, strict_diff, editblock 是代码自动生成或合并的不同策略, 通常用于处理代码的变更或生成
            # diff 模式,基于差异生成代码,生成最小的变更集,适用于局部优化,代码重构
            # strict_diff 模式,严格验证差异,确保生成的代码符合规则,适用于代码审查,自动化测试
            # editblock 模式,基于编辑块生成代码，支持较大范围的修改,适用于代码重构,功能扩展
            if self.args.auto_merge == "editblock":
                generate = CodeAutoGenerateEditBlock(args=self.args, llm=self.llm, action=self)
            else:
                generate = None

            if self.args.enable_multi_round_generate:
                generate_result = generate.multi_round_run(query=self.args.query, source_content=content)
            else:
                generate_result = generate.single_round_run(query=self.args.query, source_content=content)
            printer.print_text(f"代码生成完毕，耗时 {time.time() - start_time:.2f} 秒", style="green")

            if self.args.auto_merge:
                printer.print_text("正在自动合并代码...", style="green")
                if self.args.auto_merge == "editblock":
                    code_merge = CodeAutoMergeEditBlock(args=self.args, llm=self.llm)
                    merge_result = code_merge.merge_code(generate_result=generate_result)
                else:
                    merge_result = None

                content = merge_result.contents[0]
            else:
                content = generate_result.contents[0]

            with open(self.args.target_file, "w") as file:
                file.write(content)