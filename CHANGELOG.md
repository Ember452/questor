# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed — structure-hardening repair round (branch `ci/structure-hardening`, 2026-10-24)
- The react backend host loop now converts unexpected engine exceptions into
  error events and keeps running; previously they escaped the loop, tore down
  the reader and runtime in the `finally` block, and exited the host silently
  with code 0.
- `plan_mode_change` never fired because its gate named two nonexistent tools;
  it now reacts to `enter_plan_mode` / `exit_plan_mode` and reads the fresh
  mode from settings (`app_state` lags until `sync_app_state`).
- Channel attachment names keep Unicode word characters — CJK names were
  collapsed to bare extensions by the ASCII-only filter — and same-named
  downloads dedupe with a counter suffix instead of overwriting each other.
- Team-memory escape messages no longer depend on `Path.resolve()`'s
  symlink-following behavior, which differs between Windows hosts.
- Fixed a flaky bash-tool timeout test: its string-form monkeypatch could land
  on a re-imported module object after other tests disturbed `sys.modules`,
  letting a real subprocess replace the fake.

### Removed
- The dead swarm mailbox permission protocol (~1,100 lines across
  `permission_sync`, `permission_models`, the mailbox factories and two test
  files): zero callers in src and tests, and its sender/poller schemas were
  mutually incompatible — an approval would have decoded as a denial.

### Changed
- Single-sourced the prompt-too-long needle table in `contracts/errors.py`
  (the engine and compactor copies were byte-identical duplicates that had to
  be kept in sync by hand), replaced coordinator prompt-prefix sniffing with
  an explicit `QueryContext.coordinator_mode` flag, added
  `ToolRegistry.unregister()` so the product gateway stops reaching into the
  registry's internals, and collapsed the three submit/snapshot blocks in
  `handle_line` into one helper.
- Revived the CI test ratchet: `check.py` no longer passes `--fast` to
  `baseline-check`, so pinned pytest counts and node ids are enforced in CI
  again — deleting a test can no longer pass silently.
- Made the gates platform-deterministic: mypy pins `platform = "win32"`
  (typeshed trims msvcrt attributes by running OS), prompt-surface snapshots
  normalize masked-path separators and per-host memory-dir hashes, and the
  namespace extractor pins user skill dirs to empty so the document reflects
  only what the repository ships (registration was picking up every skill
  installed in the developer's home directory).
- GRAPH.md's kind column now actually classifies rows (facade / banned /
  contract / primitive / implementation — it previously printed one identical
  label for every row) and a package fan-in Top10 section puts the computed
  in-degree to work; guard scans gained mtime-validated caches.
- Root `AGENTS.md` is a fully Chinese signpost again, with new sections for
  feature placement (which package owns a new feature; when to open a new
  package) and a conduct quick-reference; ADR-0002 dropped the top-level
  directory cap in favor of "no directory without content".

## Pre-reset v1 era (condensed; details removed from this file)

The entries that used to fill this file documented the pre-reset v1
architecture — `kernel/` with `DefaultTurnLoop`, `CliSurface`, a SQLite-backed
fact stream, extension descriptors and the P0–P10 adversarial audit rounds
that hardened tool fault isolation, memory write discipline, recall and
compaction. That codebase left the repository when the v2 engine baseline was
established (commit `30a0c38`).

The full record is not lost:

- `git log --follow -- CHANGELOG.md` reaches every removed entry up to that
  commit;
- the pre-reset documentation set is archived at
  [docs-pre-reset-v1/README.md](./docs-pre-reset-v1/README.md);
- decisions that still bind the v2 tree live on in [docs/adr](./docs/adr).
