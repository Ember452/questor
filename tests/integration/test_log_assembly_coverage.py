"""刀1 缺陷 A①/A③：组合根装配覆盖四入口 + stdout 洁净。

真子进程走 ``python -m questor``（与 P3 kill/resume 同法），避免 mock 掩盖装配缺口：
- A①：``--resume`` 起手即应有 stderr 日志行（当前实测为零——configure_logging 只在
  ``interactive()`` 里调，``--resume/--list/--dream`` 三条路径裸奔）。
- A③：``--list`` 的 stdout 只含 run id 哨兵、零日志行（console sink 必须绑 stderr，
  否则机器可读的 stdout 被日志污染）。

判红前置：T1.1（装配上移）+ T1.3（显式 stderr handler）实现之前，A① 必红。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from questor.contracts.common import new_id
from questor.contracts.events import SubmitMessage
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import to_snapshot

_REPO_ROOT = str(Path(__file__).resolve().parents[2])

# 一条日志行的形状：format = "%(asctime)s %(levelname)s %(name)s: %(message)s"。
_LOG_LINE_RE = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b.*questor")


async def _seed_resumable_run(store_path: str, run_id: str) -> None:
    """落一条 ``run_started`` + turn 边界 checkpoint，使 ``--resume`` 能重建并 replay（触发 log_event）。"""
    store = await SQLiteStore(store_path).connect()
    run = Run(run_id=run_id, budget=Budget(max_turns=2, approval_timeout_seconds=1))
    run, _ = reduce(
        run,
        SubmitMessage(run_id=run_id, content=Message(id="u", role=Role.USER, content=(ContentBlock(type="text", text="hi"),), seq=0)),
    )
    await store.append(run_id, ({"type": "run_started", "data": {}},))
    await store.save_checkpoint(
        {
            "cp_id": new_id("cp"),
            "run_id": run_id,
            "seq": run.seq,
            "turn": run.turn,
            "kind": "auto",
            "state_digest": json.dumps(to_snapshot(run)),
            "pending": [],
        }
    )
    await store.close()


def _run_cli(args: list[str], db: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "QUESTOR_STORE_PATH": db,
        "QUESTOR_MEMORY_DB": str(Path(db).parent / "memory.db"),
        "QUESTOR_LOG_LEVEL": "INFO",
        # 把文件面定向到 tmp，避免装配生效后在仓里落日分片（新默认是 <cwd>/.questor/logs）。
        "QUESTOR_LOG_DIR": str(Path(db).parent / "logs"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",  # 去联网拉 cost map 的噪声/超时，让 A① 判据确定
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
    }
    return subprocess.run(
        [sys.executable, "-m", "questor", *args],
        env=env,
        cwd=_REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_resume_has_stderr_log_lines(tmp_path: Path) -> None:
    """A①：``--resume`` 起手即有 stderr 日志行（当前实测为零 → 修复前判红）。"""
    run_id = new_id("run")
    db = str(tmp_path / "state.db")
    asyncio.run(_seed_resumable_run(db, run_id))

    proc = _run_cli(["--resume", run_id], db)
    assert proc.returncode == 0, proc.stderr
    # 装配生效（刀2 接新管线）后，--resume 起手即有投影到 stderr 的 questor 事件行（live 队列驱至
    # 终态会 emit run_completed；新版经带外投影 → pipeline → console sink 渲染）。
    assert re.search(r"questor\.events\.run_\w+", proc.stderr), f"expected a projected questor.events.* line on stderr, got: {proc.stderr!r}"
    assert _LOG_LINE_RE.search(proc.stderr), proc.stderr


def test_list_stdout_has_no_log_lines(tmp_path: Path) -> None:
    """A③：``--list`` 的 stdout 只含 run id 哨兵，零日志行。"""
    db = str(tmp_path / "state.db")
    proc = _run_cli(["--list"], db)
    assert proc.returncode == 0, proc.stderr
    assert "(no unfinished runs)" in proc.stdout, proc.stdout
    # 任何日志行都绝不出现在机器可读的 stdout 上。
    assert _LOG_LINE_RE.search(proc.stdout) is None, f"stdout polluted by log lines: {proc.stdout!r}"


def test_dream_has_stderr_log_lines(tmp_path: Path) -> None:
    """A①：``--dream`` 起手即有 stderr 日志行（装配覆盖四入口的另一证明）。

    仅断言"进程不因缺日志装配而崩" + "若配置生效则 stderr 可见 questor 日志"。dream 走
    _amain 起手的 configure_logging，即便无可萃取也有可观测装配面。"""
    db = str(tmp_path / "state.db")
    proc = _run_cli(["--dream"], db)
    assert proc.returncode == 0, proc.stderr
    # --dream 的机器输出（deep_dream: ...）走 stdout，不得有日志行；日志（若有）走 stderr。
    assert _LOG_LINE_RE.search(proc.stdout) is None, f"stdout polluted: {proc.stdout!r}"
