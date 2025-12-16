import hashlib
import json
import os
import time
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
import threading

from autocoder_nano.index.symbols_utils import extract_symbols, symbols_info_to_str
from autocoder_nano.core import AutoLLM
from autocoder_nano.core import prompt
from autocoder_nano.actypes import SourceCode, AutoCoderArgs, IndexItem, SymbolType, FileList
from autocoder_nano.rag.token_counter import count_tokens
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


class IndexManager:
    def __init__(self, args: AutoCoderArgs, source_codes: List[SourceCode], llm: AutoLLM = None):
        self.args = args
        self.sources = source_codes
        self.source_dir = args.source_dir
        self.index_dir = os.path.join(self.source_dir, ".auto-coder")
        self.index_file = os.path.join(self.index_dir, "index.json")
        self.llm = llm
        self.llm.setup_default_model_name(args.chat_model)
        self.conversation_prune_safe_zone_tokens = args.conversation_prune_safe_zone_tokens  # 模型输入最大长度
        # 使用 time.sleep(self.anti_quota_limit) 防止超过 API 频率限制
        self.anti_quota_limit = args.anti_quota_limit
        # 如果索引目录不存在,则创建它
        if not os.path.exists(self.index_dir):
            os.makedirs(self.index_dir)

    def build_index(self):
        """ 构建或更新索引，使用多线程处理多个文件，并将更新后的索引数据写入文件 """
        if os.path.exists(self.index_file):
            with open(self.index_file, "r") as file:  # 读缓存
                index_data = json.load(file)
        else:  # 首次 build index
            printer.print_text("首次生成索引.", style="green")
            index_data = {}

        # 清理已不存在的文件索引
        keys_to_remove = []
        for file_path in index_data:
            if not os.path.exists(file_path):
                keys_to_remove.append(file_path)
        # 删除无效条目并记录日志
        for key in set(keys_to_remove):
            if key in index_data:
                del index_data[key]

        @prompt()
        def error_message(source_dir: str, file_path: str):
            """
            The source_dir is different from the path in index file (e.g. file_path:{{ file_path }} source_dir:{{
            source_dir }}). You may need to replace the prefix with the source_dir in the index file or Just delete
            the index file to rebuild it.
            """

        for item in index_data.keys():
            if not item.startswith(self.source_dir):
                printer.print_text(error_message.prompt(source_dir=self.source_dir, file_path=item), style="yellow")
                break

        updated_sources = []
        wait_to_build_files = []
        for source in self.sources:
            file_path = source.module_name
            if not os.path.exists(file_path):
                continue
            source_code = source.source_code
            if len(source_code) <= 0:
                continue
            md5 = hashlib.md5(source_code.encode("utf-8")).hexdigest()
            if source.module_name not in index_data or index_data[source.module_name]["md5"] != md5:
                wait_to_build_files.append(source)
        counter = 0
        num_files = len(wait_to_build_files)
        total_files = len(self.sources)
        printer.print_text(f"总文件数: {total_files}, 需要索引文件数: {num_files}", style="green")

        with ThreadPoolExecutor(max_workers=max(int(cpu_count() / 2), self.args.index_build_workers)) as executor:
            futures = [
                executor.submit(self.build_index_for_single_source, source) for source in wait_to_build_files
            ]
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    counter += 1
                    printer.print_text(f"正在构建索引:{counter}/{num_files}...", style="green")
                    module_name = result["module_name"]
                    index_data[module_name] = result
                    updated_sources.append(module_name)
        # for source in wait_to_build_files:
        #     build_result = self.build_index_for_single_source(source)
        #     if build_result is not None:
        #         counter += 1
        #         printer.print_text(f"正在构建索引:{counter}/{num_files}...", style="green")
        #         module_name = build_result["module_name"]
        #         index_data[module_name] = build_result
        #         updated_sources.append(module_name)
        if updated_sources:
            with open(self.index_file, "w") as fp:
                json_str = json.dumps(index_data, indent=2, ensure_ascii=False)
                fp.write(json_str)
        return index_data

    def split_text_into_chunks(self, text):
        """ 文本分块,将大文本分割成适合 LLM 处理的小块 """
        lines = text.split("\n")
        chunks = []
        current_chunk = []
        current_length = 0
        for line in lines:
            if current_length + len(line) + 1 <= self.conversation_prune_safe_zone_tokens:
                current_chunk.append(line)
                current_length += len(line) + 1
            else:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_length = len(line) + 1
        if current_chunk:
            chunks.append("\n".join(current_chunk))
        return chunks

    @prompt()
    def get_all_file_symbols(self, path: str, code: str) -> str:
        """
        你的目标是从给定的代码中获取代码里的符号，需要获取的符号类型包括：

        1. 函数
        2. 类
        3. 变量
        4. 所有导入语句

        如果没有任何符号,返回空字符串就行。
        如果有符号，按如下格式返回:

        ```
        {符号类型}: {符号名称}, {符号名称}, ...
        ```

        注意：
        1. 直接输出结果，不要尝试使用任何代码
        2. 不要分析代码的内容和目的
        3. 用途的长度不能超过100字符
        4. 导入语句的分隔符为^^

        下面是一段示例：

        ## 输入
        下列是文件 /test.py 的源码：

        import os
        import time
        from loguru import logger
        import byzerllm

        a = ""

        @byzerllm.prompt(render="jinja")
        def auto_implement_function_template(instruction:str, content:str)->str:

        ## 输出
        用途：主要用于提供自动实现函数模板的功能。
        函数：auto_implement_function_template
        变量：a
        类：
        导入语句：import os^^import time^^from loguru import logger^^import byzerllm

        现在，让我们开始一个新的任务:

        ## 输入
        下列是文件 {{ path }} 的源码：

        {{ code }}

        ## 输出
        """

    def build_index_for_single_source(self, source: SourceCode):
        """ 处理单个源文件，提取符号信息并存储元数据 """
        file_path = source.module_name
        if not os.path.exists(file_path):  # 过滤不存在的文件
            return None

        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".md", ".html", ".txt", ".doc", ".pdf"]:  # 过滤文档文件
            return None

        if source.source_code.strip() == "":
            return None

        md5 = hashlib.md5(source.source_code.encode("utf-8")).hexdigest()

        try:
            start_time = time.monotonic()
            source_code = source.source_code
            if count_tokens(source.source_code) > self.conversation_prune_safe_zone_tokens:
                printer.print_text(
                    f"""
                    警告[构建索引]: 源代码({source.module_name})长度过长,
                    ({len(source.source_code)}) > 模型最大输入长度({self.conversation_prune_safe_zone_tokens}),
                    正在分割为多个块...
                    """,
                    style="yellow"
                )
                chunks = self.split_text_into_chunks(source_code)
                symbols_list = []
                for chunk in chunks:
                    chunk_symbols = self.get_all_file_symbols.with_llm(self.llm).run(source.module_name, chunk)
                    time.sleep(self.anti_quota_limit)
                    symbols_list.append(chunk_symbols.output)
                symbols = "\n".join(symbols_list)
            else:
                single_symbols = self.get_all_file_symbols.with_llm(self.llm).run(source.module_name, source_code)
                symbols = single_symbols.output
                time.sleep(self.anti_quota_limit)

            printer.print_text(f"解析并更新索引：{file_path}（MD5: {md5}），耗时 {time.monotonic() - start_time:.2f} 秒",
                               style="green")
        except Exception as e:
            printer.print_text(f"源文件 {file_path} 处理失败: {e}", style="yellow")
            return None

        return {
            "module_name": source.module_name,
            "symbols": symbols,
            "last_modified": os.path.getmtime(file_path),
            "md5": md5,
        }

    @prompt()
    def _get_target_files_by_query(self, indices: str, query: str) -> str:
        """
        下面是已知文件以及对应的符号信息：

        {{ indices }}

        用户的问题是：

        {{ query }}

        现在，请根据用户的问题以及前面的文件和符号信息，寻找相关文件路径。返回结果按如下格式：

        ```json
        {
            "file_list": [
                {
                    "file_path": "path/to/file.py",
                    "reason": "The reason why the file is the target file"
                },
                {
                    "file_path": "path/to/file.py",
                    "reason": "The reason why the file is the target file"
                }
            ]
        }
        ```

        如果没有找到，返回如下 json 即可：

        ```json
            {"file_list": []}
        ```

        请严格遵循以下步骤：

        1. 识别特殊标记：
           - 查找query中的 `@` 符号，它后面的内容是用户关注的文件路径。
           - 查找query中的 `@@` 符号，它后面的内容是用户关注的符号（如函数名、类名、变量名）。

        2. 匹配文件路径：
           - 对于 `@` 标记，在indices中查找包含该路径的所有文件。
           - 路径匹配应该是部分匹配，因为用户可能只提供了路径的一部分。

        3. 匹配符号：
           - 对于 `@@` 标记，在indices中所有文件的符号信息中查找该符号。
           - 检查函数、类、变量等所有符号类型。

        4. 分析依赖关系：
           - 利用 "导入语句" 信息确定文件间的依赖关系。
           - 如果找到了相关文件，也包括与之直接相关的依赖文件。

        5. 考虑文件用途：
           - 使用每个文件的 "用途" 信息来判断其与查询的相关性。

        6. 请严格按格式要求返回结果,无需额外的说明

        请确保结果的准确性和完整性，包括所有可能相关的文件。
        """

    def read_index(self) -> List[IndexItem]:
        """ 读取并解析索引文件，将其转换为 IndexItem 对象列表 """
        if not os.path.exists(self.index_file):
            return []

        with open(self.index_file, "r") as file:
            index_data = json.load(file)

        index_items = []
        for module_name, data in index_data.items():
            index_item = IndexItem(
                module_name=module_name,
                symbols=data["symbols"],
                last_modified=data["last_modified"],
                md5=data["md5"]
            )
            index_items.append(index_item)

        return index_items

    def _get_meta_str(self, includes: Optional[List[SymbolType]] = None):
        index_items = self.read_index()
        current_chunk = []
        for item in index_items:
            symbols_str = item.symbols
            if includes:
                symbol_info = extract_symbols(symbols_str)
                symbols_str = symbols_info_to_str(symbol_info, includes)

            item_str = f"##{item.module_name}\n{symbols_str}\n\n"
            if len(current_chunk) > self.args.filter_batch_size:
                yield "".join(current_chunk)
                current_chunk = [item_str]
            else:
                current_chunk.append(item_str)
        if current_chunk:
            yield "".join(current_chunk)

    def get_target_files_by_query(self, query: str):
        """ 根据查询条件查找相关文件，考虑不同过滤级别 """
        all_results = []
        lock = threading.Lock()
        completed = 0

        includes = None
        if self.args.index_filter_level == 0:
            includes = [SymbolType.USAGE]
        if self.args.index_filter_level >= 1:
            includes = None

        def _process_filter_by_query(_chunk):
            result = self._get_target_files_by_query.with_llm(self.llm).with_return_type(FileList).run(_chunk, query)
            if result is not None:
                with lock:
                    all_results.extend(result.file_list)
            else:
                printer.print_text(f"无法找到分块的目标文件.原因可能是模型响应未返回格式错误.", style="yellow")
            time.sleep(self.args.anti_quota_limit)

        chunks_to_process = list(self._get_meta_str(includes=includes))
        total = len(chunks_to_process)
        with ThreadPoolExecutor(max_workers=max(int(cpu_count() / 2), self.args.index_filter_workers)) as executor:
            futures = [
                executor.submit(_process_filter_by_query, chunk) for chunk in chunks_to_process
            ]
            for future in as_completed(futures):
                future.result()
                completed += 1
                printer.print_text(f"已完成 {completed}/{total} 个分块(基于查询条件)", style="green")
        # for chunk in self._get_meta_str(includes=includes):
        #     result = self._get_target_files_by_query.with_llm(self.llm).with_return_type(FileList).run(chunk, query)
        #     if result is not None:
        #         all_results.extend(result.file_list)
        #         completed += 1
        #     else:
        #         printer.print_text(f"无法找到分块的目标文件.原因可能是模型响应未返回格式错误.", style="yellow")
        #     total += 1
        #     time.sleep(self.anti_quota_limit)

        # printer.print_text(f"已完成 {completed}/{total} 个分块(基于查询条件)", style="green")
        all_results = list({file.file_path: file for file in all_results}.values())
        if self.args.index_filter_file_num > 0:
            limited_results = all_results[: self.args.index_filter_file_num]
            return FileList(file_list=limited_results)
        return FileList(file_list=all_results)

    @prompt()
    def _get_related_files(self, indices: str, file_paths: str) -> str:
        """
        下面是所有文件以及对应的符号信息：

        {{ indices }}

        请参考上面的信息，找到被下列文件使用或者引用到的文件列表：

        {{ file_paths }}

        请按如下格式进行输出：

        ```json
        {
            "file_list": [
                {
                    "file_path": "path/to/file.py",
                    "reason": "The reason why the file is the target file"
                },
                {
                    "file_path": "path/to/file.py",
                    "reason": "The reason why the file is the target file"
                }
            ]
        }
        ```

        如果没有相关的文件，输出如下 json 即可：

        ```json
        {"file_list": []}
        ```

        注意，
        1. 找到的文件名必须出现在上面的文件列表中
        2. 原因控制在20字以内, 且使用中文
        3. 请严格按格式要求返回结果,无需额外的说明
        """

    def get_related_files(self, file_paths: List[str]):
        """ 根据文件路径查询相关文件 """
        all_results = []
        lock = threading.Lock()
        completed = 0
        total = 0

        def _process_filter_by_file(_chunk):
            nonlocal completed
            result = self._get_related_files.with_llm(self.llm).with_return_type(
                FileList).run(_chunk, "\n".join(file_paths))
            if result is not None:
                with lock:
                    all_results.extend(result.file_list)
                    completed += 1
            else:
                printer.print_text(f"无法找到分块的目标文件.原因可能是模型响应未返回格式错误.", style="yellow")
            time.sleep(self.args.anti_quota_limit)

        chunks_to_process = list(self._get_meta_str())
        total = len(chunks_to_process)
        with ThreadPoolExecutor(max_workers=max(int(cpu_count() / 2), self.args.index_filter_workers)) as executor:
            futures = [
                executor.submit(_process_filter_by_file, chunk) for chunk in chunks_to_process
            ]
            for future in as_completed(futures):
                future.result()
                completed += 1
                printer.print_text(f"已完成 {completed}/{total} 个分块(基于相关文件)", style="green")

        # for chunk in self._get_meta_str():
        #     result = self._get_related_files.with_llm(self.llm).with_return_type(
        #         FileList).run(chunk, "\n".join(file_paths))
        #     if result is not None:
        #         all_results.extend(result.file_list)
        #         completed += 1
        #     else:
        #         printer.print_text(f"无法找到与分块相关的文件。原因可能是模型限制或查询条件与文件不匹配.", style="yellow")
        #     total += 1
        #     time.sleep(self.anti_quota_limit)
        # printer.print_text(f"已完成 {completed}/{total} 个分块(基于相关文件)", style="green")
        all_results = list({file.file_path: file for file in all_results}.values())
        return FileList(file_list=all_results)

    @prompt()
    def verify_file_relevance(self, file_content: str, query: str) -> str:
        """
        请验证下面的文件内容是否与用户问题相关:

        文件内容:
        {{ file_content }}

        用户问题:
        {{ query }}

        相关是指，需要依赖这个文件提供上下文，或者需要修改这个文件才能解决用户的问题。
        请给出相应的可能性分数：0-10，并结合用户问题，理由控制在50字以内，并且使用中文。
        请严格按格式要求返回结果。
        格式如下:

        ```json
        {
            "relevant_score": 0-10,
            "reason": "这是相关的原因..."
        }
        ```
        """