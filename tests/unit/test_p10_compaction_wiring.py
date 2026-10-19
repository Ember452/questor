"""P10 Major-1（TDD）—— 生产组合根注入可恢复压缩（`QUESTOR_COMPACTION` → `CliSurface` → `_loop`）。

审计 Major-1 指出：压缩机制真实但生产 `DefaultTurnLoop(...)` 从不注入 `compaction`、`src/` 无
`CompactionConfig(` 构造 → shipped 产品恒不压缩。本测试钉住补齐后的生产接线与解析口径。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.contracts.policy import CompactionConfig
from questor.surfaces._assembly import compaction_from_env
from questor.surfaces.cli import CliSurface


@pytest.mark.parametrize("value", [None, "", "off", "OFF"])
def test_default_off(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("QUESTOR_COMPACTION", raising=False)
    else:
        monkeypatch.setenv("QUESTOR_COMPACTION", value)
    assert compaction_from_env() is None  # 默认不压缩：向后兼容、不动既有 800 行为


def test_on_uses_context_size_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUESTOR_COMPACTION", "on")
    cfg = compaction_from_env()
    assert isinstance(cfg, CompactionConfig)
    assert cfg.max_items is not None  # 触发信号=context 条数（体量），非累计花费
    assert cfg.trigger_tokens is None  # 明确不用累计 token 作生产触发


def test_items_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUESTOR_COMPACTION", "items:8")
    cfg = compaction_from_env()
    assert cfg is not None and cfg.max_items == 8


@pytest.mark.parametrize("value", ["bogus", "items:0", "items:abc", "true"])
def test_invalid_rejects_startup(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("QUESTOR_COMPACTION", value)
    with pytest.raises(SystemExit):
        compaction_from_env()


def test_clisurface_forwards_compaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 显式注入：CliSurface.compaction 即该配置（_loop 会透传给 DefaultTurnLoop）。
    monkeypatch.delenv("QUESTOR_COMPACTION", raising=False)
    cfg = CompactionConfig(max_items=5)
    surface = CliSurface(workspace_root=tmp_path, compaction=cfg)
    assert surface.compaction is cfg


def test_clisurface_reads_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUESTOR_COMPACTION", "on")
    surface = CliSurface(workspace_root=tmp_path)
    assert surface.compaction is not None and surface.compaction.max_items == 24


def test_clisurface_default_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUESTOR_COMPACTION", raising=False)
    assert CliSurface(workspace_root=tmp_path).compaction is None
