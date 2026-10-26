"""wire 模块镜像测试：映射表与 schema 的一致性。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.serve import wire
from questorharness.bootstrap.hosts.serve.wire_types import SERVER_FRAME_KINDS


def test_mapping_values_are_declared_kinds() -> None:
    """映射产出的每个 kind 都必须在契约里。"""
    produced = {kind for kinds in wire.STREAM_EVENT_TO_KINDS.values() for kind in kinds}
    assert produced <= set(SERVER_FRAME_KINDS)


def test_usage_frame_shape() -> None:
    """用量帧字段名是 camelCase。"""
    from questorharness.contracts.usage import UsageSnapshot

    assert wire.usage_frame(UsageSnapshot(input_tokens=1, output_tokens=2)) == {
        "inputTokens": 1,
        "outputTokens": 2,
    }


def test_ask_request_frame_carries_options_only_when_present() -> None:
    """A2：有选项才带 `options`（additive），老帧形状不变。"""

    frame = wire.ask_request_frame(prompt_id="q1", question="选？", options=["a", "b"])
    assert frame["options"] == ["a", "b"]
    bare = wire.ask_request_frame(prompt_id="q2", question="选？")
    assert "options" not in bare
