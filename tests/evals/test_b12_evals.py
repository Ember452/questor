"""B12 · G 评测环跑手：10 个任务 × 确定性判分器 × 六指标出数（无 key、无网络）。

这里唯一的新东西是**编排**：真实 `DefaultTurnLoop` + 真实 `SQLiteStore`/`SQLiteMemoryStore` +
`ScriptedProvider`，判据只看 durable 事实（事件流、Domain_State、记忆库正文）。
六指标从跑出来的证据里算，不是从假设里编（§10「前四个只能从消费+引用口径算出」）。

`pytest -m eval` 选此目录；确定性判据（同输入两次同轨迹）单独一条，防时序漂移冒充"通过"。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from metrics import (
    Metric,
    duplicate_reminder_rate,
    forgetting_rate,
    per_task_cost,
    recall_hit_rate,
    revoke_rate,
    write_noise_rate,
)
from tasks import TASKS, EvalTask, TaskEvidence, grade

from questor.capabilities.tools._output import envelope_for_text
from questor.capabilities.tools.read import ReadTool
from questor.contracts.events import DeleteMemory, EventType, SubmitMessage, WriteMemory
from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.contracts.policy import CompactionConfig
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.providers.artifact_store import FileSystemArtifactStore
from questor.providers.fake import ScriptedProvider
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.state.checkpoint import open_tool_use_ids, orphan_tool_result_ids
from questor.state.domain_state import Run

pytestmark = pytest.mark.eval

_COMPACTION = {"tiny": CompactionConfig(keep_head=1, keep_tail=1, max_items=3), "small": CompactionConfig(keep_head=2, keep_tail=4, max_items=6)}


def _answer(text: str) -> list[StreamChunk]:
    return [StreamChunk(kind="text", text=text), StreamChunk(kind="finish", finish_reason="stop")]


def _read(call_id: str, path: str) -> list[StreamChunk]:
    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": call_id, "name": "read", "args_delta": json.dumps({"file_path": path})}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


def _unknown(call_id: str) -> list[StreamChunk]:
    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": call_id, "name": "no-such-tool", "args_delta": "{}"}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


def _citation(text: str, entries: list[dict[str, Any]]) -> list[StreamChunk]:
    """模型自报引用的形状（§6.3）：正文 + `<citation_entries>` JSON 块，harness 必须把它剥掉。"""
    block = f"{text}\n<citation_entries>{json.dumps({'entries': entries})}</citation_entries>"
    return _answer(block)


def _user_message(text: str, seq: int) -> Message:
    return Message(id=f"ops-u{seq}", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=seq)


def _turns(recipe: tuple[str, ...]) -> list[list[StreamChunk]]:
    turns: list[list[StreamChunk]] = []
    for item in recipe:
        parts = item.split(":")
        kind = parts[0]
        if kind == "answer":
            turns.append(_answer(parts[1]))
        elif kind == "read":
            turns.append(_read(parts[1], parts[2]))
        elif kind == "unknown":
            turns.append(_unknown(parts[1]))
        elif kind == "citation":
            turns.append(_citation(parts[1], [{"path": "memory/eval-note.md", "line_start": 1, "line_end": 2}]))
        else:  # 未知配方是评测集的 bug，不许静默跳过
            raise AssertionError(f"unknown turn recipe {item!r}")
    return turns


def _fixture_files(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "a.txt").write_text("alpha file", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta file", encoding="utf-8")
    (tmp_path / "big.txt").write_text("B" * 40_000, encoding="utf-8")


class _Harness:
    """一个任务一套 store；跑完提供 durable 证据（判分器与指标共用同一份事实）。"""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.store: SQLiteStore | None = None
        self.mem: SQLiteMemoryStore | None = None
        self.artifacts: FileSystemArtifactStore | None = None

    async def __aenter__(self) -> _Harness:
        _fixture_files(self.tmp)
        self.store = await SQLiteStore(str(self.tmp / "s.db")).connect()
        self.mem = await SQLiteMemoryStore(db_path=str(self.tmp / "m.db"), memory_root=str(self.tmp / "mem")).connect()
        self.artifacts = FileSystemArtifactStore(self.tmp / "artifacts")
        await self.artifacts.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self.artifacts is not None and self.mem is not None and self.store is not None
        await self.artifacts.close()
        await self.mem.close()
        await self.store.close()

    def loop(self, task: EvalTask) -> DefaultTurnLoop:
        assert self.store is not None and self.mem is not None and self.artifacts is not None
        read = ReadTool()
        return DefaultTurnLoop(
            provider=ScriptedProvider(_turns(task.turns)),
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(),
            bus=InProcessEventBus(self.store),
            tool_for=lambda name: {"read": read}.get(name),
            tools=(read,),
            workspace_root=self.tmp,
            store=self.store,
            memory_store=self.mem,
            artifact_store=self.artifacts,
            output_envelope=envelope_for_text,
            compaction=_COMPACTION.get(task.compaction),
        )

    async def run(self, task: EvalTask) -> TaskEvidence:
        assert self.store is not None and self.mem is not None
        loop = self.loop(task)
        run_id = f"eval-{task.id}"
        run = Run(run_id=run_id, budget=Budget(max_turns=8))
        final = await loop.drive(run, task.prompt)
        ops_run_id = f"{run_id}-ops"
        extras: dict[str, object] = {}
        if task.post:
            extras = await self._post_steps(loop, task, ops_run_id)
        events = list(await self.store.replay(run_id, 0))
        if task.post:
            events += list(await self.store.replay(ops_run_id, 0))
        events = tuple(events)
        types = tuple(str(e["type"]) for e in events)
        written = [e for e in events if e["type"] == EventType.MEMORY_WRITTEN]
        deleted = [e for e in events if e["type"] == EventType.MEMORY_DELETED]
        citations: list[str] = []
        for env in events:
            if env["type"] != EventType.MESSAGE_COMPLETED:
                continue
            payload = env["data"].get("citations") or {}
            for entry in payload.get("entries", []) if isinstance(payload, dict) else []:
                citations.append(f"{entry['path']}:{entry['line_start']}-{entry['line_end']}")
        window_ids = tuple(
            str(env["data"]["window_id"]) for env in events if env["type"] == EventType.COMPACT_APPLIED and env["data"].get("window_id")
        )
        archived = any(env["type"] == EventType.TOOL_COMPLETED and env["data"].get("artifact_ref") for env in events)
        previews = [len(str(env["data"].get("preview", ""))) for env in events if env["type"] == EventType.TOOL_COMPLETED]
        written_ids: list[str] = []
        for hit in await self.mem.search(task.prompt[:24], k=5):
            written_ids.append(f"{hit.path}:{hit.start_line}-{hit.end_line}")
        memory_chunks: list[str] = []
        for path in await self.mem.list_memory_paths():
            memory_chunks.append(await self.mem.read_memory_text(path))
        memory_text = "\n".join(memory_chunks)
        tokens = sum(len(str(e["data"])) for e in events if e["type"] == EventType.RUN_COMPLETED)
        return TaskEvidence(
            task_id=task.id,
            status=final.status.name,
            types=types,
            events=events,
            memory_text=memory_text,
            written_ids=tuple(written_ids),
            deleted_count=len(deleted),
            cited_ids=tuple(citations),
            open_tool_use_ids=open_tool_use_ids(final.context.items),
            orphan_result_ids=orphan_tool_result_ids(final.context.items),
            recovery_pointers=len(final.context.recovery_pointers),
            window_ids=window_ids,
            archived=archived,
            preview_bytes=max(previews) if previews else 0,
            tokens=tokens,
            written_seq_count=len(written),
            second_write_idempotent=extras.get("second_write_idempotent"),  # type: ignore[arg-type]
        )

    async def _post_steps(self, loop: DefaultTurnLoop, task: EvalTask, ops_run_id: str) -> dict[str, object]:
        """驱动后的附加步骤：在未终态的伴跑 run 上经同一咽喉写 / 撤回记忆，并测幂等重写。

        为什么开另一个 run：终态 run 不接受后续命令（reduce 会拒并落一条 warning），而本任务集要测
        的是"命令面能不能正确落账"，不是"能不能违反终态"。所有步骤仍走 `loop._transition`，
        不开第二写入口（C4/C16）。返回的 extras 由 `run()` 并进证据（判分器只看证据，不看日志）。
        """
        assert self.mem is not None
        extras: dict[str, object] = {}
        base = Run(run_id=ops_run_id, budget=Budget(max_turns=4))
        started = await loop._transition(base, SubmitMessage(run_id=ops_run_id, content=_user_message(task.prompt, 0)))
        await loop._emit(started.events)
        run = started.run
        payload = MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text=task.prompt, attributed_to="user")
        command = WriteMemory(run_id=ops_run_id, payload=payload)
        write_key: str | None = None
        if "write_memory" in task.post:
            applied = await loop._transition(run, command)
            assert applied.accepted, f"{task.id}: first WriteMemory was not accepted"
            await loop._emit(applied.events)
            ack = next((env for env in applied.events if env.type == EventType.MEMORY_WRITTEN), None)
            assert ack is not None, f"{task.id}: WriteMemory produced no memory_written event"
            write_key = f"mem:{ops_run_id}:{ack.seq}"
            await self.mem.write(payload, idempotency_key=write_key)
            run = applied.run  # 链式推进：下一条命令必须建在**已应用后**的状态上，否则 seq 相撞
        if "duplicate_store_write" in task.post and write_key is not None:
            # 同一幂等键再写一次：store 必须返回原 receipt 且不再 append（写不双份）
            receipt = await self.mem.write(payload, idempotency_key=write_key)
            extras["second_write_idempotent"] = bool(receipt.get("idempotent"))
        if "delete_written" in task.post and write_key is not None:
            hits = await self.mem.search(task.prompt[:24], k=1)
            assert hits, f"{task.id}: memory write produced no searchable entry"
            entry_id = f"{hits[0].path}:{hits[0].start_line}-{hits[0].end_line}"
            deleted = await loop._transition(run, DeleteMemory(run_id=ops_run_id, entry_id=entry_id, reason="eval revoke"))
            assert deleted.accepted, f"{task.id}: DeleteMemory was rejected"
            await loop._emit(deleted.events)
            await self.mem.soft_delete(entry_id, idempotency_key=f"memdel:{ops_run_id}")
        return extras


@pytest.mark.parametrize("task", list(TASKS), ids=[task.id for task in TASKS])
async def test_b12_task_passes_its_deterministic_grader(tmp_path: Path, task: EvalTask) -> None:
    async with _Harness(tmp_path / task.id) as harness:
        evidence = await harness.run(task)
        outcome = grade(task, evidence)
        assert outcome.passed, f"{task.id} failed: {outcome.failures}"


def test_task_set_is_ten_and_all_ids_unique() -> None:
    """10 个任务、id 唯一（任务集本身也是被测物：少一个任务就是少一条判据）。"""
    assert len(TASKS) == 10
    assert len({task.id for task in TASKS}) == 10


@pytest.mark.parametrize("task", [TASKS[0], TASKS[7]], ids=["answer-only", "compaction"])
async def test_same_input_same_trace_twice(tmp_path: Path, task: EvalTask) -> None:
    """确定性：同输入两次跑的**事件类型序列**逐字相同（防时序漂移冒充通过）。"""
    async with _Harness(tmp_path / "r1") as first:
        evidence_a = await first.run(task)
    async with _Harness(tmp_path / "r2") as second:
        evidence_b = await second.run(task)
    assert [env["type"] for env in evidence_a.events] == [env["type"] for env in evidence_b.events]


async def test_six_metrics_are_computable_from_run_evidence(tmp_path: Path) -> None:
    """六指标能出数（§13 B12 验收），且成本那条诚实停在 token 级（§17-9）。"""
    evidence: list[TaskEvidence] = []
    async with _Harness(tmp_path / "metrics") as harness:
        for task in (TASKS[4], TASKS[5], TASKS[6], TASKS[9]):
            evidence.append(await harness.run(task))
        store = harness.store
        assert store is not None
        # 重复提醒率的真实数据源：一条义务投两次（attempting 重投 bump attempts）
        await store.create_obligation("del-1", "obl-1", "cli", session_id="sess-1")
        await store.create_obligation("del-2", "obl-2", "cli", session_id="sess-1")
        for _ in range(2):
            claimed = await store.claim_obligation(now=time.time())
            for row in claimed:
                await store.finish_delivery(str(row["delivery_id"]), "failed", error_class="flood")
        rows = [row for delivery_id in ("del-1", "del-2") if (row := await store.delivery_row(delivery_id)) is not None]

    cited = [entry_id for item in evidence for entry_id in item.cited_ids]
    written = [entry_id for item in evidence for entry_id in item.written_ids]
    consumed = ["memory/eval-note.md:1-2"]  # 人工标的"被消费"集（条目级，与 §6.3 同形状）
    expected_facts = {f"fact-{index}": needle for index, needle in enumerate([TASKS[4].prompt])}
    memory_text = "\n".join(item.memory_text for item in evidence)
    deleted = sum(item.deleted_count for item in evidence)

    metrics: tuple[Metric, ...] = (
        recall_hit_rate(cited, ["memory/eval-note.md:1-2"]),
        forgetting_rate(expected_facts, memory_text),
        write_noise_rate([(identifier, time.time() - 40 * 86_400) for identifier in written], consumed, now=time.time()),
        duplicate_reminder_rate(rows),
        revoke_rate(len(written), deleted),
        per_task_cost(sum(item.tokens for item in evidence), sum(1 for item in evidence if item.status.endswith("COMPLETED"))),
    )
    by_name = {metric.name: metric for metric in metrics}
    assert set(by_name) == {
        "recall_hit_rate",
        "forgetting_rate",
        "write_noise_rate",
        "duplicate_reminder_rate",
        "revoke_rate",
        "cost_per_succeeded_task",
    }
    # 出数判据：citation 真被解析、任务真跑成了、义务真投了两次
    assert by_name["recall_hit_rate"].value == 1.0, by_name["recall_hit_rate"]
    assert by_name["forgetting_rate"].value == 0.0, by_name["forgetting_rate"]
    assert by_name["duplicate_reminder_rate"].denominator == 2
    assert by_name["duplicate_reminder_rate"].value == 1.0, by_name["duplicate_reminder_rate"]
    assert by_name["revoke_rate"].value == 1.0, by_name["revoke_rate"]
    assert by_name["write_noise_rate"].denominator == len(written)
    # 成本：没有价目表就没有美元数（verified=False 是判据，不是免责声明）
    cost = by_name["cost_per_succeeded_task"]
    assert cost.verified is False and "UNVERIFIED" in cost.note or "price table" in cost.note
    assert cost.value is not None and cost.value > 0

    priced = per_task_cost(1_000_000, 10, {"input": 1.0, "output": 2.0})
    assert priced.verified is True and priced.value == 100_000.0 and "cost_usd=" in priced.note


def test_metrics_refuse_to_invent_zeroes() -> None:
    """分母为 0 → `value=None`，不是 0.0：「没有样本」与「样本全过」是两件事。"""
    assert recall_hit_rate([], []).value is None
    assert forgetting_rate({}, "whatever").value is None
    assert write_noise_rate([], [], now=time.time()).value is None
    assert duplicate_reminder_rate([]).value is None
    assert revoke_rate(0, 0).value is None
    assert per_task_cost(1200, 0).value is None
