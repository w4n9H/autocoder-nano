import hashlib
from pathlib import Path
from typing import Union


def generate_file_md5(file_path: str) -> str:
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def generate_content_md5(content: Union[str, bytes]) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    md5_hash = hashlib.md5()
    md5_hash.update(content)
    return md5_hash.hexdigest()


def get_file_size(file_path: str | Path) -> int:
    """获取文件大小（字节）"""
    return Path(file_path).stat().st_size


def load_tokenizer(tokenizer_path: str = None):
    from autocoder_nano.actypes import VariableHolder
    from tokenizers import Tokenizer
    from importlib import resources
    try:
        if not tokenizer_path:
            tokenizer_path = resources.files("autocoder_nano").joinpath("data/tokenizer.json").__str__()
        VariableHolder.TOKENIZER_PATH = tokenizer_path
        VariableHolder.TOKENIZER_MODEL = Tokenizer.from_file(tokenizer_path)
    except FileNotFoundError:
        tokenizer_path = None