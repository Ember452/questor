"""单一组合根（composition root）：所有生产入口共用的装配点（#161 / #154）。

这是把 L5 具体适配器（``SQLiteStore``/``SQLiteMemoryStore``/sandbox/ProcessRunner/ArtifactStore）
注入 L6 :class:`CliSurface` 的**唯一**位置——env 只在此读、内核保持 env-free（DESIGN §11）。
与 ``__main__`` 同处顶层包（非受 T20 守卫的 surfaces 层）：只有组合根可 import 具体 store，
surfaces 层自身只持 ``StorePort``/``MemoryStorePort`` 抽象（C4/C14）。

`python -m questor`（``__main__``）与 `python -m questor.surfaces.cli`（``cli.main``）都经
:func:`build_app`，杜绝历史上"第二入口装配显著弱于第一入口"（model 落回 echo、无 store/memory/exec）
的漂移（#161）。exec/写围栏/归档三件套在此真装配（#154），生产入口下 bash/powershell/write 可达。

装配的**输入形状**由 :class:`AssembleSpec` 声明（OPT-2a）：它是 frozen 纯数据，不是服务定位器，
未给的字段一律保持历史自建路径（零行为变更）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from questor.config.model import load_config
from questor.contracts.memory import MemoryStorePort, RecallPort
from questor.contracts.ports import ContextAssemblerPort, ProviderPort, StorePort, SurfacePort
from questor.memory.recall import MemoryRecall
from questor.providers.artifact_store import FileSystemArtifactStore
from questor.providers.fake import FakeEmbedder
from questor.providers.process_runner import SandboxedProcessRunner
from questor.providers.provider_factory import provider_from_env
from questor.providers.sandbox import select_sandbox
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces._assembly import log_dir_from_env, payload_preview_from_env, production_compaction_from_env
from questor.surfaces.cli import CliSurface

#: 组合根自述行 logger（一方 inline 记录；DoD A① "起手即有日志"由装配点兑现，两个入口共用）。
_LOG = logging.getLogger("questor.composition")


# ---- env 读取（组合根独占；默认 <cwd>/.questor 布局）---------------------
# 具体读取已收口到 ``questor.config.model.load_config()``（OPT-3 c2）：本模块只做"取子块"。
# 每个函数仍**现读现用**（无缓存）——与历史逐字等价。
def store_path() -> str:
    return load_config().paths.store_path


def memory_db_path() -> str:
    return load_config().paths.memory_db


def memory_root() -> str:
    return load_config().paths.memory_root


def skills_dir_from_env() -> str:
    return load_config().paths.skills_dir


def mcp_json_from_env() -> str:
    return load_config().paths.mcp_json


def model_from_env() -> str:
    """模型名取自 ``QUESTOR_MODEL``（缺省回落离线 "echo"）。必须透传给 CliSurface.model，
    否则 surface 缺省 "echo" 会在 litellm 的 ``request.model or self.model`` 里覆盖真供应商模型。"""
    return load_config().llm.model_name


def sidecar_generation_from_env() -> int:
    return load_config().sidecar.generation


def sidecar_bootstrap_from_env() -> str:
    return load_config().sidecar.bootstrap_path


def web_dist_from_env() -> Path | None:
    return load_config().sidecar.web_dist


@dataclass(frozen=True, slots=True)
class AssembleSpec:
    """一次装配的**输入规格**（OPT-2a）：纯数据，字段默认 ``None`` = 走现路径自建。

    红线（刻意不做的三件事）：
    - **不是服务定位器**：没有 ``get(name)``/动态解析/按名注入，也不持有 registry 或容器；
    - **不管生命周期**：没有 init/teardown/scope，句柄的连接与关闭仍归 :func:`build_app` /
      :func:`close_app`；
    - **不改构造顺序**：未给的字段按历史顺序与默认值自建（``store → memory → artifact → sandbox →
      process_runner → surface``），因此默认 spec 与无 spec 逐字段等价。

    字段状态：``surface``/``provider_factory``/``store``/``memory``/``artifact``/``sandbox``/
    ``context_assembler`` 已接线（OPT-2a / OPT-12a）；``loop``/``policy_factory``/``summarizer``/
    ``memory_strategy``/``profile`` 是已定形、待后续刀接线的接缝——**本轮不改任何装配行为**。
    """

    surface: object | None = None
    provider_factory: Callable[[], ProviderPort] | None = None
    store: StorePort | None = None
    memory: MemoryStorePort | None = None
    artifact: object | None = None
    sandbox: object | None = None
    loop: object | None = None
    policy_factory: Callable[[], object] | None = None
    summarizer: object | None = None
    context_assembler: ContextAssemblerPort | None = None
    memory_strategy: object | None = None
    profile: str | None = None
    #: 沙箱后端选择（OPT-7）：只选后端、不放宽 fail-closed；None = 现探测。
    sandbox_backend: str | None = None
    #: 记忆召回端口（B8）：None = 组合根自己构造默认实现（生产默认开，见 `build_app`）。
    recall: RecallPort | None = None


@dataclass
class App:
    """一次装配的产物：store/memory + exec 三件套 + 已注入它们的 surface。调用方负责 :func:`close_app`。"""

    store: SQLiteStore
    memory: SQLiteMemoryStore
    artifact_store: FileSystemArtifactStore
    sandbox: object
    process_runner: object
    surface: SurfacePort


async def build_app(spec: AssembleSpec | None = None) -> App:
    """连接持久层 + 装配 exec/写围栏/归档 + 构造 surface。**唯一装配口径**。

    ``spec is None`` 时逐字走历史路径；给了 spec 则按字段取用，**未给的字段仍按历史顺序自建**
    （OPT-2a：默认 spec 与无 spec 逐字段等价）。注入语义：
    - ``store``/``memory``/``artifact``/``sandbox``：直接采用，不再 connect（句柄生命周期归调用方，
      仍由 :func:`close_app` 统一回收）；
    - ``provider_factory``：只在装配时调用一次；None → 组合根按 env 选 provider（现路径）；
    - ``surface``：采用给定实例，不再构造 CliSurface（其余句柄仍装配，供 App 字段/关闭与自述日志）。
    """
    spec = spec or AssembleSpec()
    path = store_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    store = spec.store if spec.store is not None else await SQLiteStore(path).connect()
    memory = spec.memory if spec.memory is not None else await SQLiteMemoryStore(db_path=memory_db_path(), memory_root=memory_root()).connect()
    # exec 三件套：内容寻址归档 + 平台 sandbox 探测 + 受控进程执行器（#154）。
    data_root = Path(store_path()).parent
    artifact_store = spec.artifact if spec.artifact is not None else FileSystemArtifactStore(data_root / "artifacts")
    if spec.artifact is None:
        await artifact_store.connect()
    sandbox = spec.sandbox if spec.sandbox is not None else select_sandbox(spec.sandbox_backend)
    process_runner = SandboxedProcessRunner(sandbox, artifact_store=artifact_store, data_root=data_root)
    if spec.surface is None:
        provider = (
            spec.provider_factory()
            if spec.provider_factory is not None
            else provider_from_env(payload_preview=payload_preview_from_env())
        )
        # B8 `[behavior]`：生产入口默认开自动召回（直接构造 CliSurface 仍默认无召回）。
        # embedding 用确定性 fake：CI 无密钥时只证向量通道接得通，真检索质量仍 UNVERIFIED。
        recall = spec.recall if spec.recall is not None else MemoryRecall(memory, embedder=FakeEmbedder(), enabled=True)
        # B10 `[behavior]`：生产入口默认开可恢复压缩。翻的是**默认值**而不是**开关能力**：
        # 显式 QUESTOR_COMPACTION=off 仍逐字关；直接构造 CliSurface 的路径不读这个口径（不变）。
        model = model_from_env()
        surface = CliSurface(
            store=store,
            memory_store=memory,
            provider=provider,
            model=model,
            skills_dir=Path(skills_dir_from_env()),
            mcp_json_path=Path(mcp_json_from_env()),
            log_dir=Path(log_dir_from_env()),
            process_runner=process_runner,
            artifact_store=artifact_store,
            sandbox=sandbox,
            context_assembler=spec.context_assembler,
            # B7 `[behavior]`：生产入口默认开档1 记忆索引注入（直接构造 CliSurface 仍默认关）。
            memory_index_enabled=True,
            recall=recall,
            compaction=production_compaction_from_env(model),
        )
    else:
        surface = spec.surface
    _LOG.info(
        "composition root ready store=%s memory_db=%s sandbox=%s",
        path,
        memory_db_path(),
        sandbox.describe().backend.value,
    )
    return App(store=store, memory=memory, artifact_store=artifact_store, sandbox=sandbox, process_runner=process_runner, surface=surface)


async def close_app(app: App) -> None:
    """按打开的反序释放持久层与归档句柄（artifact 为纯文件系统，close 幂等）。"""
    await app.artifact_store.close()
    await app.memory.close()
    await app.store.close()
