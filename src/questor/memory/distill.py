"""Deep Dream 离线蒸馏 + run-完成→daily flush（design/06 §1/§3；ADR-0025；T13）。

**离线/维护路径**：不进活 run 热 loop（design/05 §5"只读分支快照重放"）；写经
:class:`MemoryStorePort` **同一收口**（无旁路、无裸句柄，HARD C4）。核心纪律：

- **原子写**：真源 md 经 store 的 ``write_memory_text``/``append_memory_text``（临时文件 + ``os.replace``）。
- **输入 hash 去重**：以"本次喂入的 daily 原料"为 ``idempotency_key`` → 同原料二次运行 **no-op**（不重复重写 core）。
- **只删不编**：provider 判定无可萃取（返回 ``None`` 或空哨兵）即**不写**、绝不杜撰材料外内容。
- **空哨兵跳过**：``无/None/n/a`` 视为无价值。
- **dreams 不进索引**：写 ``memory/dreams/*.md``，``sync`` 映射层排除（防近重复噪声）。

诚实边界：真 LLM 蒸馏**质量** UNVERIFIED；本模块的结构与纪律用注入 provider 测。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from questor.contracts.common import JsonObject, require_aware, utc_now
from questor.contracts.memory import MemoryStorePort

_EMPTY_SENTINELS = frozenset({"", "无", "none", "n/a"})
_DAILY_DATE = re.compile(r"memory/(\d{4}-\d{2}-\d{2})\.md")
#: 蒸馏 provider（通常是 LLM 调用）transient 失败的有界重试次数（承 Cow summarizer 重试纪律）。
_MAX_DISTILL_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class DistillOutcome:
    """一次蒸馏的产物：重写后的 core 精华 + 梦境日记（可各自为空哨兵表示无可萃取）。"""

    new_core: str
    dream: str


class DistillProvider(Protocol):
    """蒸馏算子（通常是一次 LLM 调用；测试用确定性 fake，真 LLM 质量 UNVERIFIED）。

    返回 ``None`` 视为"无可萃取"→ 跳过写（只删不编）。"""

    async def distill(self, core: str, dailies: list[str]) -> DistillOutcome | None: ...


def _is_empty(value: str) -> bool:
    return value.strip().lower() in _EMPTY_SENTINELS


def _batch_hash(dailies: list[str]) -> str:
    """对本次喂入的 daily 原料取语义哈希，作跨运行的去重键（不含可变 core，保证二次同原料 no-op）。"""
    return hashlib.sha256("\x1f".join(dailies).encode("utf-8")).hexdigest()


async def _call_distill(
    provider: DistillProvider, core: str, dailies: list[str], *, attempts: int = _MAX_DISTILL_ATTEMPTS
) -> DistillOutcome | None:
    """有界重试 transient 蒸馏失败（如 LLM 网络抖动）；耗尽后上抛，绝不静默吞（ADR-0025）。

    幂等靠 ``deep_dream`` 的输入哈希键：重投同一原料不会重复写 core。"""
    last: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            return await provider.distill(core, dailies)
        except Exception as exc:  # noqa: BLE001 - transient 重试；最终失败上抛由调用方（CLI/surface）记日志
            last = exc
    assert last is not None  # 循环至少执行一次，last 必非 None
    raise last


def _recent_daily_paths(paths: list[str], *, lookback_days: int, now: datetime) -> list[str]:
    cutoff = (now - timedelta(days=lookback_days)).date()
    today = now.date()
    out: list[str] = []
    for path in paths:
        match = _DAILY_DATE.search(path.replace("\\", "/"))
        if match is None:
            continue
        try:
            day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if cutoff <= day <= today:
            out.append(path)
    return sorted(out)


async def deep_dream(
    store: MemoryStorePort,
    provider: DistillProvider,
    *,
    lookback_days: int = 7,
    now: datetime | None = None,
) -> JsonObject:
    """把近期 daily 蒸馏回 core + 产梦境日记；原子写 + 输入哈希去重 + 只删不编 + 空哨兵跳过。"""
    now = now or utc_now()
    require_aware(now, "deep_dream.now")
    core = await store.read_memory_text("MEMORY.md")
    paths = list(await store.list_memory_paths())
    daily_paths = _recent_daily_paths(paths, lookback_days=lookback_days, now=now)
    dailies = [await store.read_memory_text(p) for p in daily_paths]
    batch = _batch_hash(dailies)
    outcome = await _call_distill(provider, core, dailies)
    if outcome is None or _is_empty(outcome.new_core):
        # 空哨兵跳过：无可萃取即不写、不杜撰（只删不编）。二次同原料亦走此路或命中 ledger，均 no-op。
        return {"wrote": False, "reason": "empty-sentinel", "input_hash": batch}
    date = now.strftime("%Y-%m-%d")
    core_receipt = await store.write_memory_text(
        "MEMORY.md", outcome.new_core.rstrip() + "\n", idempotency_key=f"dream:{batch}"
    )
    if not _is_empty(outcome.dream):
        await store.append_memory_text(
            f"memory/dreams/{date}.md",
            f"\n## dream {date}\n\n{outcome.dream.strip()}\n",
            idempotency_key=f"dreamlog:{batch}",
        )
    await store.sync()  # 文件真源变了 → 重建派生索引（dreams 按映射不进索引）
    return {
        "wrote": True,
        "input_hash": batch,
        "idempotent": core_receipt.get("idempotent", False),
        "core_path": core_receipt["path"],
    }


async def flush_run_to_daily(
    store: MemoryStorePort,
    *,
    summary_text: str,
    run_id: str,
    now: datetime | None = None,
) -> JsonObject:
    """run-完成边界的 episodic→daily 落盘：只 append 浓缩 summary（I3 绝不写 delta）。

    以 ``run_id`` 作幂等键 → 重复 flush no-op、失败可重试（claim-then-commit，ADR-0025）。"""
    now = now or utc_now()
    require_aware(now, "flush_run_to_daily.now")
    if _is_empty(summary_text):
        return {"wrote": False, "reason": "empty-summary"}
    date = now.strftime("%Y-%m-%d")
    receipt = await store.append_memory_text(
        f"memory/{date}.md",
        f"\n## [daily] {now.isoformat()} run={run_id}\n\n{summary_text.strip()}\n",
        idempotency_key=f"flush:{run_id}",
    )
    await store.sync()
    return {"wrote": not receipt.get("idempotent", False), "idempotent": receipt.get("idempotent", False), "path": receipt["path"]}
