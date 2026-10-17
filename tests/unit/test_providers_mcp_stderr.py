"""MCP 子进程 stderr 独立文件 + run_id 注入（C14/C15 单元判红）。

真源：DESIGN §16.4 D-16.4-A/B；`docs/pitfalls.md` 第 3 条（contextvars 不过进程边界→只能显式注入）。
落点=providers（L5）。形状改造自 hermes `mcp_tool_config.py:22-63`（append/行缓冲/errors=replace），
**run_id 注入为自写**（hermes 是单一共享文件、无 per-run 关联）。不可写时降级 devnull（不崩，仿 hermes）。"""

from __future__ import annotations

import pytest

from questor.providers.mcp_stderr import open_mcp_stderr_log


def test_creates_per_run_file_with_run_id_in_name_and_marker(tmp_path) -> None:
    handle = open_mcp_stderr_log(tmp_path / "mcp", "run-42")
    try:
        handle.write("child line\n")
        handle.flush()
    finally:
        handle.close()
    log_file = tmp_path / "mcp" / "mcp-stderr-run-42.log"
    assert log_file.exists()
    text = log_file.read_text(encoding="utf-8")
    assert "run_id=run-42" in text  # 首行标记（辅关联）


def test_unsafe_run_id_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        open_mcp_stderr_log(tmp_path / "mcp", "../escape")


def test_unwritable_dir_degrades_to_devnull_no_raise(tmp_path) -> None:
    # log_dir 位置被一个普通文件占据 → mkdir 失败；须降级、不抛（C14：观测面绝不拖垮被观测物）。
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")
    handle = open_mcp_stderr_log(blocker / "mcp", "run-7")  # 不抛
    assert handle is not None
    handle.write("still works\n")  # 写到 devnull，不崩
    handle.close()
