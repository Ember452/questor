"""P7 T7：`tool_completed` additive 带 **有界 preview + artifact_ref 指针 + truncated**（C18/C20/ADR-0019/ADR-0035）。

判红点：
- `EXTERNAL_EVENT_FIELDS[TOOL_COMPLETED]` 现含 preview/artifact_ref/truncated（原仅 tool_call_id/status）。
- reduce 派生：短输出 preview=全文、truncated=False、无 artifact_ref；超长 display 截到上限且 truncated=True；
  归档信封（result 为 archived_tool_result dict）→ 取内层 preview + artifact_ref.artifact_id + truncated=True。
- **C20 第二载体红线**：preview/artifact_ref 是**协议字段（给前端）**，**绝不进带外投影**——
  `observability.projection.project` 的 fields 里不得出现 preview/artifact_ref。
- 全文**绝不回退进事件**：事件里最多一屏 preview（≤ 上界），其余靠 artifact 指针（本测试断言 preview 有界）。
"""

from __future__ import annotations

from questor.contracts.events import Envelope, EventType
from questor.kernel.events import EXTERNAL_EVENT_FIELDS, project
from questor.observability.projection import project as obs_project
from questor.state import reduce

_PREVIEW_LIMIT = 4096


def test_whitelist_carries_bounded_preview_and_pointer() -> None:
    allowed = EXTERNAL_EVENT_FIELDS[EventType.TOOL_COMPLETED]
    assert allowed is not None
    assert {"tool_call_id", "status", "preview", "artifact_ref", "truncated"} <= set(allowed), allowed


def test_short_display_has_full_preview_not_truncated() -> None:
    data = reduce._tool_completed_data("tc1", "success", result="ok", display="all good")  # noqa: SLF001
    assert data["preview"] == "all good"
    assert data["truncated"] is False
    assert "artifact_ref" not in data


def test_long_display_is_bounded_and_flagged() -> None:
    big = "x" * (_PREVIEW_LIMIT + 1000)
    data = reduce._tool_completed_data("tc1", "success", result="", display=big)  # noqa: SLF001
    assert len(data["preview"]) <= _PREVIEW_LIMIT
    assert data["truncated"] is True
    assert "artifact_ref" not in data  # 未归档时不臆造指针


def test_archived_envelope_yields_pointer_and_bounded_preview() -> None:
    envelope = {
        "kind": "archived_tool_result",
        "artifact_ref": {"artifact_id": "artifact://deadbeef12345678", "sha256": "abc", "total_bytes": 999999},
        "preview": "head of the big output",
        "total_bytes": 999999,
    }
    data = reduce._tool_completed_data("tc1", "success", result=envelope, display=None)  # noqa: SLF001
    assert data["artifact_ref"] == "artifact://deadbeef12345678"
    assert data["preview"] == "head of the big output"
    assert data["truncated"] is True


def test_project_forwards_preview_and_pointer_to_external_wire() -> None:
    internal = Envelope(
        v=1,
        seq=2,
        run_id="r",
        type=EventType.TOOL_COMPLETED,
        data={"tool_call_id": "tc1", "status": "success", "preview": "p", "artifact_ref": "artifact://x", "truncated": True},
    )
    projected = project(internal)
    assert projected is not None
    assert set(projected.data) == {"tool_call_id", "status", "preview", "artifact_ref", "truncated"}, projected.data


def test_preview_never_enters_out_of_band_projection() -> None:
    """C20：preview/artifact_ref 是事件协议字段，绝不进带外日志（投影 fields 不得含它们）。"""
    env = Envelope(
        v=1,
        seq=3,
        run_id="r",
        type=EventType.TOOL_COMPLETED,
        data={"tool_call_id": "tc1", "status": "success", "preview": "SECRET-ish payload", "artifact_ref": "artifact://x", "truncated": True},
    )
    entry = obs_project(env)
    assert entry is not None
    assert "preview" not in entry.fields, entry.fields
    assert "artifact_ref" not in entry.fields, entry.fields
    assert entry.fields.get("status") == "success"  # 既有白名单标量仍在
