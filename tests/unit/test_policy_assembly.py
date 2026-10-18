"""P9 T4：装配接缝——reduce 发 run_started 带 additive policy_ref + CliSurface 经 registry 解析默认策略。

真依赖判据：`Run.policy_ref` 字段存在 ≠ run_started 带出它（reduce 生产者）；`policy_id`
硬编码 ReActPolicy 存在 ≠ 经 PolicyRegistry 解析（装配门）。本测钉两处消费者都接通。
"""

from __future__ import annotations

from questor.contracts.common import thaw
from questor.contracts.events import EventType, SubmitMessage
from questor.contracts.policy import PolicyRef
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.providers.fake import EchoProvider
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.surfaces.cli import CliSurface


def _user_msg(run_id: str) -> Message:
    return Message(id=f"msg-{run_id}", role=Role.USER, content=(ContentBlock(type="text", text="hi"),), seq=0)


def test_reduce_run_started_carries_policy_ref() -> None:
    run = Run(run_id="r1", policy_ref=PolicyRef(id="react", fingerprint="react:1"))
    _, events = reduce(run, SubmitMessage(run_id="r1", content=_user_msg("r1")))
    started = next(e for e in events if e.type == EventType.RUN_STARTED)
    assert started.data["run_id"] == "r1"
    assert thaw(started.data["policy_ref"]) == {"id": "react", "fingerprint": "react:1"}


def test_reduce_run_started_without_policy_ref_omits_key() -> None:
    # 无 policy_ref（None）→ 不发 null 值（additive optional；旧消费者忽略）。
    run = Run(run_id="r2")
    _, events = reduce(run, SubmitMessage(run_id="r2", content=_user_msg("r2")))
    started = next(e for e in events if e.type == EventType.RUN_STARTED)
    assert "policy_ref" not in started.data


def test_surface_resolves_default_policy_ref_via_registry() -> None:
    surface = CliSurface(provider=EchoProvider())
    port, ref = surface._resolve_for_run("run_x")
    assert ref == PolicyRef(id="react", fingerprint="react:1")
    assert port.id == "react"
    # 确定性：同 run_id → 同 ref（热替换只影响新 run，活 run 用其冻结快照）。
    assert surface._resolve_for_run("run_x")[1] == ref


def test_surface_fail_open_on_unknown_policy_id() -> None:
    # 装配点用 fail-open：policy_id 写错 → 回落默认 react、run 仍起（C10）。
    surface = CliSurface(provider=EchoProvider(), policy_id="does-not-exist")
    port, ref = surface._resolve_for_run("run_y")
    assert ref.id == "react"
