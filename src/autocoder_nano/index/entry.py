import os
import time
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
import threading

# from loguru import logger
# from rich.console import Console
# from rich.table import Table

from autocoder_nano.index.index_manager import IndexManager
from autocoder_nano.actypes import SourceCode, TargetFile, VerifyFileRelevance, AutoCoderArgs
from autocoder_nano.core import AutoLLM
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


def build_index_and_filter_files(args: AutoCoderArgs, llm: AutoLLM, sources: List[SourceCode]) -> str:
    def get_file_path(_file_path):
        if _file_path.startswith("##"):
            return _file_path.strip()[2:]
        return _file_path

    final_files: Dict[str, TargetFile] = {}
    printer.print_text("第一阶段：处理 REST/RAG/Search 资源...", style="green")
    for source in sources:
        if source.tag in ["REST", "RAG", "SEARCH"]:
            final_files[get_file_path(source.module_name)] = TargetFile(
                file_path=source.module_name, reason="Rest/Rag/Search"
            )

    if not args.skip_build_index and llm:
        printer.print_text("第二阶段：为所有文件构建索引...", style="green")
        index_manager = IndexManager(args=args, llm=llm, source_codes=sources)
        index_data = index_manager.build_index()
        indexed_files_count = len(index_data) if index_data else 0
        printer.print_text(f"总索引文件数: {indexed_files_count}", style="green")

        if not args.skip_filter_index and args.index_filter_level >= 1:
            printer.print_text("第三阶段：执行 Level 1 过滤(基于查询) ...", style="green")
            target_files = index_manager.get_target_files_by_query(args.query)
            if target_files:
                for file in target_files.file_list:
                    file_path = file.file_path.strip()
                    final_files[get_file_path(file_path)] = file

            if target_files is not None and args.index_filter_level >= 2:
                printer.print_text("第四阶段：执行 Level 2 过滤（基于相关文件）...", style="green")
                related_files = index_manager.get_related_files(
                    [file.file_path for file in target_files.file_list]
                )
                if related_files is not None:
                    for file in related_files.file_list:
                        file_path = file.file_path.strip()
                        final_files[get_file_path(file_path)] = file

            # 如果 Level 1 filtering 和 Level 2 filtering 都未获取路径，则使用全部文件
            if not final_files:
                printer.print_text("Level 1, Level 2 过滤未找到相关文件, 将使用所有文件 ...", style="yellow")
                for source in sources:
                    final_files[get_file_path(source.module_name)] = TargetFile(
                        file_path=source.module_name,
                        reason="No related files found, use all files",
                    )

            printer.print_text("第五阶段：执行相关性验证 ...", style="green")
            verified_files = {}
            temp_files = list(final_files.values())
            verification_results = []

            def _print_verification_results(results):
                data_list = []
                if result:
                    for _file_path, _score, _status, _reason in results:
                        data_list.append(
                            [os.path.relpath(_file_path, args.source_dir),
                             f"{_score}/{_status}" if _score is not None else "N/A",
                             _reason])
                printer.print_table_compact(
                    data=data_list,
                    title="文件相关性验证结果",
                    headers=["文件路径", "得分/状态", "原因/错误"]
                )

            def _verify_single_file(single_file: TargetFile):
                for _source in sources:
                    if _source.module_name == single_file.file_path:
                        file_content = _source.source_code
                        try:
                            _result = index_manager.verify_file_relevance.with_llm(llm).with_return_type(
                                VerifyFileRelevance).run(
                                file_content=file_content,
                                query=args.query
                            )
                            if _result.relevant_score >= args.verify_file_relevance_score:
                                verified_files[single_file.file_path] = TargetFile(
                                    file_path=single_file.file_path,
                                    reason=f"Score:{_result.relevant_score}, {_result.reason}"
                                )
                                return single_file.file_path, _result.relevant_score, "PASS", _result.reason
                            else:
                                return single_file.file_path, _result.relevant_score, "FAIL", _result.reason
                        except Exception as e:
                            error_msg = str(e)
                            verified_files[single_file.file_path] = TargetFile(
                                file_path=single_file.file_path,
                                reason=f"Verification failed: {error_msg}"
                            )
                            return single_file.file_path, None, "ERROR", error_msg
                return

            with ThreadPoolExecutor(max_workers=max(int(cpu_count() / 2), args.index_filter_workers)) as executor:
                futures = [
                    executor.submit(_verify_single_file, pending_verify_file) for pending_verify_file in temp_files
                ]
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        verification_results.append(result)
            # for pending_verify_file in temp_files:
            #     result = _verify_single_file(pending_verify_file)
            #     if result:
            #         verification_results.append(result)
            #     time.sleep(args.anti_quota_limit)

            _print_verification_results(verification_results)
            # Keep all files, not just verified ones
            final_files = verified_files

    printer.print_text("第六阶段：筛选文件并应用限制条件 ...", style="green")
    if args.index_filter_file_num > 0:
        printer.print_text(f"> 从 {len(final_files)} 个文件中获取前 {args.index_filter_file_num} 个文件(Limit)", style="green")
    final_filenames = [file.file_path for file in final_files.values()]
    if not final_filenames:
        printer.print_text("未找到目标文件，你可能需要重新编写查询并重试.", style="yellow")
    if args.index_filter_file_num > 0:
        final_filenames = final_filenames[: args.index_filter_file_num]

    def _shorten_path(path: str, keep_levels: int = 3) -> str:
        """
        优化长路径显示，保留最后指定层级
        示例：/a/b/c/d/e/f.py -> .../c/d/e/f.py
        """
        parts = path.split(os.sep)
        if len(parts) > keep_levels:
            return ".../" + os.sep.join(parts[-keep_levels:])
        return path

    def _print_selected(data):
        printer.print_table_compact(
            data=[[_shorten_path(_file, keep_levels=3), _reason] for _file, _reason in data],
            title="代码上下文文件",
            headers=["文件路径", "原因"]
        )

    printer.print_text("第七阶段：准备最终输出 ...", style="green")
    _print_selected(
        [
            (file.file_path, file.reason)
            for file in final_files.values()
            if file.file_path in final_filenames
        ]
    )
    result_source_code = ""
    depulicated_sources = set()

    for file in sources:
        if file.module_name in final_filenames:
            if file.module_name in depulicated_sources:
                continue
            depulicated_sources.add(file.module_name)
            result_source_code += f"##File: {file.module_name}\n"
            result_source_code += f"{file.source_code}\n\n"

    return result_source_code