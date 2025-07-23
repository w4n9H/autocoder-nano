import os
import uuid
from collections import Counter

import pandas as pd
from pandas import DataFrame

from autocoder_nano.utils.db_context_utils import DuckDBLocalContext
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


class NoteBook:

    def __init__(self, project_root: str, database_name: str = "notes.db", keywords_filter_length: int = 3,
                 keywords_freq_top_n: int = 10):
        self.database_name = database_name

        self.notebook_dir = os.path.join(project_root, ".auto-coder", "notebook")
        os.makedirs(self.notebook_dir, exist_ok=True)

        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)
        # from cutword import NER
        from cutword import Cutter
        self.cutter = Cutter(want_long_word=True)
        # self.ner = NER()

        self.keywords_filter_length = keywords_filter_length
        self.keywords_freq_top_n = keywords_freq_top_n

        if self.database_name == ":memory:":
            raise Exception("AgenticNoteBook 不支持 :memory: 用法,请指定数据库名称")

        self.database_path = os.path.join(self.notebook_dir, self.database_name)

        if not os.path.exists(self.database_path):
            self._initialize()

    @classmethod
    def class_name(cls) -> str:
        return "DuckDBVectorStore"

    def _initialize(self) -> None:
        """
        user_id
        身份标识：唯一确定笔记所有者
        数据隔离：实现用户间的数据隔离
        扩展基础：支持多租户、个性化、分析等功能
        安全边界：定义数据访问权限边界
        context
        情境智能：使笔记具有"记忆"其产生背景的能力
        精准检索：大幅提高搜索结果的相关性
        矛盾解决：帮助理解表面矛盾背后的情境差异
        行为预测：基于历史上下文预测用户需求
        个性适配：根据上下文调整Agent的响应风格
        """
        _query = """
        -- 主笔记表
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY DEFAULT nextval('note_id_seq'),
            user_id VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            content TEXT NOT NULL,
            context TEXT,          -- 简化的上下文信息
            is_conflicted BOOLEAN DEFAULT FALSE
        );
        -- 关键词索引表
        CREATE TABLE IF NOT EXISTS keywords (
            keyword VARCHAR NOT NULL,
            note_id BIGINT NOT NULL,
            PRIMARY KEY (keyword, note_id)
        );
        -- 实体表 (简化的实体存储)
        CREATE TABLE IF NOT EXISTS entities (
            note_id BIGINT NOT NULL,
            entity_type VARCHAR NOT NULL,
            entity_value VARCHAR NOT NULL,
            PRIMARY KEY (note_id, entity_type, entity_value)
        );
        -- 新增：全文检索表
        CREATE TABLE IF NOT EXISTS full_text (
            document_identifier VARCHAR,
            tokenized_content TEXT,
            note_id INTEGER NOT NULL
        );
        """
        with DuckDBLocalContext(self.database_path) as _conn:
            _conn.execute("CREATE SEQUENCE IF NOT EXISTS note_id_seq;")
            _conn.execute(_query)
            # 创建索引加速搜索
            _conn.execute("CREATE INDEX idx_keywords ON keywords(keyword)")
            _conn.execute("CREATE INDEX idx_entities ON entities(entity_value)")

    def _extract_tokens(self, text) -> list[str]:
        """ 分词 """
        return self.cutter.cutword(text)

    def _calculate_tf(self, keywords: list[str]) -> Counter:
        """ 计算词频(TF) """
        return Counter(filter(lambda x: len(x) >= self.keywords_filter_length, keywords))

    def _filter_keywords(self, keyword_freq: Counter) -> list[str]:
        """ 分词 """
        return [kw for kw, _ in keyword_freq.most_common(self.keywords_freq_top_n)]

    # def _extract_entities(self, text):
    #     doc = self.ner.predict(text, return_words=False)
    #     entities = [(ent.entity, ent.ner_type_zh) for ent in doc[0] if doc[0]]
    #     return entities

    def extract_features(self, text: str):
        """提取关键词和实体"""
        # 去长度>3的词组统计词频,并取前5的词组作为keywords
        keywords = self._extract_tokens(text)
        keyword_freq = self._calculate_tf(keywords)
        top_keywords: list[str] = self._filter_keywords(keyword_freq)

        # 提取实体,关键词
        return {
            "keywords": " ".join(keywords),
            # "entities": self._extract_entities(text),
            "top_keywords": top_keywords,
            "tf_keywords": keyword_freq
        }

    def add_note(self, user_id, text, context=None) -> int:
        # 提取文本特征
        features = self.extract_features(text)

        _insert_query = """
        INSERT INTO notes (user_id, content, context) VALUES (?, ?, ?) RETURNING id
        """
        query_params = [user_id, text, context]
        with DuckDBLocalContext(self.database_path) as _conn:
            _note_id = _conn.execute(_insert_query, query_params).fetchone()[0]

        # 索引关键词
        self._index_keywords(_note_id, features["top_keywords"])
        # 全文索引
        self._index_full_text(_note_id, features["keywords"])
        # 索引实体
        # self._index_entities(_note_id, features["entities"])
        # 重建全文索引
        self._rebuild_full_text_index()

        return _note_id

    def _rebuild_full_text_index(self):
        with DuckDBLocalContext(self.database_path) as _conn:
            try:
                _conn.execute("PRAGMA drop_fts_index('full_text');")
            except:
                pass
            finally:
                _conn.execute("PRAGMA create_fts_index('full_text', 'document_identifier', 'tokenized_content');")

    def _index_full_text(self, note_id, keywords: str):
        """ 全文索引 """
        with DuckDBLocalContext(self.database_path) as _conn:
            _insert_query = """INSERT INTO full_text (document_identifier, tokenized_content, note_id) 
            VALUES (?, ?, ?)"""
            query_params = [str(uuid.uuid4()), keywords, note_id]
            _conn.execute(_insert_query, query_params).fetchall()

    def _index_keywords(self, note_id, keywords):
        """ 索引 keywords """
        with DuckDBLocalContext(self.database_path) as _conn:
            for keyword in keywords:
                _insert_query = """INSERT OR IGNORE INTO keywords (keyword, note_id) VALUES (?, ?)"""
                query_params = [keyword, note_id]
                _conn.execute(_insert_query, query_params).fetchall()

    def _index_entities(self, note_id, entities):
        """ 索引实体 """
        with DuckDBLocalContext(self.database_path) as _conn:
            for ent in entities:
                _insert_query = """INSERT OR IGNORE INTO entities (note_id, entity_type, entity_value) 
                VALUES (?, ?, ?)"""
                query_params = [note_id, ent[1], ent[0]]
                _conn.execute(_insert_query, query_params).fetchall()

    def _keyword_search(self, user_id, query, limit):
        """ 关键词搜索 """
        query_words = self._extract_tokens(query)
        _query_sql = f"""
        SELECT n.id, n.content, n.created_at
        FROM notes n
        JOIN keywords k ON n.id = k.note_id
        WHERE n.user_id = ? 
          AND k.keyword IN ({','.join(['?']*len(query_words))})
        GROUP BY n.id, n.content, n.created_at
        ORDER BY COUNT(k.keyword) DESC
        LIMIT ?
        """
        query_params = [user_id, *query_words, limit]
        with DuckDBLocalContext(self.database_path) as _conn:
            return _conn.execute(_query_sql, query_params).fetchdf()

    # def _entity_search(self, user_id, query, limit):
    #     """ 实体搜索 """
    #     query_entities = [i[0] for i in self._extract_entities(query)]
    #     if query_entities:
    #         query_entities_join = f"{','.join(['?']*len(query_entities))}"
    #     else:
    #         query_entities_join = ""
    #     print(query_entities_join)
    #     _query_sql = f"""
    #     SELECT n.id, n.content, n.created_at
    #     FROM notes n
    #     JOIN entities e ON n.id = e.note_id
    #     WHERE n.user_id = ?
    #       AND e.entity_value IN (?)
    #     GROUP BY n.id, n.content, n.created_at
    #     ORDER BY COUNT(e.entity_value) DESC
    #     LIMIT ?
    #     """
    #     query_params = [user_id, query_entities_join, limit]
    #     with DuckDBLocalContext(self.database_path) as _conn:
    #         return _conn.execute(_query_sql, query_params).fetchdf()

    def _fulltext_search(self, user_id, query, limit):
        """ 全文搜索 """
        query_words = self._extract_tokens(query)
        query_words_join = " ".join(query_words)
        _query_sql = """
        SELECT n.id, n.content, n.created_at
        FROM notes n
        JOIN (
            SELECT note_id, score
            FROM (
                SELECT *, fts_main_full_text.match_bm25(
                    document_identifier, ?
                ) AS score
                FROM full_text
            ) sq
            WHERE score IS NOT NULL
            ORDER BY score DESC
        ) f ON n.id = f.note_id
        WHERE n.user_id = ?
        GROUP BY n.id, n.content, n.created_at
        LIMIT ?
        """
        query_params = [query_words_join, user_id, limit]
        with DuckDBLocalContext(self.database_path) as _conn:
            return _conn.execute(_query_sql, query_params).fetchdf()

    def search_by_query(self, user_id, query, limit=5) -> DataFrame:
        """ 统一搜索接口 """
        fs_df = self._keyword_search(user_id, query, limit)
        # es_df = self._entity_search(user_id, query, limit)
        fts_df = self._fulltext_search(user_id, query, limit)
        combined = pd.concat([fs_df, fts_df], axis=0, ignore_index=True)
        result = combined.drop_duplicates()
        printer.print_key_value(
            items={
                "关键词检索": f"{len(fs_df)} 条",
                # "实体检索": f"{len(es_df)} 条",
                "全文检索": f"{len(fts_df)} 条",
                "整体去重后数据条数": f"{len(result)} 条",
            },
            title="Notebook 检索结果"
        )
        return result


if __name__ == '__main__':
    source_dir = "/Users/moofs/Code/autocoder-nano"
    note = NoteBook(source_dir)
    # note.add_note(
    #     user_id="agentic",
    #     text="AutoCoder Nano 是一款轻量级的编码助手, 利用大型语言模型（LLMs）帮助开发者编写, 理解和修改代码",
    #     context="编码助手"
    # )
    # note.add_note(
    #     user_id="agentic",
    #     text="它提供了一个交互式命令行界面，支持在软件开发场景中与LLMs互动，具备代码生成, 文件管理和上下文代码理解等功能。",
    #     context="编码助手"
    # )
    # note.add_note(
    #     user_id="agentic",
    #     text="AutoCoder Nano 是 Auto-Coder 生态系统的简化版本，设计轻量且依赖极少。它旨在通过提供增强AI功能的命令行界面，弥合自然语言指令与代码修改之间的鸿沟。",
    #     context="编码助手"
    # )
    # note.add_note(
    #     user_id="agentic",
    #     text="我在2025年5月20日新增了rag功能",
    #     context="编码助手"
    # )

    # print(note.search_by_query("agentic", "AutoCoder Nano 是什么", search_type="KEYWORD"))
    # print(note.search_by_query("agentic", "我2025年5月20日更新了什么", search_type="ENTITY"))
    print(note.search_by_query("agentic", "AutoCoder Nano 是什么", search_type="FULLTEXT"))
