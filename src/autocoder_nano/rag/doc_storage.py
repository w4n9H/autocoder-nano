import hashlib
import json
import os
from typing import Optional, List, Any, Dict

import duckdb
import numpy as np

from autocoder_nano.core import AutoLLM
from autocoder_nano.core import prompt
from autocoder_nano.actypes import SourceCode, AutoCoderArgs


@prompt()
def _generate_embedding(user_input: str) -> str:
    """
    你是一个专业的自然语言处理助手，擅长将文本转换为高质量的嵌入向量（embedding）。你的任务是根据输入的文本，生成语义丰富、高质量的嵌入表示。

    任务要求：
    1. 理解输入文本的语义和上下文。
    2. 生成一个固定长度的向量表示，捕捉文本的核心语义信息。
    3. 确保生成的向量适合用于下游任务，如文本相似度计算、聚类或检索。

    输入文本：
    {{ user_input }}

    输出格式：
    1. 返回一个长度为 {指定维度，如 512、768 等} 的浮点数列表。
    2. 向量值范围应在 [-1, 1] 之间。
    3. 确保向量已经归一化（可选，根据需求）。

    示例：
    输入文本："深度学习是人工智能的一个重要分支。"
    输出：[0.123, -0.456, 0.789, ..., 0.234]
    长度为指定维度的浮点数列表
    [0.123, -0.456, 0.789, ..., 0.234]

    输出要求:
    1.长度为指定维度的浮点数列表
    2.仅返回列表,无需返回其他数据
    """


class DuckDBLocalContext:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._conn = None

    def _install_load_extension(self, ext_list):
        for ext in ext_list:
            self._conn.install_extension(ext)
            self._conn.load_extension(ext)

    def __enter__(self) -> "duckdb.DuckDBPyConnection":
        if not os.path.exists(os.path.dirname(self.database_path)):
            raise ValueError(
                f"Directory {os.path.dirname(self.database_path)} does not exist."
            )

        self._conn = duckdb.connect(self.database_path)
        self._install_load_extension(["json", "fts", "vss"])

        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn:
            self._conn.close()


class DuckDBVectorStore:

    def __init__(
            self, llm: AutoLLM, args: AutoCoderArgs, database_name: str = ":memory:", table_name: str = "documents",
            embed_dim: Optional[int] = None, persist_dir: str = "./storage"
    ) -> None:
        self.llm = llm
        self.args = args
        self.database_name = database_name
        self.table_name = table_name
        self.embed_dim = embed_dim
        self.persist_dir = persist_dir
        self.cache_dir = os.path.join(self.persist_dir, '.cache')

        if self.database_name != ":memory:":
            self.database_path = os.path.join(self.cache_dir, self.database_name)

        if self.database_name == ":memory:":
            self._conn = duckdb.connect(self.database_name)
            self._install_load_extension(["json", "fts", "vss"])
            self._initialize()
        else:
            if not os.path.exists(self.database_path):
                if not os.path.exists(self.cache_dir):
                    os.makedirs(self.cache_dir)
                self._initialize()
            self._conn = None

    @classmethod
    def class_name(cls) -> str:
        return "DuckDBVectorStore"

    @property
    def client(self) -> Any:
        """Return client."""
        return self._conn

    def _install_load_extension(self, ext_list):
        for ext in ext_list:
            self._conn.install_extension(ext)
            self._conn.load_extension(ext)

    @staticmethod
    def _apply_pca(embedding, target_dim):
        # 生成固定随机投影矩阵（避免每次调用重新生成）
        np.random.seed(42)  # 固定随机种子保证一致性
        source_dim = len(embedding)
        projection_matrix = np.random.randn(source_dim, target_dim) / np.sqrt(source_dim)

        # 执行投影
        reduced = np.dot(embedding, projection_matrix)
        return reduced

    @staticmethod
    def _generate_dynamic_score(scores: List[float], sigma: int | float = 1):
        """
        高精度要求,减少误召回,mean + 3*std,预计保留约 0.1%
        mean + 2*std, 预计保留约 2.5%
        高召回率要求,避免漏检,mean + 1*std, 预计保留约 16%
        对抗数据偏移,自适应调整,自动根据当次查询结果调整
        """
        scores = np.array(scores)

        # 异常值过滤（剔除前1%高分）
        q99 = np.quantile(scores, 0.99)
        filtered = scores[scores < q99]

        return np.mean(filtered) + sigma * np.std(filtered)

    def _embedding(self, context: str, norm: bool = True, dim: int | None = None) -> List[float]:
        emb_model = self.llm
        emb_model.setup_default_model_name(self.args.emb_model)
        res = emb_model.embedding([context])
        embedding = res.output

        if dim:
            embedding = self._apply_pca(embedding, target_dim=dim)  # 降维后形状 (1024,)

        if norm:
            embedding = embedding / np.linalg.norm(embedding)

        return embedding.tolist()

    def _initialize(self) -> None:
        if self.embed_dim is None:
            _query = f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    _id VARCHAR,
                    file_path VARCHAR,
                    content TEXT,
                    raw_content TEXT,
                    vector FLOAT[],
                    mtime FLOAT
                );
            """
        else:
            _query = f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    _id VARCHAR,
                    file_path VARCHAR,
                    content TEXT,
                    raw_content TEXT,
                    vector FLOAT[],
                    mtime FLOAT
                );
            """

        if self.database_name == ":memory:":
            self._conn.execute(_query)
        elif self.database_path is not None:
            with DuckDBLocalContext(self.database_path) as _conn:
                _conn.execute(_query)

    def truncate_table(self):
        _truncate_query = f"""TRUNCATE TABLE {self.table_name};"""
        if self.database_name == ":memory:":
            self._conn.execute(_truncate_query)
        elif self.database_path is not None:
            with DuckDBLocalContext(self.database_path) as _conn:
                _conn.execute(_truncate_query)

    def query_by_path(self, file_path: str):
        _exists_query = f"""SELECT _id FROM {self.table_name} WHERE file_path = ?"""
        query_params = [
            file_path
        ]
        _final_results = []
        if self.database_name == ":memory:":
            _final_results = self._conn.execute(_exists_query, query_params).fetchall()
        elif self.database_path is not None:
            with DuckDBLocalContext(self.database_path) as _conn:
                _final_results = _conn.execute(_exists_query, query_params).fetchall()
        return _final_results

    def delete_by_ids(self, _ids: List[str]):
        _delete_query = f"""DELETE FROM {self.table_name} WHERE _id IN (?);"""
        query_params = [
            ','.join(_ids)
        ]
        if self.database_name == ":memory:":
            _final_results = self._conn.execute(_delete_query, query_params).fetchall()
        elif self.database_path is not None:
            with DuckDBLocalContext(self.database_path) as _conn:
                _final_results = _conn.execute(_delete_query, query_params).fetchall()
        return _final_results

    def _node_to_table_row(self, context_chunk: Dict[str, str | float], dim: int | None = None) -> Any:
        return (
            context_chunk["_id"],
            context_chunk["file_path"],
            context_chunk["content"],
            context_chunk["raw_content"],
            self._embedding(context_chunk["raw_content"], norm=True, dim=dim),
            context_chunk["mtime"]
        )

    def add_doc(self, context_chunk: Dict[str, str | float], dim: int | None = None):
        """
        {
            "_id": f"{doc.module_name}_{chunk_idx}",
            "file_path": file_info.file_path,
            "content": chunk,
            "raw_content": chunk,
            "vector": chunk,
            "mtime": file_info.modify_time,
        }
        """
        if self.database_name == ":memory:":
            _table = self._conn.table(self.table_name)
            _row = self._node_to_table_row(context_chunk, dim=dim)
            _table.insert(_row)
        elif self.database_path is not None:
            with DuckDBLocalContext(self.database_path) as _conn:
                _table = _conn.table(self.table_name)
                _row = self._node_to_table_row(context_chunk, dim=dim)
                _table.insert(_row)

    def vector_zscore_search(
            self, query, similarity_value: float = 0.7, similarity_top_k: int = 10, query_dim: int | None = None
    ):
        # -- 计算相对相似度排名
        _query = f"""
            SELECT _id, file_path, mtime, normalized_score
            FROM (
                SELECT _id, file_path, mtime, 
                       (score - MIN(score) OVER()) / (MAX(score) OVER() - MIN(score) OVER()) AS normalized_score
                FROM (
                  SELECT *, list_cosine_similarity(vector, ?) AS score
                  FROM {self.table_name}
                )
            )
            WHERE normalized_score IS NOT NULL
            AND normalized_score >= ?
            ORDER BY normalized_score DESC LIMIT ?;
        """
        query_params = [
            self._embedding(query, norm=True, dim=query_dim),
            similarity_value,
            similarity_top_k,
        ]
        _final_results = []
        if self.database_name == ":memory:":
            _final_results = self._conn.execute(_query, query_params).fetchall()
        elif self.database_path is not None:
            with DuckDBLocalContext(self.database_path) as _conn:
                _final_results = _conn.execute(_query, query_params).fetchall()
        print(_final_results)
        return _final_results

    def vector_dynamic_score_search(
            self, query: str, similarity_top_k: int = 10, query_dim: int | None = None
    ):
        _db_query = f"""
            SELECT _id, file_path, mtime, score
            FROM (
                SELECT *, list_cosine_similarity(vector, ?) AS score
                FROM {self.table_name}
            ) sq
            WHERE score IS NOT NULL
            ORDER BY score DESC LIMIT ?;
        """
        query_params = [
            self._embedding(query, norm=True, dim=query_dim),
            similarity_top_k,
        ]

        _final_results = []
        if self.database_name == ":memory:":
            _final_results = self._conn.execute(_db_query, query_params).fetchall()
        elif self.database_path is not None:
            with DuckDBLocalContext(self.database_path) as _conn:
                _final_results = _conn.execute(_db_query, query_params).fetchall()

        _scores = [r[3] for r in _final_results]
        _dynamic_score = self._generate_dynamic_score(_scores)

        return [r for r in _final_results if r[3] >= _dynamic_score]

    def vector_search(
            self, query: str, similarity_value: float = 0.7, similarity_top_k: int = 10, query_dim: int | None = None
    ):
        """
        list_cosine_similarity: 计算两个列表之间的余弦相似度
        list_cosine_distance: 计算两个列表之间的余弦距离
        list_dot_product: 计算两个大小相同的数字列表的点积
        """
        _db_query = f"""
            SELECT _id, file_path, mtime, score
            FROM (
                SELECT *, list_cosine_similarity(vector, ?) AS score
                FROM {self.table_name}
            ) sq
            WHERE score IS NOT NULL
            AND score >= ?
            ORDER BY score DESC LIMIT ?;
        """
        query_params = [
            self._embedding(query, norm=True, dim=query_dim),
            similarity_value,
            similarity_top_k,
        ]

        _final_results = []
        if self.database_name == ":memory:":
            _final_results = self._conn.execute(_db_query, query_params).fetchall()
        elif self.database_path is not None:
            with DuckDBLocalContext(self.database_path) as _conn:
                _final_results = _conn.execute(_db_query, query_params).fetchall()
        return _final_results

    def full_text_search(self, query: str, similarity_top_k: int = 10):
        # https://duckdb.org/docs/extensions/full_text_search
        pass


if __name__ == "__main__":
    # 初始化向量数据库
    import time
    auto_llm = AutoLLM()
    auto_llm.setup_sub_client("emb_model",
                              "",
                              "https://ark.cn-beijing.volces.com/api/v3",
                              "doubao-embedding-text-240715")
    vs = DuckDBVectorStore(
        llm=auto_llm, database_name="nano_storage.db", table_name="rag",
        persist_dir=""
    )

    # 测试写入功能
    # for root, dirs, files in os.walk("", followlinks=True):
    #     for file in files:
    #         file_path = os.path.join(root, file)
    #         with open(file_path, "r", encoding="utf-8") as fp:
    #             content = fp.read()
    #             if len(content) < 4000:
    #                 s = {
    #                     "_id": f"{file_path}",
    #                     "file_path": file_path,
    #                     "content": content,
    #                     "raw_content": content,
    #                     "vector": "",
    #                     "mtime": 0.1,
    #                 }
    #                 vs.add_doc(s)
    #         time.sleep(1)

    # 测试搜索功能
    test_query = "服务器被入侵了该怎么办"
    search_results = vs.vector_search(test_query, similarity_value=0.6, similarity_top_k=200, query_dim=1024)
    print(f"使用默认方式, 搜索 '{test_query}'：")
    print(f"搜索到 {len(set([i[1] for i in search_results]))} 个结果")
    for result in search_results:
        print(f"- {result[1]} (相似度: {result[3]:.4f})")

    # search_results = vs.vector_zscore_search(test_query, similarity_value=0.6, similarity_top_k=200, query_dim=1024)
    # print(f"使用分数重校准(Z-Score标准化)后, 搜索 '{test_query}'：")
    # print(f"搜索到 {len(set([i[1] for i in search_results]))} 个结果")
    # for result in search_results:
    #     print(f"- {result[1]} (相似度: {result[3]:.4f})")
    #
    # search_results = vs.vector_dynamic_score_search(test_query, similarity_top_k=200, query_dim=1024)
    # print(f"使用分数重校准(动态score)后, 搜索 '{test_query}'：")
    # print(f"搜索到 {len(set([i[1] for i in search_results]))} 个结果")
    # for result in search_results:
    #     print(f"- {result[1]} (相似度: {result[3]:.4f})")

    # 诊断数据分布问题
    # test_query = ""
    # search_results = vs.check_vector(test_query)
    # print(f"搜索 '{test_query}' 结果：")
    # for result in search_results:
    #     print(result)

    # 测试查询 query_by_path
    # search_results = vs.query_by_path("")
    # print(search_results)

    # 测试 delete_by_ids
    # search_results = vs.delete_by_ids([""])
    # print(search_results)

    # 测试 truncate_table
    # vs.truncate_table()