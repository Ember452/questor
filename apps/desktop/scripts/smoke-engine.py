"""打包产物冒烟：握手行合法 + stdin EOF 快速退出。需要先 `node scripts/build-engine.mjs`。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXE = ROOT / "apps/desktop/dist/engine/questor-engine.exe"


def main() -> int:
    if not EXE.is_file():
        print(f"missing engine build: {EXE}", file=sys.stderr)
        return 2
    proc = subprocess.Popen(
        [str(EXE), "--studio-host", "--serve-no-auth"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(EXE.parent),
        text=True,
        encoding="utf-8",
    )
    assert proc.stdout is not None and proc.stdin is not None
    line = proc.stdout.readline().strip()
    print("handshake:", line)
    payload = json.loads(line)
    assert isinstance(payload.get("port"), int) and 1 <= payload["port"] <= 65535
    assert isinstance(payload.get("token"), str) and len(payload["token"]) >= 32
    started = time.monotonic()
    proc.stdin.close()
    code = proc.wait(timeout=10)
    elapsed = time.monotonic() - started
    print(f"exit={code} elapsed={elapsed:.2f}s")
    assert elapsed <= 5, "stdin EOF must end the host quickly"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
