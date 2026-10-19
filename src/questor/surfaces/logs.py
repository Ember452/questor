"""L6 surfaces：``questor logs`` 只读**消费命令**（DESIGN §14；P10/ADR-0049 刀 3）。

定位：**旁路只读观测**，绝不是第二真相——主干查询走 ``event_log`` 权威（经 StorePort 读），
按日 JSONL 只作"账本外信息"（第三方噪声/provider 原始错误等）的旁路补充，二者按 ``run_id+seq``
合并成时间线。本模块**不写库、不改状态、不触发 GC**；损坏 JSONL 行跳过并计入 ``malformed_lines``。

分层：surfaces 只读 StorePort 抽象（C4，无裸句柄旁路）；不 import kernel 具体实现。
usage session 聚合（TB4/ADR-0041）= 跨 run 读 **durable ``run_completed.usage``**（经 ``replay_global``
的 gseq 派生），**不依赖从不发射的 ``usage_delta``**、不落第二真相、每次现算。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from questor.contracts.events import EventType
from questor.contracts.ports import StorePort


def read_bypass_rows(log_dir: Path, *, run_id: str | None = None) -> tuple[list[dict[str, Any]], int]:
    """只读扫描按日主干 JSONL，返回 (匹配行, 损坏行数)。绝不写/删文件（旁路只读）。

    承 DESIGN §10「跨进程行交错 rare 接受」：坏行跳过并计数，不崩、不引跨进程锁。
    """
    rows: list[dict[str, Any]] = []
    malformed = 0
    if not log_dir.is_dir():
        return rows, malformed
    for path in sorted(log_dir.glob("questor-*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(rec, dict):
                malformed += 1
                continue
            if run_id is None or rec.get("context", {}).get("run_id") == run_id:
                rows.append(rec)
    return rows, malformed


def _token_of(usage: dict[str, Any], *keys: str) -> int:
    """从 usage dict 里按优先级取整数字段（缺则 0）。"""
    for k in keys:
        v = usage.get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return 0


def session_totals(events: Iterable[dict[str, Any]]) -> dict[str, int]:
    """跨 run 聚合 durable ``run_completed.usage``（TB4/ADR-0041）。读侧现算、不落表。

    只认终态 ``run_completed`` 事件里的 usage（唯一 durable 用量真源）；``usage_delta`` 属 live-only
    且生产路径从不发射，**绝不作为聚合源**（对抗评审 MAJ-4）。"""
    total = {"runs_completed": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for env in events:
        if env.get("type") != EventType.RUN_COMPLETED:
            continue
        total["runs_completed"] += 1
        usage = env.get("data", {}).get("usage") or {}
        if not isinstance(usage, dict):
            continue
        inp = _token_of(usage, "input_tokens", "prompt_tokens")
        out = _token_of(usage, "output_tokens", "completion_tokens")
        tot = _token_of(usage, "total_tokens") or (inp + out)
        total["input_tokens"] += inp
        total["output_tokens"] += out
        total["total_tokens"] += tot
    return total


async def run_logs_command(store: StorePort, log_dir: Path, *, run_id: str | None = None, totals: bool = False) -> str:
    """命令主体：读 event_log（权威）+ 旁路 JSONL，产出人读文本输出（stdout）。全程只读。

    - ``totals=True`` → 输出跨 run 的 ``run_completed`` usage 聚合（session 总花费，读侧投影）。
    - 否则 → 合并时间线：账本事件 + 旁路独有信息，按 ``run_id+seq`` 排序。
    """
    if totals:
        events = await store.replay_global(0)
        agg = session_totals(events)
        lines = [
            f"runs_completed={agg['runs_completed']}",
            f"input_tokens={agg['input_tokens']}",
            f"output_tokens={agg['output_tokens']}",
            f"total_tokens={agg['total_tokens']}",
        ]
        return "\n".join(lines)

    # 账本侧（权威）：给定 run 则取该 run 全 seq，否则取全局 catch-up 流。
    if run_id is not None:
        ledger = await store.replay(run_id, 0)
    else:
        ledger = await store.replay_global(0)
    bypass, malformed = read_bypass_rows(log_dir, run_id=run_id)
    # 合并成时间线：账本行 + 旁路行（旁路只补账本没有的 source=event 之外的独有信息，按 seq 归并）。
    merged: list[tuple[int, int, str]] = []  # (run_key_sort, seq, text)
    for idx, env in enumerate(ledger):
        merged.append((0, int(env.get("seq", idx)), f"[ledger] {env.get('type')} seq={env.get('seq')}"))
    for rec in bypass:
        seq = rec.get("fields", {}).get("seq")
        merged.append((1, int(seq) if isinstance(seq, int) else 0, f"[bypass] {rec.get('level')} {rec.get('msg')}"))
    merged.sort(key=lambda t: (t[1], t[0]))
    out = [text for _kind, _seq, text in merged]
    if malformed:
        out.append(f"(skipped {malformed} malformed JSONL lines)")
    if not out:
        out.append("(no log records)")
    return "\n".join(out)
