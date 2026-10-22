"""统一组合根（#161）+ exec/写围栏/归档三件套接线（#154）的回归钉。

- build_app 必须把 process_runner/artifact_store/sandbox 装进 surface，并透传给 DefaultTurnLoop；
- 第二生产入口 `surfaces.cli.main()` 必须与 `__main__` 共用 build_app：model 来自 env（不落 "echo" 缺省）、
  有 store、exec 三件套齐备（#161 旧症：CliSurface() 零参 → 全丢）。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

import questor.surfaces.cli as cli_mod
from questor.composition import AssembleSpec, build_app, close_app
from questor.kernel.events import InProcessEventBus


def _point_env_to_tmp(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    q = tmp_path / ".questor"
    monkeypatch.setenv("QUESTOR_STORE_PATH", str(q / "state.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_DB", str(q / "memory.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_ROOT", str(q / "memory_store"))
    monkeypatch.setenv("QUESTOR_MODEL", "shared-model-from-env")
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(tmp_path / "logs"))


async def test_build_app_wires_exec_trio_into_surface(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    _point_env_to_tmp(monkeypatch, tmp_path)
    app = await build_app()
    try:
        assert app.surface.model == "shared-model-from-env"
        assert app.surface.process_runner is not None, "exec ProcessRunner 未接线（#154）"
        assert app.surface.artifact_store is not None, "归档 store 未接线（#154）"
        assert app.surface.sandbox is not None, "sandbox 未探测/注入（#154）"
        # _loop 必须把三件套透传给 DefaultTurnLoop（否则 run_process 仍恒 raise）。
        surface_obj = app.surface.registry.freeze_for_run("run_w")
        loop = app.surface._loop(InProcessEventBus(app.store), asyncio.Event(), surface_obj, run_id="run_w")
        assert loop.process_runner is not None
        assert loop.artifact_store is not None
        assert loop.sandbox is not None
    finally:
        await close_app(app)


async def test_build_app_rolls_back_handles_on_failure(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """W1-002：build_app 中途失败必须回滚已连的句柄，不留非守护 aiosqlite worker 挂死进程。"""
    _point_env_to_tmp(monkeypatch, tmp_path)
    baseline = set(threading.enumerate())

    def boom():
        raise RuntimeError("provider factory boom")

    with pytest.raises(RuntimeError):
        await build_app(AssembleSpec(provider_factory=boom))
    await asyncio.sleep(0.2)  # 让被回滚的 worker 线程真正退出
    # 只拦非守护的连接 worker（挂死主因，如 aiosqlite 的 Thread-N）；asyncio_ 默认执行器线程不算。
    leaked = [t.name for t in threading.enumerate() if t not in baseline and t.is_alive() and not t.name.startswith("asyncio_")]
    assert not leaked, f"失败回滚后仍有残留 worker 线程: {leaked}"


def test_cli_main_uses_shared_composition_root(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """第二入口 cli.main() 经 build_app：不再落到 model="echo"/store=None 的裸 CliSurface()。"""
    _point_env_to_tmp(monkeypatch, tmp_path)
    captured: dict = {}

    async def fake_interactive(surface=None):  # noqa: ANN001
        captured["surface"] = surface
        return 0

    # 隔离全局副作用：不把日志装配跑到真实/仓库目录，不阻塞交互——只验第二入口经 build_app 装配。
    monkeypatch.setattr(cli_mod, "interactive", fake_interactive)
    monkeypatch.setattr(cli_mod, "assemble_logging", lambda: None)
    rc = cli_mod.main()
    assert rc == 0
    surface = captured["surface"]
    assert surface is not None
    assert surface.model == "shared-model-from-env", "第二入口 model 未从 env 装配（#161 旧症：落回 echo）"
    assert surface.store is not None, "第二入口无 store → 无法落库/resume（#161）"
    assert surface.process_runner is not None, "第二入口 exec 未接线（#161/#154）"
