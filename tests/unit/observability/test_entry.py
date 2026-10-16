"""T2.2 内核契约 ``observability/entry.py`` 判例（DESIGN §4；G-L4）。

覆盖 ``LogEntry.__post_init__`` 五不变式全 fail-closed + ``LogLevel`` 有序。内核零依赖：
本测试只用 stdlib 造一个"领域对象样"的假对象来验白名单拒收（不许 import questor）。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from questor.observability.entry import MAX_MSG_CHARS, LogEntry, LogLevel


def _ts() -> datetime:
    return datetime.now(UTC)


def _entry(**over) -> LogEntry:  # noqa: ANN003
    base = dict(
        ts=_ts(),
        level=LogLevel.INFO,
        logger="questor.kernel.loop",
        msg="hello",
        fields={},
        traceback=None,
        source="inline",
        context={},
    )
    base.update(over)
    return LogEntry(**base)


class _FakeDomain:
    """伪装成领域对象的任意实例——白名单必须当场拒收。"""

    def __repr__(self) -> str:
        return "<FakeDomain run=...>"


def test_valid_entry_constructs() -> None:
    e = _entry(fields={"n": 1, "flag": True, "s": "x", "none": None}, context={"run_id": "r1", "turn": 3})
    assert e.level is LogLevel.INFO
    assert e.fields["n"] == 1


def test_loglevel_is_ordered_numeric() -> None:
    # 级别可比较（供 pipeline 过滤）；顺序 DEBUG<INFO<WARNING<ERROR<CRITICAL。
    assert LogLevel.DEBUG < LogLevel.INFO < LogLevel.WARNING < LogLevel.ERROR < LogLevel.CRITICAL


def test_naive_ts_rejected() -> None:
    # G-L4：naive datetime 当场 ValueError（必须 tz-aware）。
    with pytest.raises(ValueError):
        _entry(ts=datetime(2026, 1, 1, 12, 0, 0))


def test_aware_non_utc_ts_accepted() -> None:
    # 只要 tz-aware 即可（不强制 UTC；落盘按各自 ts 推文件名）。
    _entry(ts=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=8))))


@pytest.mark.parametrize("container", ["fields", "context"])
def test_non_whitelist_value_type_error(container: str) -> None:
    # G-L4：非白名单值 → TypeError，**不是**静默 str() 转换。
    with pytest.raises(TypeError):
        _entry(**{container: {"run": _FakeDomain()}})


@pytest.mark.parametrize("bad", [[1, 2], {"a": 1}, (1, 2), b"bytes", 1.5 + 2j])
def test_various_non_scalar_values_rejected(bad: object) -> None:
    with pytest.raises(TypeError):
        _entry(fields={"v": bad})


def test_non_str_key_type_error() -> None:
    with pytest.raises(TypeError):
        _entry(fields={1: "int key"})


def test_oversized_msg_truncated_with_flag() -> None:
    # msg 超 max_msg_chars → 截断 + 附 msg_truncated=True（禁止无限长行污染 JSONL）。
    big = "x" * (MAX_MSG_CHARS + 100)
    e = _entry(msg=big)
    assert len(e.msg) == MAX_MSG_CHARS
    assert e.msg_truncated is True


def test_normal_msg_not_truncated() -> None:
    e = _entry(msg="short")
    assert e.msg_truncated is False


def test_source_must_be_inline_or_event() -> None:
    # source 只允许二值。
    _entry(source="event")
    with pytest.raises(ValueError):
        _entry(source="other")


def test_context_fields_key_collision_rejected() -> None:
    # context ∩ fields 同键 → ValueError（禁止静默覆盖/靠合并顺序定义语义）。
    with pytest.raises(ValueError):
        _entry(fields={"run_id": "a"}, context={"run_id": "b"})


def test_entry_is_frozen() -> None:
    # frozen dataclass：外层不可 setattr。
    e = _entry()
    with pytest.raises(FrozenInstanceError):
        e.msg = "mutated"  # type: ignore[misc]
