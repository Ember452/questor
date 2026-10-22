from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path

CONTRACT_SECTION = "importlinter:contract:engine-app-boundary"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _lint_imports() -> subprocess.CompletedProcess[str]:
    executable = shutil.which("lint-imports")
    assert executable is not None, "lint-imports is not installed; run uv sync --extra dev"
    return subprocess.run(
        [executable],
        cwd=_project_root(),
        text=True,
        capture_output=True,
        check=False,
    )


def test_import_linter_contract_is_configured() -> None:
    parser = configparser.ConfigParser()
    assert parser.read(_project_root() / ".importlinter", encoding="utf-8")
    assert CONTRACT_SECTION in parser
    contract = parser[CONTRACT_SECTION]
    assert contract["type"] == "forbidden"
    assert "questorharness" in contract["source_modules"].split()
    assert "questor" in contract["forbidden_modules"].split()
    root_packages = parser["importlinter"]["root_packages"].split()
    assert {"questorharness", "questor"}.issubset(root_packages)


def test_import_linter_contracts_pass() -> None:
    result = _lint_imports()
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Engine must not import the product app KEPT" in output
    assert "Contracts: 2 kept, 0 broken." in output
    assert "BROKEN" not in output


def test_import_linter_rejects_engine_to_app_import() -> None:
    probe = _project_root() / "src" / "questorharness" / f"_import_boundary_probe_{os.getpid()}.py"
    probe.write_text("from questor.workspace import get_skills_dir\n", encoding="utf-8")
    try:
        result = _lint_imports()
        output = result.stdout + result.stderr
        assert result.returncode != 0, output
        assert "_import_boundary_probe_" in output
        assert "-> questor" in output
    finally:
        probe.unlink(missing_ok=True)

    clean = _lint_imports()
    assert clean.returncode == 0, clean.stdout + clean.stderr
