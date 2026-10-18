"""P8 T7 判据：子权限投影 project_parent_permission（子 ⊆ 父、永不放大、fail-closed）。

对齐 [ADR-0040](docs/adr/0040)。核心安全契约：mode 不宽于父（且默认 default）、rules 全继承不删限制、
denylist 只扩大、approval_policy/protect_sensitive_paths 不放宽、enforce_read_only 只加强。
"""

from __future__ import annotations

import pytest

from questor.contracts.state_schema import PermissionRule
from questor.kernel.subagent_permission import project_parent_permission
from questor.state.domain_state import PermissionCtx


def _rule(tool: str, action: str) -> PermissionRule:
    return PermissionRule(id=f"{tool}-{action}", tool_pattern=tool, argument_pattern="*", action=action)


def test_child_mode_defaults_to_default_not_inherit_full_auto():
    parent = PermissionCtx(mode="full_auto")
    child = project_parent_permission(parent)
    assert child.mode == "default"  # 不继承父 full_auto（D-4 推荐：便利与隔离分开）


def test_child_mode_never_exceeds_parent_even_if_requested():
    parent = PermissionCtx(mode="plan")
    child = project_parent_permission(parent, requested_mode="full_auto")
    assert child.mode == "plan"  # 请求被夹到 ≤ 父（plan 是最严档）


def test_child_inherits_all_rules_no_drop_no_add():
    deny = _rule("rm", "deny")
    ask = _rule("write", "ask")
    parent = PermissionCtx(mode="default", rules=(deny, ask))
    child = project_parent_permission(parent)
    # 子不得删任何限制（丢 deny/ask = 放大），也不得新增宽松规则。
    assert child.rules == (deny, ask)


def test_child_denylist_is_superset_of_parent():
    parent = PermissionCtx(denylist=frozenset({"/etc/passwd"}))
    child = project_parent_permission(parent, extra_deny={"/secret/key"})
    assert {"/etc/passwd", "/secret/key"} <= set(child.denylist)  # 只扩大


def test_child_does_not_relay_parent_approvals_decisions():
    # 子从空 approvals/decisions 起（跨 run 审批各自独立，request_id 前缀 child_run_id）。
    parent = PermissionCtx()
    child = project_parent_permission(parent)
    assert child.approvals == () and child.decisions == ()


def test_child_approval_policy_and_sensitive_paths_not_relaxed():
    parent = PermissionCtx(approval_policy="never", protect_sensitive_paths=True, enforce_read_only=True)
    child = project_parent_permission(parent)
    assert child.approval_policy == "never"
    assert child.protect_sensitive_paths is True
    assert child.enforce_read_only is True  # 只加强不放松


def test_unknown_requested_mode_rejected_fail_closed():
    with pytest.raises(ValueError):
        project_parent_permission(PermissionCtx(), requested_mode="YOLO")
