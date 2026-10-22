# Continuous Integration

The workflow is `.github/workflows/ci.yml`.

## Jobs

- `guards` on Ubuntu: guard self-tests, real guards, and `lint-imports`.
- `tests` on Windows: `uv run pytest -m "unit or integration"`.

E2E suites are not run by CI by default because they need provider
credentials, a built frontend, or Docker. Run them explicitly:

```bash
QUESTOR_RUN_E2E=1 uv run pytest -m e2e -v
```

## Local equivalent

```bash
uv sync --extra dev --frozen
uv run python scripts/guards/_guard_kit.py --self-test
uv run python scripts/guards/check_thread_leak.py --self-test
uv run python scripts/guards/check_secret_projection.py --self-test
uv run python scripts/guards/check_doc_cross_refs.py --self-test
uv run python scripts/guards/check_thread_leak.py --fail-on-empty
uv run python scripts/guards/check_secret_projection.py --fail-on-empty
uv run python scripts/guards/check_doc_cross_refs.py --fail-on-empty
uv run lint-imports
uv run pytest -m "unit or integration"
```

## Design notes

- The Ubuntu job is guards-only to avoid claiming an unverified Linux test
  baseline; the Windows job matches the current test baseline.
- `uv sync --frozen` keeps CI on the committed lockfile.
- `check_thread_leak.py` is also wired into `tests/conftest.py` at session
  start/finish, so a leaked non-daemon thread fails the test process instead of
  hanging the job.
