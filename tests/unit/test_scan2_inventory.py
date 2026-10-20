"""PLAN SCAN-2：全量 tests/ 覆盖清单（结构性判据，不硬编码易漂数字）。

 SCAN-2 的老毛病是"只数顶层"，漏掉 `tests/unit/{capabilities,observability}` 这类子目录，
以及 support fixture 完全没盘。本测试把**口径**钉成可执行的：

1. 每个桶都非空（空桶=扫描面静默缩小，不是"通过"）；
2. 各桶之和 == tests/ 下 .py 总数（新增目录必须显式登记，否则立刻红）；
3. support fixture 基建在清单里可见（它们不是 `test_*.py`，但计划里的回归门会点名它们）；
4. 每个桶的文件名唯一（同名跨桶会让"点名现有测试"的口径歧义）。

刻意**不断言绝对数字**：数字随每刀变化，硬编码只会制造噪声红（与
`check_doc_cross_refs.EXPECTED` 的机械计数分工不同，那边负责数、这边负责形状）。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
_BUCKETS = ("unit", "integration", "support", "evals", "e2e")


def _py_files(root: Path) -> list[Path]:
    return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]


def test_every_bucket_is_non_empty() -> None:
    for bucket in _BUCKETS:
        files = _py_files(_TESTS / bucket)
        assert files, f"bucket {bucket!r} resolved to zero files (SCAN-2 blind spot again)"


def test_buckets_sum_to_the_total_so_a_new_directory_cannot_hide() -> None:
    total = len(_py_files(_TESTS))
    counts = Counter({bucket: len(_py_files(_TESTS / bucket)) for bucket in _BUCKETS})
    root_level = len([p for p in _TESTS.glob("*.py")])
    assert sum(counts.values()) + root_level == total, (
        f"tests/ has files outside the known buckets ({dict(counts)} + {root_level} != {total}); "
        "add a bucket here and register it in check_doc_cross_refs.EXPECTED"
    )


def test_support_fixtures_are_visible_and_named() -> None:
    names = {p.name for p in _py_files(_TESTS / "support")}
    assert {"mcp_demo_server.py", "tool_ctx.py", "__init__.py"} <= names, names


def test_unit_subdirectories_are_counted_not_just_top_level() -> None:
    """旧口径只数顶层，漏掉 capabilities/observability 两个子树（SCAN-2 的原病）。"""
    subdirs = {p.parent.relative_to(_TESTS / "unit").parts[0] for p in _py_files(_TESTS / "unit") if p.parent != _TESTS / "unit"}
    assert {"capabilities", "observability"} <= subdirs, subdirs
    nested = [p for p in _py_files(_TESTS / "unit") if len(p.relative_to(_TESTS / "unit").parts) > 1]
    assert len(nested) > 20, f"expected the nested unit subtrees to be inventoried, got {len(nested)}"


def test_test_file_names_are_unique_across_buckets() -> None:
    names = [p.name for bucket in _BUCKETS for p in _py_files(_TESTS / bucket) if p.name.startswith("test_")]
    duplicates = {name for name, count in Counter(names).items() if count > 1}
    assert not duplicates, f"duplicate test file names across buckets: {sorted(duplicates)}"


@pytest.mark.parametrize("bucket", _BUCKETS)
def test_bucket_paths_exist(bucket: str) -> None:
    assert (_TESTS / bucket).is_dir()
