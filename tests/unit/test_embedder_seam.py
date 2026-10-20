"""B8 收口修正：向量能力必须有**单一接缝**，生产不得把确定性 fake 当能力开。

判据对着评审抓到的那条缺陷写：

- 生产默认 `keyword + structured 开、向量关`（本仓无真 embedding 适配器），且**召回仍真在工作**；
- store 侧与 query 侧只能是同一个 embedder 实例——"半接"会让不同空间的余弦值决定注入哪几条，
  而且不会有任何测试变红，所以这一条必须由判据守住；
- 用户明确要了向量能力（设 `QUESTOR_EMBED_MODEL`）但没有实现时：出声 + 关闭，绝不静默塞个 fake。
"""

from __future__ import annotations

import logging
from pathlib import Path

from questor.composition import AssembleSpec, build_app, close_app
from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.memory.recall import MemoryRecall
from questor.providers.embedder_factory import EMBEDDER_BUILDERS, embedder_from_env, shared_embedder
from questor.providers.fake import FakeEmbedder
from questor.providers.store_memory_sqlite import SQLiteMemoryStore

_FACT = "the deploy window is WEDNESDAY-0400"

# 下面的用例故意用“存进去就是这句”的短语作 query：keyword 通道是 LIKE 包含判定，
# 不接向量时它能真命中；拿只有向量才能命中的自然语言问法来判“召回仍在工作”，
# 等于拿一个需要向量的前提去证不需要向量的结论。


def _point_env(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setenv("QUESTOR_STORE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_ROOT", str(tmp_path / "memory_store"))
    monkeypatch.setenv("QUESTOR_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("QUESTOR_MCP_JSON", str(tmp_path / "mcp.json"))
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("QUESTOR_EMBED_MODEL", raising=False)


async def _seed_memory(memory: SQLiteMemoryStore, text: str = _FACT) -> None:
    await memory.write(
        MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text=text, attributed_to="user"),
        idempotency_key=f"seed-{len(text)}",
    )


async def test_production_default_keeps_recall_on_but_vector_off(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """生产默认：召回开着、向量通道关着，而且**关着也真能召回**（keyword 通道不是摆设）。"""
    _point_env(monkeypatch, tmp_path)
    app = await build_app()
    try:
        await _seed_memory(app.memory)
        recall = app.surface.recall
        assert isinstance(recall, MemoryRecall)
        assert recall.enabled is True
        assert recall.embedder is None and recall.vector_channel_enabled is False
        block = await recall.recall(_FACT)
        assert block is not None and _FACT in block.text
        assert all(entry_id.count(":") >= 1 for entry_id in block.entry_ids)  # 条目级归因仍在
    finally:
        await close_app(app)


def test_composition_does_not_import_test_doubles() -> None:
    """`composition.py` 源码里不得出现替身模块（守卫 `check_extension_points` E 的可见镜像）。"""
    source = (Path(__file__).resolve().parents[2] / "src" / "questor" / "composition.py").read_text(encoding="utf-8")
    assert "from questor.providers.fake" not in source  # 注释里提到 FakeEmbedder 是历史说明，不算 import


async def test_injected_embedder_is_the_same_instance_on_both_sides(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """显式注 `spec.embedder` 时，store 侧与 query 侧必须是同一实例（同一向量空间）。"""
    _point_env(monkeypatch, tmp_path)
    embedder = FakeEmbedder()
    app = await build_app(AssembleSpec(embedder=embedder))
    try:
        assert app.memory.embedder is embedder
        assert app.surface.recall.embedder is embedder
        assert app.surface.recall.vector_channel_enabled is True
    finally:
        await close_app(app)


async def test_mismatched_store_embedder_closes_the_vector_channel(tmp_path: Path, caplog) -> None:  # noqa: ANN001
    """store 自带 A、query 传 B：判据是**关掉向量通道并出声**，不是硬拼一个能跑的假象。"""
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem"), embedder=FakeEmbedder()).connect()
    try:
        other = FakeEmbedder()
        assert other is not memory.embedder
        with caplog.at_level(logging.WARNING, logger="questor.embedders"):
            assert shared_embedder(memory, other) is None
        assert "vector channel stays off" in caplog.text
        # 同实例时才放行
        assert shared_embedder(memory, memory.embedder) is memory.embedder
        assert shared_embedder(memory, None) is None
    finally:
        await memory.close()


async def test_vector_off_results_are_identical_to_no_vector(tmp_path: Path) -> None:
    """关向量与"根本没有向量能力"必须逐字同结果：防"半接"留下任何静默差异。"""
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        await _seed_memory(memory)
        plain = MemoryRecall(memory, enabled=True)
        off = MemoryRecall(memory, embedder=None, enabled=True)
        query = _FACT
        a, b = await plain.recall(query), await off.recall(query)
        assert a is not None and b is not None
        assert a.text == b.text and a.entry_ids == b.entry_ids
        assert plain.vector_channel_enabled is False and off.vector_channel_enabled is False
    finally:
        await memory.close()


def test_embedder_from_env_is_none_unless_an_implementation_is_registered(monkeypatch, caplog) -> None:  # noqa: ANN001
    """没设 env → 安静 None；设了但没有 builder → **出声** None（绝不退回 fake）。"""
    monkeypatch.delenv("QUESTOR_EMBED_MODEL", raising=False)
    assert embedder_from_env() is None

    monkeypatch.setenv("QUESTOR_EMBED_MODEL", "text-embedding-3-small")
    assert not EMBEDDER_BUILDERS, "仓内若接入了真 embedding，本判据要连带更新（不只是让它变绿）"
    with caplog.at_level(logging.WARNING, logger="questor.embedders"):
        assert embedder_from_env() is None
    assert "no registered embedding builder" in caplog.text
