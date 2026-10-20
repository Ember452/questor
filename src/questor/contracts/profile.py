"""L0 权限词汇：mode 规范值域 + profile → 收紧预设（OPT-3/OPT-4 c3；ADR-0052）。

为什么放在 contracts：这是**词汇**，不是机制。mode 的合法值域、profile 的收紧预设都是数据 +
纯函数；kernel/state/surfaces 只引用它，禁止各自再写字面集（OPT-3 c4 就是把 5 处 Python 侧真源
收到这里）。wire 真源仍是 ``protocol/event.schema.json``——本文件不替代它，只保证 Python 侧
「只有一处说得出合法 mode 是什么」。

三条红线：
1. **不做别名/大小写映射**：:func:`normalize` 只认 canonical 精确值，未知回落 ``default`` 且不抛。
   放宽词表是**行为变更**（HTTP/委托目前对非精确值一律拒），在 wire 真源同步前 Python 侧不得先"宽容"。
2. **预设只收紧**：:class:`PermissionPreset` 只携带收紧旋钮（mode 只许更严、审批只许更严、
   ``enforce_read_only``/``protect_sensitive_paths`` 只许加），**绝不放宽 capability floor**——
   floor 只由 sandbox + capability 事实决定（``kernel.capability_floor``，C9/C17）。
3. **纯数据 + 纯函数**：只 import stdlib；不读 env、不碰 IO、不持有句柄（C1/C4）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

#: 规范 mode 字面值（大小写敏感；与 5 处历史真源逐字一致）。
MODE_PLAN = "plan"
MODE_DEFAULT = "default"
MODE_FULL_AUTO = "full_auto"

#: 协议枚举顺序（wire 现状）：``delegate`` 参数 schema / ``permission_mode_changed.mode`` 均按此序，
#: 顺序参与 ``ProviderRequest.tools`` 的字节形态，**不得**为了"看着顺眼"重排。
PERMISSION_MODES: tuple[str, ...] = (MODE_DEFAULT, MODE_PLAN, MODE_FULL_AUTO)

#: 合法 mode 精确集（判定用）：未知值一律拒绝/回落，绝不推断。
PERMISSION_MODE_SET: frozenset[str] = frozenset(PERMISSION_MODES)

#: 宽松度序（越大越宽）：子权限投影据此夹取（子 ⊆ 父，永不放大，ADR-0040）。
PERMISSION_MODE_RANK: Mapping[str, int] = MappingProxyType({MODE_PLAN: 0, MODE_DEFAULT: 1, MODE_FULL_AUTO: 2})

#: profile 名（**不是** mode 别名）：给某一束收紧旋钮起的名字，用于把"更严"表达成可复用词汇。
PROFILE_DEFAULT = "default"
PROFILE_READ_ONLY = "read_only"

#: 全部已知 profile（顺序仅用于展示；未知一律回落 default）。
PROFILES: tuple[str, ...] = (PROFILE_DEFAULT, PROFILE_READ_ONLY)


@dataclass(frozen=True, slots=True)
class PermissionPreset:
    """一个 profile 映射出的**收紧**旋钮（frozen 纯数据）。

    字段语义：
    - ``mode``：``None`` = 不改当前 mode；非 None 只许**更严或相等**（rank ≤ 当前），
      故预设不可能借 mode 放宽任何判定；
    - ``approval_policy``：``"ask"``（默认）或 ``"never"``（把 ask 直接降为 deny，更严）；
    - ``protect_sensitive_paths``：保持内置敏感路径拦截（只许 True）；
    - ``enforce_read_only``：拒绝一切非只读工具（只许加）。

    这里**没有**任何能改 sandbox/capability 的字段：capability floor 不随 profile 变化（C9/C17）。
    """

    profile: str
    mode: str | None
    approval_policy: str
    protect_sensitive_paths: bool
    enforce_read_only: bool


#: profile → 预设。只读映射（ProxyType）：L0 词汇表不允许被运行时改写。
_PRESETS: Mapping[str, PermissionPreset] = MappingProxyType(
    {
        PROFILE_DEFAULT: PermissionPreset(
            profile=PROFILE_DEFAULT,
            mode=None,
            approval_policy="ask",
            protect_sensitive_paths=True,
            enforce_read_only=False,
        ),
        PROFILE_READ_ONLY: PermissionPreset(
            profile=PROFILE_READ_ONLY,
            mode=MODE_PLAN,
            approval_policy="ask",
            protect_sensitive_paths=True,
            enforce_read_only=True,
        ),
    }
)


def normalize(raw: str | None) -> str:
    """把外部来的 mode 字符串收敛到 canonical 值；未知/None → ``default``（**不抛**）。

    只做精确匹配：不做 ``strip``/大小写/别名映射——那些都会悄悄放宽 HTTP 端点与委托参数的
    拒收面（行为变更）。调用方仍需按 ``PERMISSION_MODE_SET`` 决定"接受还是拒绝"；
    本函数只用于"要一个合法默认值"的场景（如展示、状态回落）。
    """
    return raw if raw in PERMISSION_MODE_SET else MODE_DEFAULT


def permission_preset_for(profile: str | None) -> PermissionPreset:
    """profile → 收紧预设；未知/None 回落 default 预设（不抛，fail-safe 到最保守的"无收紧"）。

    "fail-safe"在这里指**不改变现状**：default 预设不给任何收紧旋钮，等价于不套用预设；
    套用只可能更严，绝不会更宽（预设没有放宽字段）。
    """
    return _PRESETS.get(profile or "", _PRESETS[PROFILE_DEFAULT])


__all__ = [
    "MODE_DEFAULT",
    "MODE_FULL_AUTO",
    "MODE_PLAN",
    "PERMISSION_MODES",
    "PERMISSION_MODE_RANK",
    "PERMISSION_MODE_SET",
    "PROFILES",
    "PROFILE_DEFAULT",
    "PROFILE_READ_ONLY",
    "PermissionPreset",
    "normalize",
    "permission_preset_for",
]
