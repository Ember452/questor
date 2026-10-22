# Continuous Integration

The workflows are `.github/workflows/ci.yml` and
`.github/workflows/pr-lint.yml`.

## Jobs

- `guards` on Ubuntu: pre-commit, guard self-tests, real guards, and
  `lint-imports`.
- `tests` on Windows: `uv run pytest -m "unit or integration"`.
- `PR title` on pull requests: Conventional Commits type plus a lowercase
  subject.

PR titles must look like:

```text
feat: add repository guards
fix: propagate provider overrides
```

The subject after the colon must start with a lowercase letter.

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
uv run pre-commit run --all-files
uv run lint-imports
uv run pytest -m "unit or integration"
```

The Makefile wraps the same checks:

```bash
make guards
make lint
make test
make ci
```

## Design notes

- The Ubuntu job is guards-only to avoid claiming an unverified Linux test
  baseline; the Windows job matches the current test baseline.
- `uv sync --frozen` keeps CI on the committed lockfile.
- `check_thread_leak.py` is also wired into `tests/conftest.py` at session
  start/finish, so a leaked non-daemon thread fails the test process instead of
  hanging the job.
- `.pre-commit-config.yaml` runs YAML/TOML/JSON syntax checks, critical Ruff
  checks, and the secret/doc guards.
- `pr-lint.yml` uses `pull_request_target` with read-only PR permissions; it
  does not check out or execute contributor code.
