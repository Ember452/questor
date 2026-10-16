"""组合根入口（composition root）：装配 StorePort + MemoryStorePort 后启动 CLI 传输面。

用 ``python -m questor`` 运行。本模块**可以** import 具体适配器（``SQLiteStore``/
``SQLiteMemoryStore``）——它是把 L5 实现注入 L6 surfaces 的唯一装配点；surfaces 自身只持
``StorePort``/``MemoryStorePort`` 抽象（C4/C14）。

- ``python -m questor``：交互 REPL（每轮真实落库到 store，支撑 resume）。
- ``python -m questor --resume <run_id>``：从持久态续跑被 kill/重启的 run（P3）。
- ``python -m questor --list``：列出未完成的 run id（供选择续跑）。
- ``python -m questor --dream``：离线 Deep Dream 蒸馏（夜间批处理，把近期 daily 固化回 core）。

路径：state 取 ``QUESTOR_STORE_PATH``（默认 ``<cwd>/.questor/state.db``）；记忆库取
``QUESTOR_MEMORY_DB``（默认 ``<cwd>/.questor/memory.db``）、md 真源根取 ``QUESTOR_MEMORY_ROOT``
（默认 ``<cwd>/.questor/memory_store``）。记忆与 event-log 分库（ADR-0023 故障隔离）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from questor.memory.distill import DistillOutcome, deep_dream
from questor.observability.logging import configure_logging
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface, interactive


def _store_path() -> str:
    return os.environ.get("QUESTOR_STORE_PATH", str(Path.cwd() / ".questor" / "state.db"))


def _memory_db_path() -> str:
    return os.environ.get("QUESTOR_MEMORY_DB", str(Path.cwd() / ".questor" / "memory.db"))


def _memory_root() -> str:
    return os.environ.get("QUESTOR_MEMORY_ROOT", str(Path.cwd() / ".questor" / "memory_store"))


def _log_level_from_env() -> int:
    """日志级别取自 ``QUESTOR_LOG_LEVEL``（默认 INFO）；env 读取属组合根职责，内核不读 env（DESIGN §11）。"""
    return getattr(logging, os.environ.get("QUESTOR_LOG_LEVEL", "INFO").upper(), logging.INFO)


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
    # 日志装配上移至组合根唯一入口（刀1 缺陷修复）：覆盖 REPL/--resume/--list/--dream
    # 四入口——此前仅 ``interactive()`` 配置，崩溃恢复的 ``--resume`` 裸奔无日志（DESIGN §11）。
    configure_logging(level=_log_level_from_env())
    path = _store_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    store = await SQLiteStore(path).connect()
    memory = await SQLiteMemoryStore(db_path=_memory_db_path(), memory_root=_memory_root()).connect()
    try:
        if argv and argv[0] == "--dream":
            lookback = int(os.environ.get("QUESTOR_DREAM_LOOKBACK", "7"))
            result = await deep_dream(memory, _HeuristicDistiller(), lookback_days=lookback)
            print(
                f"deep_dream: wrote={result.get('wrote')} reason={result.get('reason', '-')} "
                f"input_hash={str(result.get('input_hash', ''))[:12]}"
            )
            return 0
        surface = CliSurface(store=store, memory_store=memory)
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
