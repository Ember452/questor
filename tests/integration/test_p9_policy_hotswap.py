"""P9 T10：策略热替换 = 新 run（ADR-0009/0045 决策 7）集成——改 registry 只影响新 run 解析。

真依赖判据：`policy_ref` 进 Run 只是值对象冻结；本测证 "热替换"的门在装配解析点——
换 registry 后既有 run 的 ref 不变、新 run 拿到新 snapshot（活 run 不 mid-swap）。
"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.policy import PolicyTrust
from questor.policy.registry import PolicyEntry
from questor.providers.fake import EchoProvider
from questor.surfaces.cli import CliSurface


class _ReactV2:
    """react 的"新版本"变体（内容指纹不同）——模拟算子改了默认策略实现。"""

    id = "react"
    fingerprint = "react:2"

    def propose_action(self, view):  # pragma: no cover - 不在本测调用
        raise NotImplementedError


def test_registry_change_affects_only_new_runs(tmp_path: Path) -> None:
    surface = CliSurface(workspace_root=tmp_path, provider=EchoProvider())

    _p1, ref1 = surface._resolve_for_run("run-live")
    assert ref1.fingerprint == "react:1"

    # 注入更高 trust 的同 id 变体（PROJECT > SYSTEM）——"换了策略"。
    surface.policy_registry.register(PolicyEntry(id="react", factory=_ReactV2, trust=PolicyTrust.PROJECT))

    _p2, ref2 = surface._resolve_for_run("run-new")
    assert ref2.fingerprint == "react:2"  # 新 run 用新快照
    # 活 run 创建时冻结的 ref 绝不随之变（值语义；下面断言的是"已解析出的旧 ref 不被回填"）。
    assert ref1.fingerprint == "react:1"
