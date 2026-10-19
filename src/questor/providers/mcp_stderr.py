"""L5 MCP 子进程 stderr 独立通道 + spawn 侧 run_id 注入（C14/C15；DESIGN §16.4）。

**为什么**（`docs/pitfalls.md` 第 3 条）：MCP server 是子进程，`contextvars`/`bind()` 不过进程边界，
其 stderr 无法靠 ambient 关联到某个 run。故关联只能在 spawn 边界**显式注入**——文件名带 `run_id`（主）、
首行标记（辅）。stderr 走**独立文件**、绝不并入主干 `questor-<date>.jsonl`（C20：第三方输出不进观测面第二载体）。

实现采用 append / 行缓冲 / `errors="replace"` / 不可写退 devnull 的降级策略；
**run_id 注入为本仓设计**——每 run 独立文件、显式关联，不靠共享文件隐式关联。只依赖 stdlib；被 `capabilities/mcp` 或
组合根在起子进程时调用（不落进 observability 内核九文件）。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO


def _is_safe_run_id(run_id: str) -> bool:
    return bool(run_id) and not any(part in {"", ".", ".."} for part in Path(run_id).parts)


def _devnull() -> TextIO:
    return open(os.devnull, "w", encoding="utf-8")


def open_mcp_stderr_log(log_dir: Path, run_id: str) -> TextIO:
    """为某 run 打开 MCP 子进程 stderr 的独立文件，返回可交给 SDK `stdio_client(errlog=…)` 的句柄。

    - 文件名 `mcp-stderr-<run_id>.log`（主关联）+ 首行 `# questor run_id=… ts=…`（辅标记）。
    - `run_id` 必须是安全标识符（含路径分隔/`..` → ValueError），避免目录穿越。
    - 目录不可建/不可写 → 降级到 devnull 句柄、**不抛**（观测面绝不拖垮被观测物）。
    调用方负责在使用完毕后 `close()` 该句柄。
    """
    if not _is_safe_run_id(run_id):
        raise ValueError(f"unsafe run_id for MCP stderr log: {run_id!r}")
    target_dir = Path(log_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        handle = open(
            target_dir / f"mcp-stderr-{run_id}.log",
            "a",
            encoding="utf-8",
            errors="replace",
            buffering=1,  # 行缓冲：子进程输出尽快落盘
        )
    except OSError:
        return _devnull()
    handle.write(f"# questor run_id={run_id} ts={datetime.now(UTC).isoformat()}\n")
    handle.flush()
    return handle
