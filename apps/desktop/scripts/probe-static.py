"""诊断：同一份 dist 分别由源码宿主与冻结产物宿主提供，比较 / 的响应。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "apps/web/dist"


def probe(name: str, exe: list[str], *, frozen: bool) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QUESTOR_WEB_DIST"] = str(DIST)
    proc = subprocess.Popen(
        exe,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT if not frozen else ROOT / "apps/desktop/dist/engine"),
        env=env,
        text=True,
        encoding="utf-8",
    )
    port = json.loads(proc.stdout.readline())["port"]
    print(f"== {name} port={port} ==")
    for path in ("/", "/index.html", "/nope"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                print(path, response.status, response.read(60))
        except urllib.error.HTTPError as exc:
            print(path, exc.code, exc.read(120))
    proc.stdin.close()
    proc.wait(timeout=10)


probe("source", [sys.executable, "-m", "questorharness", "--studio-host", "--serve-no-auth"], frozen=False)
probe(
    "frozen",
    [str(ROOT / "apps/desktop/dist/engine/questor-engine.exe"), "--studio-host", "--serve-no-auth"],
    frozen=True,
)
