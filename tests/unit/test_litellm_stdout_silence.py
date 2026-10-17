"""Issue #127 判据：litellm 自带的 stdout 型 handler 必须在 provider 装配时被摘掉。

真实机制（复审时纠正过一次误判，记在 ``docs/pitfalls.md`` 第 4 条 / ADR-0027）：litellm 的 ``_logging`` 用的是它自己的
``LevelRoutingStreamHandler``——**stdlib Handler，不是 loguru**——按级别分流，INFO/DEBUG 写
``sys.stdout``、WARNING+ 写 ``sys.stderr``。observability 的降噪名单与级别门只能决定"要不要生成记录"，
管不住第三方库自己往哪个流写；而 ``--list`` 的 stdout 是机器可读输出。
"""

from __future__ import annotations

import logging
import sys

import pytest

from questor.providers import litellm_adapter


def test_litellm_debug_info_suppressed() -> None:
    """装配 provider 模块后必须关掉 litellm 的请求/响应调试转储。"""
    assert litellm_adapter.litellm.suppress_debug_info is True


def test_no_stdout_bound_handler_left_on_litellm_loggers() -> None:
    """litellm 的三个包级 logger 上不得再留有写 stdout 的 handler。

    判红样例：把 ``_tame_litellm_logging`` 的 ``removeHandler`` 去掉，本用例即红——
    它会重新列出那个 ``LevelRoutingStreamHandler``。
    """
    remaining = litellm_adapter.litellm_stdout_handlers()
    assert remaining == [], f"litellm 仍挂着写 stdout 的 handler：{[(n, type(h).__name__) for n, h in remaining]}"


def test_litellm_record_does_not_reach_stdout(capfd: pytest.CapFood) -> None:
    """经 litellm 自己的 logger 打一条 INFO：stdout 必须干净（可见性走我们的桥/stderr）。

    不 skip、不 mock：直接经 litellm 用的那个 logger 名打真记录。写向 stdout 的 handler 已被摘掉，
    所以 stdout 必须干净（可见性由我们 root 上的桥接管）。
    """
    handlers = litellm_adapter.litellm_stdout_handlers()
    assert handlers == []  # 前置：确认没有残留的 stdout handler 会绕过本判据

    logger = logging.getLogger("LiteLLM")
    saved = logger.level
    logger.setLevel(logging.INFO)  # 不靠降噪名单凑绿：让记录肯定生成
    try:
        logger.info("probe-%s", "litellm-must-not-hit-stdout")
        cap = capfd.readouterr()
    finally:
        logger.setLevel(saved)  # 全局 logger 级别必须还原，不泄给后续用例
    assert "litellm-must-not-hit-stdout" not in cap.out, "litellm 的记录落到了 stdout（污染机器可读输出）"


def test_writes_to_stdout_helper_recognizes_stdout_streams() -> None:
    """``_writes_to_stdout`` 要认得“绑到 stdout 的流”，也不能误报绑 stderr 的常规 handler。"""
    assert litellm_adapter._writes_to_stdout(logging.StreamHandler(sys.stdout)) is True
    assert litellm_adapter._writes_to_stdout(logging.StreamHandler(sys.stderr)) is False
