"""L0 profile 词汇：normalize 严格性 + 预设只收紧 + 5 处 Python 真源归一（OPT-3/OPT-4 c5）。

两件事必须钉死：
1. ``normalize`` 不放宽词表（大小写/空格/别名都不认）——它一旦"宽容"，HTTP 端点与 ``delegate``
   参数的拒收面就会静默变宽（行为变更）；
2. 任何 profile 的预设都不能放宽 capability floor：预设里没有能碰 sandbox/capability 的字段，
   且 mode 只许更严或不变。
"""

from __future__ import annotations

import pytest

from questor.capabilities.subagent.delegate import DelegateTool
from questor.contracts.events import SetPermissionMode
from questor.contracts.profile import (
    MODE_DEFAULT,
    MODE_FULL_AUTO,
    MODE_PLAN,
    PERMISSION_MODE_RANK,
    PERMISSION_MODE_SET,
    PERMISSION_MODES,
    PROFILE_DEFAULT,
    PROFILE_READ_ONLY,
    PROFILES,
    PermissionPreset,
    normalize,
    permission_preset_for,
)
from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.state_schema import Budget
from questor.contracts.tool import Capability, Risk, ToolSpec
from questor.kernel.capability_floor import apply_capability_floor
from questor.kernel.permission_policy import PermissionMode
from questor.kernel.subagent_permission import _MODE_RANK
from questor.state.domain_state import Run
from questor.state.reduce import reduce


def test_mode_vocabulary_is_the_wire_order() -> None:
    """枚举顺序 = 协议顺序（参与 ``ProviderRequest.tools`` 字节形态，不得重排）。"""
    assert PERMISSION_MODES == (MODE_DEFAULT, MODE_PLAN, MODE_FULL_AUTO)
    assert [mode.value for mode in PermissionMode] == list(PERMISSION_MODES)
    assert PERMISSION_MODE_SET == frozenset({MODE_DEFAULT, MODE_PLAN, MODE_FULL_AUTO})
    assert dict(PERMISSION_MODE_RANK) == {MODE_PLAN: 0, MODE_DEFAULT: 1, MODE_FULL_AUTO: 2}


def test_normalize_is_strict_and_never_raises() -> None:
    """``normalize("default") == "default"``；未知/None 回落 default；**不**做大小写/空格/别名映射。"""
    assert normalize(MODE_DEFAULT) == MODE_DEFAULT
    assert normalize(MODE_PLAN) == MODE_PLAN
    assert normalize(MODE_FULL_AUTO) == MODE_FULL_AUTO
    assert normalize(None) == MODE_DEFAULT
    assert normalize("") == MODE_DEFAULT
    assert normalize("yolo") == MODE_DEFAULT
    assert normalize("FULL_AUTO") == MODE_DEFAULT, "大小写不认：放宽词表是行为变更"
    assert normalize(" plan") == MODE_DEFAULT, "空格不认：HTTP/delegate 现在就是精确匹配"
    assert normalize("auto") == MODE_DEFAULT, "别名不认（没有 auto → full_auto 的映射）"


def test_default_profile_is_neutral_and_read_only_profile_tightens() -> None:
    """default = 不收紧；read_only = mode 收窄到 plan + 只读闸 + 敏感路径拦截。"""
    neutral = permission_preset_for(PROFILE_DEFAULT)
    assert neutral == permission_preset_for(None) == permission_preset_for("no-such-profile")
    assert neutral.mode is None, "default 预设不得改 mode"
    assert (neutral.approval_policy, neutral.protect_sensitive_paths, neutral.enforce_read_only) == ("ask", True, False)

    strict = permission_preset_for(PROFILE_READ_ONLY)
    assert strict.profile == PROFILE_READ_ONLY
    assert strict.mode == MODE_PLAN
    assert (strict.approval_policy, strict.protect_sensitive_paths, strict.enforce_read_only) == ("ask", True, True)


def test_presets_can_only_tighten_never_widen_the_floor() -> None:
    """结构不变式：预设没有放宽字段，且 mode 只许更严（rank ≤ default）。"""
    widening = {"sandbox", "capability", "floor", "allow", "permission_mode_floor"}
    for profile in PROFILES:
        preset = permission_preset_for(profile)
        assert isinstance(preset, PermissionPreset)
        assert not (set(PermissionPreset.__slots__) & widening), "预设字段里出现可能放宽 floor 的名字"
        assert preset.protect_sensitive_paths is True, "敏感路径拦截不可被 profile 关掉"
        assert preset.approval_policy in {"ask", "never"}, "审批策略只许 ask/never（never 更严）"
        if preset.mode is not None:
            assert PERMISSION_MODE_RANK[preset.mode] <= PERMISSION_MODE_RANK[MODE_DEFAULT], f"{profile} 放宽了 mode"


@pytest.mark.parametrize("profile", PROFILES)
def test_floor_still_denies_unsandboxed_exec_under_every_profile(profile: str) -> None:
    """端到端：任何 profile 都改不动 capability floor（NONE sandbox 下 exec 恒拒）。"""
    preset = permission_preset_for(profile)
    outcome = apply_capability_floor(
        tool_spec=ToolSpec(
            name="run",
            description="exec tool",
            params={"type": "object"},
            capability=Capability.EXEC,
            risk=Risk.HIGH,
        ),
        sandbox=SandboxDescriptor(
            backend=SandboxBackend.NONE,
            confinement=Confinement.NONE,
            fences_writes=False,
            fences_network=False,
            isolates_process_tree=False,
            limitation="none",
        ),
        shell_analysis=None,
        args_summary="echo hi",
        mode=preset.mode or MODE_DEFAULT,
    )
    assert outcome is not None
    assert outcome.decision.value == "deny"
    assert outcome.floor_applied == "exec-capability"


def test_python_sources_agree_with_the_canonical_vocabulary() -> None:
    """5 处 Python 真源都指向同一份词汇（枚举/rank/委托 schema/reduce 判定）。"""
    assert dict(_MODE_RANK) == dict(PERMISSION_MODE_RANK)
    assert DelegateTool().spec.params["properties"]["mode"]["enum"] == list(PERMISSION_MODES)
    # reduce 侧：合法值接受、非法值拒绝且不改 mode、不发 permission_mode_changed。
    run = Run(run_id="run-mode", budget=Budget())
    accepted, events = reduce(run, SetPermissionMode(run_id=run.run_id, mode=MODE_PLAN, changed_by="test"))
    assert accepted.permission_ctx.mode == MODE_PLAN
    assert [event.type for event in events if event.type == "permission_mode_changed"] == ["permission_mode_changed"]
    rejected, rejected_events = reduce(run, SetPermissionMode(run_id=run.run_id, mode="yolo", changed_by="test"))
    assert rejected.permission_ctx.mode == MODE_DEFAULT
    assert all(event.type != "permission_mode_changed" for event in rejected_events)
