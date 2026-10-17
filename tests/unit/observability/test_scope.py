"""T2.3 关联作用域 ``observability/scope.py`` 判例（DESIGN §5；D5/D6）。

覆盖：bind 的加键/嵌套合并/退出还原；同键重盖章（restamp）；两 asyncio task 各自 bind
互不串号（task 作用域，D6）；非白名单值当场拒收（与 LogEntry 一致，fail-closed）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from questor.observability.scope import bind, current_context


def test_empty_context_by_default() -> None:
    assert current_context() == {}


def test_bind_sets_and_restores() -> None:
    with bind(run_id="r1", turn=3):
        assert current_context() == {"run_id": "r1", "turn": 3}
    # 退出即还原（token reset）。
    assert current_context() == {}


def test_nested_bind_is_additive_and_restores() -> None:
    # 加键语义：嵌套 bind 合并新键，内层退出只还原到外层，不动外层键。
    with bind(run_id="r1"):
        with bind(turn=1):
            assert current_context() == {"run_id": "r1", "turn": 1}
        # 内层退出：turn 撤销，run_id 仍在。
        assert current_context() == {"run_id": "r1"}


def test_same_key_restamp_wins_inner() -> None:
    # 同键覆盖 = 重盖章：内层新值生效，退出还原外层旧值（loop 每轮 bind(turn=…) 靠此）。
    with bind(turn=1):
        with bind(turn=2):
            assert current_context()["turn"] == 2
        assert current_context()["turn"] == 1


def test_none_value_allowed() -> None:
    with bind(trace_id=None):
        assert current_context() == {"trace_id": None}


def test_non_whitelist_value_rejected() -> None:
    # 与 LogEntry 白名单一致：非 str/int/float/bool/None 当场 TypeError，不静默转。
    with pytest.raises(TypeError):
        with bind(run=object()):
            pass


async def test_two_tasks_do_not_interleave() -> None:
    # task 作用域：两个并发 asyncio task 各绑自己的 run_id，互不串号（D6）。
    seen: dict[str, dict] = {}

    async def _run(rid: str, delay: Callable[[], asyncio.Future]) -> None:
        with bind(run_id=rid):
            await delay()
            seen[rid] = current_context()

    a = asyncio.create_task(_run("A", lambda: asyncio.sleep(0.01)))
    b = asyncio.create_task(_run("B", lambda: asyncio.sleep(0.02)))
    await asyncio.gather(a, b)
    assert seen["A"] == {"run_id": "A"}
    assert seen["B"] == {"run_id": "B"}


def test_current_context_returns_copy() -> None:
    # current_context 返回快照副本：外部改写不影响内部作用域。
    with bind(run_id="r1"):
        snap = current_context()
        snap["run_id"] = "tampered"
        assert current_context() == {"run_id": "r1"}
