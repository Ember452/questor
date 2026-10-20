"""CLI 入口：委托组合根 ``composition.build_app`` 装配 StorePort + MemoryStorePort 后启动传输面。

用 ``python -m questor`` 运行。具体适配器（``SQLiteStore``/``SQLiteMemoryStore``）的装配是
``composition.build_app`` 的职责（唯一组合根，#161）；本入口只解析 argv 并调用它，不再自行 import
L5 实现。surfaces 自身只持 ``StorePort``/``MemoryStorePort`` 抽象（C4/C14）。

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
import sys
from pathlib import Path

from questor.composition import (
    build_app,
    close_app,
    sidecar_bootstrap_from_env,
    sidecar_generation_from_env,
    web_dist_from_env,
)
from questor.config.model import load_config
from questor.memory.distill import DistillOutcome, deep_dream
from questor.schedule import Scheduler
from questor.surfaces._assembly import assemble_logging, log_dir_from_env, reconfigure_output_streams
from questor.surfaces.cli import inspect_extensions_text, interactive
from questor.surfaces.http_sse import EventServer, create_app
from questor.surfaces.logs import run_logs_command
from questor.surfaces.maintenance import run_maintenance_command
from questor.surfaces.serve import serve

#: 组合根自述行 logger（一方 inline 记录；DoD A① 的"起手即有日志"靠它兑现）。
_LOG = logging.getLogger("questor.composition")

#: 可识别的入口选项；`--resume` 需带 run_id，但选项名本身在此。
_KNOWN_COMMANDS: frozenset[str] = frozenset(
    {"--serve", "--serve-openai", "--resume", "--list", "--dream", "--inspect-extensions"}
)

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
  maintenance        reclaim expired leases + stale unacked claims (Lane D hygiene)
  -h, --help         show this usage and exit (no store, no logging assembly, no REPL)

env (read by the composition root only; the kernel stays env-free):
  QUESTOR_MODEL, QUESTOR_STORE_PATH, QUESTOR_MEMORY_DB, QUESTOR_MEMORY_ROOT,
  QUESTOR_SKILLS_DIR, QUESTOR_MCP_JSON, QUESTOR_LOG_DIR, QUESTOR_LOG_LEVEL,
  QUESTOR_LOG_KEEP_DAYS, QUESTOR_LOG_PAYLOAD, QUESTOR_SIDECAR_GENERATION,
  QUESTOR_SIDECAR_BOOTSTRAP, QUESTOR_WEB_DIST, QUESTOR_DREAM_LOOKBACK,
  QUESTOR_OPENAI_API_KEYS, QUESTOR_OPENAI_HOST, QUESTOR_OPENAI_PORT
"""


class _HeuristicDistiller:
    """无密钥离线 fallback 蒸馏器：**合并**现有 core + 近期 daily 的非标题行去重回写（单调不回退）。

    诚实边界：真 LLM 蒸馏质量 UNVERIFIED；配置 ``LITELLM_API_KEY`` 时可换成 LLM-backed
    ``DistillProvider`` 注入（``--dream`` 的 distiller 在本 CLI 入口选定并注入）。无可萃取时返回 ``None`` → 空哨兵跳过。"""

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


def _scheduler_for(store: object, cfg: object) -> Scheduler | None:
    """按 config 构造 E 环调度器（默认 off；serve/serve-openai 共用）。"""
    schedule = cfg.schedule  # type: ignore[attr-defined]
    if not schedule.enabled:
        return None
    return Scheduler(
        store,
        max_per_hour=schedule.max_per_hour,
        quota_retry_seconds=schedule.quota_retry_seconds,
        interval_seconds=schedule.interval_seconds,
    )


async def _amain(argv: list[str]) -> int:
    """组合根主流程：**先判参数、再装配**。`-h/--help` 与未知选项在任何装配之前返回（Issue #148）。

    为何必须前置：旧实现只逐个比 `argv[0]`，help 缺失就落 `else` 直起 REPL（fail-open），
    而 store/记忆库 connect 已在前面执行——一次 `--help` 会顺手建 state.db/memory.db 与日志面。
    失败语义：help 退 0（走 stdout）；未知选项退 2（走 stderr）。
    """
    # 本入口的顺序（#161）：先判参数、再装配——日志经 ``assemble_logging``（带内桥 + console + 按日
    # JSONL + errors 分流），应用 store/memory/exec 三件套/surface 经 ``composition.build_app``；参数由组合根
    # 注入、内核 env-free（config⟂observability）。sidecar 宿主与 surfaces.cli.main() 均复用同一 build_app、不自配。
    reconfigure_output_streams()  # 先于一切输出把 stdout/stderr 重配为 UTF-8 兜底（#180，防非 UTF-8 宿主 print CJK 崩）
    if argv and argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    if argv and argv[0].startswith("-") and argv[0] not in _KNOWN_COMMANDS:
        # fail-closed：拼错的选项不得当"无参数"静默起 REPL（自动化/CI 里要的是明确失败码）。
        print(f"unknown option: {argv[0]}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2
    if argv and argv[0] == "--inspect-extensions":
        # B5：只打印装配链，先于日志/存储装配（与 --help 同纪律：不建库、不装日志）。
        # 刻意不进 _USAGE：`test_assemble_spec_default` 钉了 --help 逐字节快照，改它属改既有断言。
        print(inspect_extensions_text())
        return 0
    assemble_logging()
    # env 读取收口在 config（OPT-3 c2）：本入口只取子块；解析/校验仍在各自使用点。
    cfg = load_config()
    # 唯一装配口径（#161/#154）：所有 store/memory/exec 三件套/surface 均在 composition.build_app 构造，
    # 与 surfaces.cli.main() 共用同一路径——两个生产入口不再漂移。
    app = await build_app()
    _LOG.info("cli entry dispatched", extra={"log_fields": {"entry": argv[0] if argv else "repl"}})
    try:
        if argv and argv[0] == "--dream":
            lookback = cfg.dream_lookback
            result = await deep_dream(app.memory, _HeuristicDistiller(), lookback_days=lookback)
            print(
                f"deep_dream: wrote={result.get('wrote')} reason={result.get('reason', '-')} "
                f"input_hash={str(result.get('input_hash', ''))[:12]}"
            )
            return 0
        surface = app.surface
        if argv and argv[0] == "--serve":
            # sidecar 常驻服务：EventServer 复用已装配的 surface + store（surface 只持 StorePort 抽象，C4），
            # serve 面只 bind loopback 临时口 + 写 bootstrap，不 import 具体 store（ADR-0032 / S6）。
            server = EventServer(surface, app.store, ledger_enabled=cfg.delivery.enabled, scheduler=_scheduler_for(app.store, cfg))
            await serve(
                server,
                generation=sidecar_generation_from_env(),
                bootstrap_path=Path(sidecar_bootstrap_from_env()),
                static_dir=web_dist_from_env(),
            )
            return 0
        if argv and argv[0] == "--serve-openai":
            # 鉴权外部 OpenAI lane（ADR-0043）：fail-closed——无 API key 直接拒起，绝不开无鉴权对外端点。
            keys = list(cfg.openai.api_keys)
            if not keys:
                print("--serve-openai refuses to start without QUESTOR_OPENAI_API_KEYS (fail-closed)", file=sys.stderr)
                return 2
            host = cfg.openai.host  # 默认 loopback；跨机暴露属算子显式配置（C12）。
            port = cfg.openai.port
            import uvicorn  # 延迟 import：仅服务入口需要。

            server = EventServer(surface, app.store, ledger_enabled=cfg.delivery.enabled, scheduler=_scheduler_for(app.store, cfg))
            openai_app = create_app(server, openai_api_keys=keys)
            _LOG.info("openai lane serving host=%s port=%s", host, port)
            await uvicorn.Server(uvicorn.Config(openai_app, host=host, port=port, log_level="warning")).serve()
            return 0
        if argv and argv[0] == "--list":
            unfinished = await app.store.list_unfinished_runs()
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
            out = await run_logs_command(app.store, Path(log_dir_from_env()), run_id=run_id, totals="--totals" in rest, expand="--expand" in rest)
            print(out)
            return 0
        if argv and argv[0] == "maintenance":
            # P10/ADR-0050：账本卫生回收生产触发（过期 lease + 超 TTL 未 ack claim；不碰 acked）。
            print(await run_maintenance_command(app.store))
            return 0
        return await interactive(surface)
    finally:
        await close_app(app)


def main() -> int:
    """CLI 入口；Ctrl-C 退出码 130。"""
    try:
        return asyncio.run(_amain(sys.argv[1:]))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
