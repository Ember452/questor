"""B7/c3：cache 三条款（4 断点预算 / TTL 按 query source / 三段 hash 断裂）—— v3 §6.1。"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.events import EventType
from questor.contracts.ports import ProviderRequest
from questor.contracts.tool import Capability, Risk, ToolSpec
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.memory.cache_plan import (
    BREAKPOINT_SLOTS,
    MAX_CACHE_BREAKPOINTS,
    CacheSegments,
    break_reason,
    cache_ttl_for,
    plan_cache,
    replacement_order,
)
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import EchoProvider
from questor.state.domain_state import Run


def _spec(name: str) -> ToolSpec:
    return ToolSpec(name=name, description=f"{name} tool for cache plan tests", params={}, capability=Capability.READONLY, risk=Risk.LOW)


def test_slot_table_is_the_documented_four() -> None:
    assert MAX_CACHE_BREAKPOINTS == 4
    assert BREAKPOINT_SLOTS == ("system", "history_start", "tool_face", "reserved")


def test_budget_is_fail_soft_cuts_breakpoints_not_content() -> None:
    segments = CacheSegments(system="base prompt", tools=("read", "write"), history_start=3)
    full = plan_cache(segments)
    assert full.breakpoints == ("system", "history_start", "tool_face")
    tight = plan_cache(segments, max_breakpoints=1)
    assert tight.breakpoints == ("system",)
    assert tight.dropped == ("history_start", "tool_face")
    # 砍断点不改指纹：内容一位未动（"砍断点不砍内容"）。
    assert tight.system_hash == full.system_hash


def test_ttl_is_gated_by_query_source() -> None:
    assert cache_ttl_for("main") == "long"
    assert cache_ttl_for("MAIN") == "long"
    for source in ("side", "recall-selector", "summarizer", "", None):
        assert cache_ttl_for(source) is None  # 内部调用不得污染用户前缀资产


def test_break_reason_names_the_first_changed_dimension() -> None:
    base = CacheSegments(system="a", tools=("read",), history_start=1)
    plan = plan_cache(base)
    assert break_reason(None, plan) is None  # 首轮建基线，不算断裂
    assert break_reason(plan, plan) is None
    assert break_reason(plan, plan_cache(CacheSegments(system="b", tools=("read",), history_start=1))) == "system"
    assert break_reason(plan, plan_cache(CacheSegments(system="a", tools=("read", "write"), history_start=1))) == "tools"
    assert break_reason(plan, plan_cache(CacheSegments(system="a", tools=("read",), history_start=9))) == "history"
    shrunk = plan_cache(base, max_breakpoints=1)
    assert break_reason(plan, shrunk) == "budget"


def test_frozen_prefix_is_never_the_first_sacrifice() -> None:
    assert replacement_order(frozen_bytes=10, fresh_bytes=900, budget=100) == ("fresh",)
    assert replacement_order(frozen_bytes=900, fresh_bytes=10, budget=100) == ("fresh",)  # frozen 超预算也先动 fresh
    assert replacement_order(frozen_bytes=10, fresh_bytes=10, budget=100) == ("fresh", "frozen")


def test_event_payload_matches_the_wire_whitelist() -> None:
    from questor.kernel.events import EXTERNAL_EVENT_FIELDS

    plan = plan_cache(CacheSegments(system="SESSION-PRIVATE-TOKEN", tools=("read",), history_start=1))
    data = plan.event_data(reason="system")
    assert set(data) == set(EXTERNAL_EVENT_FIELDS[EventType.CACHE_BREAK])
    assert "SESSION-PRIVATE-TOKEN" not in repr(data)  # 只 hash，零正文（C18/C20）


def _loop(bus: InProcessEventBus) -> DefaultTurnLoop:
    return DefaultTurnLoop(
        provider=EchoProvider(),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=lambda _name: None,
        workspace_root=Path.cwd(),
    )


async def test_loop_emits_cache_break_when_the_prefix_changes() -> None:
    bus = InProcessEventBus()
    seen: list = []
    bus.add_observer(seen.append)
    loop = _loop(bus)
    run = Run(run_id="run_cache")
    first = ProviderRequest(model="m", messages=(), system="base", tools=(_spec("read"),))
    await loop._track_cache_break(run, 1, first)
    assert [env.type for env in seen] == []  # 首轮建基线，不出声
    await loop._track_cache_break(run, 2, first)
    assert [env.type for env in seen] == []  # 未变即无断裂
    await loop._track_cache_break(run, 3, ProviderRequest(model="m", messages=(), system="base+", tools=(_spec("read"),)))
    breaks = [env for env in seen if env.type == EventType.CACHE_BREAK]
    assert len(breaks) == 1 and breaks[0].data["reason"] == "system"
    assert breaks[0].data["breakpoints"] == 2


async def test_side_query_loop_never_reports_breaks() -> None:
    bus = InProcessEventBus()
    seen: list = []
    bus.add_observer(seen.append)
    loop = DefaultTurnLoop(
        provider=EchoProvider(),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=lambda _name: None,
        workspace_root=Path.cwd(),
        query_source="side",
    )
    run = Run(run_id="run_side")
    await loop._track_cache_break(run, 1, ProviderRequest(model="m", messages=(), system="a"))
    await loop._track_cache_break(run, 2, ProviderRequest(model="m", messages=(), system="b"))
    assert seen == []  # 不开 cache 的来源不建基线也不报断裂（内部调用不污染用户前缀观测）
