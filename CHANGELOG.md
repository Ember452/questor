# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 设计文档体系：VISION、ROADMAP、STRUCTURE、design（分层/状态/事件/工具/循环/策略/记忆/工程红线）。
- 架构决策记录 ADR-0001…0011。
- 外部参考扫描报告 R01–R09（docs/references）。
- 仓库治理：README、LICENSE、CONTRIBUTING、SECURITY、CODE_OF_CONDUCT、.github 模板与 dependabot、工程卫生配置。

### Added — P0 (interface skeleton)
- `src/questor` 8-layer package skeleton with L0 contracts (commands/events/state-schema/policy/tool/ports) and stub base classes.
- Mechanical layering guards: `.importlinter` + ruff `banned-api` + a self-written AST checker (dynamic imports, fail-on-empty, self-test).
- `protocol/event.schema.json` as the external-event single source + `check_protocol_schema.py --check` drift guard.
- CI `ci-python.yml` (boundaries as an independent blocking job) + `verify_p0.py` one-click check.

### Added — P1 (minimal runnable loop)
- `reduce()` single writer: tool_use/tool_result pairing, terminal uniqueness, cancel backfill of open calls.
- SQLite event-sourcing store (per-run seq, `after_seq` replay) + `closed_prefix` checkpoint write-gate.
- In-process event bus: internal→external projection, live-only deltas, first-writer-wins terminal, version gate.
- Turn loop (phase pipeline) with serial tools, budget termination, deny + illegal-intent non-crash paths.
- Three-state permission engine (non-overridable realpath denylist); `read` tool; LiteLLM + scripted providers; in-process ReAct policy.
- CLI terminal surface + HTTP/SSE service (`/run`,`/events`,`/cancel` with `id:<seq>` + `Last-Event-ID` resume) + structured logging.

### Fixed (P0/P1 adversarial audit, 2026-10-15)
- C2: deep-freeze JSON leaves (`ToolCall.args`, `ContentBlock.input/payload/provider_state`, `Envelope.data`) via `immutables` so COW states no longer share mutable leaves.
- C7/ADR-0011: Cancel no longer emits two events with the same seq (was causing a store `IntegrityError`).
- Capability/risk fail-closed: exec/write/network with no capable sandbox backend are denied in the loop.
- Protocol guard now fails on an empty `EventType` set; bus prunes subscriber queues at terminal; `python -m questor` launches the CLI.

<!-- 实现里程碑 (P0/P1/…) 达成后在此按 Keep a Changelog 追记 -->
