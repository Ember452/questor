"""``--help`` / 未知选项的入口行为回归（Issue #148：``python -m questor --help`` 曾直接掉进 REPL）。

真子进程走 ``python -m questor``（与 `test_log_assembly_coverage.py` 的刀1 A①/A③ 同法，不 mock 组合根）：

- **help 判据**：退出码 0 + stdout 有用法 + **不起 REPL** + **不建任何 store/记忆库/日志面**
  ——参数校验必须前于装配，否则一次 `--help` 也会顺手落库。
- **未知选项判据**：退出码 2 + 用法进 stderr，绝不把拼错的参数当"无参数"静默起 REPL（fail-open）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])

#: 四个入口的命令名，用法文本必须逐个提到（少一个就是文档与实现漂移）。
_COMMANDS = ("--serve", "--resume", "--list", "--dream")

#: REPL 起手的提示语；出现在 stdout 就说明进程掉进了交互态，等于没处理参数。
_REPL_PROMPT = "type a message"


def _run_cli(args: list[str], tmp_path: Path, *, io_encoding: str | None = None) -> subprocess.CompletedProcess[str]:
    """在 tmp_path 指定的隔离路径下真起子进程跑 CLI（store/记忆库/日志全部指向 tmp，不落仓库 cwd）。

    ``io_encoding`` 强制子进程 stdout/stderr 的编码（``PYTHONIOENCODING``）：用它把 Windows 非 UTF-8
    代码页（runner 实测 cp1252）的宿主在任何开发机上**确定性复现**，避免"本地绿、CI 红"。
    """
    env = {
        **os.environ,
        "QUESTOR_STORE_PATH": str(tmp_path / "state.db"),
        "QUESTOR_MEMORY_DB": str(tmp_path / "memory.db"),
        "QUESTOR_MEMORY_ROOT": str(tmp_path / "memory_store"),
        "QUESTOR_LOG_DIR": str(tmp_path / "logs"),
        "QUESTOR_LOG_LEVEL": "INFO",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",  # 不联网拉 cost map，判据确定
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
    }
    if io_encoding is not None:
        env["PYTHONIOENCODING"] = io_encoding
    return subprocess.run(
        [sys.executable, "-m", "questor", *args],
        env=env,
        cwd=_REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_help_prints_usage_and_exits_zero(tmp_path: Path) -> None:
    """``--help``：退出码 0、stdout 有用法且逐个提到四个入口、不进 REPL（修复前判红：掉进 REPL 无 usage）。"""
    proc = _run_cli(["--help"], tmp_path)
    assert proc.returncode == 0, f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert "usage:" in proc.stdout.lower(), f"stdout 没有用法行：{proc.stdout!r}"
    missing = [cmd for cmd in _COMMANDS if cmd not in proc.stdout]
    assert not missing, f"用法文本缺少入口：{missing}"
    assert _REPL_PROMPT not in proc.stdout, f"--help 掉进了交互 REPL：{proc.stdout!r}"


def test_short_help_flag_behaves_the_same(tmp_path: Path) -> None:
    """``-h`` 与 ``--help`` 同义（标准 CLI 约定，修复前判红：同样掉 REPL）。"""
    proc = _run_cli(["-h"], tmp_path)
    assert proc.returncode == 0, f"rc={proc.returncode}\nstderr={proc.stderr!r}"
    assert "usage:" in proc.stdout.lower(), f"stdout 没有用法行：{proc.stdout!r}"
    assert _REPL_PROMPT not in proc.stdout, f"-h 掉进了交互 REPL：{proc.stdout!r}"


def test_help_does_not_assemble_stores(tmp_path: Path) -> None:
    """help/未知选项必须**先于装配**返回：tmp 下一个字节都不该被创建（不建库、不建日志面）。"""
    for args in (["--help"], ["-h"], ["--nope"]):
        proc = _run_cli(args, tmp_path)
        created = sorted(p.name for p in tmp_path.iterdir())
        assert not created, f"{args} 之后装配产生了文件 {created}（参数校验必须前于 store/日志装配）：{proc.stdout!r}"


def test_unknown_option_is_refused_not_repl(tmp_path: Path) -> None:
    """拼错的选项（``--resum``）必须明确失败：退出码 2 + 用法进 stderr，绝不静默起 REPL。"""
    proc = _run_cli(["--resum", "run_x"], tmp_path)
    assert proc.returncode == 2, f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert _REPL_PROMPT not in proc.stdout, f"未知选项被当成无参数起了 REPL：{proc.stdout!r}"
    assert "usage:" in proc.stderr.lower(), f"stderr 没有用法行：{proc.stderr!r}"
    assert "--resum" in proc.stderr, f"stderr 未点名将错的选项：{proc.stderr!r}"


def test_help_survives_a_non_utf8_console_codepage(tmp_path: Path) -> None:
    """用法与错误提示必须能打到**非 UTF-8 代码页**的 stdout 上（CI Windows runner 实测 cp1252）。

    旧实现把中文写进 CLI 的用户可见输出：在 cp1252 宿主上 ``print`` 直接 ``UnicodeEncodeError``
    带堆栈崩掉（rc=1、stdout 空）——中文只属于注释/docstring（AGENTS §5.6：一方输出用英文）。
    本用例用 ``PYTHONIOENCODING`` 把该代码页钉住，在任何开发机上确定性复现。
    """
    proc = _run_cli(["--help"], tmp_path, io_encoding="cp1252")
    assert proc.returncode == 0, f"rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert "UnicodeEncodeError" not in proc.stderr, f"用法输出在 cp1252 宿主上崩了：{proc.stderr!r}"
    assert "usage:" in proc.stdout.lower(), f"cp1252 下 stdout 没有用法行：{proc.stdout!r}"
    missing = [cmd for cmd in _COMMANDS if cmd not in proc.stdout]
    assert not missing, f"用法文本缺少入口：{missing}"


def test_unknown_option_survives_a_non_utf8_console_codepage(tmp_path: Path) -> None:
    """未知选项的 stderr 提示同样要过代码页这一关（它打的是同一份用法文本）。"""
    proc = _run_cli(["--nope"], tmp_path, io_encoding="cp1252")
    assert proc.returncode == 2, f"rc={proc.returncode}\nstderr={proc.stderr!r}"
    assert "UnicodeEncodeError" not in proc.stderr, f"stderr 在 cp1252 宿主上崩了：{proc.stderr!r}"
    assert "usage:" in proc.stderr.lower(), f"cp1252 下 stderr 没有用法行：{proc.stderr!r}"
