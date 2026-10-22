# Repository Guards

Small, dependency-free checks used by local development and CI.

Run every guard's self-test:

```bash
uv run python scripts/guards/_guard_kit.py --self-test
uv run python scripts/guards/check_thread_leak.py --self-test
uv run python scripts/guards/check_secret_projection.py --self-test
uv run python scripts/guards/check_doc_cross_refs.py --self-test
```

Run the real checks:

```bash
uv run python scripts/guards/check_thread_leak.py --fail-on-empty
uv run python scripts/guards/check_secret_projection.py --fail-on-empty
uv run python scripts/guards/check_doc_cross_refs.py --fail-on-empty
uv run lint-imports
```

## `_guard_kit.py`

Shared utilities only:

- deterministic `walk_py()` with generated/vendor directory pruning
- UTF-8/BOM-safe `read_text()` and `count_lines()`
- uniform `EXIT_OK` / `EXIT_RED` / `EXIT_CONFIG`
- `fail_on_empty()` so an empty scan cannot silently pass
- `run_self_test()` for consistent PASS/FAIL output

New guards should import the kit instead of reimplementing walking or exit codes.

## `check_thread_leak.py`

Detects non-daemon threads that survive after tests complete and installs a
daemon watchdog that forces a non-zero exit if interpreter shutdown is blocked.

`tests/conftest.py` snapshots the baseline at session start and checks again at
session finish. The standalone `--self-test` proves that the guard can detect a
leak, pass after cleanup, and arm a daemon watchdog.

## `check_secret_projection.py`

AST scan of `src/questorharness` and `src/questor`:

- event constructor payloads must not contain secret-shaped field names or keys
- logging calls must not receive direct secret-shaped names or keys

It is intentionally conservative; aliases such as `auth.value` are not
inferred. Use it as a tripwire, not as a replacement for secret handling review.

## `check_doc_cross_refs.py`

Checks:

- relative Markdown links under `docs/`
- repository paths written in backticks, such as `src/...` and `tests/...`
- empty documentation sets or reference sets when `--fail-on-empty` is used

The v1 archive in `docs-pre-reset-v1/` is excluded.
