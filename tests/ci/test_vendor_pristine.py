"""vendored 区守卫：`apps/web` 的每一处改动都必须登记在 VENDOR.md。

规则（与 VENDOR.md 的四个小节一一对应）：
- `基线: <sha>` 必须存在且可解析；
- `git diff <基线> -- apps/web` 的每个路径（相对 apps/web）必须出现在
  `已改` / `已裁` / `新增` 之一；
- `禁区` 里的路径出现任何 diff（含新增）即红。

守卫自带纯函数自证：喂一组假路径，必须能判出未登记项与禁区项。
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VENDOR = REPO / "apps/web/VENDOR.md"
SECTIONS = ("已改", "已裁", "新增")
FORBIDDEN = "禁区"


def _parse(vendor_text: str) -> tuple[str, dict[str, set[str]]]:
    """把 VENDOR.md 拆成（基线 sha，{小节: 路径集合}）。"""
    baseline = ""
    current = ""
    entries: dict[str, set[str]] = {FORBIDDEN: set(), **{name: set() for name in SECTIONS}}
    for raw in vendor_text.splitlines():
        line = raw.strip()
        if line.startswith("基线:"):
            baseline = line.split(":", 1)[1].strip()
            continue
        if line.startswith("## "):
            current = line[3:].strip()
            continue
        if current in entries and (match := re.match(r"^- `([^`]+)`", line)):
            entries[current].add(match.group(1))
    return baseline, entries


def _matches(path: str, patterns: set[str]) -> bool:
    """路径是否命中某小节的任一登记（支持 `**` 通配）。"""
    return any(fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("*")) for pattern in patterns)


def evaluate(changed: list[str], vendor_text: str) -> list[str]:
    """纯函数：返回问题清单（空 = 通过）。"""
    baseline, entries = _parse(vendor_text)
    problems: list[str] = []
    if not baseline:
        problems.append("VENDOR.md: missing `基线: <sha>` line")
    for path in changed:
        if _matches(path, entries[FORBIDDEN]):
            problems.append(f"forbidden path changed: {path}")
            continue
        if not any(_matches(path, entries[name]) for name in SECTIONS):
            problems.append(f"unregistered vendored change: {path}")
    return problems


def _changed_paths(baseline: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", baseline, "--", "apps/web"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return [
        line.strip()[len("apps/web/") :]
        for line in result.stdout.splitlines()
        if line.strip().startswith("apps/web/")
    ]


def test_matcher_self_test() -> None:
    """自证：未登记与禁区两条路径都必须判红。"""
    vendor = (
        "基线: deadbeef\n\n## 禁区\n\n- `src/generated/**`\n\n"
        "## 已改\n\n- `src/app/x.ts`\n\n## 已裁\n\n## 新增\n"
    )
    problems = evaluate(["src/app/x.ts", "src/app/y.ts", "src/generated/a.ts"], vendor)
    assert any("unregistered" in item and "src/app/y.ts" in item for item in problems)
    assert any("forbidden" in item and "src/generated/a.ts" in item for item in problems)
    assert evaluate(["src/app/x.ts"], vendor) == []


def test_vendor_manifest_covers_every_change() -> None:
    """真实守卫：`apps/web` 相对基线的每个变化都在 VENDOR.md 登记。"""
    baseline, _ = _parse(VENDOR.read_text(encoding="utf-8"))
    assert baseline, "VENDOR.md is missing its baseline line"
    problems = evaluate(_changed_paths(baseline), VENDOR.read_text(encoding="utf-8"))
    assert not problems, "; ".join(problems)
