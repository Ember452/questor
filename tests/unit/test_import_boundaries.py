from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_import_linter_contracts_pass() -> None:
    executable = shutil.which("lint-imports")
    assert executable is not None, "lint-imports is not installed; run uv sync --extra dev"

    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [executable],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
