"""默认 ``AssembleSpec`` 与历史 ``build_app()`` 的逐字段等价钉（OPT-2a a3）。

零行为变更的判据不是"看代码像"：默认 spec 装出的 App 必须与无 spec 的历史路径**逐字段相等**
（类型 + 关键标量 + surface 装配面），并且 CLI 的用法文本/退出码快照一字不差。
spec 真注入时还要证明"给了就用、没给仍自建"（否则接缝只是摆设）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from questor.composition import AssembleSpec, build_app, close_app
from questor.providers.artifact_store import FileSystemArtifactStore
from questor.providers.fake import EchoProvider
from questor.providers.sandbox import detect_sandbox
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: ``python -m questor --help`` 的**完整 stdout 快照**（逐字节；``print`` 末尾带一个换行）。
#: 用法文本是用户可见输出，任何改动都必须有意识：改这里 = 改契约（AGENTS §5.6）。
_USAGE_SNAPSHOT = """usage: python -m questor [command]

commands:
  (none)             start the interactive REPL (every turn is persisted; supports --resume)
  --serve            run the HTTP+SSE sidecar (bind 127.0.0.1:0 + write bootstrap)
  --serve-openai     run the authenticated external OpenAI-compat API lane (requires QUESTOR_OPENAI_API_KEYS)
  --resume <run_id>  resume a killed/restarted run from durable state
  --list             list unfinished run ids
  --dream            run offline Deep Dream distillation
  logs [--run ID]    read-only log consumption (event_log + bypass JSONL timeline)
  logs --run ID --expand  recover a run's compacted originals via covered_hash (fail-closed)
  logs --totals      cross-run usage totals projected from durable run_completed
  maintenance        reclaim expired leases + stale unacked claims (Lane D hygiene)
  -h, --help         show this usage and exit (no store, no logging assembly, no REPL)

env (read by the composition root only; the kernel stays env-free):
  QUESTOR_MODEL, QUESTOR_STORE_PATH, QUESTOR_MEMORY_DB, QUESTOR_MEMORY_ROOT,
  QUESTOR_SKILLS_DIR, QUESTOR_MCP_JSON, QUESTOR_LOG_DIR, QUESTOR_LOG_LEVEL,
  QUESTOR_LOG_KEEP_DAYS, QUESTOR_LOG_PAYLOAD, QUESTOR_SIDECAR_GENERATION,
  QUESTOR_SIDECAR_BOOTSTRAP, QUESTOR_WEB_DIST, QUESTOR_DREAM_LOOKBACK,
  QUESTOR_OPENAI_API_KEYS, QUESTOR_OPENAI_HOST, QUESTOR_OPENAI_PORT
"""


def _point_env_to_tmp(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """把组合根读的全部路径类 env 指向 tmp（不落仓库 cwd），并清掉密钥走离线 Echo。"""
    q = tmp_path / ".questor"
    monkeypatch.setenv("QUESTOR_STORE_PATH", str(q / "state.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_DB", str(q / "memory.db"))
    monkeypatch.setenv("QUESTOR_MEMORY_ROOT", str(q / "memory_store"))
    monkeypatch.setenv("QUESTOR_SKILLS_DIR", str(q / "skills"))
    monkeypatch.setenv("QUESTOR_MCP_JSON", str(tmp_path / "mcp.json"))
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("QUESTOR_MODEL", "shared-model-from-env")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)


async def test_default_spec_reproduces_legacy_build_app_fields(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """``build_app(AssembleSpec())`` 与 ``build_app()`` 逐字段相等（类型 + 标量 + surface 装配面）。"""
    _point_env_to_tmp(monkeypatch, tmp_path)
    legacy = await build_app()
    spec_app = await build_app(AssembleSpec())
    try:
        assert type(spec_app.store) is type(legacy.store) is SQLiteStore
        assert spec_app.store.path == legacy.store.path
        assert type(spec_app.memory) is type(legacy.memory) is SQLiteMemoryStore
        assert (spec_app.memory.db_path, spec_app.memory.memory_root) == (legacy.memory.db_path, legacy.memory.memory_root)
        assert type(spec_app.artifact_store) is type(legacy.artifact_store) is FileSystemArtifactStore
        assert spec_app.artifact_store.root == legacy.artifact_store.root
        assert type(spec_app.process_runner) is type(legacy.process_runner)
        # sandbox 是平台探测结果：比对它的公开描述（backend/能力事实/限制）而不是对象身份。
        assert spec_app.sandbox.describe() == legacy.sandbox.describe()

        spec_surface, legacy_surface = spec_app.surface, legacy.surface
        assert spec_surface.model == legacy_surface.model == "shared-model-from-env"
        assert spec_surface.system == legacy_surface.system
        assert (spec_surface.policy_id, spec_surface.ab_table, spec_surface.compaction) == (
            legacy_surface.policy_id,
            legacy_surface.ab_table,
            legacy_surface.compaction,
        )
        assert (spec_surface.mcp_json_path, spec_surface.log_dir, spec_surface.workspace_root) == (
            legacy_surface.mcp_json_path,
            legacy_surface.log_dir,
            legacy_surface.workspace_root,
        )
        assert type(spec_surface.provider) is type(legacy_surface.provider) is EchoProvider
        assert spec_surface.process_runner is spec_app.process_runner
        assert spec_surface.sandbox is spec_app.sandbox
        # 工具名册（含顺序）也是装配面的一部分：默认 spec 不得少注册/多注册任何工具。
        assert [tool.spec.name for tool in spec_surface.registry.list_available()] == [
            tool.spec.name for tool in legacy_surface.registry.list_available()
        ]
    finally:
        await close_app(legacy)
        await close_app(spec_app)


async def test_spec_fields_are_used_and_absent_fields_still_self_build(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """给了的字段直接用（不再自建）、没给的仍自建——接缝必须真接线而不是被忽略。"""
    _point_env_to_tmp(monkeypatch, tmp_path)
    store = await SQLiteStore(str(tmp_path / "injected.db")).connect()
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "injected-memory.db"), memory_root=str(tmp_path / "mem")).connect()
    artifact = FileSystemArtifactStore(tmp_path / "artifacts")
    await artifact.connect()
    sandbox = detect_sandbox()
    provider_calls: list[int] = []

    def _factory():
        provider_calls.append(1)
        return EchoProvider()

    app = await build_app(AssembleSpec(store=store, memory=memory, artifact=artifact, sandbox=sandbox, provider_factory=_factory))
    try:
        assert app.store is store
        assert app.memory is memory
        assert app.artifact_store is artifact
        assert app.sandbox is sandbox
        assert app.surface.store is store, "注入的 store 未进 surface（仍自建了一头）"
        assert app.surface.sandbox is sandbox
        assert provider_calls == [1], "provider_factory 未恰好被调用一次"
        assert isinstance(app.surface.provider, EchoProvider)
        # 未给的 process_runner 仍按历史口径自建（sandbox/artifact 取自注入值）。
        assert app.process_runner is not None
        assert app.surface.process_runner is app.process_runner
    finally:
        await close_app(app)


def test_cli_usage_and_exit_code_snapshot_unchanged(tmp_path: Path) -> None:
    """``--help`` 的 stdout/退出码逐字节快照（零行为变更的对外证据）。"""
    env = {
        **os.environ,
        "QUESTOR_STORE_PATH": str(tmp_path / "state.db"),
        "QUESTOR_MEMORY_DB": str(tmp_path / "memory.db"),
        "QUESTOR_MEMORY_ROOT": str(tmp_path / "memory_store"),
        "QUESTOR_LOG_DIR": str(tmp_path / "logs"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "PYTHONPATH": str(_REPO_ROOT / "src"),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "questor", "--help"],
        env=env,
        cwd=_REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"rc={proc.returncode}\nstderr={proc.stderr!r}"
    assert proc.stdout == _USAGE_SNAPSHOT + "\n", f"用法快照漂移：{proc.stdout!r}"
