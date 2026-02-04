import hashlib
import os
from pathlib import Path
from typing import Union, Optional, List
from collections import defaultdict

from autocoder_nano.utils.sys_utils import default_exclude_dirs


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


def auto_count_file_extensions(
        directory_path: str, include_hidden: bool = False, exclude_dirs: List[str] = None, top_n: int = 3
):  # -> dict[str, int]:
    programming_languages = {
        # Python
        '.py': 'Python',
        # JavaScript/TypeScript
        '.js': 'JavaScript',
        '.jsx': 'JavaScript (React)',
        '.ts': 'TypeScript',
        '.tsx': 'TypeScript (React)',
        '.vue': 'Vue.js',
        '.svelte': 'Svelte',
        # Java
        '.java': 'Java',
        '.kt': 'Kotlin',
        '.kts': 'Kotlin Script',
        '.scala': 'Scala',
        '.groovy': 'Groovy',
        # C/C++
        '.c': 'C',
        '.cpp': 'C++',
        '.cc': 'C++',
        '.cxx': 'C++',
        '.h': 'C/C++ Header',
        '.hpp': 'C++ Header',
        '.hxx': 'C++ Header',
        # C#
        '.cs': 'C#',
        # Go
        '.go': 'Go',
        # Rust
        '.rs': 'Rust',
        # Swift
        '.swift': 'Swift',
        # Ruby
        '.rb': 'Ruby',
        '.erb': 'Ruby (ERB)',
        # PHP
        '.php': 'PHP',
        # Shell/Bash
        '.sh': 'Shell',
        '.bash': 'Bash',
        '.zsh': 'Zsh',
        # PowerShell
        '.ps1': 'PowerShell',
        '.psm1': 'PowerShell Module',
        # HTML/CSS
        '.html': 'HTML',
        '.htm': 'HTML',
        '.xhtml': 'XHTML',
        '.css': 'CSS',
        '.scss': 'SCSS',
        '.sass': 'SASS',
        '.less': 'LESS',
        '.styl': 'Stylus',
        # SQL
        '.sql': 'SQL',
        '.psql': 'PostgreSQL',
        # R
        '.r': 'R',
        '.R': 'R',
        # Lua
        '.lua': 'Lua',
        # Perl
        '.pl': 'Perl',
        '.pm': 'Perl Module',
        # Elixir
        '.ex': 'Elixir',
        '.exs': 'Elixir Script',
        # Clojure
        '.clj': 'Clojure',
        '.cljs': 'ClojureScript',
        '.cljc': 'Clojure Common',
        # Objective-C
        '.m': 'Objective-C',
        '.mm': 'Objective-C++',
        # WebAssembly
        '.wat': 'WebAssembly Text',
        '.wasm': 'WebAssembly Binary',
    }

    if exclude_dirs is None:
        exclude_dirs = default_exclude_dirs

    extension_counter = defaultdict(int)

    # 使用os.walk以便更好地控制目录排除
    for root, dirs, files in os.walk(str(directory_path)):
        # 排除指定的目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        # 如果不包含隐藏文件，排除以.开头的目录
        if not include_hidden:
            dirs[:] = [d for d in dirs if not d.startswith('.')]

        for filename in files:
            # 处理隐藏文件
            if not include_hidden and filename.startswith('.'):
                continue

            # 获取文件扩展名
            _, ext = os.path.splitext(filename)
            ext = ext.lower()

            # 检查是否是编程语言文件
            if ext in programming_languages:
                extension_counter[ext] += 1
    # 按数量降序排序
    return dict(sorted(extension_counter.items(), key=lambda x: x[1], reverse=True)[:top_n])