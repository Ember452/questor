"""B12 · G 评测环的六个指标（v3 §10；纯函数、零 IO、零网络）。

**为什么口径必须先选对**：前四个指标只能从 §6.3 的「消费 + 引用」打点算出来——kind 级打点
算不出写入噪声率，命中当消费会把噪声率虚假清零（指标自证其美）。所以本模块的输入形状是
**条目级** id（``path:start-end``），不是 kind。

诚实边界（写进返回值，不藏在注释里）：
- 分母为 0 → ``value=None``，**不编 0.0**（"没有样本"与"样本全过"是两件事）；
- 每任务成本只能算到 token：没有价目表就没有美元数，``verified=False`` + UNVERIFIED（§17-9）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

#: 写入噪声率的观察窗（天）：写入后这么久还没被**条目级**消费就算噪声（§10 表）。
NOISE_WINDOW_DAYS = 30
_SECONDS_PER_DAY = 86_400.0

#: 价目表缺失时的成本标记（不得用假汇率把 token 换算成钱）。
COST_UNVERIFIED = "cost_usd requires a price table (design/17-9); token-level only"


@dataclass(frozen=True, slots=True)
class Metric:
    """一个指标的完整口径披露：数值 + 分子分母 + 数据来源 + 是否已验证。"""

    name: str
    numerator: float
    denominator: float
    value: float | None
    source: str
    verified: bool = True
    note: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "source": self.source,
            "verified": self.verified,
            "note": self.note,
        }


def _ratio(name: str, numerator: float, denominator: float, source: str, *, note: str = "", verified: bool = True) -> Metric:
    """除零一律 ``None``（不编 0.0）：这是本模块唯一的时间/数量约定。"""
    value = numerator / denominator if denominator else None
    return Metric(name=name, numerator=numerator, denominator=denominator, value=value, source=source, verified=verified, note=note)


def entry_id(path: str, line_start: int, line_end: int) -> str:
    """条目级 id（与 §6.3 citation / 消费打点**同一形状**）。"""
    return f"{path}:{line_start}-{line_end}"


def recall_hit_rate(cited: Iterable[str], expected: Iterable[str]) -> Metric:
    """召回命中率 = 被引用过的 / 应该被引用的（§10 行 1，数据源 §6.3 citation）。

    分母是**人工标的应引用集**，不是"命中集"：把命中当分母就等于让被测系统自己出题。
    """
    expected_ids = set(expected)
    hit = len(expected_ids & set(cited))
    return _ratio("recall_hit_rate", hit, len(expected_ids), "message_completed.citations")


def forgetting_rate(expected_facts: Mapping[str, str], memory_text: str) -> Metric:
    """遗忘率 = 应记未记的 / 应记的（§10 行 2，数据源 = 事实流 + 记忆库 diff）。

    ``expected_facts`` 是**人工标注**（id -> 必须出现在记忆正文里的片段）；不标就没有这条指标，
    用启发式猜"该记什么"会把它变成自证。
    """
    missed = sum(1 for needle in expected_facts.values() if needle not in memory_text)
    return _ratio("forgetting_rate", missed, len(expected_facts), "event_log vs memory store diff (hand-labelled)")


def write_noise_rate(
    written: Sequence[tuple[str, float]],
    consumed: Iterable[str],
    *,
    now: float,
    window_days: int = NOISE_WINDOW_DAYS,
) -> Metric:
    """写入噪声率 = 写入满 ``window_days`` 仍未被**条目级**消费的条目 / 写入条目（§10 行 3）。

    还没到观察窗的条目**整体剔除**（不进分子也不进分母）：不然刚写好的记忆会被算成噪声，
    而这个指标一旦能被"写入时间"稀释，就再也不会红。
    """
    consumed_ids = set(consumed)
    cutoff = now - window_days * _SECONDS_PER_DAY
    aged = [(identifier, ts) for identifier, ts in written if ts <= cutoff]
    noisy = sum(1 for identifier, _ts in aged if identifier not in consumed_ids)
    return _ratio("write_noise_rate", noisy, len(aged), "memory_written + memory_consumed(entry-level)")


def duplicate_reminder_rate(delivery_rows: Sequence[Mapping[str, object]]) -> Metric:
    """重复提醒率 = 同一义务投过 ≥2 次的 / 义务数（§10 行 4，数据源 = D 环 attempts/recovered）。

    分子用 ``attempts >= 2``（真投了两次以上才会重复打扰）；``recovered`` 只进 note——
    崩溃重投是"恢复"，与"静默重投"要能分开看。
    """
    total = len(delivery_rows)
    repeated = sum(1 for row in delivery_rows if int(row.get("attempts", 0) or 0) >= 2)
    recovered = sum(1 for row in delivery_rows if row.get("recovered"))
    return _ratio(
        "duplicate_reminder_rate",
        repeated,
        total,
        "deliveries.attempts/recovered",
        note=f"recovered={recovered}",
    )


def revoke_rate(written_count: float, deleted_count: float) -> Metric:
    """撤回率 = 用户删掉的条数 / 写入条数（§10 行 5，数据源 = durable `memory_deleted`）。

    只从事件流计数（§20 C-7 不建历史表）：撤回史与撤回率必须有同一个出处，否则一边数 seq
    一边数表行就会得出两个"用户删了几条"。
    """
    return _ratio("revoke_rate", deleted_count, written_count, "event_log: memory_deleted / memory_written")


def per_task_cost(total_tokens: float, succeeded_tasks: float, price_per_million_tokens: Mapping[str, float] | None = None) -> Metric:
    """每成功任务成本（§10 行 6）。默认**只到 token**：没有价目表就没有美元数。

    传了价目表才算钱（键 ``input`` / ``output`` 每百万 token），并把 ``verified`` 置 True；
    不传就老实标 UNVERIFIED——本仓没有任何汇率，编一个就是把假设写成结论（§17-9）。
    """
    per_task = total_tokens / succeeded_tasks if succeeded_tasks else None
    note = f"tokens_per_succeeded_task={per_task}" if per_task is not None else "no succeeded tasks"
    verified = False
    if price_per_million_tokens is not None:
        rates = {k: float(v) for k, v in price_per_million_tokens.items()}
        cost = per_task * (rates.get("input", 0.0) + rates.get("output", 0.0)) / 1_000_000 if per_task is not None else None
        note = f"cost_usd={cost} from supplied price table"
        verified = True
    else:
        note = f"{note}; {COST_UNVERIFIED}"
    return Metric(
        name="cost_per_succeeded_task",
        numerator=total_tokens,
        denominator=succeeded_tasks,
        value=per_task,
        source="run_completed.usage (token only)",
        verified=verified,
        note=note,
    )


__all__ = [
    "COST_UNVERIFIED",
    "NOISE_WINDOW_DAYS",
    "Metric",
    "duplicate_reminder_rate",
    "entry_id",
    "forgetting_rate",
    "per_task_cost",
    "recall_hit_rate",
    "revoke_rate",
    "write_noise_rate",
]
