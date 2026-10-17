"""组合根入口（composition root）：装配 StorePort + MemoryStorePort 后启动 CLI 传输面。

用 ``python -m questor`` 运行。本模块**可以** import 具体适配器（``SQLiteStore``/
``SQLiteMemoryStore``）——它是把 L5 实现注入 L6 surfaces 的唯一装配点；surfaces 自身只持
``StorePort``/``MemoryStorePort`` 抽象（C4/C14）。

- ``python -m questor``：交互 REPL（每轮真实落库到 store，支撑 resume）。
- ``python -m questor --serve``：起 HTTP+SSE sidecar 服务（bind ``127.0.0.1:0`` + 写 bootstrap，ADR-0032）。
- ``python -m questor --resume <run_id>``：从持久态续跑被 kill/重启的 run（P3）。
- ``python -m questor --list``：列出未完成的 run id（供选择续跑）。
- ``python -m questor --dream``：离线 Deep Dream 蒸馏（夜间批处理，把近期 daily 固化回 core）。

路径：state 取 ``QUESTOR_STORE_PATH``（默认 ``<cwd>/.questor/state.db``）；记忆库取
``QUESTOR_MEMORY_DB``（默认 ``<cwd>/.questor/memory.db``）、md 真源根取 ``QUESTOR_MEMORY_ROOT``
（默认 ``<cwd>/.questor/memory_store``）。记忆与 event-log 分库（ADR-0023 故障隔离）。

日志（ADR-0027 / DESIGN §10/§11）：目录取 ``QUESTOR_LOG_DIR``（默认 ``<cwd>/.questor/logs/``，写
按日 JSONL 主干 + ``errors``/``llm`` 分流）；console 级别取 ``QUESTOR_LOG_LEVEL``（默认 INFO，主干
文件恒 DEBUG）；保留天数取 ``QUESTOR_LOG_KEEP_DAYS``（默认 14，启动懒清理）；``QUESTOR_LOG_PAYLOAD``
（默认 off）为 preview 开关、实装归刀 3、本期非 off 值拒绝启动。这些 env 只在组合根读、内核 env-free。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from questor.memory.distill import DistillOutcome, deep_dream
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces._assembly import assemble_logging, log_dir_from_env
from questor.surfaces.cli import CliSurface, interactive
from questor.surfaces.http_sse import EventServer
from questor.surfaces.serve import serve

#: 组合根自述行 logger（一方 inline 记录；DoD A① 的"起手即有日志"靠它兑现）。
_LOG = logging.getLogger("questor.composition")


def _store_path() -> str:
    return os.environ.get("QUESTOR_STORE_PATH", str(Path.cwd() / ".questor" / "state.db"))


def _memory_db_path() -> str:
    return os.environ.get("QUESTOR_MEMORY_DB", str(Path.cwd() / ".questor" / "memory.db"))


def _memory_root() -> str:
    return os.environ.get("QUESTOR_MEMORY_ROOT", str(Path.cwd() / ".questor" / "memory_store"))


def _skills_dir_from_env() -> str:
    """技能搜索目录取自 ``QUESTOR_SKILLS_DIR``（默认 ``<cwd>/.questor/skills``）；env 读属组合根职责。

    与 ``QUESTOR_STORE_PATH``/``QUESTOR_LOG_DIR`` 同族命名；目录不存在时 catalog 为空（合法，不报错）。"""
    return os.environ.get("QUESTOR_SKILLS_DIR", str(Path.cwd() / ".questor" / "skills"))


def _mcp_json_from_env() -> str:
    """MCP 配置文件取自 ``QUESTOR_MCP_JSON``（默认 ``<cwd>/mcp.json``，已在 PROTECTED_IN_ROOTS 写保护）。

    文件不存在时 bootstrap 发现为空（无 MCP server 是合法的，不报错、不改动 run）。"""
    return os.environ.get("QUESTOR_MCP_JSON", str(Path.cwd() / "mcp.json"))


def _model_from_env() -> str:
    """模型名取自 ``QUESTOR_MODEL``（缺省回落离线 ``"echo"``）；env 读取属组合根职责（DESIGN §11）。

    必须在此透传给 ``CliSurface.model``：否则 surface 用缺省 "echo"，经 loop → ``ProviderRequest.model``
    在 litellm 的 ``request.model or self.model`` 里以非空真值 "echo" 覆盖 ``LiteLLMProvider`` 自带的
    ``QUESTOR_MODEL``，模型名就到不了真实供应商（P4 复审发现的接线缺陷）。"""
    return os.environ.get("QUESTOR_MODEL") or "echo"


def _sidecar_generation_from_env() -> int:
    """sidecar 代次由启动方（Rust 注入的 env）指定、默认 1；随 bootstrap 落盘作陈旧连接栅栏基（ADR-0032）。解析失败回落 1，绝不在装配期崩。"""
    try:
        return int(os.environ.get("QUESTOR_SIDECAR_GENERATION", "1"))
    except ValueError:
        return 1


def _sidecar_bootstrap_from_env() -> str:
    """bootstrap 落盘路径取自 ``QUESTOR_SIDECAR_BOOTSTRAP``（默认 ``<cwd>/.questor/sidecar-bootstrap.json``）；env 读属组合根职责。"""
    return os.environ.get("QUESTOR_SIDECAR_BOOTSTRAP", str(Path.cwd() / ".questor" / "sidecar-bootstrap.json"))


def _web_dist_from_env() -> Path | None:
    """桌面前端静态产物目录取自 ``QUESTOR_WEB_DIST``（未设或目录不存在则 None → sidecar 只跑 API，不挂静态）。

    给定后 sidecar 一并伺服前端、webview 指本服务根路径（ADR-0007）；env 读属组合根职责，serve 面不读 env。"""
    dist = os.environ.get("QUESTOR_WEB_DIST")
    if not dist:
        return None
    path = Path(dist)
    return path if path.is_dir() else None


class _HeuristicDistiller:
    """无密钥离线 fallback 蒸馏器：**合并**现有 core + 近期 daily 的非标题行去重回写（单调不回退）。

    诚实边界：真 LLM 蒸馏质量 UNVERIFIED；配置 ``LITELLM_API_KEY`` 时可换成 LLM-backed
    ``DistillProvider`` 注入（本组合根是唯一装配点）。无可萃取时返回 ``None`` → 空哨兵跳过。"""

    @staticmethod
    def _facts(text: str) -> set[str]:
        return {line.lstrip("- ").strip() for line in text.splitlines() if line.strip() and not line.startswith("#")}

    async def distill(self, core: str, dailies: list[str]) -> DistillOutcome | None:
        # 合并现有 core 与近期 daily：新原料为空时仍保留既有精华，避免 --dream 把 core 越刷越小。
        facts = self._facts(core) | self._facts("\n".join(dailies))
        if not facts:
            return None
        new_core = "# MEMORY\n" + "".join(f"- {f}\n" for f in sorted(facts))
        return DistillOutcome(new_core=new_core, dream=f"consolidated {len(facts)} fact(s) into core")


async def _amain(argv: list[str]) -> int:
    # 组合根唯一装配入口（DESIGN §11；T2.14）：读 env 族并装**完整管线**——带内桥 + console(stderr)
    # + 按日 JSONL 文件面 + errors 分流——覆盖 REPL/--resume/--list/--dream 四入口。参数由组合根注入、
    # 内核 env-free（config⟂observability）。sidecar 宿主入口须调同一装配口径、不自配。
    assemble_logging()
    path = _store_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    store = await SQLiteStore(path).connect()
    memory = await SQLiteMemoryStore(db_path=_memory_db_path(), memory_root=_memory_root()).connect()
    # 起手一条一方记录钉住"装配与存储就绪"（DoD A①）：路径不含会话内容，零原文政策不破。
    _LOG.info(
        "composition root ready store=%s memory_db=%s",
        path,
        _memory_db_path(),
        extra={"log_fields": {"entry": argv[0] if argv else "repl"}},
    )
    try:
        if argv and argv[0] == "--dream":
            lookback = int(os.environ.get("QUESTOR_DREAM_LOOKBACK", "7"))
            result = await deep_dream(memory, _HeuristicDistiller(), lookback_days=lookback)
            print(
                f"deep_dream: wrote={result.get('wrote')} reason={result.get('reason', '-')} "
                f"input_hash={str(result.get('input_hash', ''))[:12]}"
            )
            return 0
        surface = CliSurface(
            store=store,
            memory_store=memory,
            model=_model_from_env(),
            skills_dir=Path(_skills_dir_from_env()),
            mcp_json_path=Path(_mcp_json_from_env()),
            log_dir=Path(log_dir_from_env()),
        )
        if argv and argv[0] == "--serve":
            # sidecar 常驻服务：EventServer 复用已装配的 surface + store（surface 只持 StorePort 抽象，C4），
            # serve 面只 bind loopback 临时口 + 写 bootstrap，不 import 具体 store（ADR-0032 / S6）。
            server = EventServer(surface, store)
            await serve(
                server,
                generation=_sidecar_generation_from_env(),
                bootstrap_path=Path(_sidecar_bootstrap_from_env()),
                static_dir=_web_dist_from_env(),
            )
            return 0
        if argv and argv[0] == "--list":
            unfinished = await store.list_unfinished_runs()
            for run_id in unfinished:
                print(run_id)
            if not unfinished:
                print("(no unfinished runs)")
            return 0
        if argv and argv[0] == "--resume":
            if len(argv) < 2:
                print("usage: python -m questor --resume <run_id>", file=sys.stderr)
                return 2
            final = await surface.resume(argv[1])
            if final is None:
                print(f"no checkpoint for run {argv[1]}", file=sys.stderr)
                return 1
            return 0
        return await interactive(surface)
    finally:
        await memory.close()
        await store.close()


def main() -> int:
    """CLI 入口；Ctrl-C 退出码 130。"""
    try:
        return asyncio.run(_amain(sys.argv[1:]))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
