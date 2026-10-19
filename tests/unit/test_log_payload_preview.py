"""P10 TB3（TDD）—— ``QUESTOR_LOG_PAYLOAD`` preview 解析口径（fail-closed，off 默认零原文）。"""

from __future__ import annotations

import pytest

from questor.surfaces._assembly import payload_preview_from_env


def _set(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("QUESTOR_LOG_PAYLOAD", raising=False)
    else:
        monkeypatch.setenv("QUESTOR_LOG_PAYLOAD", value)


@pytest.mark.parametrize("value", [None, "", "off", "OFF"])
def test_off_and_empty_return_none(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    _set(monkeypatch, value)
    assert payload_preview_from_env() is None


@pytest.mark.parametrize("value", ["truncate:1", "truncate:2000", "TRUNCATE:500"])
def test_truncate_budget_parsed(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    _set(monkeypatch, value)
    assert payload_preview_from_env() is not None
    assert payload_preview_from_env() > 0


@pytest.mark.parametrize("value", ["on", "true", "truncate:0", "truncate:abc", "truncate:99999", "500"])
def test_invalid_values_reject_startup(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    # 宁可不启动也不静默忽略：非法 preview 规格必须 fail-closed 拒绝启动。
    _set(monkeypatch, value)
    with pytest.raises(SystemExit):
        payload_preview_from_env()
