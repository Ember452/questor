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
