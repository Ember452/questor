"""L2 子权限投影：从父 ``PermissionCtx`` 生成子 agent 的 ``PermissionCtx``（子⊆父、永不放大、fail-closed）。

层：L2 kernel——可依赖 L0 ``contracts`` + L1 ``state``；**不 import** L3+ / surfaces / providers（C1/C14）。
对齐 [ADR-0040](../../../docs/adr/0040-child-permission-inheritance-narrowing.md) / HARD C17。capability floor
不在此判（由 OS 能力探针在 kernel 执行边界决定；同机子与父 floor 相同，绝不因"是子"而降档）。
"""

from __future__ import annotations

from collections.abc import Iterable

from questor.state.domain_state import PermissionCtx

#: mode 宽松度序（越大越宽）。子档位夹到 ≤ 父（永不放大）；默认取保守的 ``default``。
_MODE_RANK: dict[str, int] = {"plan": 0, "default": 1, "full_auto": 2}
_DEFAULT_CHILD_MODE = "default"


def project_parent_permission(
    parent: PermissionCtx,
    *,
    requested_mode: str | None = None,
    extra_deny: Iterable[str] = (),
    extra_read_only: bool = False,
) -> PermissionCtx:
    """生成子 run 的 PermissionCtx——只能等于或更严于父，绝不放宽（fail-closed）。

    用法：spawn 时由内核端口调用，把结果作为子 Run 的 ``permission_ctx``。纯函数，只读父、不改父。

    收缩方向（子 ⊆ 父，永不放大）：
    - ``mode``：默认 ``default``；若请求更宽则**夹到 ≤ 父档位**（父 ``plan`` → 子至多 ``plan``；
      父 ``full_auto`` 不传染子）。便利与隔离分开——父全自动不代表子可无围栏。
    - ``rules``：**全继承父规则**——删掉任何 ``deny``/``ask`` 都等于放大，故一条不删；也不注入新宽松规则。
    - ``denylist``：``父 ∪ extra``（只扩大；敏感路径不可被 mode/rules 覆盖，承 ADR-0014）。
    - ``approval_policy`` / ``protect_sensitive_paths``：原样继承（不得比父更宽）。
    - ``enforce_read_only``：``父 or extra``（只加强）。
    - ``approvals`` / ``decisions``：清空——子审批独立、历史 decision 不回溯（``request_id`` 前缀 ``child_run_id``
      跨 run 唯一，承 ADR-0016）。

    失败语义：``requested_mode`` 不在已知档位 → ``ValueError``（fail-closed，绝不猜测放宽）。
    依赖：``PermissionCtx`` 为 L1 权威结构；本函数不触碰 StorePort/沙箱句柄（策略层无裸句柄，C4/C8）。
    """
    if requested_mode is not None and requested_mode not in _MODE_RANK:
        raise ValueError(f"unknown requested_mode {requested_mode!r}")
    want = requested_mode or _DEFAULT_CHILD_MODE
    # 子档位不得宽于父：rank 越大越宽，超出即回落到父的 mode。
    child_mode = want if _MODE_RANK[want] <= _MODE_RANK[parent.mode] else parent.mode
    return PermissionCtx(
        mode=child_mode,
        rules=parent.rules,
        denylist=frozenset(parent.denylist) | frozenset(extra_deny),
        approvals=(),
        decisions=(),
        workspace_root=parent.workspace_root,
        cwd=parent.cwd,
        approval_policy=parent.approval_policy,
        protect_sensitive_paths=parent.protect_sensitive_paths,
        enforce_read_only=parent.enforce_read_only or extra_read_only,
    )
