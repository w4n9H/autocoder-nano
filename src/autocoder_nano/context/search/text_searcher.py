"""
Text search functionality for conversations and messages.

This module provides comprehensive text search capabilities including
full-text search, keyword matching, and relevance-based ranking.
"""

import re
import math
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import Counter, defaultdict

from autocoder_nano.rag.token_counter import cut_tokens


class TextSearcher:
    """用于对话和消息的文本搜索器，带有相关性排序功能。"""

    def __init__(self, case_sensitive: bool = False, stemming: bool = False):
        """
        初始化文本搜索器。

        Args:
            case_sensitive: 搜索是否区分大小写
            stemming: 是否应用基本（简化）的词干提取
        """
        self.case_sensitive = case_sensitive
        self.stemming = stemming

        # 用于过滤的常见中英文停用词
        self.stop_words = {
            'a', 'an', 'and', 'are', 'as', 'at', 'be', 'been', 'by', 'for',
            'from', 'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that',
            'the', 'to', 'was', 'will', 'with', 'would', 'could', 'should',
            'have', 'had', 'has', 'do', 'does', 'did', 'can', 'may', 'might'
        }

    def _normalize_text(self, text: str) -> str:
        """规范化文本以用于搜索."""
        if not self.case_sensitive:
            text = text.lower()
        return text

    def _tokenize(self, text: str) -> List[str]:
        """将文本分词为单词."""
        # 简单分词 - 根据单词边界分割
        # tokens = re.findall(r'\b\w+\b', text)
        tokens = cut_tokens(text)

        # 规范化词元（token）
        tokens = [self._normalize_text(token) for token in tokens]

        # 如果不区分大小写，则移除停用词
        if not self.case_sensitive:
            tokens = [token for token in tokens if token not in self.stop_words]

        # 如果启用，应用基本词干提取
        if self.stemming:
            tokens = [self._basic_stem(token) for token in tokens]

        return tokens

    @staticmethod
    def _basic_stem(word: str) -> str:
        """应用非常基础的词干提取规则."""
        # 简单的英文词干提取规则
        if len(word) <= 3:
            return word

        # 移除常见后缀
        suffixes = ['ing', 'ed', 'er', 'est', 'ly', 's']
        for suffix in suffixes:
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                return word[:-len(suffix)]

        return word

    def _calculate_tf_idf(self, query_terms: List[str], documents: List[Dict[str, Any]]) -> Dict[int, Dict[str, float]]:
        """计算文档的 TF-IDF 分数."""
        # 统计包含每个词的文档数量
        doc_count = defaultdict(int)
        doc_terms = {}

        for i, doc in enumerate(documents):
            # 从文档中组合可搜索文本
            searchable_text = self._get_searchable_text(doc)
            terms = self._tokenize(searchable_text)
            doc_terms[i] = Counter(terms)

            # 统计此文档中的唯一词
            unique_terms = set(terms)
            for term in unique_terms:
                doc_count[term] += 1

        # 计算 TF-IDF 分数
        total_docs = len(documents)
        tf_idf_scores = {}

        for i, doc in enumerate(documents):
            tf_idf_scores[i] = {}
            doc_term_counts = doc_terms[i]
            doc_length = sum(doc_term_counts.values())

            for term in query_terms:
                if term in doc_term_counts and doc_length > 0:
                    # 词频 (Term Frequency)
                    tf = doc_term_counts[term] / doc_length

                    # 逆文档频率 (Inverse Document Frequency)
                    idf = math.log(total_docs / max(1, doc_count[term]))

                    # TF-IDF 分数
                    tf_idf_scores[i][term] = tf * idf
                else:
                    tf_idf_scores[i][term] = 0.0

        return tf_idf_scores

    def _get_searchable_text(self, item: Dict[str, Any]) -> str:
        """从对话或消息中提取可搜索文本."""
        if isinstance(item, dict):
            # 处理不同的item类型
            text_parts = []

            # 为对话添加名称和描述
            if 'name' in item:
                text_parts.append(item['name'])
            if 'description' in item:
                text_parts.append(item.get('description', ''))

            # 为消息添加内容
            if 'content' in item:
                content = item['content']
                if isinstance(content, str):
                    text_parts.append(content)
                elif isinstance(content, dict):
                    # 从字典内容中提取文本
                    for value in content.values():
                        if isinstance(value, str):
                            text_parts.append(value)
                elif isinstance(content, list):
                    # 从列表内容中提取文本
                    for value in content:
                        if isinstance(value, str):
                            text_parts.append(value)
                        elif isinstance(value, dict):
                            for nested_value in value.values():
                                if isinstance(nested_value, str):
                                    text_parts.append(nested_value)

            # 为对话添加消息内容
            if 'messages' in item:
                for message in item.get('messages', []):
                    text_parts.append(self._get_searchable_text(message))

            return ' '.join(filter(None, text_parts))

        return str(item)

    def search_conversations(
            self,
            query: str,
            conversations: List[Dict[str, Any]],
            max_results: Optional[int] = None,
            min_score: float = 0.0
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        使用相关性评分搜索对话。

        Args:
            query: 搜索查询字符串
            conversations: 对话字典列表
            max_results: 要返回的最大结果数量
            min_score: 最小相关性分数阈值

        Returns:
            按相关性排序的 (对话, 分数) 元组列表
        """
        if not query.strip() or not conversations:
            return [(conv, 0.0) for conv in conversations[:max_results]]

        # 对查询进行分词
        query_terms = self._tokenize(query)
        if not query_terms:
            return [(conv, 0.0) for conv in conversations[:max_results]]

        # 计算 TF-IDF 分数
        tf_idf_scores = self._calculate_tf_idf(query_terms, conversations)

        # 计算相关性分数
        results = []
        for i, conversation in enumerate(conversations):
            # 对所有查询词求和 TF-IDF 分数
            total_score = sum(tf_idf_scores[i].values())

            # 为完全短语匹配应用提升
            searchable_text = self._get_searchable_text(conversation)
            normalized_text = self._normalize_text(searchable_text)
            normalized_query = self._normalize_text(query)

            if normalized_query in normalized_text:
                total_score *= 1.5  # 为完全短语匹配提升

            # 为标题匹配应用提升
            if 'name' in conversation:
                title_text = self._normalize_text(conversation['name'])
                if any(term in title_text for term in query_terms):
                    total_score *= 1.2  # 为标题匹配提升

            if total_score >= min_score:
                results.append((conversation, total_score))

        # 按相关性分数排序（降序）
        results.sort(key=lambda x: x[1], reverse=True)

        # 应用结果数量限制
        if max_results:
            results = results[:max_results]

        return results

    def search_messages(
            self,
            query: str,
            messages: List[Dict[str, Any]],
            max_results: Optional[int] = None,
            min_score: float = 0.0,
            by_sort: bool = False
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        使用相关性评分搜索消息。

        Args:
            query: 搜索查询字符串
            messages: 消息字典列表
            max_results: 要返回的最大结果数量
            min_score: 最小相关性分数阈值
            by_sort: 是否排序

        Returns:
            按相关性排序的 (消息, 分数) 元组列表
        """
        if not query.strip() or not messages:
            return [(msg, 0.0) for msg in messages[:max_results]]

        # 对查询进行分词
        query_terms = self._tokenize(query)
        if not query_terms:
            return [(msg, 0.0) for msg in messages[:max_results]]

        # 计算 TF-IDF 分数
        tf_idf_scores = self._calculate_tf_idf(query_terms, messages)

        # 计算相关性分数
        results = []
        for i, message in enumerate(messages):
            # 对所有查询词求和 TF-IDF 分数
            total_score = sum(tf_idf_scores[i].values())

            # 为完全短语匹配应用提升
            searchable_text = self._get_searchable_text(message)
            normalized_text = self._normalize_text(searchable_text)
            normalized_query = self._normalize_text(query)

            if normalized_query in normalized_text:
                total_score *= 1.5  # Boost for exact phrase match

            # Apply boost for recent messages (if timestamp available)
            if 'timestamp' in message:
                # Simple recency boost - more recent messages get slight boost
                import time
                current_time = time.time()
                message_time = message['timestamp']
                age_hours = (current_time - message_time) / 3600

                # Boost decreases with age, but not too dramatically
                recency_boost = max(1.0, 1.1 - (age_hours / (24 * 30)))  # Diminishes over a month
                total_score *= recency_boost

            if total_score >= min_score:
                results.append((message, total_score))

        # Sort by relevance score (descending)
        if by_sort:
            results.sort(key=lambda x: x[1], reverse=True)

        # Apply result limit
        if max_results:
            results = results[:max_results]

        return results

    def highlight_matches(
            self,
            text: str,
            query: str,
            highlight_format: str = "**{}**"
    ) -> str:
        """
        在文本中高亮显示查询匹配项。

        Args:
            text: 需要高亮匹配项的文本
            query: 搜索查询
            highlight_format: 高亮显示的格式字符串（例如，使用 "**{}**" 表示加粗）

        Returns:
            带有高亮匹配项的文本
        """
        if not query.strip():
            return text

        query_terms = self._tokenize(query)
        if not query_terms:
            return text

        # Create regex pattern for all query terms
        escaped_terms = [re.escape(term) for term in query_terms]
        pattern = r'\b(' + '|'.join(escaped_terms) + r')\b'

        # Apply highlighting
        flags = 0 if self.case_sensitive else re.IGNORECASE

        def highlight_replacer(match):
            return highlight_format.format(match.group(1))

        return re.sub(pattern, highlight_replacer, text, flags=flags)

    def get_search_suggestions(
            self,
            partial_query: str,
            conversations: List[Dict[str, Any]],
            max_suggestions: int = 5
    ) -> List[str]:
        """
        基于部分查询获取搜索建议。

        Args:
            partial_query: 部分搜索查询
            conversations: 要分析的对话列表
            max_suggestions: 最大建议数量

        Returns:
            建议的搜索词列表
        """
        if len(partial_query) < 2:
            return []

        # Extract all terms from conversations
        all_terms = set()
        for conversation in conversations:
            searchable_text = self._get_searchable_text(conversation)
            terms = self._tokenize(searchable_text)
            all_terms.update(terms)

        # Find matching terms
        partial_lower = partial_query.lower()
        suggestions = []

        for term in all_terms:
            if term.lower().startswith(partial_lower) and term.lower() != partial_lower:
                suggestions.append(term)

        # Sort by length (shorter terms first) and alphabetically
        suggestions.sort(key=lambda x: (len(x), x))

        return suggestions[:max_suggestions]