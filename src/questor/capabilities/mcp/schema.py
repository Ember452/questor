"""L3 远程 MCP inputSchema → provider 兼容 JSON Schema 归一（C18；`docs/plan/05` T3）。

改造自 DeepCode `core/mcp/schema.py:8-39`（MIT）：把不可信的远程 schema 归一成 provider 可用的
形状——非 object 根退化为空对象、`type:[X,null]` 折叠为 `X`+`nullable`、`oneOf/anyOf` 含单一 null
分支时并入、object 补 `properties`/`required`。纯函数、递归、绝不崩（形状异常也产出可用结构）。
"""

from __future__ import annotations

from typing import Any


def normalize_mcp_schema(schema: Any) -> dict[str, Any]:
    """递归归一一段 JSON Schema；非 dict 输入返回空对象 schema。"""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    normalized = dict(schema)
    raw_type = normalized.get("type")
    if isinstance(raw_type, list):
        non_null = [item for item in raw_type if item != "null"]
        if "null" in raw_type and len(non_null) == 1:
            normalized["type"] = non_null[0]
            normalized["nullable"] = True
    for key in ("oneOf", "anyOf"):
        branch = _nullable_branch(normalized.get(key))
        if branch is not None:
            merged = {name: value for name, value in normalized.items() if name != key}
            merged.update(branch)
            merged["nullable"] = True
            normalized = merged
            break
    properties = normalized.get("properties")
    if isinstance(properties, dict):
        normalized["properties"] = {
            name: normalize_mcp_schema(value) if isinstance(value, dict) else value
            for name, value in properties.items()
        }
    if isinstance(normalized.get("items"), dict):
        normalized["items"] = normalize_mcp_schema(normalized["items"])
    if normalized.get("type") == "object":
        normalized.setdefault("properties", {})
        normalized.setdefault("required", [])
    return normalized


def _nullable_branch(options: Any) -> dict[str, Any] | None:
    """`oneOf/anyOf` 恰含一个 null + 一个非 null 分支时返回该非 null 分支，否则 None。"""
    if not isinstance(options, list):
        return None
    non_null: list[dict[str, Any]] = []
    saw_null = False
    for option in options:
        if not isinstance(option, dict):
            return None
        if option.get("type") == "null":
            saw_null = True
        else:
            non_null.append(option)
    return non_null[0] if saw_null and len(non_null) == 1 else None
