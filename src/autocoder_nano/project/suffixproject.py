import os
import re

from loguru import logger

from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs, SourceCode
from autocoder_nano.rag.doc_entry import RAGFactory
from autocoder_nano.utils.sys_utils import default_exclude_dirs


class SuffixProject:
    def __init__(self, llm: AutoLLM, args: AutoCoderArgs, exclude_files=""):
        self.llm = llm
        self.args = args
        self.target_file = args.target_file
        self.directory = args.source_dir
        self.project_type = args.project_type
        self.suffixs = [
            suffix.strip() if suffix.startswith(".") else f".{suffix.strip()}"
            for suffix in self.project_type.split(",") if suffix.strip()
        ]
        self.exclude_files = args.exclude_files
        self.exclude_patterns = self.parse_exclude_files(self.exclude_files)
        self.sources = []
        self.sources_set = set()
        self.default_exclude_dirs = default_exclude_dirs

    @staticmethod
    def parse_exclude_files(exclude_files):
        if not exclude_files:
            return []

        if isinstance(exclude_files, str):
            exclude_files = [exclude_files]

        exclude_patterns = []
        for pattern in exclude_files:
            if pattern.startswith("regex://"):
                pattern = pattern[8:]
                exclude_patterns.append(re.compile(pattern))
            else:
                raise ValueError(
                    "Invalid exclude_files format. Expected 'regex://<pattern>' "
                )
        return exclude_patterns

    def should_exclude(self, file_path):
        for pattern in self.exclude_patterns:
            if pattern.search(file_path):
                return True
        return False

    @staticmethod
    def read_file_content(file_path):  # 读取代码文件
        with open(file_path, "r") as file:
            return file.read()

    def convert_to_source_code(self, file_path):
        module_name = file_path
        try:
            source_code = self.read_file_content(file_path)
        except Exception as e:
            logger.warning(f"Failed to read file: {file_path}. Error: {str(e)}")
            return None
        return SourceCode(module_name=module_name, source_code=source_code)

    def is_suffix_file(self, file_path):
        return any([file_path.endswith(suffix) for suffix in self.suffixs])

    def get_rag_source_codes(self):
        # /conf enable_rag_search:true
        # /conf enable_rag_context:true
        # /conf rag_url:/path
        # /conf enable_hybrid_index:true
        if not self.args.enable_rag_search and not self.args.enable_rag_context and not self.args.rag_url:
            return []

        rag = RAGFactory.get_rag(self.llm, self.args, "")
        docs = rag.search(self.args.query)
        for doc in docs:
            doc.tag = "RAG"
        return docs

    def get_rest_source_codes(self):
        source_codes = []
        if self.args.urls:
            urls = self.args.urls
            for url in urls:
                source_codes.append(self.convert_to_source_code(url))
            for source in source_codes:
                source.tag = "REST"
        return source_codes

    def get_source_codes(self):
        for root, dirs, files in os.walk(self.directory, followlinks=True):
            dirs[:] = [d for d in dirs if d not in self.default_exclude_dirs]
            for file in files:
                file_path = os.path.join(root, file)
                if self.should_exclude(file_path):
                    continue
                if self.is_suffix_file(file_path):
                    source_code = self.convert_to_source_code(file_path)
                    if source_code is not None:
                        yield source_code

    def output(self):
        return open(self.target_file, "r").read()

    def run(self):
        if self.target_file:
            # v1:写入文件版本
            with open(self.target_file, "w") as file:

                for code in self.get_rest_source_codes():
                    if code.module_name not in self.sources_set:
                        self.sources_set.add(code.module_name)
                        self.sources.append(code)
                        file.write(f"##File: {code.module_name}\n")
                        file.write(f"{code.source_code}\n\n")

                for code in self.get_source_codes():
                    if code.module_name not in self.sources_set:
                        self.sources_set.add(code.module_name)
                        self.sources.append(code)
                        file.write(f"##File: {code.module_name}\n")
                        file.write(f"{code.source_code}\n\n")