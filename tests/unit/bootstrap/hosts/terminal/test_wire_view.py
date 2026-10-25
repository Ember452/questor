"""`wire_view` 的契约：13 kind 穷尽、未知 kind 降级、帧不进视图模型。"""

from __future__ import annotations

import dataclasses

import pytest

from questorharness.bootstrap.hosts.serve.wire_types import SERVER_FRAME_KINDS
from questorharness.bootstrap.hosts.terminal import wire_view as view


def _frame(kind: str, **fields: object) -> dict[str, object]:
    return {"seq": 1, "kind": kind, **fields}


def test_known_kinds_equal_the_wire_schema() -> None:
    """schema 加一个 kind 而这里没跟上 → 红（否则终端会静默丢帧）。"""
    assert set(view.KNOWN_KINDS) == set(SERVER_FRAME_KINDS)


def test_turn_started_projects_turn_identity() -> None:
    item = view.view_of(_frame("turn_started", turnId="t-1", index=3, via="cli"))
    assert item == view.TurnStartedItem(turn_id="t-1", index=3, via="cli")


def test_text_projects_the_delta() -> None:
    assert view.view_of(_frame("text", text="你好")) == view.TextItem(text="你好")


def test_message_projects_blocks_and_usage() -> None:
    item = view.view_of(
        _frame(
            "message",
            blocks=[
                {"type": "text", "text": "完成"},
                {"type": "image", "mediaType": "image/png"},
                {"type": "tool_use", "id": "c1", "name": "bash"},
                {"type": "tool_result", "toolUseId": "c1", "content": "ok", "isError": True},
            ],
            usage={"inputTokens": 10, "outputTokens": 4},
        )
    )
    assert isinstance(item, view.MessageItem)
    assert item.usage == view.UsageVM(input_tokens=10, output_tokens=4)
    assert item.blocks == (
        view.TextBlockVM(text="完成"),
        view.ImageBlockVM(media_type="image/png"),
        view.ToolUseBlockVM(tool_use_id="c1", name="bash"),
        view.ToolResultBlockVM(tool_use_id="c1", content="ok", is_error=True),
    )


def test_tool_dispatch_and_result_project_call_ids() -> None:
    dispatch = view.view_of(_frame("tool_dispatch", toolCallId="c1", tool="bash"))
    result = view.view_of(
        _frame("tool_result", toolCallId="c1", tool="bash", output="done", isError=False)
    )
    assert dispatch == view.ToolDispatchItem(tool_call_id="c1", tool="bash")
    assert result == view.ToolResultItem(
        tool_call_id="c1", tool="bash", output="done", is_error=False
    )


def test_approval_request_keeps_detail_for_the_diff_card() -> None:
    item = view.view_of(
        _frame("approval_request", id="p1", tool="edit_file", subject="a.py", detail="+1/-2")
    )
    assert item == view.ApprovalItem(
        prompt_id="p1", tool="edit_file", subject="a.py", detail="+1/-2"
    )


def test_ask_request_projects_the_question() -> None:
    item = view.view_of(_frame("ask_request", id="p2", question="选哪个？"))
    assert item == view.AskItem(prompt_id="p2", question="选哪个？")


def test_notice_projects_level_and_text() -> None:
    item = view.view_of(_frame("notice", level="warning", text="代理未设置"))
    assert item == view.NoticeItem(level="warning", text="代理未设置")


def test_compaction_frames_project_their_three_shapes() -> None:
    started = view.view_of(_frame("compaction_started", trigger="auto"))
    progress = view.view_of(
        _frame("compaction_progress", phase="compact_retry", attempt=2, message="重试")
    )
    done = view.view_of(_frame("compaction_done", trigger="auto", ok=True))
    assert started == view.CompactionStartedItem(trigger="auto")
    assert progress == view.CompactionProgressItem(phase="compact_retry", attempt=2, message="重试")
    assert done == view.CompactionDoneItem(trigger="auto", ok=True)


def test_turn_done_projects_outcome_and_usage() -> None:
    item = view.view_of(
        _frame(
            "turn_done",
            turnId="t-1",
            cancelled=False,
            outcome="completed",
            durationMs=1200,
            checkpointTurn=False,
            usage={"inputTokens": 3, "outputTokens": 5},
        )
    )
    assert item == view.TurnDoneItem(
        turn_id="t-1",
        cancelled=False,
        outcome="completed",
        duration_ms=1200,
        checkpoint_turn=False,
        usage=view.UsageVM(input_tokens=3, output_tokens=5),
    )


def test_stream_reset_projects_the_reason() -> None:
    item = view.view_of(_frame("stream_reset", reason="replay_gap", watermark=42))
    assert item == view.StreamResetItem(reason="replay_gap")


def test_unknown_kind_degrades_without_raising() -> None:
    """未来新增 kind 先到终端时必须可见地降级，不能抛异常也不能静默丢。"""
    item = view.view_of(_frame("brand_new_kind", payload=1))
    assert isinstance(item, view.UnsupportedItem)
    assert item.kind == "brand_new_kind"
    assert "未登记" in item.reason


def test_malformed_known_kind_degrades_instead_of_raising() -> None:
    """字段缺失或类型不符（旧服务端/半截帧）走同一降级路径。"""
    item = view.view_of(_frame("text"))
    assert isinstance(item, view.UnsupportedItem)
    assert item.kind == "text"


def test_frame_dict_never_leaks_into_the_view_model() -> None:
    """视图模型只带投影后的字段；把 raw frame 挂进来等于第二份状态源。"""
    frame = _frame("tool_result", toolCallId="c1", tool="bash", output="x", isError=False)
    item = view.view_of(frame)
    assert not isinstance(item, dict)
    for field in dataclasses.fields(item):
        assert not isinstance(getattr(item, field.name), dict)


def test_items_are_frozen() -> None:
    """视图模型不可变：渲染层不能回写状态。"""
    item = view.view_of(_frame("text", text="hi"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.text = "changed"  # type: ignore[misc] # 冻结数据类：运行期赋值必须失败


def test_usage_extras_project_when_present() -> None:
    """波 D1：窗口/费用/缓存命中能拿到就带出来，拿不到就是 None（不伪造 0）。"""
    with_extras = view.view_of(
        _frame(
            "turn_done",
            turnId="t",
            cancelled=False,
            outcome="completed",
            durationMs=1,
            checkpointTurn=False,
            usage={
                "inputTokens": 1,
                "outputTokens": 2,
                "costUsd": 0.5,
                "contextWindow": 200000,
                "contextUsed": 1200,
                "cachedTokens": 300,
            },
        )
    )
    assert isinstance(with_extras, view.TurnDoneItem)
    assert with_extras.usage is not None
    assert with_extras.usage.cost_usd == 0.5
    assert with_extras.usage.context_window == 200000
    assert with_extras.usage.context_used == 1200
    assert with_extras.usage.cached_tokens == 300

    bare = view.view_of(
        _frame(
            "turn_done",
            turnId="t",
            cancelled=False,
            outcome="completed",
            durationMs=1,
            checkpointTurn=False,
            usage={"inputTokens": 1, "outputTokens": 2},
        )
    )
    assert isinstance(bare, view.TurnDoneItem)
    assert bare.usage is not None
    assert bare.usage.cost_usd is None
    assert bare.usage.context_window is None


def test_todos_projects_rows_and_path() -> None:
    """W-D4：清单快照按行投影，勾选态进布尔字段（渲染层不做二次解析）。"""
    item = view.view_of(
        _frame(
            "todos",
            path="TODO.md",
            items=[
                {"text": "写文档", "checked": True},
                {"text": "补测试", "checked": False},
            ],
        )
    )
    assert item == view.TodosItem(
        path="TODO.md",
        rows=(
            view.TodoRow(text="写文档", checked=True),
            view.TodoRow(text="补测试", checked=False),
        ),
    )


def test_todos_with_broken_rows_degrades() -> None:
    """清单行坏掉时整帧降级，而不是渲染半张清单。"""
    item = view.view_of(_frame("todos", path="TODO.md", items=["不是对象"]))
    assert isinstance(item, view.UnsupportedItem)
    assert item.kind == "todos"


def test_approval_patch_projects_structured_fields() -> None:
    """波 D2：结构化 diff 字段走独立字段，不靠拆 detail 字符串。"""
    item = view.view_of(
        _frame(
            "approval_request",
            id="p1",
            tool="edit_file",
            subject="a.py",
            detail="+1/-2",
            patch="@@ -1 +1 @@\n-a\n+b",
            added=1,
            removed=1,
        )
    )
    assert isinstance(item, view.ApprovalItem)
    assert item.added == 1
    assert item.removed == 1
    assert item.patch is not None and "@@" in item.patch
