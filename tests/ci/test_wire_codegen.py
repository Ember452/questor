"""契约 codegen 守卫：schema 与生成物四向漂移即红。

四向 = (改 schema 不改生成物 | 改生成物不改 schema) × (缺字段 | 多字段)。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "protocol" / "app-wire.schema.json"
GENERATOR = REPO / "scripts" / "codegen" / "gen_wire_py.py"
GENERATED = REPO / "src" / "questorharness" / "bootstrap" / "hosts" / "serve" / "wire_types.py"


def _run(schema: Path, out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """在给定的 schema/输出对上跑生成器。"""
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--schema", str(schema), "--out", str(out), *extra],
        capture_output=True,
        text=True,
        check=False,
    )


def test_repository_generated_file_is_current() -> None:
    """仓内生成物必须与 schema 同步。"""
    result = _run(SCHEMA, GENERATED, "--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_schema_change_without_regeneration_is_red(tmp_path: Path) -> None:
    """改 schema 不重新生成 → 红。"""
    schema = tmp_path / "schema.json"
    out = tmp_path / "wire_types.py"
    shutil.copy(SCHEMA, schema)
    assert _run(schema, out).returncode == 0
    schema.write_text(schema.read_text(encoding="utf-8").replace('"text"', '"text2"', 1), "utf-8")
    result = _run(schema, out, "--check")
    assert result.returncode == 1
    assert "stale" in result.stdout


def test_generated_edit_without_schema_is_red(tmp_path: Path) -> None:
    """手改生成物 → 红。"""
    schema = tmp_path / "schema.json"
    out = tmp_path / "wire_types.py"
    shutil.copy(SCHEMA, schema)
    assert _run(schema, out).returncode == 0
    out.write_text(out.read_text(encoding="utf-8") + "\n# hand edit\n", "utf-8")
    assert _run(schema, out, "--check").returncode == 1


def test_missing_definition_is_red(tmp_path: Path) -> None:
    """生成物少一个定义（缺字段方向）→ 红。"""
    schema = tmp_path / "schema.json"
    out = tmp_path / "wire_types.py"
    shutil.copy(SCHEMA, schema)
    assert _run(schema, out).returncode == 0
    text = out.read_text(encoding="utf-8").replace("class Notice(TypedDict):", "class NoticeX(TypedDict):")
    out.write_text(text, "utf-8")
    assert _run(schema, out, "--check").returncode == 1


def test_unknown_keyword_fails_loudly(tmp_path: Path) -> None:
    """schema 用了生成器不认识的键 → 直接失败，不静默忽略。"""
    schema = tmp_path / "schema.json"
    out = tmp_path / "wire_types.py"
    shutil.copy(SCHEMA, schema)
    broken = schema.read_text(encoding="utf-8").replace('"type": "string"', '"type": "string", "format": "x"', 1)
    schema.write_text(broken, "utf-8")
    result = _run(schema, out)
    assert result.returncode != 0
    assert "unsupported schema keywords" in (result.stdout + result.stderr)
