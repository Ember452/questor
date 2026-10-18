# capabilities/subagent — sub-agent orchestration (P8)

L3 home for the `delegate` tool (`delegate.py`): a strategy proposes delegating a self-contained
sub-task; it runs through the normal tool lifecycle (permission/sandbox/timeout in the Harness, C8).
The actual spawn is performed by the injected `SubagentSpawnerPort` (impl: `surfaces/subagent_orchestrator.py`,
L6, wired by the composition root) — this package never touches the registry/bus/store directly (C1/C14).

Semantics live in the ADRs, not here: subagent = independent Run linked by `TaskNode.assigned_run_id`
(ADR-0038); fan-out admission gate (ADR-0041); child permission ⊆ parent, fail-closed (ADR-0040);
`peer_started`/`peer_ended` event shapes (ADR-0042); DAG dependency validation in `reduce` (ADR-0037).
