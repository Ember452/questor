"""P9 T1：policy_ref 契约 additive（PolicyRef / PolicyTrust / Run.policy_ref / 快照 round-trip）。

覆盖 ADR-0045 的纯 additive 面（事件 lockstep 的 TOOLS_CHANGED/run_started.policy_ref 归 T2）。
判红点：字段存在≠gate 存在——本测只钉"契约形状 + 快照不破坏旧数据"，不声称 A/B 路由已通。
"""

from __future__ import annotations

import dataclasses

import pytest

from questor.contracts.policy import PolicyRef, PolicyTrust
from questor.state.domain_state import Run
from questor.state.snapshot import from_snapshot, to_snapshot


def test_policy_ref_is_frozen_value_object() -> None:
    ref = PolicyRef(id="react", fingerprint="fp123")
    assert ref.id == "react"
    assert ref.fingerprint == "fp123"
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.id = "x"  # type: ignore[misc]


def test_policy_trust_members() -> None:
    # trust 优先级三级，ADR-0045/design/05 §2；分桶/优先级消费者在 T3 registry，本测只钉枚举形状。
    assert {t.value for t in PolicyTrust} == {"system", "user", "project"}


def test_run_policy_ref_defaults_none() -> None:
    # additive 默认 None：不破坏既有 Run 构造点（http_sse/cli 等）。
    assert Run(run_id="run_1").policy_ref is None


def test_run_policy_ref_round_trips_through_snapshot() -> None:
    run = Run(run_id="run_2", policy_ref=PolicyRef(id="react", fingerprint="fp"))
    back = from_snapshot(to_snapshot(run))
    assert back.policy_ref == PolicyRef(id="react", fingerprint="fp")


def test_old_snapshot_without_policy_ref_reads_none() -> None:
    # 旧快照（v1/v2/v3 无 policy_ref 键）必须仍读得出、policy_ref=None（不破坏 checkpoint 兼容）。
    snap = to_snapshot(Run(run_id="run_3"))
    snap.pop("policy_ref", None)
    assert from_snapshot(snap).policy_ref is None
