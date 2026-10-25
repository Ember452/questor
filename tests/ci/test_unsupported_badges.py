"""未实现徽标与终端映射表的双向断言（渲染侧真源 ↔ 产品契约真源）。"""

from __future__ import annotations

import re
from pathlib import Path

from questorharness.bootstrap.hosts.terminal import unsupported

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPING = REPO_ROOT / "docs/plan/mapping/terminal-coding.md"
ROW_RE = re.compile(r"^\|\s*([A-Z]\d+)\s*\|[^|]*\|\s*(ready|declared|absent)\s*\|")


def _mapping_statuses(text: str) -> dict[str, str]:
    """从映射表里取出 `id -> status`（表头行不匹配，因为第二列不是 status）。"""
    statuses: dict[str, str] = {}
    for line in text.splitlines():
        match = ROW_RE.match(line)
        if match:
            statuses[match.group(1)] = match.group(2)
    return statuses


def test_mapping_file_exists() -> None:
    """映射表是产品契约真源，不能被静默删除。"""
    assert MAPPING.is_file(), MAPPING


def test_registry_equals_mapping_absent_rows() -> None:
    """左多 = 渲染了一个没有登记的能力；右多 = 真功能黑洞。两边都必须为 0。"""
    statuses = _mapping_statuses(MAPPING.read_text(encoding="utf-8"))
    absent = {key for key, status in statuses.items() if status == "absent"}
    assert absent, "映射表没有任何 absent 行，说明解析器已失效"
    assert set(unsupported.UNSUPPORTED) == absent


def test_mapping_parser_self_test() -> None:
    """自证：少写一行或改错状态，解析结果立刻不同。"""
    sample = (
        "| id | 功能 | status | 载体 |\n"
        "|---|---|---|---|\n"
        "| A1 | 审批第三档 | absent | 徽标 |\n"
        "| A4 | 检查点回滚 | declared | 部分可用 |\n"
    )
    assert _mapping_statuses(sample) == {"A1": "absent", "A4": "declared"}


def test_badge_ids_are_sorted_and_stable() -> None:
    """id 是跨文档契约：顺序稳定，便于 diff 审计。"""
    ids = list(unsupported.UNSUPPORTED)
    assert ids == sorted(ids)
