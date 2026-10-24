#!/usr/bin/env python3
"""Generate the skeleton of docs/architecture/NAMESPACES.md (R10).

The generator owns two columns (name, producer); the consumers column is filled
with every tracked file that mentions the name, so no row is ever born empty.
Re-running is idempotent: an existing ``consumers`` cell is kept verbatim, which
is the only hand-maintained part of the document.

Usage:
    uv run python scripts/guards/gen_namespaces.py --write
    uv run python scripts/guards/gen_namespaces.py --check
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import EXIT_OK, EXIT_RED, read_text, tracked_files
    from ._namespace_sources import NAMESPACES, collect_code_names
except ImportError:  # direct script execution
    from _guard_kit import EXIT_OK, EXIT_RED, read_text, tracked_files
    from _namespace_sources import NAMESPACES, collect_code_names

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "docs/architecture/NAMESPACES.md"
HEADER = "<!-- generated skeleton by scripts/guards/gen_namespaces.py; consumers column is reviewed by hand -->"
TABLE_HEAD = "| name | producer | consumers |"
TABLE_SEP = "| --- | --- | --- |"
EMPTY = "—"


def _mentions(root: Path, name: str, producer: str, limit: int = 2) -> list[str]:
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    hits: list[str] = []
    for path in tracked_files(root, ("src",)):
        relative = path.relative_to(root).as_posix()
        if relative == producer:
            continue
        if pattern.search(read_text(path)):
            hits.append(relative)
        if len(hits) >= limit:
            break
    return hits


def _existing_consumers() -> dict[tuple[str, str], str]:
    """Read the current document so hand-edited consumer cells survive."""
    found: dict[tuple[str, str], str] = {}
    if not TARGET.exists():
        return found
    namespace = ""
    for line in read_text(TARGET).splitlines():
        if line.startswith("## "):
            namespace = line[3:].strip()
            continue
        if not line.startswith("| ") or line.startswith("| name ") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            continue
        found[(namespace, cells[0])] = cells[2]
    return found


def render(root: Path) -> str:
    names = collect_code_names(root)
    previous = _existing_consumers()
    lines = [
        "# Namespace registries",
        "",
        HEADER,
        "",
        "每个命名空间一张表：`name` 是模型/用户可见的名字，`producer` 是定义它的文件，",
        "`consumers` 是读取它的文件（生成器填到前两个命中，人可以改）。",
        "同一命名空间内名字唯一（大小写不敏感），表中每个路径都必须真实存在，",
        "代码里出现的名字必须出现在表里——三条断言由 `scripts/guards/check_name_registries.py` 执行。",
        "",
        "`—` 表示生成器没有找到第二个引用点，不是豁免。",
        "",
    ]
    for namespace in NAMESPACES:
        entries = names[namespace]
        lines.append(f"## {namespace}")
        lines.append("")
        lines.append(f"共 {len(entries)} 条。")
        lines.append("")
        lines.append(TABLE_HEAD)
        lines.append(TABLE_SEP)
        for name, producer in entries:
            kept = previous.get((namespace, name))
            if kept is not None:
                consumers = kept
            else:
                hits = _mentions(root, name, producer)
                consumers = " / ".join(f"`{hit}`" for hit in hits) if hits else EMPTY
            lines.append(f"| {name} | `{producer}` | {consumers} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true", help="rewrite the namespace document")
    action.add_argument("--check", action="store_true", help="fail when the document is stale")
    args = parser.parse_args(argv)

    generated = render(REPO_ROOT)
    if args.write:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(generated, encoding="utf-8", newline="\n")
        print(f"namespace document written: {TARGET.relative_to(REPO_ROOT)}")
        return EXIT_OK

    if not TARGET.exists():
        print(f"namespace document missing: {TARGET.relative_to(REPO_ROOT)}", file=sys.stderr)
        return EXIT_RED
    # 与 _guard_kit.read_text 同口径(utf-8-sig):一个 BOM 不该让 --check 永久红。
    if read_text(TARGET) != generated:
        print(
            "namespace document is stale; run `uv run python scripts/guards/gen_namespaces.py --write`",
            file=sys.stderr,
        )
        # 直接给出差异行:这份文档的骨架从真实导入枚举,平台差异(若有)只有
        # 看得到 diff 才能定位,一句 stale 在远端 CI 上等于零信息。
        import difflib

        diff = list(
            difflib.unified_diff(
                read_text(TARGET).splitlines(),
                generated.splitlines(),
                fromfile="NAMESPACES.md (committed)",
                tofile="NAMESPACES.md (rendered here)",
                lineterm="",
                n=1,
            )
        )[:60]
        if diff:
            print("\n".join(diff), file=sys.stderr)
        return EXIT_RED
    print("namespace document: OK (up to date)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
