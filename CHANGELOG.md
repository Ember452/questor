# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — 对外文档层（分支 docs/open-source-surface，2026-10-26）
- New reader-facing documentation set in Chinese: install, quickstart, desktop, and
  troubleshooting guides; CLI, environment-variable, and settings references;
  an `internals/` layer that explains the turn lifecycle, the event model, and the
  permission gate; plus privacy/diagnostics and MCP integration pages.
- `docs/README.md` is now a reader-routing page with a Diátaxis mapping and an
  explicit language policy (new pages in Chinese, existing English pages converted
  as they are touched; no parallel `en/` tree).
- `README.md` was rewritten for first-time readers and no longer links to the
  removed pre-reset documentation tree.

### Changed
- `check_doc_cross_refs` now also scans an explicit allowlist of root documents
  (`README`, `CONTRIBUTING`, `SECURITY`, `AGENTS`, `CODE_OF_CONDUCT`, `CHANGELOG`,
  `THIRD_PARTY_NOTICES`, `CLAUDE`). Its self-test proves a dead link in a root
  document turns the guard red and that unlisted root files stay out of scope.
- The guard also enforces reachability: every `docs/**/*.md` must be walkable from
  `docs/README.md` by following links, so a new page that nobody indexes turns CI
  red instead of quietly going stale. `docs/plan/README.md` was added as the plan
  index, which previously had five unreachable pages.
- `pyproject.toml` gained `[project.urls]`, keywords, classifiers and authors, so a
  package page has somewhere to point. `requires-python` stays `>=3.10` (an
  untested lower bound) and the contributor guide now says plainly that only 3.13
  is verified, instead of the two documents contradicting each other.

### Fixed
- `README.md` advertised a Tauri desktop shell; the shipped shell is Electron
  (`apps/desktop`). It also described `python -m questor` as the full-screen TUI,
  which is `python -m questorharness`; the product entry point runs a line-mode REPL.
- `CONTRIBUTING.md` claimed there were no console scripts and no optional
  dependencies; both exist (`questor`/`questorharness`/`oh`/`openh`, and a `dev`
  extra), and it pointed at deleted documents (roadmap, vision, hard constraints,
  ADR-0012, ADR-0036).
- `.github/PULL_REQUEST_TEMPLATE.md` required the retired hard-constraints document
  in its definition of done, so every PR author saw a dead reference.
- AGENTS.md still referenced the removed design directory, roadmap and pitfalls
  file as live paths.
- `.gitignore` had mojibake in six comment lines that had swallowed the
  `scripts/_*` ignore rule and its negation onto comment lines, so temporary
  scripts were silently not ignored; the file was also saved with a UTF-8 BOM.

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
