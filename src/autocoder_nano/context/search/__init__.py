"""
Search and filtering module for conversations.

This module provides text search and filtering capabilities for conversations
and messages, supporting full-text search, keyword matching, and complex
filtering operations.
"""

from autocoder_nano.context.search.text_searcher import TextSearcher
from autocoder_nano.context.search.filter_manager import FilterManager

__all__ = [
    'TextSearcher',
    'FilterManager'
]