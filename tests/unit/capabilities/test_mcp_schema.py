"""远程 inputSchema → provider 兼容 JSON Schema 归一的判红用例（C18；`docs/plan/05` T3）。

改造自 DeepCode `core/mcp/schema.py:8-39`：非 object 根退化为空对象 schema；`type:[X,null]`
折叠为 `X` + `nullable`；`oneOf/anyOf` 含单一 null 分支时并入；object 补 properties/required。
纯函数、递归、绝不崩（远程 schema 不可信，形状异常也要归一出可用结构）。"""

from __future__ import annotations

from questor.capabilities.mcp.schema import normalize_mcp_schema


def test_non_object_root_becomes_empty_object_schema() -> None:
    assert normalize_mcp_schema(None) == {"type": "object", "properties": {}}
    assert normalize_mcp_schema("junk") == {"type": "object", "properties": {}}


def test_nullable_type_list_collapses() -> None:
    out = normalize_mcp_schema({"type": ["string", "null"]})
    assert out["type"] == "string"
    assert out["nullable"] is True


def test_object_defaults_properties_and_required() -> None:
    out = normalize_mcp_schema({"type": "object"})
    assert out["properties"] == {}
    assert out["required"] == []


def test_nested_property_normalized() -> None:
    out = normalize_mcp_schema({"type": "object", "properties": {"age": {"type": ["integer", "null"]}}})
    assert out["properties"]["age"]["type"] == "integer"
    assert out["properties"]["age"]["nullable"] is True


def test_oneof_with_single_null_branch_merged() -> None:
    out = normalize_mcp_schema({"oneOf": [{"type": "string"}, {"type": "null"}]})
    assert out["type"] == "string"
    assert out["nullable"] is True
    assert "oneOf" not in out
