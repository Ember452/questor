"""Run standalone end-to-end suites through pytest."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_E2E_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _E2E_DIR.parents[1]
_SCRIPTS = (
    "e2e_smoke.py",
    "e2e_local_system_scenarios.py",
    "react_tui_e2e.py",
    "e2e_cli_flags.py",
    "e2e_docker_sandbox.py",
    "e2e_harness_features.py",
    "e2e_headless_rendering.py",
    "e2e_react_tui_redesign.py",
    "e2e_real_skills_plugins.py",
    "e2e_tui_interactions.py",
)


@pytest.mark.e2e
@pytest.mark.parametrize("script_name", _SCRIPTS)
def test_e2e_suite(script_name: str) -> None:
    if os.environ.get("QUESTOR_RUN_E2E") != "1":
        pytest.skip("set QUESTOR_RUN_E2E=1 to run real end-to-end suites")

    script = _E2E_DIR / script_name
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=_PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, (
        f"{script_name} failed\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
