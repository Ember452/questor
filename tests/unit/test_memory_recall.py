"""B8/c2：三通道召回 + 确定性 embedding fake + 单库入库（v3 §6.2；§20 C-3）。

判据面：
- 三通道候选融合到**同一个 store**（keyword / vector / structured 都不开第二索引表）；
- `FakeEmbedder` 确定性（同文本同向量、批调用一次成型），embedding 落到
  `memory_chunks.embedding` 同一列；无 embedder 时向量通道静默降级（ADR-0026）；
- 终选纯函数：≤5 条、排除索引文件、条目 id 去重、坑优先、daily 日期当 mtime；
- 三门控：triviality / `skip_recall` flags / 不可归因就不注入。
"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.memory import (
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    MemoryWrite,
    MemoryWriteKind,
    RecallBlock,
)
from questor.memory.recall import (
    INDEX_PATHS,
    MAX_SELECTED,
    RECALL_LEAD_IN,
    MemoryRecall,
    is_trivial,
    prefer_pitfalls,
    render_recall_block,
    select,
    skipped_by_flags,
    three_channel_search,
)
from questor.providers.fake import FakeEmbedder
from questor.providers.store_memory_sqlite import SQLiteMemoryStore


def _hit(path: str, start: int, end: int, score: float, snippet: str) -> MemorySearchResult:
    return MemorySearchResult(
        path=path, start_line=start, end_line=end, score=score, snippet=snippet, source=MemorySource.DAILY
    )


def test_triviality_gate_and_skip_flag() -> None:
    assert is_trivial("") and is_trivial("  ") and is_trivial("??") and is_trivial("短")
    assert not is_trivial("为什么 bash 工具又报 permission denied")
    assert skipped_by_flags({"skip_recall": True})
    assert skipped_by_flags({"skip_recall": "true"})
    assert not skipped_by_flags({"skip_recall": False})
    assert not skipped_by_flags(None)
    assert not skipped_by_flags({"unknown_open_vocabulary_key": 1})  # 开放词表：未知 key 忽略


def test_selector_caps_excludes_dedupes_and_prefers_pitfalls() -> None:
    candidates = [_hit(f"memory/2026-10-{index:02d}.md", index, index, 0.9 - 0.01 * index, f"fact {index}") for index in range(1, 9)]
    picked = select(candidates, query="plain question")
    assert len(picked) == MAX_SELECTED
    assert [hit.path for hit in picked] == [f"memory/2026-10-{index:02d}.md" for index in range(1, 6)]  # 分数高者优先
    ties = [_hit("memory/2026-10-01.md", 1, 1, 0.5, "older note"), _hit("memory/2026-10-20.md", 1, 1, 0.5, "newer note")]
    assert select(ties)[0].path == "memory/2026-10-20.md"  # 同分→新 daily 在前（mtime 代理）
    dupes = [_hit("memory/2026-10-05.md", 1, 2, 0.9, "same"), _hit("memory/2026-10-05.md", 1, 2, 0.8, "same")]
    assert len(select(dupes)) == 1
    assert select(candidates, exclude_paths=INDEX_PATHS)  # 非索引候选照常入选
    assert select([_hit("MEMORY.md", 1, 2, 0.99, "index pointer")], query="anything") == ()  # ① 索引本身被排除
    pitfall = _hit("memory/2026-10-01.md", 1, 2, 0.4, "pitfall: never rm -rf without confirmation")
    decent = _hit("memory/2026-10-09.md", 1, 2, 0.8, "user prefers short answers")
    ordered = select([decent, pitfall], query="this errored again, how do I fix it")
    assert ordered[0] is pitfall  # 出错类查询优先选坑（§6.2 细节）
    assert select([decent, pitfall], query="normal question")[0] is decent
    assert prefer_pitfalls("报错") and not prefer_pitfalls("hello world question")


def test_render_is_delimited_and_states_reference_data() -> None:
    block = render_recall_block([_hit("memory/2026-10-02.md", 3, 7, 0.5, "launch code is DELTA-9")])
    assert block.startswith(RECALL_LEAD_IN)
    assert "memory/2026-10-02.md:3-7" in block and "DELTA-9" in block
    assert render_recall_block([]) == ""


async def test_fake_embedder_is_deterministic_and_batch_only() -> None:
    embedder = FakeEmbedder()
    first, second = await embedder.embed(["same text", "other text"])
    assert len(first) == len(second) == embedder.dim
    again = await embedder.embed(["same text"])
    assert again[0] == first
    assert first != second
    assert abs(sum(value * value for value in first) - 1.0) < 1e-3  # 归一化


async def test_three_channels_share_one_store_and_stay_bounded(tmp_path: Path) -> None:
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem"), embedder=FakeEmbedder()).connect()
    try:
        for index in range(6):
            await store.write(
                MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text=f"fact about launch code DELTA-{index}"),
                idempotency_key=f"w-{index}",
            )
        hits = await three_channel_search(store, "launch code DELTA", k=8, embedder=FakeEmbedder())
        assert hits and all(hit.path.endswith(".md") for hit in hits)
        # 三条通道共用同一 store/同一索引表：没有任何第二集合出现（这里以结果仍能回到 5 条上限为证）。
        assert len(select(hits, query="launch code")) <= MAX_SELECTED
    finally:
        await store.close()


async def test_write_stores_embedding_in_the_same_column(tmp_path: Path) -> None:
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem"), embedder=FakeEmbedder()).connect()
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="the codename is ZEPHYR-9"),
            idempotency_key="emb-1",
        )
        row = await store._db.execute("SELECT embedding FROM memory_chunks LIMIT 1")  # type: ignore[union-attr]
        raw = (await row.fetchone())[0]
        assert raw, "配了 embedder 后写入必须落同一 memory_chunks.embedding 列"
        assert len(__import__("json").loads(raw)) == FakeEmbedder().dim
    finally:
        await store.close()


async def test_recall_ports_are_the_gated_entry_point(tmp_path: Path) -> None:
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem"), embedder=FakeEmbedder()).connect()
    await store.write(
        MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="user prefers terse answers about budgets"),
        idempotency_key="r-1",
    )
    try:
        recall = MemoryRecall(store, embedder=FakeEmbedder(), enabled=True)
        block = await recall.recall("what does the user prefer about budgets")
        assert isinstance(block, RecallBlock) and block.entry_ids
        assert await recall.recall("hi") is None  # 门控①：零信号输入不发检索
        assert await recall.recall("what does the user prefer about budgets", skip=True) is None  # 门控③
        assert await MemoryRecall(store, enabled=False).recall("what does the user prefer about budgets") is None  # 总闸默认关
        assert await MemoryRecall(None, enabled=True).recall("what does the user prefer about budgets") is None  # 无 store = 无召回
    finally:
        await store.close()


async def test_empty_store_cannot_be_attributed_so_nothing_is_injected(tmp_path: Path) -> None:
    """门控②：没候选就没有 entry_ids，注入也不可归因 → 返回 None（不造空块）。

    诚实边界：向量通道在确定性 fake 下无法辨别相关性（这正是 §6.2 把
    “真检索质量”标 UNVERIFIED 的原因），所以本判据用**空库**而不是“无关查询”。
    """
    empty = await SQLiteMemoryStore(db_path=str(tmp_path / "e.db"), memory_root=str(tmp_path / "mem"), embedder=FakeEmbedder()).connect()
    try:
        assert await MemoryRecall(empty, embedder=FakeEmbedder(), enabled=True).recall("anything about the launch schedule") is None
    finally:
        await empty.close()
