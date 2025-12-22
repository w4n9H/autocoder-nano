import dataclasses
from enum import Enum
from typing import List, Dict, Any, Optional, Union, Tuple, Set, Callable

from pydantic import BaseModel, Field, SkipValidation


class AutoCoderArgs(BaseModel):
    request_id: Optional[str] = None  #
    file: Optional[str] = ''  #
    source_dir: Optional[str] = None  # 项目的路径
    git_url: Optional[str] = None  #
    target_file: Optional[str] = None  # 用于存储 提示词/生成代码 或其他信息的目标文件
    query: Optional[str] = None  # 你想让模型做什么
    template: Optional[str] = 'common'  #
    project_type: Optional[str] = None  # 项目的类型
    index_build_workers: Optional[int] = 2  # 构建索引的线程数量
    index_filter_level: Optional[int] = 0  # 用于查找相关文件的过滤级别
    index_filter_file_num: Optional[int] = -1  #
    index_filter_workers: Optional[int] = 1  # 过滤文件的线程数量
    index_model_max_input_length: Optional[int] = 6000  # 模型最大输入长度[废弃]
    filter_batch_size: Optional[int] = 10  #
    anti_quota_limit: Optional[int] = 1  # 请求模型时的间隔时间(s)
    skip_build_index: Optional[bool] = True  # 是否跳过索引构建(索引可以帮助您通过查询找到相关文件)
    skip_filter_index: Optional[bool] = True  #
    verify_file_relevance_score: Optional[int] = 6  #
    auto_merge: Optional[Union[bool, str]] = False  # 自动合并代码 True or False, 'editblock'
    enable_multi_round_generate: Optional[bool] = False  # 启用多轮生成
    editblock_similarity: Optional[float] = 0.9  # 编辑块相似性
    execute: Optional[bool] = None  # 模型是否生成代码
    context: Optional[str] = None  #
    human_as_model: Optional[bool] = False  #
    human_model_num: Optional[int] = 1  #
    include_project_structure: Optional[bool] = False  # 在生成代码的提示中是否包含项目目录结构
    urls: Optional[Union[str, List[str]]] = ""  # 一些文档的URL/路径，可以帮助模型了解你当前的工作
    # model: Optional[str] = ""  # 您要驱动运行的模型
    model_max_input_length: Optional[int] = 6000  # 模型最大输入长度[废弃]
    skip_confirm: Optional[bool] = False
    silence: Optional[bool] = False
    exclude_files: Optional[Union[str, List[str]]] = ""

    # RAG 相关参数
    rag_url: Optional[str] = ""
    rag_doc_filter_relevance: int = 6  # 文档过滤相关性阈值,高于该值才会被认为高度相关
    rag_context_window_limit: Optional[int] = 30000  # RAG上下文窗口大小 120k 60k 30k
    rag_params_max_tokens: Optional[int] = 4096
    full_text_ratio: Optional[float] = 0.7
    segment_ratio: Optional[float] = 0.2
    buff_ratio: Optional[float] = 0.1
    required_exts: Optional[str] = None  # 指定处理的文件后缀,例如.pdf,.doc
    monitor_mode: bool = False  # 监控模式,会监控doc_dir目录中的文件变化
    enable_hybrid_index: bool = False  # 开启混合索引
    disable_auto_window: bool = False
    hybrid_index_max_output_tokens: Optional[int] = 30000
    rag_type: Optional[str] = "simple"
    tokenizer_path: Optional[str] = None
    enable_rag_search: Optional[Union[bool, str]] = False
    enable_rag_context: Optional[Union[bool, str]] = False
    disable_segment_reorder: bool = False
    disable_inference_enhance: bool = False
    duckdb_vector_dim: Optional[int] = 1024  # DuckDB 向量化存储的维度
    duckdb_query_similarity: Optional[float] = 0.7  # DuckDB 向量化检索 相似度 阈值
    duckdb_query_top_k: Optional[int] = 50  # DuckDB 向量化检索 返回 TopK个结果(且大于相似度)

    # Web search 相关参数
    search_bocha_key: Optional[str] = None
    search_metaso_key: Optional[str] = None
    search_size: Optional[int] = 10

    # Git 相关参数
    skip_commit: Optional[bool] = False

    # Rules 相关参数
    enable_rules: Optional[bool] = False

    # Agent 相关参数
    generate_max_rounds: Optional[int] = 5
    enable_agentic_ask: Optional[bool] = False
    only_ask: Optional[bool] = False

    # 模型相关参数
    current_chat_model: Optional[str] = ""
    current_code_model: Optional[str] = ""
    model: Optional[str] = ""  # 默认模型
    chat_model: Optional[str] = ""  # AI Chat交互模型
    index_model: Optional[str] = ""  # 代码索引生成模型
    code_model: Optional[str] = ""  # 编码模型
    commit_model: Optional[str] = ""  # Git Commit 模型
    emb_model: Optional[str] = ""  # RAG Emb 模型
    recall_model: Optional[str] = ""  # RAG 召回阶段模型
    chunk_model: Optional[str] = ""  # 段落重排序模型
    qa_model: Optional[str] = ""  # RAG 提问模型
    vl_model: Optional[str] = ""  # 多模态模型

    # 上下文管理相关参数
    conversation_prune_safe_zone_tokens: int = 76800  # 按照常见的 128k 窗口 60% 计算,最佳安全窗口为 76800
    conversation_prune_ratio: float = 0.7
    conversation_prune_group_size: Optional[int] = 4
    conversation_prune_strategy: Optional[str] = "tool_output_cleanup"

    context_prune_strategy: Optional[str] = "extract"
    context_prune: Optional[bool] = True
    context_prune_safe_zone_tokens: Optional[int] = 20000
    context_prune_sliding_window_size: Optional[int] = 1000
    context_prune_sliding_window_overlap: Optional[int] = 100

    class Config:
        protected_namespaces = ()


class ServerArgs(BaseModel):
    host: str = None
    port: int = 8000
    uvicorn_log_level: str = "info"
    allow_credentials: bool = False
    allowed_origins: List[str] = ["*"]
    allowed_methods: List[str] = ["*"]
    allowed_headers: List[str] = ["*"]
    ssl_keyfile: str = None
    ssl_certfile: str = None
    response_role: str = "assistant"
    doc_dir: str = ""
    tokenizer_path: Optional[str] = None


class EnvInfo(BaseModel):
    os_name: str
    os_version: str
    python_version: str
    conda_env: Optional[str]
    virtualenv: Optional[str]
    has_bash: bool
    default_shell: Optional[str]
    home_dir: Optional[str]
    cwd: Optional[str]


class SourceCode(BaseModel):
    module_name: str
    source_code: str
    tag: str = ""
    tokens: int = -1
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SourceCodeList:
    def __init__(self, sources: List[SourceCode]):
        self.sources = sources

    def to_str(self):
        return "\n".join([f"##File: {source.module_name}\n{source.source_code}\n" for source in self.sources])


class LLMRequest(BaseModel):
    model: str  # 指定使用的语言模型名称
    messages: List[Dict[str, str]]  # 包含对话消息的列表，每个消息是一个字典，包含 "role"（角色）和 "content"（内容）
    stream: bool = False  # 是否以流式方式返回响应，默认为 False
    max_tokens: Optional[int] = None  # 生成的最大 token 数量，如果未指定，则使用模型默认值
    temperature: Optional[float] = 1  # None  # 控制生成文本的随机性，值越高生成的内容越随机，默认为模型默认值
    top_p: Optional[float] = 1  # None  # 控制生成文本的多样性，值越高生成的内容越多样，默认为模型默认值
    n: Optional[int] = 1  # None  # 生成多少个独立的响应，默认为 1
    stop: Optional[List[str]] = None  # 指定生成文本的停止条件，当生成的内容包含这些字符串时停止生成
    presence_penalty: Optional[float] = 0  # None  # 控制生成文本中是否鼓励引入新主题，值越高越鼓励新主题，默认为 0
    frequency_penalty: Optional[float] = 0  # None  # 控制生成文本中是否减少重复内容，值越高越减少重复，默认为 0


class LLMResponse(BaseModel):
    output: Union[str, List[float]] = ''  # 模型的输出，可以是字符串或浮点数列表
    input: Union[str, Dict[str, Any]] = ''  # 模型的输入，可以是字符串或字典
    metadata: Dict[str, Any] = dataclasses.field(
        default_factory=dict  # 元数据，包含与响应相关的额外信息，默认为空字典
    )


class SingleOutputMeta:
    def __init__(self, input_tokens_count: int = 0,
                 generated_tokens_count: int = 0,
                 reasoning_content: str = "",
                 finish_reason: str = "",
                 first_token_time: float = 0.0,
                 extra_info: Dict[str, Any] = {}):
        self.input_tokens_count = input_tokens_count
        self.generated_tokens_count = generated_tokens_count
        self.reasoning_content = reasoning_content
        self.finish_reason = finish_reason
        self.first_token_time = first_token_time
        self.extra_info = extra_info


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


class FileSystemModel(BaseModel):
    project_root: str
    get_all_file_names_in_project: SkipValidation[Callable]
    get_all_file_in_project: SkipValidation[Callable]
    get_all_dir_names_in_project: SkipValidation[Callable]
    get_all_file_in_project_with_dot: SkipValidation[Callable]
    get_symbol_list: SkipValidation[Callable]


class MemoryConfig(BaseModel):
    get_memory_func: SkipValidation[Callable]
    save_memory_func: SkipValidation[Callable]

    class Config:
        arbitrary_types_allowed = True


class SymbolItem(BaseModel):
    symbol_name: str
    symbol_type: SymbolType
    file_name: str


class VariableHolder:
    TOKENIZER_PATH = None
    TOKENIZER_MODEL = None


class DeleteEvent(BaseModel):
    file_paths: Set[str]


class AddOrUpdateEvent(BaseModel):
    file_infos: List[Tuple[str, str, float, str]]


class DocRelevance(BaseModel):
    is_relevant: bool
    relevant_score: int


class TaskTiming(BaseModel):
    submit_time: float = 0
    end_time: float = 0
    duration: float = 0
    real_start_time: float = 0
    real_end_time: float = 0
    real_duration: float = 0


class FilterDoc(BaseModel):
    source_code: SourceCode
    relevance: DocRelevance
    task_timing: TaskTiming


class RagConfig(BaseModel):
    filter_config: Optional[str] = None
    answer_config: Optional[str] = None


# New model class for cache items
class CacheItem(BaseModel):
    file_path: str
    relative_path: str
    content: List[Dict[str, Any]]  # Serialized SourceCode objects
    modify_time: float
    md5: str


# New model class for file information
class FileInfo(BaseModel):
    file_path: str
    relative_path: str
    modify_time: float
    file_md5: str


class RuleFile(BaseModel):
    """规则文件的Pydantic模型"""
    description: str = Field(default="", description="规则的描述")
    globs: List[str] = Field(default_factory=list, description="文件匹配模式列表")
    always_apply: bool = Field(default=False, description="是否总是应用规则")
    content: str = Field(default="", description="规则文件的正文内容")
    file_path: str = Field(default="", description="规则文件的路径")
