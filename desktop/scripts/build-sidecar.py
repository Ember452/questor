#!/usr/bin/env python3
"""sidecar 三段式步骤②：PyInstaller **onedir** 冻结 `questor --serve`（Phase 7 T8；STRUCTURE §9）。

onedir（非 onefile）：persistent 资源目录、无需系统 Python、避免每次启动解包重校验（参考仓踩坑结论）。
产物 `dist/questor-sidecar/questor-sidecar.exe` 由 `verify-release-bundle` 校验（恰一个 + 内嵌解释器），
再由 tauri `bundle.resources` 打进桌面包。冻结窄锁见 `desktop/sidecar-requirements.{in,lock}`。

用法：`uv run python desktop/scripts/build-sidecar.py`（在已装 sidecar 依赖的环境里）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_OUT = _ROOT / "build" / "sidecar"
_ENTRY = _OUT / "_questor_sidecar_entry.py"

# 这些包有动态 import / 数据文件，PyInstaller 需显式 collect-all 才能自包含（litellm 尤甚）。
# 不含 mcp：`mcp.cli` 在 import 时 sys.exit，collect-all 会枚举它而崩；SDK 由 capabilities/mcp 懒 import。
_COLLECT_ALL = (
    "uvicorn",
    "sse_starlette",
    "litellm",
    "fastapi",
    "pydantic",
    "pydantic_core",
    "aiosqlite",
    "jsonschema",
    "questor",
)


def _write_entry() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    # 冻结产物入口 = 常驻 sidecar serve（代次/bootstrap 路径经 env 注入，与 `python -m questor --serve` 同义）。
    _ENTRY.write_text(
        "import sys\n"
        "from questor.__main__ import main\n"
        "if __name__ == '__main__':\n"
        "    sys.argv = [sys.argv[0], '--serve']\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )


def main() -> int:
    _write_entry()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir",
        "--name", "questor-sidecar",
        "--distpath", str(_OUT / "dist"),
        "--workpath", str(_OUT / "work"),
        "--specpath", str(_OUT / "spec"),
    ]
    for pkg in _COLLECT_ALL:
        cmd += ["--collect-all", pkg]
    cmd.append(str(_ENTRY))
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(_ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
