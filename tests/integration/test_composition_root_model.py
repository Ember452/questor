"""组合根模型接线回归测试（bug：``__main__`` 生成 ``CliSurface`` 未传 ``model``）。

此前 ``CliSurface(store=…, memory_store=…)`` 缺省 ``model="echo"``，经 loop → ``ProviderRequest.model``
在 ``litellm_adapter`` 的 ``request.model or self.model`` 里以非空真值 "echo" 覆盖了 ``LiteLLMProvider``
自带的 ``QUESTOR_MODEL``，导致 ``QUESTOR_MODEL`` 到不了真实模型。本测试锁死这条接线：

- 组合根必须把 ``QUESTOR_MODEL`` 透传到 ``CliSurface.model``（有 env → 用之；无 env → 回落 "echo"）。
- ``CliSurface.model`` 必须真的落到 ``ProviderRequest.model``（守住 ``request.model or self.model`` 语义，
  防止有人误改优先级再次丢模型）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

from questor import __main__ as questor_main
from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.observability import configure as log_configure
from questor.observability import exporter as log_exporter
from questor.observability import pipeline as log_pipeline
from questor.surfaces.cli import CliSurface


class _RecordingProvider(ProviderPort):
    """记录最近一次请求的 ``model``，随即礼貌收尾（单轮结束，不调工具）。"""

    def __init__(self) -> None:
        self.seen_model: str | None = None

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        self.seen_model = request.model
        yield StreamChunk(kind="finish", finish_reason="stop")


async def _capture_surface(tmp_path: Path, monkeypatch, argv: list[str]) -> CliSurface:  # noqa: ANN001
    """跑组合根 ``_amain``，但把 ``interactive`` 换成"记录 surface 即返回"，避免阻塞读 stdin/联网。"""
    captured: dict[str, CliSurface] = {}

    async def _fake_interactive(surface: CliSurface | None = None) -> int:
        assert surface is not None
        captured["surface"] = surface
        return 0

    # store/记忆库都落 tmp_path，用真实 SQLiteStore（不 mock 装配缺口），跑完 finally 自关连接。
    monkeypatch.setattr(questor_main, "interactive", _fake_interactive)
    monkeypatch.setenv("QUESTOR_STORE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_ROOT", str(tmp_path / "memory_store"))
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(tmp_path / "logs"))  # 组合根会建文件面，别落在仓库 cwd
    # ``_amain`` 起手装完整日志装配（带内桥 + console + 文件 sink），是进程级单例；跑完必须整体回滚，
    # 否则残留的桥/console 泄进后续 ``test_configure`` 用例（幂等断言变 2 桥）。T2.14 引入的行为。
    root = logging.getLogger()
    saved = (list(root.handlers), root.level, list(log_exporter._registry), log_configure._state)
    try:
        await questor_main._amain(argv)  # noqa: SLF001 - 组合根入口本身就是被测对象
    finally:
        log_configure._teardown()  # noqa: SLF001
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        log_exporter._registry[:] = saved[2]
        log_configure._state = saved[3]
        log_pipeline.reset()
    return captured["surface"]


async def test_composition_root_passes_questor_model_to_surface(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """有 ``QUESTOR_MODEL`` 时，组合根生成的 ``CliSurface.model`` 必须等于该值（修复前判红：为 "echo"）。"""
    monkeypatch.setenv("QUESTOR_MODEL", "deepseek/deepseek-v4-flash")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)  # 无 key → provider 走离线 Echo，不联网
    surface = await _capture_surface(tmp_path, monkeypatch, [])
    assert surface.model == "deepseek/deepseek-v4-flash", (
        f"QUESTOR_MODEL 未透传到组合根 surface：实际 model={surface.model!r}"
    )


async def test_composition_root_defaults_model_to_echo_when_unset(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """无 ``QUESTOR_MODEL`` 时回落离线 "echo"（守住"不过度修复"，离线冒烟面不变）。"""
    monkeypatch.delenv("QUESTOR_MODEL", raising=False)
    surface = await _capture_surface(tmp_path, monkeypatch, [])
    assert surface.model == "echo"


async def test_surface_model_reaches_provider_request(tmp_path: Path) -> None:
    """``CliSurface.model`` 必须落到 ``ProviderRequest.model``（守住 request/provider 优先级语义）。"""
    provider = _RecordingProvider()
    surface = CliSurface(workspace_root=tmp_path, provider=provider, model="deepseek/deepseek-v4-flash")
    await surface.run_once("hi")
    assert provider.seen_model == "deepseek/deepseek-v4-flash", (
        f"surface.model 未进入请求：provider 收到 model={provider.seen_model!r}"
    )
