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

## Test suite scaling policy

Measured 2026-10-24: ~1,931 selected tests, full `pytest -m "unit or
integration"` run ≈ 2 minutes locally, collection ≈ 3.5s. At this scale every
sharding/impact mechanism is negative value; the full run is pinned to the
pre-push hook and CI instead of being optimized away.

### Known slow items (maintained ledger)

Diagnose with `--durations=20` (already on CI). When a new item becomes the
top cost, add it here with its cause before optimizing anything.

| item | cost | nature |
| --- | --- | --- |
| first `import lark_oapi` in the process | ~9.7s | the SDK imports 11,098 modules (its entire API tree incl. `ws`); paid once per pytest process and attributed to whichever Feishu test imports first; not actionable on our side |
| `test_bash_tool_timeout_returns_partial_output_for_real_command` | ~6.3s | exercises a real subprocess timeout by design |
| `test_interactive_repl_refuses_a_non_tty_stdin_with_a_clean_error` | ~5.4s | real subprocess, by design |

### Triggers (adopt only when they fire)

| trigger | action |
| --- | --- |
| selected tests ≥ 5,000 (`tests/fixtures/baseline/summary.json` `total`) | adopt sharding: pytest-split with `least_duration` plus a refreshed duration baseline, or pytest-xdist only if suite state is provably worker-safe. Enforced by `scripts/guards/check_test_infra_policy.py` |
| CI tests job consistently > 10 min | same as above (the guard enforces the count trigger; the duration is the manual review signal) |
| > 300 test files, or doc-only PRs paying for the full test job | add `paths-filter` + a mirror skip job + a single aggregate required job, all three together — a skipped matrix job without its skip mirror leaves branch protection pending forever |
| tests job consistently > 15 min | split dependency installation into a cached artifact so shards only execute tests |

### Do not adopt before the trigger fires

- **pytest-xdist** — questor's tests share real state (SQLite, contextvars,
  subprocesses); parallel workers turn that into flaky reds.
- **`.test_durations` baselines** — they rot whenever the test set changes
  (crewAI eventually disabled its duration-based splitting for exactly this).
- **Impact-analysis runners (testmon, pytest-picked)** — dynamic dependency
  tracking is unsound with fixture side effects and subprocesses; "fewer tests
  ran and nobody noticed" is a false green.

The guard fails the build when these appear below the threshold, and fails
when the threshold is crossed without sharding — the policy cannot be
forgotten, only consciously changed (guard + this document in one commit).
