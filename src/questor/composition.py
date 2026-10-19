"""单一组合根（composition root）：所有生产入口共用的装配点（#161 / #154）。

这是把 L5 具体适配器（``SQLiteStore``/``SQLiteMemoryStore``/sandbox/ProcessRunner/ArtifactStore）
注入 L6 :class:`CliSurface` 的**唯一**位置——env 只在此读、内核保持 env-free（DESIGN §11）。
与 ``__main__`` 同处顶层包（非受 T20 守卫的 surfaces 层）：只有组合根可 import 具体 store，
surfaces 层自身只持 ``StorePort``/``MemoryStorePort`` 抽象（C4/C14）。

`python -m questor`（``__main__``）与 `python -m questor.surfaces.cli`（``cli.main``）都经
:func:`build_app`，杜绝历史上"第二入口装配显著弱于第一入口"（model 落回 echo、无 store/memory/exec）
的漂移（#161）。exec/写围栏/归档三件套在此真装配（#154），生产入口下 bash/powershell/write 可达。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from questor.providers.artifact_store import FileSystemArtifactStore
from questor.providers.process_runner import SandboxedProcessRunner
from questor.providers.sandbox import detect_sandbox
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces._assembly import log_dir_from_env
from questor.surfaces.cli import CliSurface

#: 组合根自述行 logger（一方 inline 记录；DoD A① "起手即有日志"由装配点兑现，两个入口共用）。
_LOG = logging.getLogger("questor.composition")


# ---- env 读取（组合根独占；默认 <cwd>/.questor 布局）---------------------
def store_path() -> str:
    return os.environ.get("QUESTOR_STORE_PATH", str(Path.cwd() / ".questor" / "state.db"))


def memory_db_path() -> str:
    return os.environ.get("QUESTOR_MEMORY_DB", str(Path.cwd() / ".questor" / "memory.db"))


def memory_root() -> str:
    return os.environ.get("QUESTOR_MEMORY_ROOT", str(Path.cwd() / ".questor" / "memory_store"))


def skills_dir_from_env() -> str:
    return os.environ.get("QUESTOR_SKILLS_DIR", str(Path.cwd() / ".questor" / "skills"))


def mcp_json_from_env() -> str:
    return os.environ.get("QUESTOR_MCP_JSON", str(Path.cwd() / "mcp.json"))


def model_from_env() -> str:
    """模型名取自 ``QUESTOR_MODEL``（缺省回落离线 "echo"）。必须透传给 CliSurface.model，
    否则 surface 缺省 "echo" 会在 litellm 的 ``request.model or self.model`` 里覆盖真供应商模型。"""
    return os.environ.get("QUESTOR_MODEL") or "echo"


def sidecar_generation_from_env() -> int:
    try:
        return int(os.environ.get("QUESTOR_SIDECAR_GENERATION", "1"))
    except ValueError:
        return 1


def sidecar_bootstrap_from_env() -> str:
    return os.environ.get("QUESTOR_SIDECAR_BOOTSTRAP", str(Path.cwd() / ".questor" / "sidecar-bootstrap.json"))


def web_dist_from_env() -> Path | None:
    dist = os.environ.get("QUESTOR_WEB_DIST")
    if not dist:
        return None
    path = Path(dist)
    return path if path.is_dir() else None


@dataclass
class App:
    """一次装配的产物：store/memory + exec 三件套 + 已注入它们的 surface。调用方负责 :func:`close_app`。"""

    store: SQLiteStore
    memory: SQLiteMemoryStore
    artifact_store: FileSystemArtifactStore
    sandbox: object
    process_runner: object
    surface: CliSurface


async def build_app() -> App:
    """连接持久层 + 装配 exec/写围栏/归档 + 构造 CliSurface。**唯一装配口径**。"""
    path = store_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    store = await SQLiteStore(path).connect()
    memory = await SQLiteMemoryStore(db_path=memory_db_path(), memory_root=memory_root()).connect()
    # exec 三件套：内容寻址归档 + 平台 sandbox 探测 + 受控进程执行器（#154）。
    data_root = Path(store_path()).parent
    artifact_store = FileSystemArtifactStore(data_root / "artifacts")
    await artifact_store.connect()
    sandbox = detect_sandbox()
    process_runner = SandboxedProcessRunner(sandbox, artifact_store=artifact_store, data_root=data_root)
    surface = CliSurface(
        store=store,
        memory_store=memory,
        model=model_from_env(),
        skills_dir=Path(skills_dir_from_env()),
        mcp_json_path=Path(mcp_json_from_env()),
        log_dir=Path(log_dir_from_env()),
        process_runner=process_runner,
        artifact_store=artifact_store,
        sandbox=sandbox,
    )
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
