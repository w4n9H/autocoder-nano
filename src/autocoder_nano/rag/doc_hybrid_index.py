import json
import os
# import threading
import time
import platform
from abc import ABC, abstractmethod
from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, Tuple, List

from autocoder_nano.utils.file_utils import generate_file_md5
from autocoder_nano.utils.sys_utils import default_exclude_dirs
from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import CacheItem, FileInfo, SourceCode, DeleteEvent, AddOrUpdateEvent, \
    AutoCoderArgs
from autocoder_nano.rag.doc_loaders import process_file_in_multi_process, process_file_local
from autocoder_nano.rag.doc_storage import DuckDBVectorStore
from autocoder_nano.utils.printer_utils import Printer


if platform.system() != "Windows":
    import fcntl
else:
    fcntl = None


printer = Printer()


class BaseCacheManager(ABC):
    @abstractmethod
    def get_cache(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Dict]:
        pass


class HybridIndexCache(BaseCacheManager):
    def __init__(self, llm: AutoLLM, args: AutoCoderArgs, path, ignore_spec, required_exts):
        self.llm = llm
        self.args = args
        self.path = path
        self.ignore_spec = ignore_spec
        self.required_exts = required_exts

        self.storage = DuckDBVectorStore(
            llm=self.llm,
            args=self.args,
            database_name="nano_storage.db",
            table_name="rag",
            persist_dir=self.path
        )
        self.queue = []
        self.chunk_size = 4000
        self.max_output_tokens = self.args.hybrid_index_max_output_tokens

        # 设置缓存文件路径
        self.cache_dir = os.path.join(self.path, ".cache")
        self.cache_file = os.path.join(self.cache_dir, "nano_storage_speedup.jsonl")
        self.cache: Dict[str, CacheItem] = {}
        # 创建缓存目录
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

        # self.lock = threading.Lock()
        # self.stop_event = threading.Event()
        # self.thread = threading.Thread(target=self.process_queue)
        # self.thread.daemon = True
        # self.thread.start()

        self.process_queue()
        # 加载缓存
        self.cache = self._load_cache()
        printer.print_text(f"缓存加载完成, 包含 {len(self.cache.keys())} 个文档", style="green")

    def get_cache_size(self):
        return len(self.cache.keys())

    @staticmethod
    def _chunk_text(text, max_length=1000):
        """Split text into chunks"""
        chunks = []
        current_chunk = []
        current_length = 0

        for line in text.split("\n"):
            if current_length + len(line) > max_length and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_length = 0
            current_chunk.append(line)
            current_length += len(line)

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    def _load_cache(self) -> Dict[str, CacheItem]:
        """Load cache from file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    cache = {}
                    for line in lines:
                        try:
                            data = json.loads(line.strip())
                            if isinstance(data, dict) and "file_path" in data:
                                # 转换为 CacheItem 对象
                                cache_item = CacheItem.model_validate(data)
                                cache[data["file_path"]] = cache_item
                        except json.JSONDecodeError:
                            continue
                    return cache
            except Exception as e:
                printer.print_text(f"Error loading cache file: {str(e)}", style="red")
                return {}
        return {}

    def write_cache(self):
        cache_file = self.cache_file
        if not fcntl:
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    for cache_item in self.cache.values():
                        # 确保序列化 Pydantic 模型
                        json.dump(cache_item.model_dump(), f, ensure_ascii=False)
                        f.write("\n")
            except IOError as e:
                printer.print_text(f"Error writing cache file: {str(e)}", style="red")
        else:
            lock_file = cache_file + ".lock"
            with open(lock_file, "w", encoding="utf-8") as lockf:
                try:
                    # 获取文件锁
                    fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # 写入缓存文件
                    with open(cache_file, "w", encoding="utf-8") as f:
                        for cache_item in self.cache.values():
                            # 确保序列化 Pydantic 模型
                            json.dump(cache_item.model_dump(), f, ensure_ascii=False)
                            f.write("\n")

                finally:
                    # 释放文件锁
                    fcntl.flock(lockf, fcntl.LOCK_UN)

    @staticmethod
    def fileinfo_to_tuple(file_info: FileInfo) -> Tuple[str, str, float, str]:
        return file_info.file_path, file_info.relative_path, file_info.modify_time, file_info.file_md5

    def build_cache(self):
        """Build the cache by reading files and storing in DuckDBVectorStore"""
        printer.print_text(f"[构建缓存] Building cache for path: {self.path}", style="green")

        files_to_process = []
        for file_info in self.get_all_files():
            file_path, _, _, file_md5 = file_info
            if file_path not in self.cache or self.cache[file_path].md5 != file_md5:
                files_to_process.append(file_info)

        if not files_to_process:
            return

        results = []
        items = []

        from autocoder_nano.rag.token_counter import initialize_tokenizer

        initialize_tokenizer(self.args.tokenizer_path)
        with Pool(
                processes=max(2, os.cpu_count() // 2),
                initializer=initialize_tokenizer,
                initargs=(self.args.tokenizer_path,),
        ) as pool:
            target_files_to_process = []
            for file_info in files_to_process:
                target_files_to_process.append(file_info)
            results = pool.map(process_file_in_multi_process, target_files_to_process)

        # for _process_file in files_to_process:
        #     results.append(process_file_in_multi_process(_process_file))

        for file_info, result in zip(files_to_process, results):
            content: List[SourceCode] = result
            file_path, relative_path, modify_time, file_md5 = file_info
            self.cache[file_path] = CacheItem(
                file_path=file_path,
                relative_path=relative_path,
                content=[c.model_dump() for c in content],
                modify_time=modify_time,
                md5=file_md5,
            )

            for doc in content:
                printer.print_text(f"[构建缓存] 正在处理文件: {doc.module_name}", style="green")
                chunks = self._chunk_text(doc.source_code, self.chunk_size)
                for chunk_idx, chunk in enumerate(chunks):
                    chunk_item = {
                        "_id": f"{doc.module_name}_{chunk_idx}",
                        "file_path": file_path,
                        "content": chunk,
                        "raw_content": chunk,
                        "vector": "",
                        "mtime": modify_time,
                    }
                    items.append(chunk_item)

        # Save to local cache
        printer.print_text(f"[构建缓存] 保存缓存到本地文件: {self.cache_file}", style="green")
        self.write_cache()

        if items:
            printer.print_text(f"[构建缓存] 正在从 DuckDB 存储中清除现有缓存", style="green")
            self.storage.truncate_table()
            printer.print_text(f"[构建缓存] 准备写入 DuckDB 存储, 总块数: {len(items)}, 总文件数: {len(files_to_process)}",
                               style="green")

            # Use a fixed optimal batch size instead of dividing by worker count
            batch_size = 50  # Optimal batch size for Byzer Storage
            item_batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

            total_batches = len(item_batches)
            completed_batches = 0

            printer.print_text(f"[构建缓存] 开始使用每批次 {batch_size} 条数据写入 DuckDB 存储，总批次数: {total_batches}",
                               style="green")
            start_time = time.time()

            # Use more workers to process the smaller batches efficiently
            max_workers = min(5, total_batches)  # Cap at 10 workers or total batch count
            printer.print_text(f"[构建缓存] 使用 {max_workers} 个并行工作线程进行处理", style="green")

            def batch_add_doc(_batch):
                for b in _batch:
                    self.storage.add_doc(b, dim=self.args.duckdb_vector_dim)

            with (ThreadPoolExecutor(max_workers=max_workers) as executor):
                futures = []
                # Submit all batches to the executor upfront (non-blocking)
                for batch in item_batches:
                    futures.append(
                        executor.submit(
                            batch_add_doc, batch
                        )
                    )

                # Wait for futures to complete
                for future in as_completed(futures):
                    try:
                        future.result()
                        completed_batches += 1
                        elapsed = time.time() - start_time
                        estimated_total = elapsed / completed_batches * total_batches if completed_batches > 0 else 0
                        remaining = estimated_total - elapsed

                        # Only log progress at reasonable intervals to reduce log spam
                        if ((completed_batches == 1) or
                                (completed_batches == total_batches) or
                                (completed_batches % max(1, total_batches // 10) == 0)):
                            printer.print_text(
                                f"[构建缓存] 进度: {completed_batches}/{total_batches}"
                                f"({(completed_batches / total_batches * 100):.1f}%) 预计剩余时间: {remaining:.1f}秒",
                                style="green"
                            )
                    except Exception as e:
                        printer.print_text(f"[构建缓存] 保存批次时发生错误: {str(e)}", style="red")
                        # 添加更详细的错误信息
                        printer.print_text(f"[构建缓存] 错误详情: 批次大小:{len(batch) if 'batch' in locals() else '未知'}",
                                           style="red")

            total_time = time.time() - start_time
            printer.print_text(f"[构建缓存] 所有数据块已写入，总耗时: {total_time:.2f}秒", style="green")

    def update_storage(self, file_info: FileInfo, is_delete: bool):
        results = self.storage.query_by_path(file_info.file_path)
        if results:  # [('_id',)]
            for result in results:
                self.storage.delete_by_ids([result[0]])

        items = []
        if not is_delete:
            content = [
                SourceCode.model_validate(doc) for doc in self.cache[file_info.file_path].content
            ]
            modify_time = self.cache[file_info.file_path].modify_time
            for doc in content:
                printer.print_text(f"正在处理更新文件: {doc.module_name}", style="green")
                chunks = self._chunk_text(doc.source_code, self.chunk_size)
                for chunk_idx, chunk in enumerate(chunks):
                    chunk_item = {
                        "_id": f"{doc.module_name}_{chunk_idx}",
                        "file_path": file_info.file_path,
                        "content": chunk,
                        "raw_content": chunk,
                        "vector": chunk,
                        "mtime": modify_time,
                    }
                    items.append(chunk_item)
        if items:
            for _chunk in items:
                try:
                    self.storage.add_doc(_chunk, dim=self.args.duckdb_vector_dim)
                    time.sleep(self.args.anti_quota_limit)
                except Exception as err:
                    printer.print_text(f"Error in saving chunk: {str(err)}", style="red")

    def process_queue(self):
        while self.queue:
            file_list = self.queue.pop(0)
            if isinstance(file_list, DeleteEvent):
                for item in file_list.file_paths:
                    printer.print_text(f"{item} is detected to be removed", style="green")
                    del self.cache[item]
                    # 创建一个临时的 FileInfo 对象
                    file_info = FileInfo(file_path=item, relative_path="", modify_time=0, file_md5="")
                    self.update_storage(file_info, is_delete=True)

            elif isinstance(file_list, AddOrUpdateEvent):
                for file_info in file_list.file_infos:
                    # 处理文件并创建 CacheItem
                    _file_path, _relative_path, _modify_time, _file_md5 = file_info
                    printer.print_text(f"{_file_path} is detected to be updated", style="green")
                    content = process_file_local(_file_path)
                    self.cache[_file_path] = CacheItem(
                        file_path=_file_path,
                        relative_path=_relative_path,
                        content=[c.model_dump() for c in content],
                        modify_time=_modify_time,
                        md5=_file_md5,
                    )
                    add_or_update_file_info = FileInfo(
                        file_path=_file_path,
                        relative_path=_relative_path,
                        modify_time=_modify_time,
                        file_md5=_file_md5)
                    self.update_storage(add_or_update_file_info, is_delete=False)
            self.write_cache()

    def trigger_update(self):
        printer.print_text("检查文件是否有更新.....", style="green")
        files_to_process = []
        current_files = set()
        for file_info in self.get_all_files():
            file_path, _, _, file_md5 = file_info
            current_files.add(file_path)
            if file_path not in self.cache or self.cache[file_path].md5 != file_md5:
                files_to_process.append(file_info)

        deleted_files = set(self.cache.keys()) - current_files
        printer.print_key_value(
            items={"待解析的文件": f"{files_to_process}", "待删除的文件": f"{deleted_files}"},
            title="检查索引更新"
        )
        if deleted_files:
            # with self.lock:
            self.queue.append(DeleteEvent(file_paths=deleted_files))
        if files_to_process:
            # with self.lock:
            self.queue.append(AddOrUpdateEvent(file_infos=files_to_process))

    def get_all_files(self) -> List[Tuple[str, str, float, str]]:
        all_files = []
        for root, dirs, files in os.walk(self.path, followlinks=True):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in default_exclude_dirs]

            if self.ignore_spec:
                relative_root = os.path.relpath(root, self.path)
                dirs[:] = [
                    d for d in dirs
                    if not self.ignore_spec.match_file(os.path.join(relative_root, d))
                ]
                files = [
                    f for f in files
                    if not self.ignore_spec.match_file(os.path.join(relative_root, f))
                ]

            for file in files:
                if self.required_exts and not any(
                        file.endswith(ext) for ext in self.required_exts
                ):
                    continue

                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, self.path)
                modify_time = os.path.getmtime(file_path)
                file_md5 = generate_file_md5(file_path)
                all_files.append((file_path, relative_path, modify_time, file_md5))
        return all_files

    def get_cache(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Dict]:
        """Search cached documents using query"""
        self.trigger_update()  # 检查更新

        if options is None or "query" not in options:
            return {file_path: self.cache[file_path].model_dump() for file_path in self.cache}

        query = options.get("query", "")
        printer.print_text(f"正在使用向量搜索检索数据, 你的问题: {query}", style="green")
        total_tokens = 0
        results = []

        # Add vector search if enabled
        if options.get("enable_vector_search", True):
            # 返回值包含  [(_id, file_path, mtime, score,),]
            # results = self.storage.vector_search(query, similarity_value=0.7, similarity_top_k=200)
            search_results = self.storage.vector_search(
                query,
                similarity_value=self.args.duckdb_query_similarity,
                similarity_top_k=self.args.duckdb_query_top_k,
                query_dim=self.args.duckdb_vector_dim
            )
            results.extend(search_results)
            # dynamic_score_results = self.storage.vector_dynamic_score_search(
            #     query,
            #     similarity_top_k=self.args.duckdb_query_top_k,
            #     query_dim=self.args.duckdb_vector_dim
            # )
            # results.extend(dynamic_score_results)

        # Add text search
        # if options.get("enable_text_search", True):
        #     results = self.storage.full_text_search(query)

        # Group results by file_path and reconstruct documents while preserving order
        # 这里还可以有排序优化，综合考虑一篇内容出现的次数以及排序位置
        file_paths = []
        seen = set()
        for result in results:
            _id, _file_path, _mtime, _score = result
            if _file_path not in seen:
                seen.add(_file_path)
                file_paths.append(_file_path)

        # 从缓存中获取文件内容
        result = {}
        for file_path in file_paths:
            if file_path in self.cache:
                cached_data = self.cache[file_path]
                for doc in cached_data.content:
                    if total_tokens + doc["tokens"] > self.max_output_tokens:
                        printer.print_text(
                            f"当前检索已超出用户设置 Hybrid Index Max Tokens:{self.max_output_tokens}，"
                            f"累计tokens: {total_tokens}, "
                            f"经过向量搜索共检索出 {len(result.keys())} 个文档, 共 {len(self.cache.keys())} 个文档",
                            style="green")
                        return result
                    total_tokens += doc["tokens"]
                result[file_path] = cached_data.model_dump()
        printer.print_text(
            f"用户Hybrid Index Max Tokens设置为:{self.max_output_tokens}，"
            f"累计tokens: {total_tokens}, "
            f"经过向量搜索共检索出 {len(result.keys())} 个文档, 共 {len(self.cache.keys())} 个文档",
            style="green")
        return result