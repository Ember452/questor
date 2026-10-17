"""G-L5 / DoD B①：带内 inline 行必带关联（run_id + turn 单调）——经真 loop 装配。

真装配 + 真 IO（不用 mock 冒充）：``configure_logging`` 装桥 + 按日 JSONL 文件面（console 抬到
CRITICAL 静音），跑一遍真 ``DefaultTurnLoop``；provider 在每轮流式里打一条 ``questor.kernel.probe``
inline 日志（走 stdlib → 桥 → pipeline → 文件）。断言该 inline 行携 ``run_id`` 且 ``turn`` 单调不减。

**判红样例（DESIGN §15 G-L5）**：把 ``loop.py`` 里的 ``bind(turn=...)`` 注释掉，本测试必须红——
证明关联确由 loop 的 bind 注入，而非别处顺带填上。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.contracts.state_schema import Budget, RunStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.observability import configure as log_configure
from questor.observability import exporter as log_exporter
from questor.observability import pipeline as log_pipeline
from questor.observability.entry import LogLevel
from questor.policy.react_policy import ReActPolicy
from questor.state.domain_state import Run

_TURN_ANSWER = [StreamChunk(kind="text", text="all done"), StreamChunk(kind="finish", finish_reason="stop")]


class _ProbingProvider(ProviderPort):
    """脚本化回放，但在每轮流式里打一条 inline ``questor.*`` 日志（探针）。"""

    def __init__(self, turns: list[list[StreamChunk]]) -> None:
        self._turns = turns
        self._index = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        import logging

        idx = self._index
        logging.getLogger("questor.kernel.probe").info("probe turn index %d", idx)
        chunks = self._turns[idx] if idx < len(self._turns) else _TURN_ANSWER
        for chunk in chunks:
            yield chunk
        self._index += 1


def _read_main_jsonl(log_dir: Path) -> list[dict]:
    # 主干文件按记录自身 ts 的 UTC 日期命名（sink_file `_fname`）；测试读时不能拿本地 date.today()
    # （跨 UTC/本地午夜会错配）——直接读目录下所有 questor-*.jsonl。
    rows: list[dict] = []
    for path in sorted(log_dir.glob("questor-*.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


@pytest.fixture
def clean_logging() -> Iterator[None]:
    """快照/还原全局装配态（root handler、exporter 注册表、configure._state、pipeline）。

    ``configure_logging`` 是进程级单例装配；本用例装了桥+文件 sink，必须在结束时整体回滚，
    否则残留的桥/console 会泄进后续 ``test_configure`` 用例（幂等断言变 2 桥）。
    """
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_registry = list(log_exporter._registry)
    saved_state = log_configure._state
    log_pipeline.reset()
    log_configure._state = None
    try:
        yield
    finally:
        log_configure._teardown()  # 拆掉本用例装的桥 + 注销 sink（_state 指本用例装配时）
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        log_exporter._registry[:] = saved_registry
        log_configure._state = saved_state
        log_pipeline.reset()


async def _drive_two_turn_loop(log_dir: Path) -> None:
    log_configure.configure_logging(console_level=LogLevel.CRITICAL, file_level=LogLevel.DEBUG, log_dir=log_dir)
    loop = DefaultTurnLoop(
        provider=_ProbingProvider([_TURN_ANSWER, _TURN_ANSWER]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(None),
        tool_for=lambda name: None,
        tools=(),
        workspace_root=log_dir,
        model="test-model",
    )
    run = Run(run_id="run_correlation", budget=Budget(max_turns=5))
    final = await loop.drive(run, "hello")
    assert final.status is RunStatus.COMPLETED
    log_pipeline.flush()  # 关掉节流窗，确保补齐/落盘后再由 fixture 拆装配


def test_inline_entries_carry_run_id_and_monotonic_turn(clean_logging: None, tmp_path: Path) -> None:
    asyncio.run(_drive_two_turn_loop(tmp_path))
    probes = [e for e in _read_main_jsonl(tmp_path) if e["source"] == "inline" and e["logger"] == "questor.kernel.probe"]
    assert probes, "expected inline probe rows in the JSONL"
    for e in probes:
        assert e["context"].get("run_id") == "run_correlation", f"inline row missing run_id: {e}"
    turns = [e["context"]["turn"] for e in probes]
    assert turns == sorted(turns), f"turn must be monotonically non-decreasing across inline rows: {turns}"
