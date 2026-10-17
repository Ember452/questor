"""刀 2 缺陷审计的端到端判据（Issue #126/#127；DoD A①/A③ 的真实口径）。

为什么必须真子进程 + 真文件面：D4 的"零原文"从来不是 dataclass 层能证明的事——prompt 是从
**第三方库的 DEBUG 日志**（aiosqlite 打印 SQL + 完整参数元组）漏进主干 JSONL 的；而 stdout 污染
来自 litellm 自挂的 `LevelRoutingStreamHandler`（INFO/DEBUG 直写 stdout，降噪名单与级别门管不到
“往哪个流写”）。刀 1 的 A① 就是被"mock 掉装配缺口"放过一次的，所以这里一律跑真进程、真落盘、真 grep。

三条判据在修复前均实测为红：
- prompt canary 出现在日志文件里（4 行，logger=aiosqlite）；
- ``--list`` 的 stdout 混入 ``LiteLLM:DEBUG: ... atexit`` 行；
- ``--list``/``--dream`` 的 stderr 一条一方日志都没有（当时的"有日志"全靠第三方噪声凑数）。
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

#: 一条"只能出现在 stdout 上的机器可读行"的白名单（G-L10/A③）。
#: 为什么用白名单而不是"含 level 关键字即判污"（旧正则 ``r"\\b(DEBUG|...)\\b.*questor"``）：
#: 第三方库的日志行里根本没有 ``questor`` 字样，旧正则对它们天然免疫 —— 判据从来没真正生效过。
_STDOUT_OK = re.compile(r"^(\(no unfinished runs\)|run_[0-9a-z]+|deep_dream: .*)$")


def _env_for(tmp: Path) -> dict[str, str]:
    logs = tmp / "logs"
    return {
        **{k: v for k, v in os.environ.items() if k not in {"QUESTOR_LOG_DIR", "QUESTOR_LOG_LEVEL", "QUESTOR_LOG_PAYLOAD"}},
        "QUESTOR_STORE_PATH": str(tmp / "state.db"),
        "QUESTOR_MEMORY_DB": str(tmp / "memory.db"),
        "QUESTOR_MEMORY_ROOT": str(tmp / "memory_store"),
        "QUESTOR_LOG_DIR": str(logs),
        "QUESTOR_LOG_LEVEL": "INFO",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",  # 去掉 runner/本机联网拉 cost map 的噪声，判据才确定
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
    }


def _run(args: list[str], tmp: Path, stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
    # stdin 与 input 不能同时给：有输入时交给 subprocess 自己建管道，无输入时直接 DEVNULL 使 REPL 即 EOF。
    feed = {"input": stdin_text} if stdin_text is not None else {"stdin": subprocess.DEVNULL}
    return subprocess.run(
        [sys.executable, "-m", "questor", *args],
        env=_env_for(tmp),
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        **feed,
    )


def _log_rows(tmp: Path) -> list[dict]:
    logs = tmp / "logs"
    rows: list[dict] = []
    for f in sorted(logs.glob("*.jsonl")) if logs.exists() else []:
        for line in f.read_bytes().split(b"\n"):
            if line.strip():
                rows.append(json.loads(line))
    return rows


async def _seed_finished_run(store_path: str, run_id: str) -> None:
    """落一条 run_started + turn 边界 checkpoint，使 ``--list`` 真能列出一个 run id（stdout 判据用）。"""
    store = await SQLiteStore(store_path).connect()
    run = Run(run_id=run_id, budget=Budget(max_turns=2, approval_timeout_seconds=1))
    run, _ = reduce(
        run,
        SubmitMessage(run_id=run_id, content=Message(id="u", role=Role.USER, content=(ContentBlock(type="text", text="hi"),), seq=0)),
    )
    await store.append(run_id, ({"type": "run_started", "data": {}},))
    await store.save_checkpoint(
        {"cp_id": new_id("cp"), "run_id": run_id, "seq": run.seq, "turn": run.turn, "kind": "auto", "state_digest": json.dumps(to_snapshot(run)), "pending": []}
    )
    await store.close()


def test_prompt_text_never_lands_in_log_files(tmp_path: Path) -> None:
    """#126：用户 prompt 与 checkpoint 原文绝不进日志文件，同时一方记录仍要落盘。

    后半个断言是关键：只查"文件里没有 canary"会在"文件面整个没写"时假绿（空文件当然不含敏感串）。
    """
    canary = f"CANARY-PROMPT-{new_id('x')}"
    proc = _run([], tmp_path, stdin_text=f"{canary}\n")
    assert proc.returncode == 0, proc.stderr

    rows = _log_rows(tmp_path)
    assert rows, "文件面必须真的写了日志（否则本判据是空集假绿）"
    dumped = json.dumps(rows, ensure_ascii=False)
    assert canary not in dumped, "prompt 原文漏进日志文件（第三方 DEBUG 穿透来源门）"

    first_party = [r for r in rows if str(r["logger"]).startswith("questor.")]
    assert first_party, "一方记录必须落盘（主干文件不能只剩外来噪声或干脆为空）"


def test_list_stdout_is_machine_readable_only(tmp_path: Path) -> None:
    """#127：``--list`` 的 stdout 每一行都必须是机器可读行（哨兵或 run id）。

    修复前实测混入 ``09:46:53 - LiteLLM:DEBUG: logging_worker.py:561 - [LoggingWorker] atexit: ...``
    ——那是 litellm 自己挂在 stdout 上的 `LevelRoutingStreamHandler`（INFO/DEBUG 一路走 stdout），
    而降噪名单只能决定“要不要生成记录”，定不了它往哪个流写。
    """
    run_id = new_id("run")
    asyncio.run(_seed_finished_run(str(tmp_path / "state.db"), run_id))
    proc = _run(["--list"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    bad = [line for line in proc.stdout.splitlines() if line.strip() and not _STDOUT_OK.match(line.strip())]
    assert not bad, f"stdout 混入非机器可读行：{bad}"
    assert run_id in proc.stdout, "列出的 run id 本身也必须还在"


def test_dream_and_list_emit_first_party_log_lines(tmp_path: Path) -> None:
    """DoD A① 的真实口径：``--list``/``--dream`` 起手要有**一方**日志行，不是第三方噪声凑数。"""
    for args in (["--list"], ["--dream"]):
        proc = _run(args, tmp_path)
        assert proc.returncode == 0, proc.stderr
        hits = [line for line in proc.stderr.splitlines() if re.search(r"\bquestor\.[a-z]", line)]
        assert hits, f"{args} 的 stderr 没有一方日志行（装配或自述记录缺失）"
