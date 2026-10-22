# Testing

## Layout

```text
tests/
  unit/
  integration/
  e2e/
  fixtures/
  conftest.py
```

Markers are assigned automatically from the test path:

- `tests/unit/` -> `unit`
- `tests/integration/` -> `integration`
- `tests/e2e/` -> `e2e`

## Commands

Fast unit loop:

```bash
uv run pytest -m unit
```

Integration tests:

```bash
uv run pytest -m integration
```

Unit plus integration:

```bash
uv run pytest -m "unit or integration"
```

The default command runs unit plus integration; `addopts` excludes e2e unless it
is requested explicitly:

```bash
uv run pytest
```

Real end-to-end suites are skipped unless explicitly enabled:

```bash
QUESTOR_RUN_E2E=1 uv run pytest -m e2e -v
```

PowerShell:

```powershell
$env:QUESTOR_RUN_E2E = "1"
uv run pytest -m e2e -v
```

## End-to-end scripts

Standalone harnesses live in `tests/e2e/` and are not collected directly by
pytest. `tests/e2e/test_e2e_suites.py` runs them as subprocesses when
`QUESTOR_RUN_E2E=1` is set. See `tests/e2e/README.md` for requirements.

## Structural checks

```bash
uv run lint-imports
```

This enforces that `questorharness` does not import `questor`.
`tests/integration/test_import_boundaries.py` runs the same check inside pytest.
