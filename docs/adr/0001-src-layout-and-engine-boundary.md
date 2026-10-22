# ADR 0001: src Layout and Engine Boundary

- Status: Accepted
- Date: 2026-10-22
- Deciders: Questor maintainers

## Context

The engine lived under `src/questorharness` while the product app lived in a
top-level `ohmo/` package. The mixed layout made packaging and imports
inconsistent, and the engine contained lazy imports of app modules for Feishu
group policy and cron notifications.

## Decision

- Both importable packages use the `src` layout:
  `src/questorharness` and `src/questor`.
- The product app is named `questor`; its command is `questor`.
- The engine must never import the product app. The app may import the engine.
- App behavior is injected into the engine:
  - channel media root via `QUESTORHARNESS_CHANNEL_MEDIA_DIR`
  - Feishu managed-group checker via `ChannelManager`
  - cron notifications via the `questorharness.notification_handlers` entry point
- Tests are grouped into `tests/unit`, `tests/integration`, and `tests/e2e`.
- The app workspace defaults to `~/.questor/agent`; `~/.questor` is reserved for
  legacy v1 data and future product-level state.

## Alternatives considered

- Keep the engine at `src/` and the app at the repository root. Rejected because
  it keeps two packaging styles and allows the app package to shadow installed
  code from the repository root.
- Move the engine to the repository root to match the app. Rejected because it
  loses `src` isolation for the larger package and encourages accidental root
  imports.
- Keep direct app imports in the engine. Rejected because it reverses the
  dependency direction and makes engine-only installs depend on the app.

## Consequences

- `pyproject.toml` packages are `src/questorharness` and `src/questor`.
- Engine code cannot import app code, including inside functions.
- The app owns Feishu notification and managed-group policy implementations.
- Tests now depend on path-aware root discovery; new tests under nested
  directories must account for their depth.

## Verification

- `.importlinter` contract `engine-app-boundary`.
- `tests/unit/test_import_boundaries.py`.
- Full test suite and `uv run lint-imports`.
