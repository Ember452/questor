"""B8/c4：召回端口的装配面（生产默认开、直接构造默认关、无端口即逐字不变）。

三条判据：
1. `composition.build_app()` 造的 surface **带已启用的召回端口**（生产默认开）；
2. 直接 `CliSurface(...)` 仍 `recall is None` ——既有直连构造与既有测试逐字不变；
3. 没有端口时 loop 一个字节也不多发消息（`memory_injected` 只在真有注入时发）。
"""

from __future__ import annotations

from pathlib import Path

from questor.composition import AssembleSpec, build_app, close_app
from questor.contracts.ports import StreamChunk
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.memory.recall import MAX_SELECTED, MemoryRecall
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import EchoProvider, FakeEmbedder
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.state.domain_state import Run
from questor.surfaces.cli import CliSurface


def _point_env(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setenv("QUESTOR_STORE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_ROOT", str(tmp_path / "memory_store"))
    monkeypatch.setenv("QUESTOR_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("QUESTOR_MCP_JSON", str(tmp_path / "mcp.json"))
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)


async def test_production_composition_wires_an_enabled_recall(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    _point_env(monkeypatch, tmp_path)
    app = await build_app()
    try:
        recall = app.surface.recall
        assert isinstance(recall, MemoryRecall)
        assert recall.enabled is True and recall.limit == MAX_SELECTED
        assert recall.store is app.memory
        # B8 收口修正（review 驱动）：生产**不再**拿确定性 fake 当向量能力——本仓无真 embedding
        # 适配器，所以默认是 keyword + structured 开、向量通道关。曾经此处断言
        # `recall.embedder is not None`（同一 PR 内 4 个 commit 前的决定），现按事实改回；
        # “召回默认开”的既定行为不变（上面两行仍是它的判据）。
        assert recall.embedder is None
        assert recall.vector_channel_enabled is False
    finally:
        await close_app(app)


def test_direct_surface_still_has_no_recall(tmp_path: Path) -> None:
    surface = CliSurface(workspace_root=tmp_path, provider=EchoProvider())
    assert surface.recall is None
    assert surface.memory_index_enabled is False


def test_assemble_spec_can_override_the_recall_port() -> None:
    """注入位真实生效：给了 spec.recall 就用它，不再自建。"""
    sentinel = MemoryRecall(None, enabled=False)
    spec = AssembleSpec(recall=sentinel)
    assert spec.recall is sentinel


async def test_loop_without_recall_port_emits_nothing(tmp_path: Path) -> None:
    bus = InProcessEventBus()
    seen: list = []
    bus.add_observer(seen.append)

    class _OneShot:
        async def stream(self, request):  # noqa: ANN001, ANN201
            yield StreamChunk(kind="text", text="ok")
            yield StreamChunk(kind="finish", finish_reason="stop")

    loop = DefaultTurnLoop(
        provider=_OneShot(),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=lambda _name: None,
        workspace_root=tmp_path,
    )
    await loop.drive(Run(run_id="run_bare"), "what is the launch code for the deploy?")
    types = {env.type for env in seen}
    assert "memory_injected" not in types and "memory_consumed" not in types


async def test_disabled_recall_port_is_inert(tmp_path: Path) -> None:
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        recall = MemoryRecall(memory, embedder=FakeEmbedder(), enabled=False)
        assert await recall.recall("what does the user prefer about answer length?") is None
        assert recall.limit == MAX_SELECTED
    finally:
        await memory.close()
