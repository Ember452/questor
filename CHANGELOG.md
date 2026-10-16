# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 设计文档体系：VISION、ROADMAP、STRUCTURE、design（分层/状态/事件/工具/循环/策略/记忆/工程红线）。
- 架构决策记录 ADR-0001…0019。
- 外部参考扫描报告 R01–R09（docs/references）。
- 仓库治理：README、LICENSE、CONTRIBUTING、SECURITY、CODE_OF_CONDUCT、.github 模板与 dependabot、工程卫生配置。
- 阶段计划：`docs/plan/02-p2-tools-permission.md`（P2 工具 + 权限 lite；按 2026-10-15 对抗审计全面修订，固化 Command Inbox、PermissionCtx 单一真源、capability floor、审批生命周期、Shell IR、ProcessRunner、有界 Artifact 与字段级投影）。

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

### Added — P2 foundation (T1–T13, on `feat/p2-foundation-hitl`)
- Non-blocking coverage baseline: `pytest-cov` + branch coverage XML artifact in the `tests` job (no `fail-under` gate yet).
- L0/contract vocabulary: tool-call lifecycle states, `ApprovalRequest`/`ApprovalStatus`, raw-args status, `SandboxDescriptor`, `ProcessRequest/Result`, `ArtifactRef`/`OutputBudget`, shell-analysis IR, `CommandInboxPort`/`InboxReceipt`, `PermissionDecision`/`Outcome`; protocol EventType grew 17→19 (`approval_resolved`, `permission_mode_changed`).
- Versioned snapshot (v2) round-trips full authority: `permission_ctx`/approvals/rules, task_tree, error_stack, and expanded ToolCall fields; unknown versions fail-closed with v1 lossy migration.
- `RunController` serialized Command Inbox (FIFO, idempotency, backpressure, terminal rejection) wired into the turn loop; five-layer validation reordered to args→schema→shell-analysis→validate→permission→floor.
- Pure `PermissionCtx` engine + fail-closed POSIX/PowerShell shell parsers + capability floors above `mode`; honest host sandbox backend detection.
- Harness-owned `SandboxedProcessRunner` (Job Object + taskkill process-tree cleanup, env credential scrub, output limits→artifact), content-addressed `FileSystemArtifactStore`, provider `env_safety`.
- Full HITL lifecycle (request/resolve/expire/cancel idempotency, approval timeout) driven only via Commands; CLI + HTTP (`/runs/{id}/approvals/{req}/resolve`, `/permissions`, `/runs/{id}/cancel`) submit through `RunRegistry` and never `reduce`.

### Added — P2 tools, protocol, guards (T14–T21, `feat/p2-foundation-hitl`)
- `ToolRegistry` + L0 `RunToolSurface`: per-run frozen tool view (hot register/unregister never mutates a running run), description sanitize/bounds, unknown-name candidate hints surfaced to the model.
- File tools with shared workspace-containment resolver: `read` (offset/limit + line/byte caps + dir/binary reject), `write`, `edit` (unique-anchor / `replace_all`), `apply_patch` (unified-diff, per-file all-or-nothing), `ls`/`glob`/`grep` (entry/match caps, noise-dir skip, symlink-escape + invalid-regex handling).
- `bash`/`powershell` tools built only on `ctx.run_process` (no spawn in capabilities); CLI registry now exposes the full P2 tool set; loop wires a real `ProcessRunner` + `ArtifactStore` into `ToolContext`.
- Field-level protocol: `protocol/event.schema.json` gains per-type `$defs` + `if/then` (required fields, bounded strings, `additionalProperties:false`); projection enforces a per-type outbound whitelist (full args / abs path / env values / provider state never leave).
- HITL checkpoint resume: `resume_run` restores awaiting-approval state and closes due approvals via `ExpireApproval` (permission/approval state cannot silently evaporate on restart).
- New machine guards (each with `--self-test` that goes red): AST forbidden-import rules (capabilities/surfaces/contracts), output-budget invariant guard, secret/env-value projection guard; CI runs them and adds platform-split `tests-posix` / `tests-windows` jobs so PowerShell vs bash DoD is exercised on the real platform (skip-when-absent, never faked) — Windows only on PR/dispatch/main to keep its runner minutes down.
- P2 end-to-end DoD test drives a fully-wired loop (engine + capability floor + registry + Command Inbox) for the headline dangerous-op flows.

### Fixed (found by the first P2 CI run on Linux, 2026-10-16)
- `surfaces/approval.py`: the reader thread called `loop.call_soon_threadsafe` outside its `try`, so a keystroke arriving after an approval timeout (loop already closed) raised `RuntimeError: Event loop is closed` inside a daemon thread. Now routed through `_safe_settle()`, which discards late input — that drop *is* the timeout-means-deny semantics — with two falsifiable regression tests.
- Shell-tool platform gating: the DoD tests keyed off `shutil.which("powershell")`, but the ubuntu runner ships `pwsh`, so tests that must skip did not — and they used `NullSandbox` as if it could execute. They now probe the real capability (`detect_sandbox().wrap_argv`) and skip with an explicit reason when the host cannot wrap argv, while a new always-run assertion locks the correct behaviour: no capable backend means a structured error, never an unconfined spawn.
- `tests/unit/test_loop_tool_ctx.py` hard-coded a Windows path as "absolute argv[0]", which `ProcessRequest` correctly rejects on POSIX; switched to `sys.executable`.

### Fixed (P0/P1 adversarial audit, 2026-10-15)
- C2: deep-freeze JSON leaves (`ToolCall.args`, `ContentBlock.input/payload/provider_state`, `Envelope.data`) via `immutables` so COW states no longer share mutable leaves.
- C7/ADR-0011: Cancel no longer emits two events with the same seq (was causing a store `IntegrityError`).
- Capability/risk fail-closed: exec/write/network with no capable sandbox backend are denied in the loop.
- Protocol guard now fails on an empty `EventType` set; bus prunes subscriber queues at terminal; `python -m questor` launches the CLI.

<!-- 实现里程碑 (P0/P1/…) 达成后在此按 Keep a Changelog 追记 -->
