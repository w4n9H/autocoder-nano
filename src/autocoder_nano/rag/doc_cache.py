import json
import os
# import threading
import time
import platform
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple, List

from autocoder_nano.utils.file_utils import generate_file_md5
from autocoder_nano.utils.sys_utils import default_exclude_dirs
from autocoder_nano.actypes import DeleteEvent, AddOrUpdateEvent, SourceCode
from autocoder_nano.rag.doc_loaders import process_file_in_multi_process, process_file_local
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


class AutoCoderRAGAsyncUpdateQueue(BaseCacheManager):
    def __init__(self, path: str, ignore_spec, required_exts: list):
        self.path = path
        self.ignore_spec = ignore_spec
        self.required_exts = required_exts
        self.queue = []

        self.cache_dir = os.path.join(self.path, ".cache")
        self.cache_file = os.path.join(self.cache_dir, "cache.jsonl")
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

        # self.thread = threading.Thread(target=self._process_queue)
        # self.thread.daemon = True
        # self.thread.start()

        self.process_queue()
        self.cache = self.read_cache()

    def get_cache_size(self):
        return len(self.cache.keys())

    def _process_queue(self):
        while 1:
            try:
                self.process_queue()
            except Exception as e:
                printer.print_text(f"Error in process_queue: {e}", style="red")
            time.sleep(600)  # 避免过于频繁的检查

    def load_first(self):
        if self.cache:
            return
        files_to_process = []
        for file_info in self.get_all_files():
            file_path, _, modify_time, file_md5 = file_info
            if file_path not in self.cache or self.cache[file_path].get("md5", "") != file_md5:
                files_to_process.append(file_info)
        if not files_to_process:
            return

        results = []
        for _process_file in files_to_process:
            results.append(process_file_in_multi_process(_process_file))
        for file_info, result in zip(files_to_process, results):
            if result:  # 只有当result不为空时才更新缓存
                self.update_cache(file_info, result)
            else:
                printer.print_text(f"文件 {file_info[0]} 的结果为空，跳过缓存更新", style="yellow")
        self.write_cache()

    def trigger_update(self):
        files_to_process = []
        current_files = set()
        for file_info in self.get_all_files():
            file_path, _, _, file_md5 = file_info
            current_files.add(file_path)
            if file_path not in self.cache or self.cache[file_path].get("md5", "") != file_md5:
                files_to_process.append(file_info)

        deleted_files = set(self.cache.keys()) - current_files
        printer.print_key_value(
            items={"待解析的文件": f"{files_to_process}", "待删除的文件": f"{deleted_files}"},
            title="检查索引更新"
        )
        if deleted_files:
            self.queue.append(DeleteEvent(file_paths=deleted_files))
        if files_to_process:
            self.queue.append(AddOrUpdateEvent(file_infos=files_to_process))

    def process_queue(self):
        while self.queue:
            file_list = self.queue.pop(0)
            if isinstance(file_list, DeleteEvent):
                for item in file_list.file_paths:
                    printer.print_text(f"检测到 {item} 已被移除", style="green")
                    del self.cache[item]
            elif isinstance(file_list, AddOrUpdateEvent):
                for file_info in file_list.file_infos:
                    printer.print_text(f"检测到 {file_info[0]} 已更新", style="green")
                    try:
                        result = process_file_local(file_info[0])
                        if result:  # 只有当result不为空时才更新缓存
                            self.update_cache(file_info, result)
                        else:
                            printer.print_text(f"文件 {file_info[0]} 的结果为空，跳过缓存更新", style="yellow")
                    except Exception as e:
                        printer.print_text(f"SimpleCache 在处理队列时发生错误: {e}", style="red")
            self.write_cache()

    def read_cache(self) -> Dict[str, Dict]:
        cache = {}
        if os.path.exists(self.cache_file):
            with open(self.cache_file, "r") as f:
                for line in f:
                    data = json.loads(line)
                    cache[data["file_path"]] = data
        printer.print_text(f"正在读取文档缓存, 包含 {len(cache.keys())} 个文档", style="green")
        return cache

    def write_cache(self):
        if not fcntl:
            with open(self.cache_file, "w") as f:
                for data in self.cache.values():
                    try:
                        json.dump(data, f, ensure_ascii=False)
                        f.write("\n")
                    except Exception as e:
                        printer.print_text(f"Failed to write {data['file_path']} to .cache/cache.jsonl: {e}",
                                           style="red")
        else:
            lock_file = self.cache_file + ".lock"
            with open(lock_file, "w") as lockf:
                try:
                    # 获取文件锁
                    fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # 写入缓存文件
                    with open(self.cache_file, "w") as f:
                        for data in self.cache.values():
                            try:
                                json.dump(data, f, ensure_ascii=False)
                                f.write("\n")
                            except Exception as e:
                                printer.print_text(f"Failed to write {data['file_path']} to .cache/cache.jsonl: {e}",
                                                   style="red")
                finally:
                    # 释放文件锁
                    fcntl.flock(lockf, fcntl.LOCK_UN)

    def update_cache(self, file_info: Tuple[str, str, float, str], content: List[SourceCode]):
        file_path, relative_path, modify_time, file_md5 = file_info
        self.cache[file_path] = {
            "file_path": file_path,
            "relative_path": relative_path,
            "content": [c.model_dump() for c in content],
            "modify_time": modify_time,
            "md5": file_md5,
        }

    def get_cache(self, options: Optional[Dict[str, Any]] = None):
        self.load_first()
        self.trigger_update()
        # self.process_queue()
        return self.cache

    def build_cache(self):
        pass

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
                files[:] = [
                    f for f in files
                    if not self.ignore_spec.match_file(os.path.join(relative_root, f))
                ]

            for file in files:
                if self.required_exts and not any(file.endswith(ext) for ext in self.required_exts):
                    continue
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, self.path)
                modify_time = os.path.getmtime(file_path)
                file_md5 = generate_file_md5(file_path)
                all_files.append((file_path, relative_path, modify_time, file_md5))
        return all_files