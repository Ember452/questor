"""把 app-wire 的 JSON Schema 生成 Python 类型。

单一真源是 ``protocol/app-wire.schema.json``；本脚本只用标准库，输出必须
逐字节稳定（``--check`` 用它判定漂移）。遇到不认识的 schema 关键字直接失败，
不静默忽略——静默忽略会让生成物悄悄少字段。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

# 根节点允许的元信息键。
_ROOT_KEYS: Final[frozenset[str]] = frozenset(
    {"$schema", "$id", "title", "description", "$comment", "oneOf", "$defs"}
)
# 对象节点允许的键。
_OBJECT_KEYS: Final[frozenset[str]] = frozenset(
    {"type", "description", "properties", "required", "additionalProperties", "oneOf"}
)
# 标量/数组/联合节点允许的键。
_VALUE_KEYS: Final[frozenset[str]] = frozenset(
    {"type", "description", "enum", "const", "items", "$ref", "oneOf", "additionalProperties"}
)

_SCALARS: Final[dict[str, str]] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}

_HEADER: Final[str] = '''"""AUTO-GENERATED from protocol/app-wire.schema.json. DO NOT EDIT."""

# ruff: noqa
# fmt: off

from __future__ import annotations

from typing import Final, Literal, NotRequired, TypedDict, Union
'''


def _fail(path: str, message: str) -> None:
    """打印定位信息并以非零码退出。"""
    raise SystemExit(f"gen_wire_py: {path}: {message}")


def _check_keys(node: dict[str, Any], allowed: frozenset[str], path: str) -> None:
    """拒绝不认识的键，避免生成器悄悄丢语义。"""
    unknown = sorted(set(node) - allowed)
    if unknown:
        _fail(path, f"unsupported schema keywords: {', '.join(unknown)}")


def _ref_name(node: dict[str, Any], path: str) -> str:
    """解析 ``#/$defs/Name`` 形式的引用。"""
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        _fail(path, f"only local #/$defs refs are supported, got {ref!r}")
    return ref[len("#/$defs/") :]


def _literal(values: list[Any]) -> str:
    """把 const/enum 的值渲染成 Literal[...]。"""
    rendered = []
    for value in values:
        if isinstance(value, str):
            rendered.append(json.dumps(value, ensure_ascii=False))
        elif isinstance(value, bool):
            rendered.append("True" if value else "False")
        else:
            rendered.append(str(value))
    return f"Literal[{', '.join(rendered)}]"


def _type_of(node: dict[str, Any], path: str) -> str:
    """把单个 schema 节点转换为 Python 类型表达式。"""
    _check_keys(node, _VALUE_KEYS | {"properties", "required"}, path)
    if "$ref" in node:
        return _ref_name(node, path)
    if "oneOf" in node:
        members = [_type_of(item, f"{path}.oneOf[{index}]") for index, item in enumerate(node["oneOf"])]
        return f"Union[{', '.join(members)}]"
    if "const" in node:
        return _literal([node["const"]])
    if "enum" in node:
        return _literal(list(node["enum"]))
    declared = node.get("type")
    if declared in _SCALARS:
        return _SCALARS[declared]
    if declared == "array":
        items = node.get("items")
        if not isinstance(items, dict):
            _fail(path, "array without items")
        return f"list[{_type_of(items, f'{path}.items')}]"
    if declared == "object":
        extra = node.get("additionalProperties")
        if isinstance(extra, dict):
            return f"dict[str, {_type_of(extra, f'{path}.additionalProperties')}]"
        if extra is False:
            return "dict[str, object]"
        _fail(path, "object without additionalProperties")
    _fail(path, f"unsupported type {declared!r}")
    raise AssertionError("unreachable")


def _typed_dict(name: str, node: dict[str, Any], path: str) -> str:
    """把一个 object 定义渲染成 TypedDict。"""
    _check_keys(node, _OBJECT_KEYS, path)
    properties = node.get("properties")
    if not isinstance(properties, dict):
        _fail(path, "object without properties")
    required = set(node.get("required", []))
    lines = [f"class {name}(TypedDict):"]
    if node.get("description"):
        lines.append(f'    """{node["description"]}"""')
        lines.append("")
    for field_name, field_node in properties.items():
        if not isinstance(field_node, dict):
            _fail(f"{path}.{field_name}", "property must be an object")
        annotation = _type_of(field_node, f"{path}.{field_name}")
        if field_name not in required:
            annotation = f"NotRequired[{annotation}]"
        lines.append(f"    {field_name}: {annotation}")
    if len(lines) == 1:
        lines.append("    pass")
    return "\n".join(lines)


def _union_alias(name: str, node: dict[str, Any], path: str) -> str:
    """把只有 oneOf 的定义渲染成类型别名。"""
    members = [_ref_name(item, f"{path}.oneOf[{index}]") for index, item in enumerate(node["oneOf"])]
    return f"{name} = Union[{', '.join(members)}]"


def _render(schema: dict[str, Any]) -> str:
    """渲染完整模块文本。"""
    _check_keys(schema, _ROOT_KEYS, "#")
    defs = schema.get("$defs")
    if not isinstance(defs, dict) or not defs:
        _fail("#/$defs", "missing or empty")

    blocks: list[str] = []
    aliases: list[str] = []
    kind_by_def: dict[str, str] = {}
    for name in sorted(defs):
        node = defs[name]
        if not isinstance(node, dict):
            _fail(f"#/$defs/{name}", "definition must be an object")
        path = f"#/$defs/{name}"
        if "oneOf" in node and "properties" not in node:
            aliases.append(_union_alias(name, node, path))
        elif node.get("type") == "object" and "properties" not in node:
            aliases.append(f"{name} = {_type_of(node, path)}")
        else:
            blocks.append(_typed_dict(name, node, path))
            kind = (node.get("properties") or {}).get("kind", {}).get("const")
            if isinstance(kind, str):
                kind_by_def[name] = kind

    frame_node = defs.get("ServerFrame")
    if not isinstance(frame_node, dict):
        _fail("#/$defs/ServerFrame", "missing")
    frame_kinds = sorted({kind_by_def[_ref_name(item, "#/$defs/ServerFrame")] for item in frame_node["oneOf"]})

    constants: list[str] = []
    for name, kind in sorted(kind_by_def.items(), key=lambda item: item[1]):
        constant = "KIND_" + kind.upper().replace(".", "_")
        constants.append(f'{constant}: Final[str] = {json.dumps(kind)}')

    body = _HEADER + "\n\n" + "\n\n\n".join(blocks) + "\n\n\n" + "\n\n\n".join(aliases)
    body += "\n\n\n" + "\n".join(constants) + "\n"
    body += "\n\nSERVER_FRAME_KINDS: Final[frozenset[str]] = frozenset(\n    {\n"
    for kind in frame_kinds:
        body += f"        {json.dumps(kind)},\n"
    body += "    }\n)\n"
    body += "\n\nSERVER_FRAME_KIND_BY_DEF: Final[dict[str, str]] = {\n"
    for name in sorted(kind_by_def):
        body += f"    {json.dumps(name)}: {json.dumps(kind_by_def[name])},\n"
    body += "}\n"
    return body


def main(argv: list[str] | None = None) -> int:
    """命令行入口：生成或校验。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="protocol/app-wire.schema.json")
    parser.add_argument("--out", default="src/questorharness/bootstrap/hosts/serve/wire_types.py")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    schema_path = Path(args.schema)
    out_path = Path(args.out)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise SystemExit("gen_wire_py: schema root must be an object")
    rendered = _render(schema)

    if args.check:
        current = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        if current == rendered:
            return 0
        expected = rendered.splitlines()
        actual = current.splitlines()
        for index in range(max(len(expected), len(actual))):
            want = expected[index] if index < len(expected) else "<missing>"
            have = actual[index] if index < len(actual) else "<missing>"
            if want != have:
                print(f"gen_wire_py: {out_path}:{index + 1}: generated file is stale")
                print(f"  expected: {want}")
                print(f"  actual:   {have}")
                break
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"gen_wire_py: wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
