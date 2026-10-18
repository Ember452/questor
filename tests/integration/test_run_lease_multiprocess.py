"""P9 T8：单机多进程 run 租约真验证——两个真 OS 子进程共享一套 SQLite。

DoD⑦ 的"单机多进程=已验证"落点：进程 0 抢租约并**不释放**（模拟持有驱动），进程 1 连同一 db 文件
尝试抢同一 run 租约必被拒 → 恰好一个 WIN、一个 LOSE。证明 ``BEGIN IMMEDIATE`` 单写者 + 租约行
跨进程有效（不是同进程 asyncio 假象）。跨机故障切换仍属 C12 天花板 = UNVERIFIED，不在本测。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])

_ACQUIRE = """
import asyncio, os
from questor.providers.store_sqlite import SQLiteStore

async def main():
    store = await SQLiteStore(os.environ["LEASE_DB"]).connect()
    ok = await store.acquire_lease("run_lease", os.environ["LEASE_HOLDER"], 1, ttl_seconds=60)
    print("WIN" if ok else "LOSE")
    await store.close()

asyncio.run(main())
"""


def _run_acquirer(tmp_path: Path, db: str, holder: str) -> str:
    script = tmp_path / f"acquire_{holder}.py"
    script.write_text(_ACQUIRE, encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
        "LEASE_DB": db,
        "LEASE_HOLDER": holder,
        "NO_PROXY": "127.0.0.1,localhost",
    }
    proc = subprocess.run(
        [sys.executable, str(script)], env=env, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, f"{holder} crashed: {proc.stderr[-500:]}"
    return proc.stdout.strip()


def test_two_processes_single_lease_winner(tmp_path: Path) -> None:
    db = str(tmp_path / "shared.db")
    # 顺序执行：进程 0 抢到且不释放（租约行持久在共享 db），进程 1 必被拒。
    first = _run_acquirer(tmp_path, db, "p0")
    second = _run_acquirer(tmp_path, db, "p1")
    assert [first, second] == ["WIN", "LOSE"], f"租约未拦下双驱：{first}/{second}"
