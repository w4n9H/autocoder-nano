import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from autocoder_nano.acmodels import BUILTIN_MODELS
from autocoder_nano.rag.token_counter import count_tokens
from autocoder_nano.utils.printer_utils import (
    Printer, COLOR_ERROR, COLOR_SUCCESS, COLOR_WARNING, COLOR_INFO, COLOR_SYSTEM)

printer = Printer()

# Token 缓冲常量,  有效窗口 = 模型上下文窗口大小 - 预留一次最大output输出的大小(16k)
WARNING_THRESHOLD_BUFFER_TOKENS = 30_000  # 警告阈值 = 有效窗口 - 30k
ERROR_THRESHOLD_BUFFER_TOKENS = 20_000  # 错误阈值 = 有效窗口 - 20k
AUTOCOMPACT_BUFFER_TOKENS = 10_000  # 自动压缩阈值 = 有效窗口 - 10k
MANUAL_COMPACT_BUFFER_TOKENS = 3_000  # 阻塞极限 = 有效窗口 - 3k
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3

# 错误消息常量
ERROR_MESSAGE_NOT_ENOUGH_MESSAGES = "消息数量不足, 无法进行压缩."
ERROR_MESSAGE_PROMPT_TOO_LONG = "对话过长. 按两次 Esc 键返回几条消息, 然后重试."
ERROR_MESSAGE_USER_ABORT = "API 错误: 请求已被中止"
ERROR_MESSAGE_INCOMPLETE_RESPONSE = "压缩中断 · 这可能是由于网络问题导致的——请重试. "


@dataclass
class TokenWarningState:
    """
    Token 警告状态计算结果
    """
    percent_left: int  # 剩余可用百分比
    is_above_warning_threshold: bool  # 警告阈值; 当剩余 Token 空间少于 WARNING_THRESHOLD_BUFFER_TOKENS
    is_above_error_threshold: bool  # 错误阈值; 当剩余 Token 空间少于 ERROR_THRESHOLD_BUFFER_TOKENS
    is_above_auto_compact_threshold: bool  # 自动压缩阈值; 当 自动压缩功能已启用 且当前 Token 使用量 大于等于 自动压缩阈值时
    is_at_blocking_limit: bool  # 当 Token 使用量达到“阻塞极限”时，禁止继续发送新请求，强制用户先手动压缩或清理上下文。


@dataclass
class AutoCompactTrackingState:
    """自动压缩跟踪状态"""
    compacted: bool = False
    turn_counter: int = 0
    turn_id: str = ""
    consecutive_failures: Optional[int] = None


@dataclass
class RecompactionInfo:
    """再压缩诊断信息"""
    is_recompaction_in_chain: bool
    turns_since_previous_compact: int
    previous_compact_turn_id: Optional[str] = None
    auto_compact_threshold: int = -1


@dataclass
class MicrocompactResult:
    """微压缩结果"""
    messages: List[Any]
    compaction_info: Optional[Dict[str, Any]] = None


def _get_context_window_for_model(model: str) -> int:
    """ 获取模型上下文窗口大小（适配层，实际应从模型配置获取）"""
    return BUILTIN_MODELS.get(model, {}).get('context', 128_000)


def _get_max_output_tokens_for_model(model: str) -> int:
    """ 获取模型最大输出 token 数 """
    return BUILTIN_MODELS.get(model, {}).get('output', 16_000)


def _token_count_with_estimation(messages: List[Any]) -> int:
    """ 估算消息 token 数（适配层）"""
    total = count_tokens(json.dumps(messages, ensure_ascii=False))
    return max(total, 100)  # 最小 100 tokens


def _is_auto_compact_enabled() -> bool:
    """ 检查是否启用自动压缩, 默认自动启动 """
    if os.environ.get("DISABLE_COMPACT"):
        return False
    if os.environ.get("DISABLE_AUTO_COMPACT"):
        return False
    # TODO: 从用户配置读取 autoCompactEnabled
    return True


def get_effective_context_window_size(model: str) -> int:
    """
    返回上下文窗口大小减去模型的预留输出 token。

    预留输出 token 基于 p99.99 压缩摘要输出为 17,387 tokens，
    上限设为 20,000。
    """
    reserved_tokens = min(_get_max_output_tokens_for_model(model), MAX_OUTPUT_TOKENS_FOR_SUMMARY)  # 最小 20k
    context_window = _get_context_window_for_model(model)

    return context_window - reserved_tokens


def get_auto_compact_threshold(model: str) -> int:
    """ 获取自动压缩阈值 = 有效窗口 - 缓冲区 """
    effective_context_window = get_effective_context_window_size(model)  # 有效窗口
    threshold = effective_context_window - AUTOCOMPACT_BUFFER_TOKENS

    # 支持百分比覆盖
    env_percent = os.environ.get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")
    if env_percent:
        parsed = float(env_percent)
        if 0 < parsed <= 100:
            pct_threshold = int(effective_context_window * (parsed / 100))
            return min(pct_threshold, threshold)

    return threshold


def calculate_token_warning_state(token_usage: int, model: str) -> TokenWarningState:
    """计算当前 token 用量的警告状态（四级阈值）"""
    auto_compact_threshold = get_auto_compact_threshold(model)

    threshold = (auto_compact_threshold if _is_auto_compact_enabled() else get_effective_context_window_size(model))
    percent_left = max(
        0, round(((threshold - token_usage) / threshold) * 100)
    ) if threshold > 0 else 0

    warning_threshold = threshold - WARNING_THRESHOLD_BUFFER_TOKENS
    error_threshold = threshold - ERROR_THRESHOLD_BUFFER_TOKENS
    actual_context_window = get_effective_context_window_size(model)
    blocking_limit = actual_context_window - MANUAL_COMPACT_BUFFER_TOKENS

    return TokenWarningState(
        percent_left=percent_left,
        is_above_warning_threshold=(token_usage >= warning_threshold),
        is_above_error_threshold=(token_usage >= error_threshold),
        is_above_auto_compact_threshold=(_is_auto_compact_enabled() and token_usage >= auto_compact_threshold),
        is_at_blocking_limit=(token_usage >= blocking_limit),
    )


def should_auto_compact(messages: List[Any], model: str) -> bool:
    """
    判断是否应该执行自动压缩。
    包含递归守卫（session_memory/compact/marble_origami 不触发），特性门控，token 阈值判断
    """
    if not _is_auto_compact_enabled():
        return False

    token_count = _token_count_with_estimation(messages)
    threshold = get_auto_compact_threshold(model)
    effective_window = get_effective_context_window_size(model)

    printer.print_text(
        f"自动压缩: token数={token_count} 阈值={threshold} 有效窗口={effective_window}", style=COLOR_INFO
    )

    state = calculate_token_warning_state(token_count, model)
    return state.is_above_auto_compact_threshold


#  micro compact


def microcompact_messages(messages: List[Dict]) -> MicrocompactResult:
    """
    微压缩入口。

    优先级：
    1. 时间触发微压缩（缓存已过期）
    2. 缓存编辑微压缩（API 层删除）
    3. 无操作返回原消息
    """


def auto_compact_if_needed(
        messages: List[Any], model: str, tracking: Optional[AutoCompactTrackingState] = None) -> Dict[str, Any]:
    """
    自动压缩主入口。

    流程：
    1. 断路器检查（连续失败超过上限则跳过）
    2. 判断是否需要压缩
    3. 尝试 session memory compaction（实验性）
    4. 降级到传统 compactConversation
    5. 处理成功/失败并跟踪连续失败数
    """
    # 断路器检查
    if (
            tracking is not None
            and tracking.consecutive_failures is not None
            and tracking.consecutive_failures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES
    ):
        return {"was_compacted": False}

    should_compact = should_auto_compact(messages, model)
    if not should_compact:
        return {"was_compacted": False}

    recompaction_info = RecompactionInfo(
        is_recompaction_in_chain=tracking.compacted if tracking else False,
        turns_since_previous_compact=(
            tracking.turn_counter if tracking else -1
        ),
        previous_compact_turn_id=getattr(tracking, "turn_id", None),
        auto_compact_threshold=get_auto_compact_threshold(model)
    )

    # 传统压缩路径
    try:
        compaction_result = {}
        return {
            "was_compacted": True,
            "compaction_result": compaction_result,
            "consecutive_failures": 0,
        }
    except Exception as error:
        error_msg = str(error)
        if ERROR_MESSAGE_USER_ABORT not in error_msg:
            printer.print_text(f"Auto compact 失败: {error_msg}", style=COLOR_ERROR)

        prev_failures = (tracking.consecutive_failures or 0) if tracking else 0
        next_failures = prev_failures + 1

        if next_failures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES:
            printer.print_text(
                f"自动压缩: 断路器在连续 {next_failures} 次失败后触发 — 本次会话中将跳过后续的压缩尝试",
                style=COLOR_WARNING
            )

        return {
            "was_compacted": False,
            "consecutive_failures": next_failures,
        }
