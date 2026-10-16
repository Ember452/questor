"""T15：文件工具单元覆盖（read/write/edit/apply_patch/ls/glob/grep）。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from support.tool_ctx import FakeToolContext


async def test_read_returns_full_content(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    res = await ReadTool().execute({"file_path": "a.txt"}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert "line1" in res.result and "line3" in res.result


async def test_read_offset_limit_window(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("\n".join(str(i) for i in range(100)), encoding="utf-8")
    res = await ReadTool().execute({"file_path": "big.txt", "offset": 10, "limit": 5}, FakeToolContext(tmp_path))
    assert res.status == "success"
    assert res.result.startswith("10")
    assert "truncated" in res.result


async def test_read_directory_is_error(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    res = await ReadTool().execute({"file_path": "d"}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "directory" in res.result


async def test_read_binary_is_error(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02abc")
    res = await ReadTool().execute({"file_path": "bin.dat"}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "binary" in res.result


async def test_read_escape_denied(tmp_path: Path) -> None:
    res = await ReadTool().execute({"file_path": "../../etc/passwd"}, FakeToolContext(tmp_path))
    assert res.status == "error"
    assert "escapes workspace root" in res.result


async def test_read_cancelled(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    res = await ReadTool().execute({"file_path": "a.txt"}, FakeToolContext(tmp_path, cancelled=True))
    assert res.status == "error"
    assert res.result == "cancelled"
