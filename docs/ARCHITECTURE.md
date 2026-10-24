# Architecture

> This page describes the **current** v2 layout. The **target** package
> structure, dependency rank, modes, and migration plan are in
> [Structure](architecture/STRUCTURE.md), [Migration](architecture/MIGRATION.md),
> and ADR-0002/0003. The memory provider contract is in
> [Memory](architecture/MEMORY.md) and ADR-0004.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `src/questorharness/` | Engine: agent loop, providers, tools, permissions, memory, channels, cron, sandbox |
| `src/questor/` | Product app: gateway, onboarding, workspace, Feishu group policy |
| `frontend/terminal/` | Terminal UI (deprecated, ADR-0005 Updated 2026-10-24; removed in the same change that lands the REPL thin client — see plan 02) |
| `tests/unit/` | Fast, isolated tests |
| `tests/integration/` | Tests crossing process, filesystem, transport, or service boundaries |
| `tests/e2e/` | Real end-to-end suites and their pytest gate |
| `scripts/` | Operational scripts only |
| `docs/` | Current documentation |
| `docs-pre-reset-v1/` | One-line pointer; the v1 archive itself lives outside the repository |

Both Python packages use the `src` layout. Do not add importable packages at the
repository root.

UI host: **Electron + React is the only long-term UI** (`apps/web` renderer,
`apps/desktop` host). The Python `textual` UI is gone; the Node Ink terminal and
the OHJSON backend host are **deprecated** (ADR-0005 Updated 2026-10-24) and go
away when the REPL thin client passes acceptance; do not add features to either.
See [ADR-0005](adr/0005-single-ui-host.md) and [ADR-0006](adr/0006-serve-host-and-wire-protocol.md).

## Client topology (target, ADR-0006)

One contract, two transports. The same serve routes back the terminal REPL
through an **in-process transport** (no port, no credentials) and back
Studio/Web over **loopback TCP with the credential handshake** (random
127.0.0.1 port, one-shot launch credential, HttpOnly cookie, Host/Origin
check, parent lease). `apps/web` must also run standalone in a browser
(STRUCTURE §8); Electron is just one of its hosts.

`apps/web` talks to the engine over HTTP — that is a **network relationship,
not an import edge**; the import ladder and `.importlinter` are unchanged by
host growth.

Configuration types belong in `contracts/settings.py` (future), not in
`bootstrap/`: `bootstrap` is the assembly layer and must not be imported by
lower layers. See ADR-0002 item 18.

## Dependency direction

```text
frontend/terminal  (deprecated, ADR-0005 Updated)
        |
        v
src/questor  (product app)
        |
        v
src/questorharness  (engine)
```

The engine must not import the product app. The product app may import the
engine.

This boundary is enforced by `.importlinter` and by
`tests/integration/test_import_boundaries.py`. Run:

```bash
uv run lint-imports
```

## Inversion points

App-specific behavior is injected into the engine rather than imported by it:

- Channel media root: the app sets `QUESTORHARNESS_CHANNEL_MEDIA_DIR`.
- Feishu managed-group policy: the app passes a `managed_group_checker` into
  `ChannelManager`.
- Cron notifications: the app registers a handler through the
  `questorharness.notification_handlers` entry point.
- Cron provider profile: jobs can set `provider_profile` or `profile`; the
  engine also honors `QUESTOR_PROFILE`.

## Runtime data

| Path | Owner |
| --- | --- |
| `~/.questorharness/` | Engine configuration, skills, plugins, session data |
| `~/.questor/agent/` | Product app workspace, memory, gateway config, sessions |

`~/.questor/` is reserved for legacy v1 data and future product-level state. The
v2 app uses the nested `agent` workspace so it does not read v1 sessions or
config.

## Channels

The built-in channel set is Feishu and QQ. Slack, Telegram, Discord, DingTalk,
Matrix, Mochat, Email, and WhatsApp were removed. Channel media is stored under
`QUESTORHARNESS_CHANNEL_MEDIA_DIR` when the app starts the gateway.

## Tests

Tests are split by execution boundary:

- `unit`: default fast loop.
- `integration`: process, filesystem, transport, or service boundaries.
- `e2e`: real external suites, skipped unless `QUESTOR_RUN_E2E=1`.

Markers are assigned automatically from the test path in `tests/conftest.py`.
See [Testing](guides/testing.md) for commands.
