"""B10/§17-8：`summarize()` 的输出分布实测（p99 字符/token），给 ADR-0057 的预留常数背书。

设计文档明写"questor 不得直接拍自己的数"（§7.1 末段）：20_000/13_000/3_000 是 Claude-Code 的
实测常量，而摘要预留取多少**取决于我们自己摘要输出的分布**。本评测就是那"一轮回放"的最小版本：
100 个确定性构造段 → 逐段 `summarize()` → 算 p50/p95/p99 与上界，判据落在两件事上：

① 输出恒有界（`SUMMARY_MAX_CHARS` 真的截住了，任何输入都不越界）；
② p99 显著低于 `summary_reserve=20_000` 的 token 折算值——即沿用该预留对我们自己的分布是**保守**的，
   不是"抄来的乐观值"。若这条判红，就说明默认预留必须改（本文件即那一次自测的证据）。

token 换算按 ``chars / 4`` 估（**没有官方 tokenizer，估算值，标 UNVERIFIED**）；这里不用它做任何
阈值决策，只用于把"字符分布"讲给 §7.1 的 token 口径听。
"""

from __future__ import annotations

import hashlib
import statistics

from questor.contracts.common import new_id
from questor.contracts.policy import CompactionConfig
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.kernel.compaction import SUMMARY_MAX_CHARS, summarize

_SEGMENT_COUNT = 100
_CHARS_PER_TOKEN_ESTIMATE = 4


def _segment(index: int) -> tuple[Message, ...]:
    """确定性构造一段被压上下文：条数与每条长度都随 index 增长（覆盖"短闲聊"到"长工具输出"）。

    用 sha256 派生正文而不是随机数——同一次运行与下一次运行逐字相同，分布才可复现。"""
    messages: list[Message] = []
    turns = 1 + index % 9  # 1..9 条
    for turn in range(turns):
        seed = hashlib.sha256(f"{index}:{turn}".encode()).hexdigest()
        words = " ".join(f"tok{seed[start : start + 8]}" for start in range(0, 120 + 40 * turn, 8))
        if turn % 3 == 2:  # 每三段掺一条工具结果（占位符路径也进分布）
            block = ContentBlock(type="tool_result", tool_use_id=f"tc{turn}", text=words)
        else:
            block = ContentBlock(type="text", text=words)
        role = Role.ASSISTANT if turn % 2 else Role.USER
        messages.append(Message(id=new_id("msg"), role=role, content=(block,), seq=turn))
    return tuple(messages)


def _percentile(values: list[int], q: float) -> int:
    """最近秩法（确定性、无插值歧义）：适合"分布是否越界"这类判据，不适合精细统计。"""
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round(q * (len(ordered) - 1)))))
    return ordered[rank]


def test_summary_output_is_bounded_and_measured() -> None:
    lengths = [len(summarize(_segment(index))) for index in range(_SEGMENT_COUNT)]
    assert len(lengths) == _SEGMENT_COUNT
    assert max(lengths) <= SUMMARY_MAX_CHARS  # 判据①：任何输入都不越界（C18）
    p50, p95, p99 = _percentile(lengths, 0.50), _percentile(lengths, 0.95), _percentile(lengths, 0.99)
    assert min(lengths) > 0  # 空摘要会被 reduce 拒，构造段必须都产出非空文本
    # 判据②：p99 折算 token 必须远低于默认摘要预留（20_000 token）
    p99_tokens = p99 / _CHARS_PER_TOKEN_ESTIMATE
    reserve = CompactionConfig().summary_reserve
    assert p99_tokens < reserve, f"p99={p99} chars ≈ {p99_tokens:.0f} tokens 已逼近预留 {reserve}"
    # 报告口径：下面四个百分位与均值是本文件实跑得到的值（已写入 ADR-0057）；改构造段就必须同步改 ADR，
    # 否则“实测背书”就成假话。钉成断言而不是只打印，是为了让“静悄悄改了分布”不能过关。p99=1248
    # 字符 ≈ 312 token（chars/4 估），远低于沿用的 20_000 token 预留 → 该预留对我们自己的分布是保守的。
    assert (p50, p95, p99, round(statistics.mean(lengths)), max(lengths)) == (723, 1248, 1248, 679, 1248), (
        p50,
        p95,
        p99,
        round(statistics.mean(lengths)),
        max(lengths),
    )


def test_bounding_holds_for_a_pathological_single_message() -> None:
    """越界风险最集中的形状：一条超长工具输出被压——仍必须截在 `SUMMARY_MAX_CHARS` 内。"""
    huge = (
        Message(
            id=new_id("msg"),
            role=Role.TOOL,
            content=(ContentBlock(type="tool_result", tool_use_id="tc", text="z" * 400_000),),
            seq=0,
        ),
    )
    assert len(summarize(huge)) <= SUMMARY_MAX_CHARS
