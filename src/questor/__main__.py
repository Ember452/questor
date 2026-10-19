"""组合根入口（composition root）：装配 StorePort + MemoryStorePort 后启动 CLI 传输面。

用 ``python -m questor`` 运行。本模块**可以** import 具体适配器（``SQLiteStore``/
``SQLiteMemoryStore``）——它是把 L5 实现注入 L6 surfaces 的唯一装配点；surfaces 自身只持
``StorePort``/``MemoryStorePort`` 抽象（C4/C14）。

- ``python -m questor``：交互 REPL（每轮真实落库到 store，支撑 resume）。
- ``python -m questor --serve``：起 HTTP+SSE sidecar 服务（bind ``127.0.0.1:0`` + 写 bootstrap，ADR-0032）。
- ``python -m questor --resume <run_id>``：从持久态续跑被 kill/重启的 run（P3）。
- ``python -m questor --list``：列出未完成的 run id（供选择续跑）。
- ``python -m questor --dream``：离线 Deep Dream 蒸馏（夜间批处理，把近期 daily 固化回 core）。
- ``python -m questor -h`` / ``--help``：打印用法并退出（Issue #148）——**不建库、不装日志、不起 REPL**；
  未识别的选项同理先报错退 2，绝不落回交互态。

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
from questor.surfaces.http_sse import EventServer, create_app
from questor.surfaces.logs import run_logs_command
from questor.surfaces.serve import serve

#: 组合根自述行 logger（一方 inline 记录；DoD A① 的"起手即有日志"靠它兑现）。
_LOG = logging.getLogger("questor.composition")

#: 可识别的入口选项；`--resume` 需带 run_id，但选项名本身在此。
_KNOWN_COMMANDS: frozenset[str] = frozenset({"--serve", "--serve-openai", "--resume", "--list", "--dream"})

#: CLI 用法文本（Issue #148）：与上方模块 docstring 的入口清单同源，供 `-h/--help` 与未知选项提示共用。
#: **必须 ASCII-only**：这是用户可见输出（AGENTS §5.6：一方输出用英文，中文只进注释/docstring）。
#: Windows 非 UTF-8 代码页宿主（CI runner 实测 cp1252）上 `print` 中文会直接 `UnicodeEncodeError`
#: 带堆栈崩掉，把"看个帮助"变成一个失败进程。回归由 `tests/integration/test_cli_help.py` 钉住。
_USAGE = """usage: python -m questor [command]

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
  -h, --help         show this usage and exit (no store, no logging assembly, no REPL)

env (read by the composition root only; the kernel stays env-free):
  QUESTOR_MODEL, QUESTOR_STORE_PATH, QUESTOR_MEMORY_DB, QUESTOR_MEMORY_ROOT,
  QUESTOR_SKILLS_DIR, QUESTOR_MCP_JSON, QUESTOR_LOG_DIR, QUESTOR_LOG_LEVEL,
  QUESTOR_LOG_KEEP_DAYS, QUESTOR_LOG_PAYLOAD, QUESTOR_SIDECAR_GENERATION,
  QUESTOR_SIDECAR_BOOTSTRAP, QUESTOR_WEB_DIST, QUESTOR_DREAM_LOOKBACK,
  QUESTOR_OPENAI_API_KEYS, QUESTOR_OPENAI_HOST, QUESTOR_OPENAI_PORT
"""


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
    """组合根主流程：**先判参数、再装配**。`-h/--help` 与未知选项在任何装配之前返回（Issue #148）。

    为何必须前置：旧实现只逐个比 `argv[0]`，help 缺失就落 `else` 直起 REPL（fail-open），
    而 store/记忆库 connect 已在前面执行——一次 `--help` 会顺手建 state.db/memory.db 与日志面。
    失败语义：help 退 0（走 stdout）；未知选项退 2（走 stderr）。
    """
    # 组合根唯一装配入口（DESIGN §11；T2.14）：读 env 族并装**完整管线**——带内桥 + console(stderr)
    # + 按日 JSONL 文件面 + errors 分流——覆盖 REPL/--resume/--list/--dream 四入口。参数由组合根注入、
    # 内核 env-free（config⟂observability）。sidecar 宿主入口须调同一装配口径、不自配。
    if argv and argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    if argv and argv[0].startswith("-") and argv[0] not in _KNOWN_COMMANDS:
        # fail-closed：拼错的选项不得当"无参数"静默起 REPL（自动化/CI 里要的是明确失败码）。
        print(f"unknown option: {argv[0]}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2
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
        if argv and argv[0] == "--serve-openai":
            # 鉴权外部 OpenAI lane（ADR-0043）：fail-closed——无 API key 直接拒起，绝不开无鉴权对外端点。
            keys = [k.strip() for k in os.environ.get("QUESTOR_OPENAI_API_KEYS", "").split(",") if k.strip()]
            if not keys:
                print("--serve-openai refuses to start without QUESTOR_OPENAI_API_KEYS (fail-closed)", file=sys.stderr)
                return 2
            host = os.environ.get("QUESTOR_OPENAI_HOST", "127.0.0.1")  # 默认 loopback；跨机暴露属算子显式配置（C12）。
            try:
                port = int(os.environ.get("QUESTOR_OPENAI_PORT", "8000"))
            except ValueError:
                port = 8000
            import uvicorn  # 延迟 import：仅服务入口需要。

            server = EventServer(surface, store)
            app = create_app(server, openai_api_keys=keys)
            _LOG.info("openai lane serving host=%s port=%s", host, port)
            await uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning")).serve()
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
        if argv and argv[0] == "logs":
            # P10/ADR-0049 刀 3：**只读**消费命令——读 event_log 权威 + 旁路 JSONL，不写库/不改状态。
            rest = argv[1:]
            run_id: str | None = None
            if "--run" in rest:
                i = rest.index("--run")
                run_id = rest[i + 1] if i + 1 < len(rest) else None
            out = await run_logs_command(store, Path(log_dir_from_env()), run_id=run_id, totals="--totals" in rest, expand="--expand" in rest)
            print(out)
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
