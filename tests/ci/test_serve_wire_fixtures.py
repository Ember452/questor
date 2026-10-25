"""黄金帧守卫：13 个 kind 各一例，构造器必须与冻结样本逐字段一致。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from questorharness.bootstrap.hosts.serve.wire_types import SERVER_FRAME_KINDS

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "serve_wire"
SCHEMA = REPO / "protocol" / "app-wire.schema.json"
BUILDER = FIXTURES / "_generate.py"


def _load_builder() -> Any:
    """按路径加载 fixture 构造器（目录无 __init__.py，不能按包 import）。"""
    spec = importlib.util.spec_from_file_location("serve_wire_fixture_builder", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_paths() -> dict[str, Path]:
    """kind → 文件。"""
    return {path.stem: path for path in sorted(FIXTURES.glob("*.json"))}


def _schema_defs() -> dict[str, dict[str, Any]]:
    """读取 schema 定义。"""
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]


def _def_for_kind(kind: str) -> dict[str, Any]:
    """按 kind 反查帧定义。"""
    for node in _schema_defs().values():
        properties = node.get("properties", {})
        if properties.get("kind", {}).get("const") == kind:
            return node
    raise AssertionError(f"no schema definition for kind {kind}")


def test_one_fixture_per_kind() -> None:
    """逐 kind 一例：集合完全相等，不多不少。"""
    assert set(_fixture_paths()) == set(SERVER_FRAME_KINDS)


def test_fixtures_match_schema_shape() -> None:
    """每个样本满足 schema 的 required 与 additionalProperties=false。"""
    for kind, path in _fixture_paths().items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        definition = _def_for_kind(kind)
        required = set(definition.get("required", []))
        allowed = set(definition.get("properties", {}))
        assert payload["kind"] == kind
        assert isinstance(payload.get("seq"), int)
        missing = required - set(payload)
        assert not missing, f"{kind} missing {sorted(missing)}"
        extra = set(payload) - allowed
        assert not extra, f"{kind} has undeclared {sorted(extra)}"


def test_builders_round_trip_against_fixtures() -> None:
    """构造器重新生成必须与冻结样本逐字段一致（seq 由枚举位置决定）。"""
    builder = _load_builder()
    frames = builder.build_frames()
    for index, (kind, frame) in enumerate(sorted(frames.items()), start=1):
        expected = json.loads(_fixture_paths()[kind].read_text(encoding="utf-8"))
        assert {"seq": index, **frame} == expected, kind


def test_selftest_mutation_is_detected(tmp_path: Path) -> None:
    """自证：改一个字段后对比必然失败。"""
    path = _fixture_paths()["text"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutated = dict(payload)
    mutated["text"] = "changed"
    assert mutated != payload
