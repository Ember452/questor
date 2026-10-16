"""P3 T13：真 kill/重启续跑 —— 跨连接与跨 OS 进程两条路径（ROADMAP P3 判据①）。

证明 durable resume 端到端可用：一个 run 把未完成的 `write`（PENDING）落 checkpoint 后进程消失，
重启从持久态续跑；无人批准的危险写**绝不因 resume 而静默执行**（目标文件不落盘）。

- A：跨连接——同一文件先建 checkpoint 并 close，再由**新** SQLiteStore 对象经 CliSurface.resume 续跑。
- B：跨 OS 进程——builder 子进程 persist 后退出（模拟被 kill），`python -m questor --resume` 子进程续跑。
两者都用真实文件 store + 真实 WriteTool/DefaultPermissionEngine，非 fake。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from questor.contracts.common import new_id
from questor.contracts.events import AdvanceTurn, AppendAssistantMessage, SubmitMessage
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role, RunStatus, ToolArgsStatus, ToolCallStatus
from questor.kernel.recovery import rebuild_run
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import to_snapshot
from questor.surfaces.cli import CliSurface

_REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _write_tool_use(victim: str) -> Message:
    return Message(
        id=new_id("msg"),
        role=Role.ASSISTANT,
        seq=0,
        content=(ContentBlock(type="tool_use", tool_use_id="tcw", name="write", input={"file_path": victim, "content": "boom"}, args_status=ToolArgsStatus.VALID, raw_input="{}"),),
    )


async def _persist_pending_write(store_path: str, run_id: str) -> None:
    """reduce 到一个 write 的 PENDING 调用并落 checkpoint（模拟崩溃在权限判定前）。"""
    store = await SQLiteStore(store_path).connect()
    run = Run(run_id=run_id, budget=Budget(max_turns=3, approval_timeout_seconds=1))
    run, _ = reduce(run, SubmitMessage(run_id=run_id, content=Message(id="u", role=Role.USER, content=(ContentBlock(type="text", text="write it"),), seq=0)))
    run, _ = reduce(run, AdvanceTurn(run_id=run_id, turn=1))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run_id, turn=1, message=_write_tool_use("victim.txt")))
    await store.append(run_id, ({"type": "run_started", "data": {"run_id": run_id}},))
    await store.save_checkpoint({"cp_id": new_id("cp"), "run_id": run_id, "seq": run.seq, "turn": run.turn, "kind": "auto", "state_digest": json.dumps(to_snapshot(run)), "pending": ["tcw"]})
    await store.close()


async def test_cross_connection_resume_denies_unapproved_write(tmp_path: Path) -> None:
    run_id = new_id("run")
    db = str(tmp_path / "state.db")
    await _persist_pending_write(db, run_id)  # 第一个"进程"落盘后 close（= 死亡）

    reopened = await SQLiteStore(db).connect()  # 第二个"进程"打开同一文件
    rebuilt = await rebuild_run(reopened, run_id)
    assert rebuilt is not None
    call = next(c for c in rebuilt.tool_ledger.calls if c.tool_call_id == "tcw")
    assert call.status is ToolCallStatus.PENDING  # 崩溃在权限判定前，未被执行

    surface = CliSurface(workspace_root=tmp_path, store=reopened)  # 非 tty → 无人批准
    final = await surface.resume(run_id)
    await reopened.close()

    assert final is not None and final.status is RunStatus.COMPLETED
    assert not (tmp_path / "victim.txt").exists()  # 危险写绝不因 resume 而落盘
    resumed_call = next(c for c in final.tool_ledger.calls if c.tool_call_id == "tcw")
    assert resumed_call.status is ToolCallStatus.DENIED


_BUILDER = """
import asyncio, os, json, sys
sys.path.insert(0, os.path.join({root!r}, "src"))
from questor.contracts.common import new_id
from questor.contracts.events import AdvanceTurn, AppendAssistantMessage, SubmitMessage
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role, ToolArgsStatus
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import to_snapshot

async def main():
    run_id = os.environ["RUN_ID"]
    db = os.environ["QUESTOR_STORE_PATH"]
    store = await SQLiteStore(db).connect()
    run = Run(run_id=run_id, budget=Budget(max_turns=3, approval_timeout_seconds=1))
    run, _ = reduce(run, SubmitMessage(run_id=run_id, content=Message(id="u", role=Role.USER, content=(ContentBlock(type="text", text="go"),), seq=0)))
    run, _ = reduce(run, AdvanceTurn(run_id=run_id, turn=1))
    msg = Message(id=new_id("m"), role=Role.ASSISTANT, seq=0, content=(ContentBlock(type="tool_use", tool_use_id="tcw", name="write", input={{"file_path": "victim.txt", "content": "boom"}}, args_status=ToolArgsStatus.VALID, raw_input="{{}}"),))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run_id, turn=1, message=msg))
    await store.append(run_id, ({{"type": "run_started", "data": {{}}}},))
    await store.save_checkpoint({{"cp_id": new_id("cp"), "run_id": run_id, "seq": run.seq, "turn": run.turn, "kind": "auto", "state_digest": json.dumps(to_snapshot(run)), "pending": ["tcw"]}})
    await store.close()

asyncio.run(main())
"""


@pytest.mark.timeout(180)
def test_os_level_kill_then_cli_resume(tmp_path: Path) -> None:
    run_id = new_id("run")
    db = str(tmp_path / "state.db")
    env = {**os.environ, "QUESTOR_STORE_PATH": db, "RUN_ID": run_id, "PYTHONPATH": str(Path(_REPO_ROOT) / "src")}

    # 进程 1：persist 一个 PENDING write 后退出 —— 等价于被 kill（状态已 durable，进程消失）。
    builder = tmp_path / "builder.py"
    builder.write_text(_BUILDER.format(root=_REPO_ROOT), encoding="utf-8")
    build = subprocess.run([sys.executable, str(builder)], env=env, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert build.returncode == 0, build.stderr

    # 进程 2：全新 OS 进程从同一文件 store 续跑；stdin=DEVNULL（非 tty → 拒绝未批准的危险写）。
    resume = subprocess.run(
        [sys.executable, "-m", "questor", "--resume", run_id],
        env=env,
        cwd=_REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert resume.returncode == 0, resume.stderr
    assert not (tmp_path / "victim.txt").exists()  # 跨进程 resume 也绝不静默执行未批准写
    # 续跑把 run 推到终态：进程内重开 store（用完即关，避免 aiosqlite 线程悬挂）验证它不再"未完成"。
    import asyncio

    async def _check() -> bool:
        s = await SQLiteStore(db).connect()
        try:
            return run_id in await s.list_unfinished_runs()
        finally:
            await s.close()

    assert asyncio.run(_check()) is False
