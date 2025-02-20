import hashlib
from pathlib import Path


def generate_file_md5(file_path: str) -> str:
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def get_file_size(file_path: str | Path) -> int:
    """获取文件大小（字节）"""
    return Path(file_path).stat().st_size