import dataclasses
from enum import Enum
from typing import List, Dict, Any, Optional, Union, Tuple

from pydantic import BaseModel, Field


class SourceCode(BaseModel):
    module_name: str
    source_code: str
    tag: str = ""
    tokens: int = -1
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LLMRequest(BaseModel):
    model: str  # 指定使用的语言模型名称
    messages: List[Dict[str, str]]  # 包含对话消息的列表，每个消息是一个字典，包含 "role"（角色）和 "content"（内容）
    stream: bool = False  # 是否以流式方式返回响应，默认为 False
    max_tokens: Optional[int] = None  # 生成的最大 token 数量，如果未指定，则使用模型默认值
    temperature: Optional[float] = None  # 控制生成文本的随机性，值越高生成的内容越随机，默认为模型默认值
    top_p: Optional[float] = None  # 控制生成文本的多样性，值越高生成的内容越多样，默认为模型默认值
    n: Optional[int] = None  # 生成多少个独立的响应，默认为 1
    stop: Optional[List[str]] = None  # 指定生成文本的停止条件，当生成的内容包含这些字符串时停止生成
    presence_penalty: Optional[float] = None  # 控制生成文本中是否鼓励引入新主题，值越高越鼓励新主题，默认为 0
    frequency_penalty: Optional[float] = None  # 控制生成文本中是否减少重复内容，值越高越减少重复，默认为 0


class LLMResponse(BaseModel):
    output: Union[str, List[float]] = ''  # 模型的输出，可以是字符串或浮点数列表
    input: Union[str, Dict[str, Any]] = ''  # 模型的输入，可以是字符串或字典
    metadata: Dict[str, Any] = dataclasses.field(
        default_factory=dict  # 元数据，包含与响应相关的额外信息，默认为空字典
    )


class IndexItem(BaseModel):
    module_name: str
    symbols: str
    last_modified: float
    md5: str  # 新增文件内容的MD5哈希值字段


class TargetFile(BaseModel):
    file_path: str
    reason: str = Field(
        ..., description="The reason why the file is the target file"
    )


class FileList(BaseModel):
    file_list: List[TargetFile]


class SymbolType(Enum):
    USAGE = "usage"
    FUNCTIONS = "functions"
    VARIABLES = "variables"
    CLASSES = "classes"
    IMPORT_STATEMENTS = "import_statements"


class SymbolsInfo(BaseModel):
    usage: Optional[str] = Field('', description="用途")
    functions: List[str] = Field([], description="函数")
    variables: List[str] = Field([], description="变量")
    classes: List[str] = Field([], description="类")
    import_statements: List[str] = Field([], description="导入语句")


class VerifyFileRelevance(BaseModel):
    relevant_score: int
    reason: str


class CodeGenerateResult(BaseModel):
    contents: List[str]
    conversations: List[List[Dict[str, Any]]]


class PathAndCode(BaseModel):
    path: str
    content: str


class RankResult(BaseModel):
    rank_result: List[int]


class MergeCodeWithoutEffect(BaseModel):
    success_blocks: List[Tuple[str, str]]
    failed_blocks: List[Any]


class CommitResult(BaseModel):
    success: bool
    commit_message: Optional[str] = None
    commit_hash: Optional[str] = None
    changed_files: Optional[List[str]] = None
    diffs: Optional[dict] = None
    error_message: Optional[str] = None


class Tag(BaseModel):
    start_tag: str
    content: str
    end_tag: str


class SymbolItem(BaseModel):
    symbol_name: str
    symbol_type: SymbolType
    file_name: str