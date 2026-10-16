# contracts — L0 shared vocabulary (innermost layer)

The types every layer speaks: state schema, event/command types, `ToolSpec`, and the Port
protocols (`ProviderPort`, `StorePort`, `ProcessRunnerPort`, …). This is the most stable
package in the repo — dependencies point inward, never outward (HARD C1/C14).

**Boundary vs `protocol/`** (they look like duplicates, they are not): `contracts/` holds the
**in-process Python** types; `protocol/` holds the **cross-language wire** schema (JSON Schema,
consumed by the TS client's codegen). They share no files;
`scripts/check_protocol_schema.py --check` keeps the two event-type sets in lockstep.

Must not live here: any implementation, I/O or adapter — those belong to `providers/`,
`capabilities/`, `policy/` (STRUCTURE S4). Keeping this package pure is what stops "the most
stable layer" from bloating (HARD C11).

Additive-only: new optional fields and new `type` values are fine; existing semantics never
change. Bump the version only on a breaking change (HARD C6).
