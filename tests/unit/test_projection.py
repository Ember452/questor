"""T17：投影白名单——内部类型丢弃、未知类型按 C6 处理、非白名单字段被剥离。"""

from __future__ import annotations

from questor.contracts.common import thaw
from questor.contracts.events import Envelope, EventType
from questor.kernel.events import project


def _env(etype: str, data: dict) -> Envelope:
    return Envelope(v=1, seq=1, run_id="run_x", type=etype, data=data)


def test_internal_types_are_dropped() -> None:
    assert project(_env("checkpoint_recorded", {"x": 1})) is None
    assert project(_env("reduce_rejected", {"x": 1})) is None
    assert project(_env("ledger_entry", {"x": 1})) is None


def test_whitelist_strips_non_whitelisted_fields() -> None:
    env = _env(EventType.TOOL_STARTED, {"tool_call_id": "tc", "name": "write", "capability": "write", "risk": "high", "args_summary": "out.txt", "full_args": {"content": "SECRET"}})
    projected = project(env)
    assert projected is not None
    assert "full_args" not in projected.data
    assert projected.data["args_summary"] == "out.txt"


def test_run_failed_error_is_preserved_as_whitelisted() -> None:
    env = _env(EventType.RUN_FAILED, {"error": {"code": "x", "message": "y", "retryable": False}, "leak": "z"})
    projected = project(env)
    assert projected is not None
    assert thaw(projected.data) == {"error": {"code": "x", "message": "y", "retryable": False}}


def test_heartbeat_has_empty_data() -> None:
    env = _env(EventType.HEARTBEAT, {"anything": 1})
    projected = project(env)
    assert projected is not None
    assert not projected.data


def test_unknown_type_dropped_unless_error_class() -> None:
    assert project(_env("some_future_internal", {"a": 1})) is None
    # 未知但属于错误类之外一律丢弃；错误类（warning/run_failed/resync_required）已在白名单表内正常保留。
    kept = project(_env(EventType.WARNING, {"message": "hi", "extra": "x"}))
    assert kept is not None
    assert thaw(kept.data) == {"message": "hi"}


def test_envelope_not_mutated_by_projection() -> None:
    original = _env(EventType.APPROVAL_REQUEST, {"request_id": "a", "tool_call_id": "t", "name": "n", "args_summary": "s", "risk": "high", "reason": "r", "expires_at": "2026-01-01T00:00:00+00:00", "secret_env": {"K": "V"}})
    projected = project(original)
    assert "secret_env" not in projected.data
    assert "secret_env" in original.data  # 内部信封不被破坏，只投影出净化副本
