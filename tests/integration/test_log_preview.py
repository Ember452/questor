"""P10 TB3（集成 canary）—— 真 IO 证明 preview **只进独立 llm 通道、绝不进主干**，且过脱敏。

C20 不越界款三闸的可执行判据（承 pitfalls#1/#4 真文件 canary 纪律，不测 LogEntry 构造）：
- 开 ``llm_file`` + preview：``questor.llm.preview`` 行落 ``llm-<date>.jsonl``；
- 主干 ``questor-<date>.jsonl`` **不含** preview 载荷（含凭据 shape 也被脱敏）；
- 关 preview（默认）：llm 通道根本不写。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from questor.observability import configure as log_configure
from questor.observability import exporter as log_exporter
from questor.observability import pipeline as log_pipeline
from questor.observability.entry import LogLevel

_CANARY = "SUPERSECRETPROMPTBODY"


@pytest.fixture
def clean_logging() -> Iterator[None]:
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_registry = list(log_exporter._registry)  # noqa: SLF001
    saved_state = log_configure._state  # noqa: SLF001
    log_pipeline.reset()
    log_configure._state = None
    try:
        yield
    finally:
        log_configure._teardown()  # noqa: SLF001
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        log_exporter._registry[:] = saved_registry  # noqa: SLF001
        log_configure._state = saved_state  # noqa: SLF001
        log_pipeline.reset()


def _rows(log_dir: Path, prefix: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(log_dir.glob(f"{prefix}-*.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def _emit_preview() -> None:
    logger = logging.getLogger("questor.llm.preview")
    logger.debug(
        "llm preview ok",
        extra={"log_fields": {"arguments_preview": f"{_CANARY} sk-LEAKKEYVALUE", "response_preview": "resp", "truncated": True}},
    )
    log_pipeline.flush()


def test_preview_lands_only_in_llm_lane_trunk_clean_and_redacted(clean_logging: None, tmp_path: Path) -> None:
    logging.getLogger("questor").setLevel(logging.DEBUG)  # 让 preview DEBUG 进桥
    log_configure.configure_logging(console_level=LogLevel.CRITICAL, file_level=LogLevel.DEBUG, log_dir=tmp_path, llm_file=True)
    _emit_preview()

    trunk = _rows(tmp_path, "questor")
    llm = _rows(tmp_path, "llm")
    # 主干绝不带 preview 载荷（sink_file 排除 questor.llm.preview logger）
    trunk_text = json.dumps(trunk, ensure_ascii=False)
    assert _CANARY not in trunk_text
    assert not any(r.get("logger") == "questor.llm.preview" for r in trunk)
    # llm 通道承载 preview，且凭据 shape 被脱敏（sk-... 原文不得出现）
    llm_preview = [r for r in llm if r.get("logger") == "questor.llm.preview"]
    assert llm_preview, "preview 应落独立 llm 通道"
    llm_text = json.dumps(llm_preview, ensure_ascii=False)
    assert _CANARY in llm_text  # preview 本体确实在 llm 通道
    assert "sk-LEAKKEYVALUE" not in llm_text  # 凭据被 redact 掉（fail-closed 脱敏）


def test_preview_off_default_writes_no_llm_lane(clean_logging: None, tmp_path: Path) -> None:
    logging.getLogger("questor").setLevel(logging.DEBUG)
    log_configure.configure_logging(console_level=LogLevel.CRITICAL, file_level=LogLevel.DEBUG, log_dir=tmp_path, llm_file=False)
    _emit_preview()
    llm = _rows(tmp_path, "llm")
    assert not llm  # 未授权（llm_file=False）→ preview 不落任何文件（含主干）
    trunk = _rows(tmp_path, "questor")
    assert not any(r.get("logger") == "questor.llm.preview" for r in trunk)
