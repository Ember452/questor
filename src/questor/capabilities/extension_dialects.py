"""L3 六方言 → ExtensionDescriptor 映射（B5；v3 §5.1/§5.2，OPT-5）。

"方言"指今天各自有注册/解析形状的六类扩展点：策略、工具、记忆、压缩、权限、provider。
本模块只做**声明期映射**（descriptor 数据表），不接管它们的运行期解析：

- 策略仍由 `PolicyRegistry` 解析；工具仍由 `ToolRegistry`；记忆/压缩/权限/provider 仍由各自
  组合根字段注入。
- 映射的价值是让 `inspect-extensions` 与守卫能**静态检查**六方言是否都落在 13 个封闭点位内，
  而不是为每个子系统再造一套注册表（防"新万能 DI"）。

matcher 只给带键点位；``provider`` 在 ``SessionStart`` 用 ``source`` 键（provider 选择发生在
会话起点），``memory`` 在 ``Stop`` 不带 matcher（settle 是全量观察者）。
"""

from __future__ import annotations

from questor.contracts.extension import ExtensionDescriptor, ExtensionKind, InterceptionPoint

#: 六方言的稳定名字（顺序即 inspect 输出顺序）。
DIALECTS: tuple[str, ...] = ("policy", "tool", "memory", "compaction", "permission", "provider")

_DESCRIPTORS: dict[str, ExtensionDescriptor] = {
    "policy": ExtensionDescriptor(
        id="dialect:policy",
        kind=ExtensionKind.TRANSFORM,
        at=InterceptionPoint.USER_PROMPT_SUBMIT.value,
        priority=100,
    ),
    "tool": ExtensionDescriptor(
        id="dialect:tool",
        kind=ExtensionKind.DECISION,
        at=InterceptionPoint.PRE_TOOL_USE.value,
        priority=100,
    ),
    "memory": ExtensionDescriptor(
        id="dialect:memory",
        kind=ExtensionKind.OBSERVE,
        at=InterceptionPoint.STOP.value,
        priority=90,
    ),
    "compaction": ExtensionDescriptor(
        id="dialect:compaction",
        kind=ExtensionKind.TRANSFORM,
        at=InterceptionPoint.PRE_COMPACT.value,
        matcher={"trigger": "auto"},
        priority=100,
    ),
    "permission": ExtensionDescriptor(
        id="dialect:permission",
        kind=ExtensionKind.DECISION,
        at=InterceptionPoint.PERMISSION_REQUEST.value,
        priority=100,
    ),
    "provider": ExtensionDescriptor(
        id="dialect:provider",
        kind=ExtensionKind.TRANSFORM,
        at=InterceptionPoint.SESSION_START.value,
        priority=100,
    ),
}


def dialect_descriptors() -> tuple[ExtensionDescriptor, ...]:
    """六方言的 descriptor（顺序稳定，供 inspect/守卫遍历）。"""
    return tuple(_DESCRIPTORS[name] for name in DIALECTS)


def descriptor_for(dialect: str) -> ExtensionDescriptor:
    """取单个方言的 descriptor；未知方言抛 ValueError（封闭词表，不猜）。"""
    try:
        return _DESCRIPTORS[dialect]
    except KeyError as exc:
        raise ValueError(f"unknown extension dialect {dialect!r}; known: {DIALECTS}") from exc


__all__ = ["DIALECTS", "descriptor_for", "dialect_descriptors"]
