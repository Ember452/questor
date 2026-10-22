# End-to-end suites

This directory contains real end-to-end suites that need provider credentials,
a built frontend, Docker, or an interactive terminal. They are intentionally
excluded from the fast test loop.

Run a script directly:

```bash
uv run python tests/e2e/e2e_smoke.py
```

Run the pytest gate (each suite is skipped unless explicitly enabled):

```bash
QUESTOR_RUN_E2E=1 uv run pytest tests/e2e/test_e2e_suites.py -m e2e -v
```

PowerShell:

```powershell
$env:QUESTOR_RUN_E2E = "1"
uv run pytest tests/e2e/test_e2e_suites.py -m e2e -v
```

The scripts are not collected as pytest tests directly because they are
standalone harnesses with their own argument parsing and diagnostics.
