# Architecture Notes

Detailed architecture notes live here. Start with:

- [Target structure (v2)](STRUCTURE.md) — package layout, dependency rank,
  modes, fields, file grammar, and migration waves.
- [Structure migration plan](MIGRATION.md) — move-only first, then code shape,
  then capabilities; per-phase exit criteria and rollback.
- [Memory provider contract](MEMORY.md) — Policy/Port/Provider, failure
  semantics, conformance, and rollout.
- [Current architecture](../ARCHITECTURE.md) — what exists today.

Planned topic notes:

- Engine runtime and middleware chain
- Provider and tool registries
- Channel adapter protocol
- Gateway session routing
- Memory and context compaction
- Permission and sandbox boundaries
- Desktop and frontend transport
