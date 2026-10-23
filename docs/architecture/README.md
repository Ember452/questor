# Architecture Notes

Detailed architecture notes live here. Start with:

- [Target structure (v2)](STRUCTURE.md) — package layout, dependency rank,
  modes, fields, file grammar, and migration waves.
- [Structure migration plan](MIGRATION.md) — move-only first, then code shape,
  then capabilities; per-phase exit criteria and rollback.
- [Memory provider contract](MEMORY.md) — Policy/Port/Provider, failure
  semantics, conformance, and rollout.
- [Namespace registries](NAMESPACES.md) — every tool, command, event, config key,
  env var, entry point and skill id, with its producer and consumers (generated
  skeleton, hand-reviewed consumer column; checked by `check_name_registries`).
- [Dependency graph](GRAPH.md) — generated package graph, cycles, most-imported
  modules, vacuous contracts, capability radius and the frozen indirect edges.
- [Current architecture](../ARCHITECTURE.md) — what exists today.

Planned topic notes:

- Engine runtime and middleware chain
- Provider and tool registries
- Channel adapter protocol
- Gateway session routing
- Memory and context compaction
- Permission and sandbox boundaries
- Desktop and frontend transport
