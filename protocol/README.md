# protocol — cross-language wire contract (single source of truth)

The schema for **what leaves the harness**: the external event projection, consumed by the
desktop/web TS client via codegen (P7). HARD C6/C15; see `docs/design/02-event-protocol.md`.

- `event.schema.json` — external event envelope `v1`. Required:
  `v · seq · run_id · type · ts · data`; `additionalProperties: false`.
  `seq` = per-run monotonic logical cursor (`after_seq` resume, ADR-0011).
- **Additive-only**: new `type` values and optional `data` fields are allowed; existing
  semantics never change. `v` bumps only on a breaking change. Unknown `type` must be ignored
  silently by every consumer — **except error-class events** (`run_failed` / `warning` /
  `resync_required`), which must always surface (HARD C6; see
  `contracts/events.ERROR_CLASS_EVENT_TYPES`).

Drift guard (blocking CI job, independent of change classifiers):

```
uv run python scripts/check_protocol_schema.py --check      # schema/contract/codegen TS stay in lockstep
uv run python scripts/check_protocol_schema.py --self-test  # proves the guard can go red
```

It asserts this schema's `type` enum equals `questor.contracts.events.EventType` exactly — so
the JSON Schema, the Python contract and the codegen'd TS can never silently diverge.

Current counts (mechanically synced; `check_protocol_schema --check` stays the authority, this line is
documentation only): **31** `EventType` values and **21** `Command` union members
(`src/questor/contracts/events.py`). Both grow additively only — new values never rename or renumber
an existing one, and `v` bumps only on a breaking change.

TS codegen (P7 T3): `cd desktop/web && npm run generate:protocol` writes `src/generated/event.ts`
from this schema via `json-schema-to-typescript`; `npm run check:protocol` re-generates in-memory
and exits non-zero if the committed `event.ts` is stale (drift gate, mirrors the Python `--check`).

**Boundary vs `src/questor/contracts/`**: this directory is the *wire* contract for other
languages; `contracts/` is the *in-process Python* vocabulary. Generated TS types land in the
client tree (`desktop/web/src/generated/`), never here.
