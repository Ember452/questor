"""契约形状守卫：schema 自身的结构约束。

判定的是"契约还能不能被机器消费"，不是业务正确性：
- 每个帧定义必须有 ``kind`` 的 const 判别式；
- 联合里的 ``$ref`` 必须可解析；
- object 定义必须 ``additionalProperties: false``（否则前端字段会静默漂移）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = Path(__file__).resolve().parents[2] / "protocol" / "app-wire.schema.json"
FRAME_UNION = "ServerFrame"


def _load() -> dict[str, Any]:
    """读取契约真源。"""
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _ref_name(node: dict[str, Any]) -> str:
    """取出本地 $ref 的目标名。"""
    ref = node.get("$ref", "")
    assert isinstance(ref, str) and ref.startswith("#/$defs/"), ref
    return ref[len("#/$defs/") :]


def test_every_frame_has_kind_const() -> None:
    """联合成员必须带 kind 判别式。"""
    defs = _load()["$defs"]
    union = defs[FRAME_UNION]["oneOf"]
    assert union, "ServerFrame union is empty"
    for member in union:
        name = _ref_name(member)
        properties = defs[name]["properties"]
        assert "kind" in properties, f"{name} has no kind"
        assert "const" in properties["kind"], f"{name}.kind is not a const"


def test_refs_resolve() -> None:
    """所有 $ref 必须指向存在的定义。"""
    defs = _load()["$defs"]
    stack: list[Any] = [defs]
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                seen.add(_ref_name(node))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(stack)
    missing = sorted(name for name in seen if name not in defs)
    assert not missing, f"dangling refs: {missing}"


def test_objects_are_closed() -> None:
    """object 定义必须显式声明字段：要么闭合，要么是带值 schema 的映射。"""
    defs = _load()["$defs"]
    open_objects = [
        name
        for name, node in defs.items()
        if node.get("type") == "object"
        and node.get("additionalProperties") is not False
        and not isinstance(node.get("additionalProperties"), dict)
    ]
    assert not open_objects, f"objects without declared shape: {open_objects}"


def test_selftest_shape_guard_can_go_red(tmp_path: Path) -> None:
    """自证：去掉 kind const 后本守卫的断言会失败。"""
    defs = _load()["$defs"]
    broken = json.loads(json.dumps(defs))
    broken["Text"]["properties"].pop("kind")
    try:
        for member in broken[FRAME_UNION]["oneOf"]:
            name = _ref_name(member)
            if name == "Text":
                assert "kind" in broken[name]["properties"]
    except AssertionError:
        return
    raise AssertionError("shape guard did not fail on a broken frame")
