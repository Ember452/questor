"""组合根入口（composition root）：装配 StorePort 后启动 CLI 传输面。

用 ``python -m questor`` 运行。本模块**可以** import 具体适配器（``SQLiteStore``）——它是
把 L5 实现注入 L6 surfaces 的唯一装配点；surfaces 自身只持 ``StorePort`` 抽象（C4/C14）。

- ``python -m questor``：交互 REPL（每轮真实落库到 store，支撑 resume）。
- ``python -m questor --resume <run_id>``：从持久态续跑被 kill/重启的 run（P3）。
- ``python -m questor --list``：列出未完成的 run id（供选择续跑）。
store 路径取 ``QUESTOR_STORE_PATH``，默认 ``<cwd>/.questor/state.db``（文件，跨进程可见）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface, interactive


def _store_path() -> str:
    return os.environ.get("QUESTOR_STORE_PATH", str(Path.cwd() / ".questor" / "state.db"))


async def _amain(argv: list[str]) -> int:
    path = _store_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    store = await SQLiteStore(path).connect()
    try:
        surface = CliSurface(store=store)
        if argv and argv[0] == "--list":
            unfinished = await store.list_unfinished_runs()
            for run_id in unfinished:
                print(run_id)
            if not unfinished:
                print("(no unfinished runs)")
            return 0
        if argv and argv[0] == "--resume":
            if len(argv) < 2:
                print("usage: python -m questor --resume <run_id>", file=sys.stderr)
                return 2
            final = await surface.resume(argv[1])
            if final is None:
                print(f"no checkpoint for run {argv[1]}", file=sys.stderr)
                return 1
            return 0
        return await interactive(surface)
    finally:
        await store.close()


def main() -> int:
    """CLI 入口；Ctrl-C 退出码 130。"""
    try:
        return asyncio.run(_amain(sys.argv[1:]))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
