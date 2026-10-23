# Repository Guards

Small, dependency-free checks used by local development and CI.

## Single entry point

CI and pre-commit both run **scripts/check.py**; never wire an individual guard
into a pipeline again. The list lives in one place, so the two cannot fork.

```bash
uv run python scripts/check.py --list     # which commands run, in order
uv run python scripts/check.py            # everything (CI guards job)
uv run python scripts/check.py --fast     # skip the slow snapshot checks (pre-commit)
```

Every step prints its name before it runs and the run ends with a
`step / result / seconds` table, so a red build names the guard that failed.

Run every guard's self-test by hand (what `--fast` already does for you):

```bash
uv run python scripts/guards/_guard_kit.py --self-test
uv run python scripts/guards/check_thread_leak.py --self-test
uv run python scripts/guards/check_secret_projection.py --self-test
uv run python scripts/guards/check_doc_cross_refs.py --self-test
uv run python scripts/guards/check_layout.py --self-test
```

Run a single guard by hand while debugging:

```bash
uv run python scripts/guards/check_thread_leak.py --fail-on-empty
uv run python scripts/guards/check_secret_projection.py --fail-on-empty
uv run python scripts/guards/check_doc_cross_refs.py --fail-on-empty
uv run python scripts/guards/check_layout.py --fail-on-empty
uv run python scripts/guards/gen_tree.py --check
uv run python scripts/guards/gen_structure_baseline.py --check
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

## `check_layout.py`

Pins the Phase 2 layout so it cannot silently regress:

- removed packages (`ui/`, `personalization/`, `surfaces/ipc/`) must not come back with Python sources
- `surfaces/` may only contain renderer adapters (`channels/`), never a process host
- `textual` / `prompt_toolkit` must not be imported anywhere under `src/`
- `commands/registry.py` stays ≤250 lines and each `commands/families/*.py` stays ≤600

Per-file limits are deliberately generous: they catch a god file being rebuilt, not normal growth. Every source file is also held to the ADR-0003 red line of 1200 lines.

## `gen_tree.py`

Regenerates `docs/architecture/TREE.md` from the source tree (`--write`) and fails when the committed map no longer matches the code (`--check`), so the structure document cannot drift.
