# Continuous Integration

The workflows are `.github/workflows/ci.yml` and
`.github/workflows/pr-lint.yml`.

## Jobs

- `guards` on Ubuntu: pre-commit, guard self-tests, real guards, and
  `lint-imports`.
- `tests` on Windows: `uv run pytest -m "unit or integration" -ra --tb=long --durations=20`.
- `pr-title` on pull requests: Conventional Commits type plus a lowercase
  subject.

PR titles must look like:

```text
feat: add repository guards
fix: propagate provider overrides
```

The subject after the colon must start with a lowercase letter.

## Failure output

CI is expected to explain its own failures:

- `pr-title` prints the actual title, allowed types, and valid examples.
- pytest runs with `-ra --tb=long --durations=20` so failures include full
  tracebacks, skip reasons, and slow-test context.
- guard scripts print `file:line` violations and fail loudly on empty scans.
- a `failure()` diagnostics step prints Python/uv versions, platform, and git
  status for both jobs.

E2E suites are not run by CI by default because they need provider
credentials, a built frontend, or Docker. Run them explicitly:

```bash
QUESTOR_RUN_E2E=1 uv run pytest -m e2e -v
```

## Local equivalent

```bash
uv sync --extra dev --frozen
uv run python scripts/check.py            # guards job: self-tests + live guards + snapshot checks
uv run pytest -m "unit or integration"    # tests job
```

The Makefile is a thin alias for the same single entry point, not a second
list of commands:

```bash
make guards   # scripts/check.py --fast (pre-commit caliber)
make test     # pytest -m "unit or integration"
make ci       # guards + lint + test
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
- `pr-lint.yml` uses `pull_request` with read-only permissions and an inline
  Python validator; it does not check out or execute contributor code, and the
  workflow file is read from the PR branch so the check can run before it is
  merged to `main`.
