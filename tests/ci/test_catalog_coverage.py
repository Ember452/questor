"""catalog 契约守卫：schema 的 kind 枚举必须等于 provider 注册表键集合。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from questorharness.bootstrap.hosts.serve.catalog import KINDS, PROVIDERS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "protocol" / "app-wire.schema.json"
KIND_ENUM_RE = re.compile(r'"kind":\s*\{\s*"enum":\s*\[(?P<body>[^\]]*)\]', re.S)


def _declared_kinds(text: str) -> set[str]:
    """取出 CatalogResponse 里的 kind 枚举（只匹配 name/label 那个对象块）。"""

    for match in KIND_ENUM_RE.finditer(text):
        values = {item.strip().strip('"') for item in match.group("body").split(",")}
        if "sessions" in values:
            return {value for value in values if value}
    return set()


def test_schema_declares_the_catalog_kind_enum() -> None:
    text = SCHEMA.read_text(encoding="utf-8")
    assert "CatalogResponse" in text, "schema 缺少 CatalogResponse 定义"
    assert _declared_kinds(text), "CatalogResponse 的 kind 枚举没有解析到"


def test_schema_kinds_equal_provider_registry() -> None:
    """左边多 = 声明了没有实现的 kind；右边多 = 实现了没登记的 kind。"""

    declared = _declared_kinds(SCHEMA.read_text(encoding="utf-8"))
    assert declared == set(KINDS) == set(PROVIDERS)


def test_catalog_response_is_not_a_server_frame() -> None:
    """catalog 响应进 ServerFrame 联合会触发 cardSlots 全等守卫（§2.3）。"""

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    frame_refs = [
        entry["$ref"].rsplit("/", 1)[-1]
        for entry in schema["$defs"]["ServerFrame"]["oneOf"]
    ]
    assert "CatalogResponse" not in frame_refs


def test_parser_self_test() -> None:
    sample = '{"kind": {"enum": ["sessions", "models"]}}'
    assert _declared_kinds(sample) == {"sessions", "models"}
