"""B5/c6：`--inspect-extensions` 稳定输出，且先于 store/日志装配（隐藏命令保 --help 快照）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _run(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "QUESTOR_STORE_PATH": str(tmp_path / "state.db"),
        "QUESTOR_MEMORY_DB": str(tmp_path / "memory.db"),
        "QUESTOR_MEMORY_ROOT": str(tmp_path / "memory_store"),
        "QUESTOR_LOG_DIR": str(tmp_path / "logs"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
    }
    return subprocess.run(
        [sys.executable, "-m", "questor", *args],
        env=env,
        cwd=_REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_inspect_extensions_prints_chain_before_assembly(tmp_path: Path) -> None:
    proc = _run(["--inspect-extensions"], tmp_path)
    assert proc.returncode == 0, f"rc={proc.returncode}\nstderr={proc.stderr!r}"
    text = proc.stdout
    assert "extension points: 13 live + 4 reserved" in text
    assert "[Stop]" in text and "settle-turn" in text
    assert "reserved (ADR-gated): Notification, Elicitation, TaskUpdated, PlanStep" in text
    # 与 --help 同纪律：参数校验前于装配，tmp 下一个文件都不该出现。
    assert list(tmp_path.iterdir()) == [], f"inspect 触发了装配：{[p.name for p in tmp_path.iterdir()]}"


def test_help_stays_byte_stable_and_does_not_advertise_hidden_command(tmp_path: Path) -> None:
    proc = _run(["--help"], tmp_path)
    assert proc.returncode == 0
    assert "usage:" in proc.stdout.lower()
    # 既有逐字节快照由 test_assemble_spec_default 钉住；这里只证隐藏决策没有被顺手改掉。
    assert "--inspect-extensions" not in proc.stdout
    assert list(tmp_path.iterdir()) == []
