import json
import os
import shutil

from autocoder_nano.index.entry import build_index_and_filter_files
from autocoder_nano.index.index_manager import IndexManager
from autocoder_nano.index.symbols_utils import extract_symbols
from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs, SourceCode
from autocoder_nano.project import project_source
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


def index_build(llm: AutoLLM, args: AutoCoderArgs, sources_codes: list[SourceCode] = None):
    if not sources_codes:
        sources_codes = project_source(source_llm=llm, args=args)
    index = IndexManager(args=args, source_codes=sources_codes, llm=llm)
    index.build_index()


def index_build_and_filter(llm: AutoLLM, args: AutoCoderArgs, sources_codes: list[SourceCode] = None) -> str:
    if not sources_codes:
        sources_codes = project_source(source_llm=llm, args=args)
    return build_index_and_filter_files(args=args, llm=llm, sources=sources_codes)


def index_export(project_root: str, export_path: str) -> bool:
    try:
        index_path = os.path.join(project_root, ".auto-coder", "index.json")
        if not os.path.exists(index_path):
            printer.print_text(f"索引文件不存在. ", style="red")
            return False

        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)

        converted_data = {}
        for abs_path, data in index_data.items():
            try:
                rel_path = os.path.relpath(abs_path, project_root)
                data["module_name"] = rel_path
                converted_data[rel_path] = data
            except ValueError:
                printer.print_text(f"索引转换路径失败. ", style="yellow")
                converted_data[abs_path] = data

        export_file = os.path.join(export_path, "index.json")
        with open(export_file, "w", encoding="utf-8") as f:
            json.dump(converted_data, f, indent=2)
        printer.print_text(f"索引文件导出成功.", style="green")
        return True
    except Exception as err:
        printer.print_text(f"索引文件导出失败: {err}", style="red")
        return False


def index_import(project_root: str, import_path: str):
    try:
        import_file = os.path.join(import_path, "index.json")
        if not os.path.exists(import_file):
            printer.print_text(f"导入索引文件不存在. ", style="red")
            return False
        with open(import_file, "r", encoding="utf-8") as f:
            index_data = json.load(f)
        converted_data = {}
        for rel_path, data in index_data.items():
            try:
                abs_path = os.path.join(project_root, rel_path)
                data["module_name"] = abs_path
                converted_data[abs_path] = data
            except Exception as err:
                printer.print_text(f"{rel_path} 索引转换路径失败: {err}", style="yellow")
                converted_data[rel_path] = data
        # Backup existing index
        index_path = os.path.join(project_root, ".auto-coder", "index.json")
        if os.path.exists(index_path):
            printer.print_text(f"原索引文件不存在", style="yellow")
            backup_path = index_path + ".bak"
            shutil.copy2(index_path, backup_path)

        # Write new index
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(converted_data, f, indent=2)
        return True
    except Exception as err:
        printer.print_text(f"索引文件导入失败: {err}", style="red")
        return False


__all__ = ["index_build", "index_export", "index_import", "index_build_and_filter", "extract_symbols", "IndexManager"]