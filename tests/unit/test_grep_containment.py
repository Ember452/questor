"""grep containment：不得经 symlink/junction 读入 workspace root 之外的内容（BLK-12/MAJ-9）。

grep 是 READONLY → 权限恒 ALLOW、无审批门，故路径 containment 是它的唯一屏障。修复前 grep 用
``os.walk`` + ``read_text`` 跟随文件 symlink/目录 junction 越界；与 glob 对齐补 resolve+relative_to 跳过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.capabilities.tools.grep import GrepTool
from support.tool_ctx import FakeToolContext


async def test_grep_finds_in_root_file(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("NEEDLE_INSIDE\n", encoding="utf-8")
    ctx = FakeToolContext(ws)
    r = await GrepTool().execute({"pattern": "NEEDLE_INSIDE"}, ctx)
    assert "NEEDLE_INSIDE" in (r.result or ""), "containment 修复不应过度拦截 root 内文件"


async def test_grep_skips_file_symlink_outside_root(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "out"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("OUTSIDE_TOKEN\n", encoding="utf-8")
    link = ws / "link.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError) as exc:  # Windows 建符号链接需开发者模式/管理员
        pytest.skip(f"file symlink needs privilege on this host: {exc}")
    ctx = FakeToolContext(ws)
    r = await GrepTool().execute({"pattern": "OUTSIDE_TOKEN"}, ctx)
    assert "OUTSIDE_TOKEN" not in (r.result or ""), f"grep 读入了 root 外 symlink 内容（BLK-12）：{r.result!r}"
