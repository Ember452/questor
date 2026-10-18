"""Issue #138 判据：``python -m questor.surfaces.cli`` 与 ``python -m questor`` 装配口径一致。

为什么要真子进程：入口差异只在"进程起来的那一刻"才看得见——旧行为是 ``cli.main()`` 裸调
``configure_logging()``（不传 ``log_dir``），于是那个入口永远没有文件面，也绕开
``QUESTOR_LOG_PAYLOAD`` 门；在测试进程里调函数是复现不出来的。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _run_cli_module(tmp_path: Path, payload: str | None) -> subprocess.CompletedProcess[str]:
    env = {
        **{k: v for k, v in os.environ.items() if k not in {"QUESTOR_LOG_DIR", "QUESTOR_LOG_PAYLOAD"}},
        "QUESTOR_STORE_PATH": str(tmp_path / "state.db"),
        "QUESTOR_MEMORY_DB": str(tmp_path / "memory.db"),
        "QUESTOR_MEMORY_ROOT": str(tmp_path / "memory_store"),
        "QUESTOR_LOG_DIR": str(tmp_path / "logs"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
        # 钉住宿主 locale（AGENTS §3 / Issue #148）：强制子进程以 UTF-8 写、父进程以 UTF-8 读，
        # 否则非 UTF-8 代码页（cp936/cp1252）host 上 reader 线程解码子进程输出会 UnicodeDecodeError、
        # 使 proc.stdout/stderr 变 None → `proc.stderr + proc.stdout` 抛 TypeError。跨平台确定性复现。
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    if payload is not None:
        env["QUESTOR_LOG_PAYLOAD"] = payload
    return subprocess.run(
        [sys.executable, "-m", "questor.surfaces.cli"],
        env=env,
        cwd=_REPO_ROOT,
        stdin=subprocess.DEVNULL,  # 立即 EOF → REPL 退出
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_cli_module_entry_builds_file_plane(tmp_path: Path) -> None:
    proc = _run_cli_module(tmp_path, payload=None)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "logs").is_dir(), "第二个生产入口也必须有按日文件面（旧行为：静默 console-only）"
    assert list((tmp_path / "logs").glob("questor-*.jsonl")), "文件面里必须真的落了日志"


def test_cli_module_entry_respects_payload_gate(tmp_path: Path) -> None:
    proc = _run_cli_module(tmp_path, payload="on")
    assert proc.returncode != 0, "preview 未实装时设 QUESTOR_LOG_PAYLOAD=on 必须拒绝启动，两个入口同口径"
    assert "QUESTOR_LOG_PAYLOAD" in (proc.stderr + proc.stdout)
