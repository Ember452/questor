"""§6-5：sidecar 生命周期状态机进协议（独立 status 面，非 per-run 信封）。

锁死三处 lockstep：contracts 状态/字段白名单 ⟂ protocol/sidecar_status.schema.json，
并对状态/代次的不变式做 fail-closed 校验。生产者=Rust 壳（on_crash_detect），消费者=UI。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from questor.contracts.sidecar_status import (
    SIDECAR_LIFECYCLE_STATES,
    SIDECAR_STATUS_FIELDS,
    SidecarStatus,
)

_SCHEMA = json.loads(Path("protocol/sidecar_status.schema.json").read_text(encoding="utf-8"))


def test_states_are_exactly_the_five_lifecycle_values() -> None:
    assert set(SIDECAR_LIFECYCLE_STATES) == {
        "starting",
        "ready",
        "stopping",
        "stopped",
        "crashed",
    }


def test_schema_state_enum_matches_contracts() -> None:
    assert set(_SCHEMA["properties"]["state"]["enum"]) == set(SIDECAR_LIFECYCLE_STATES)


def test_schema_field_whitelist_matches_contracts() -> None:
    # 字段级漂移门：$defs 属性名集必须 == contracts 白名单键集（增删改名只改一处即判红）。
    assert set(_SCHEMA["properties"]) == set(SIDECAR_STATUS_FIELDS)


def test_schema_is_closed_and_generation_bounded() -> None:
    assert _SCHEMA["additionalProperties"] is False
    assert set(_SCHEMA["required"]) == {"state", "generation"}
    assert _SCHEMA["properties"]["generation"]["minimum"] == 0


def test_rejects_unknown_state() -> None:
    with pytest.raises(ValueError):
        SidecarStatus(state="exploded", generation=0)


def test_rejects_negative_generation() -> None:
    with pytest.raises(ValueError):
        SidecarStatus(state="ready", generation=-1)


def test_detail_is_optional_and_bounded() -> None:
    SidecarStatus(state="crashed", generation=3)  # detail 省略合法
    with pytest.raises(ValueError):
        SidecarStatus(state="crashed", generation=3, detail="x" * 257)
