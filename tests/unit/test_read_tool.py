"""P1 T5 DoD —— read 工具：在 workspace 根内读，拒绝越界/缺失。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.read import ReadTool


class _Ctx:
    def __init__(self, root: Path, cancelled: bool = False) -> None:
        self.workspace_root = root
        self.cwd = root
        self._cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled

    def report_progress(self, message: str) -> None:  # pragma: no cover - unused
        pass

    def emit_progress(self, payload: dict) -> None:  # pragma: no cover - unused
        pass


async def test_read_returns_file_content(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi questor", encoding="utf-8")
    res = await ReadTool().execute({"file_path": "hello.txt"}, _Ctx(tmp_path))
    assert res.status == "success"
    assert res.result == "hi questor"


async def test_read_refuses_escape(tmp_path: Path) -> None:
    res = await ReadTool().execute({"file_path": "../outside.txt"}, _Ctx(tmp_path))
    assert res.status == "error"
    assert "escapes" in res.result


async def test_read_missing_file(tmp_path: Path) -> None:
    res = await ReadTool().execute({"file_path": "nope.txt"}, _Ctx(tmp_path))
    assert res.status == "error"


async def test_read_honours_cancel(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    res = await ReadTool().execute({"file_path": "a.txt"}, _Ctx(tmp_path, cancelled=True))
    assert res.status == "error"
    assert res.result == "cancelled"
