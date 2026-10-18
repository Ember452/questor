"""P9 T2：`tools_changed` + `run_started.policy_ref` 事件契约四处 lockstep 判据（C6/C15；ADR-0045/0046）。

钉的是"契约四处一致 + 投影正确 + tools_changed 为 live-only"——不是字段存在≠gate：
- ``EventType`` / ``EXTERNAL_EVENT_FIELDS`` / ``LIVE_ONLY`` / ``event.schema.json`` 四处齐；
- ``project()`` 真按白名单裁 ``tools_changed``；
- ``run_started`` 白名单含 additive ``policy_ref``（emit 生产者归 T4 reduce）。
"""

from __future__ import annotations

import json
from pathlib import Path

from questor.contracts.events import Envelope, EventType
from questor.kernel.events import EXTERNAL_EVENT_FIELDS, LIVE_ONLY, project

_SCHEMA = json.loads((Path("protocol/event.schema.json")).read_text(encoding="utf-8"))


def test_tools_changed_declared_everywhere() -> None:
    assert EventType.TOOLS_CHANGED == "tools_changed"
    assert "tools_changed" in EXTERNAL_EVENT_FIELDS, "kernel 白名单缺 tools_changed"
    assert "tools_changed" in _SCHEMA["properties"]["type"]["enum"], "schema enum 缺 tools_changed"
    assert "tools_changed" in _SCHEMA["$defs"], "schema $defs 缺 tools_changed"


def test_tools_changed_is_live_only() -> None:
    # ADR-0046：热插告警不占 durable seq、不入库（C13）。
    assert EventType.TOOLS_CHANGED in LIVE_ONLY


def test_run_started_whitelist_gains_policy_ref() -> None:
    assert "policy_ref" in EXTERNAL_EVENT_FIELDS[EventType.RUN_STARTED]
    props = _SCHEMA["$defs"]["run_started"]["properties"]
    assert "policy_ref" in props
    assert props["policy_ref"].get("additionalProperties") is False


def test_project_tools_changed_keeps_only_domain() -> None:
    env = Envelope(
        v=1,
        seq=1,
        run_id="run_1",
        type=EventType.TOOLS_CHANGED,
        data={"domain": "tools", "leak": "should be dropped"},
    )
    projected = project(env)
    assert projected is not None
    assert set(projected.data) == {"domain"}
    assert projected.data["domain"] == "tools"


def test_schema_field_level_lockstep_for_new_types() -> None:
    # 每个契约类型的 $defs 属性集 == EXTERNAL_EVENT_FIELDS 白名单（check_protocol_schema 同源判据的本地镜像）。
    for event_type, allowed in EXTERNAL_EVENT_FIELDS.items():
        if allowed is None:
            continue
        props = set(_SCHEMA["$defs"][event_type]["properties"])
        assert props == set(allowed), f"field drift on {event_type}: schema {sorted(props)} != whitelist {sorted(allowed)}"
