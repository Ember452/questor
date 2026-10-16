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

### Added — P3 persistence + resume (`feat/p3-persistence-resume`)
- **Durability is now the normal path**: the CLI loop and HTTP server persist every durable event + turn/`pre_tool`/`post_tool` checkpoints through `StorePort` (the composition root `__main__` injects `SQLiteStore`; surfaces still import no concrete store — C4/C14). A killed run leaves a durable, resumable trail.
- **Dual cursor materialized on `StorePort`** (ADR-0011/0022): per-run logical `seq` (SSE `after_seq`) + a global monotonic physical `gseq` watermark (`watermark`/`replay_global` cross-run catch-up); `meta(store_schema_version)` fails closed on a newer-than-known DDL; `list_unfinished_runs` derives resume candidates from the log (no terminal event present).
- **Cross-process resume** (ADR-0020/0021): `rebuild_run` = latest full snapshot + `seq` aligned to `sequence_head` + close due approvals; `resume_and_drive` hands the rebuilt run back to the single `DefaultTurnLoop`. Before the next provider call the loop settles still-open calls — `awaiting_approval` waits on its existing request, crashed `ready/running` calls re-dispatch once, and `pending/validated` calls re-run the **full permission gate** (resume never silently bypasses `ask`). Checkpoints keep the full authoritative state (incl. open calls & approvals); `closed_prefix` identifies the in-flight set rather than truncating it, so HITL survives restart.
- **Surfaces**: `python -m questor --resume <run_id>` / `--list` and `POST /runs/{id}/resume`, all submitting through `RunController`/`RunRegistry`, never `reduce` (C16).
- **Verified on the real platform**: cross-connection and OS-subprocess kill→`--resume` (`test_p3_kill_resume.py`, Windows); a real `uvicorn` + `httpx` SSE reconnect with `Last-Event-ID` proves `after_seq` no-loss/no-dup over an actual socket, closing the P2 audit §7 "跨真实 socket UNVERIFIED (uvicorn 未装)" item.
- **New guard** `check_replay_determinism.py` (wired into the CI `boundaries` job): asserts `snapshot + tail-replay == continuous reduce` over fixtures, with a `--self-test` that proves it can go red + fail-on-empty; plus a durability guard that no durable event bypasses `store.append` while live-only never persists.

### Added — P4 memory v1 / soul (`feat/p4-memory-soul`)
- 记忆子系统 `src/questor/memory/`（与 `state/` 分离，ADR-0023）+ L0 `contracts/memory.py`：`MemoryChunk`/`MemorySearchResult`/typed `RecoveryPointer`/typed `MemoryWrite`/`MemoryStorePort`/`VectorBackend`/`MemoryStrategyConfig`。
- 写记忆走 `Command→reduce→MemoryStorePort` 单写者路径（HARD C4/C16）：`reduce` 处理 `WriteMemory` → 内部 `memory_written` 事件（有界、**无原文**）→ kernel 在消费点 sink 落**独立 `memory.db`**；记忆正文绝不进 `Domain_State`（DoD⑤）。
- `providers/store_memory_sqlite.py`：md 文件真源 + SQLite/FTS5 派生索引、单一 `_SCHEMA` authority + `meta(memory_schema_version)` fail-closed + `BEGIN IMMEDIATE`；与 event-log 分库故障隔离（R03 D-P1）。
- 混合检索 `memory/{chunker,sync,search}.py`（ADR-0026）：markdown 感知切块 + 文件真源重建 + rank-normalize 加权融合（**非 RRF**）+ 时间衰减（daily 半衰、core 常绿）+ 无 embedding 静默降级关键词-only；`memory_search` 工具经 Harness 持有的 `MemoryStorePort`，策略/工具无裸句柄。
- Deep Dream 离线蒸馏 + run-完成→daily flush（`memory/distill.py`，ADR-0025）：原子写 + 输入哈希去重 + 只删不编 + 空哨兵跳过；CLI `--dream` 入口（无密钥走确定性 heuristic fallback；真 LLM 蒸馏质量 UNVERIFIED）。composition root 注入 `SQLiteMemoryStore`。
- 快照 schema **v2→v3**：`recovery_pointers` 定为 typed `(seq_from, seq_to, covered_hash)` + 读前 fail-closed；v1/v2 无锚旧值迁移为 `()`（不伪造锚，ADR-0024）。`covered_hash` **生产者**随 `disable_compaction=True` 后置 P10。
- 事件协议 **19→20**：新增可选外部 type `memory_written`（bounded `kind/chunk_count/source/artifact_ref`），`check_protocol_schema` enum+$defs+branches+fixtures lockstep（只增不改）。
- 策略 `policy/memory_policy.py`：记忆感知 ReAct 变体消费 `PolicyView.memory` 有界投影（L4 接缝示例、可插拔，不改 kernel）。
- 守卫：`check_layering_ast.py` 扩记忆规则（memory=state peer、只依 contracts；`policy`/`surfaces`/`capabilities` 禁 import 具体 `store_memory_sqlite`），`--self-test` 判红；已在 CI `boundaries` blocking job 运行。记忆写/读旁路=0（reduce 唯一入口 + AST 守卫）。
- 决策 ADR-0023~0026 + 阶段计划 `docs/plan/04-memory-soul.md`。质量门：405 passed / 5 skipped（DoD① 跨会话写入→检索命中、DoD② Deep Dream 产出、DoD③ 单写者、DoD④ 可插拔、DoD⑤ state/memory 分离 + evals 雏形）。UNVERIFIED：真 LLM/embedding 召回质量、trigram-CJK 未实现（后置 P10）、完整四档压缩（→P10）、跨进程记忆 exactly-once（→P9）。

### Fixed (多 tool_call 配对崩溃 — ADR-0028, 2026-10-16)
真机复现并逐段核验：模型一轮返回 ≥2 个 tool_call 时，串行循环只执行第一条就回发下一次请求，历史留下
悬空 tool_call → provider `400 …must be followed by tool messages…` → **异常穿出 `drive_controller`、整个 CLI
进程带 traceback 退出、run 不落任何终态**。
- **回发前配对关卡（新硬约束 C19）**：全仓唯一的 `ProviderPort.stream` 调用点（`kernel/loop.py::_stream_turn`）
  内先跑 `_ensure_paired_history`：一条 assistant 里**所有**未应答 tool_use 串行闭合才允许下一次请求（仍不启用
  并行，ROADMAP §2.5 口径不变）。判据取 **context 侧** `open_tool_use_ids` 而非账本 OPEN 集合——实测存在
  “context 有悬空、ledger 无条目”的分叉，账本驱动的回填盖不住。不可调和 → fail-closed 落 `run_failed(format_error)`
  且**一次都不发**（不靠投影层合成假 tool_result 骗过协议，那会把 ledger/context 分叉制度化）。
- **provider 故障归一（plan/01 T4、design/01 §8、ADR-0010 首次真接线）**：新增 `contracts/errors.py::
  classify_provider_error` 纯函数（不 import provider/litellm；状态码 → 消息 `Error code: NNN` → 有序模式表 →
  fail-closed UNKNOWN，自己绝不抛），kernel 边界捕获 `Exception` → `_fail_with_entry` 落唯一终态；BaseException
  （取消/中断）继续上抛。**400 配对违规钉为不可重试**：否则 P10 接上退避重试会把同一确定性错误打满预算。
  本轮不自动重试（退避/fallback 链/凭据池仍归 P10）。
- **stop-gate 同源路径**：策略给 `SuggestFinish` 而账本仍有 OPEN 调用时的 `continue`，实测会反复带悬空历史回发
  直到 max_turns（白烧 3 轮预算）；现由同一关卡收掉。
- **被拒收消息的 durable 泄漏**：重复 `tool_use_id` 被 `AppendAssistantMessage` 整条拒收后，loop 仍把本地消息
  当已落库定稿，经 `FinalizeRun(final=…)` **走私回 context**，留下一条永不配对的 tool_use 且因 `completed` 不进
  `--list`/resume（比崩更难查）。现改为“未产 `message_completed` 即出声”→ `run_failed`。
- **取消优先**：关卡不得为补配对而继续执行未跑调用；实测取消后 `provider.stream` 不新增、落单调用作
  `cancelled` 回填、`error_stack` 保持空（R01 F8：取消绝不进重试分类）。
- **关卡不改变“谁能跑”**：补执行仍走完整权限/floor/参数校验。实测关卡补执行一个 none 后端的 write 时
  **真的发出 `approval_request`**（理由为 write capability floor）→ 无人决策超时 fail-closed deny、目标文件不落盘；
  非法参数的落单调用也回 error 结果闭合配对。
- **复用不新写**：ADR-0021 的 `_resume_settle_open_calls` 改名 `_settle_open_calls`（resume 入口与关卡两个安全点共用，
  行为逐字不变）。`docs/log/{DESIGN,PLAN}.md`、`plan/01`、`plan/03` 同步注记。
- peer-scan（AGENTS §4.5）：位置采纳 CowAgent `agent/protocol/agent_stream.py:1604-1608`；**拒** CowAgent
  `message_utils.py:21-120` 的合成 tool_result 抹平（事件溯源下会分叉）；分类器形状改造自 hermes
  `agent/error_surface.py` + `error_classifier.py`（MIT © Nous Research，已就地注 provenance）。
- 机械守卫：新增源码级测试——全仓 `self.provider.stream(` 调用点必须唯一且在 `kernel/loop.py`、关卡必在请求
  之前（fail-on-empty；已验证“拆掉关卡即判红”）。
- 测试：`tests/integration/test_pairing_gate_and_provider_fault.py`（10）+ `tests/unit/test_provider_error_classification.py`（8），
  先红后绿（修前同文件 7 条集成测试中 6 条全红、包含“非法历史真的被发出去了”这一直接证据；仅“取消优先”当时已绿）。
  质量门：**440 passed / 5 skipped**；ruff clean；lint-imports 4 kept；AST 76 files/0 违规且 self-test 判红；
  protocol 20 types lockstep；replay/output/secret/thread 守卫全绿；`verify_p0` ALL PASS。端到端在 `CliSurface.run_once`
  层面复验：一轮 `ls`+`read` + 严格网关判 400 的 provider → `completed`、两次 stream 均无悬空、异常不再穿出。
  UNVERIFIED：真 key 下 litellm 具体异常类型与 `status_code` 载体（版本相关）。

### Fixed (log assembly coverage — PR-A / 日志刀 1, 2026-10-16)
补齐 `docs/log/DESIGN.md` §11 点名的"最严重装配缺口"（纯缺陷，不动契约/分层）：
- **四入口日志裸奔**：`configure_logging` 此前只在 `interactive()` 里调，崩溃恢复最该有日志的 `--resume`（及 `--list`/`--dream`）无 handler → INFO 全丢。修复：装配上移组合根 `__main__._amain` 起手，读 `QUESTOR_LOG_LEVEL`（默认 INFO），覆盖 REPL/`--resume`/`--list`/`--dream` 四入口（`test_log_assembly_coverage.py` 真子进程断言 `--resume` stderr 有 questor 行）。
- **`questor.bus` 死 logger**：`kernel/events.py` 定义 `_log` 却零调用，订阅者队列溢出与持久化失败无人报。修复：`emit()` 溢出→出声丢帧、持久化失败→出声后上冒（数据丢失不静默吞）（`test_bus_failures_voiced.py`）。
- **console sink 显式绑 stderr**：`configure_logging` 不再依赖 `basicConfig` 默认，显式 `StreamHandler(sys.stderr)`、幂等不叠 handler、永不污染机器可读 stdout（`test_configure_logging_idempotent.py`，DoD A③/A④）。
- 落 `docs/log/{DESIGN,PLAN}.md`（设计定稿 + 刀 1/刀 2 实施计划）；`plan/01` T12 标"部分兑现"。脱敏/节流/白名单/文件面/双通道汇流随 PR-B（刀 2，对抗评审门后）。

### Fixed (P4 adversarial audit round, 2026-10-16 — closes `docs/audit/P4-review-2026-10-16.md` CONDITIONAL GO)
对抗审计发现两处"文档宣称≠代码现实"+ 三处小问题，均已复核并修复：
- **写生产者未接线（阻断记忆可用性）**：`flush_run_to_daily` 无生产调用者、产品无 `WriteMemory` 触发器。修复：`CliSurface.run_once` 在 run 完成边界 best-effort 调 `flush_run_to_daily`（经 `MemoryStorePort` 收口、不进热 loop、`run_id` 幂等、失败仅告警），episodic→daily→Deep Dream 链在产品中真能跑；新增 `test_p4_memory_flush.py` 走真实 loop（非手动 inbox）证写→检索。
- **trigram 档位谎报**：代码只有 unicode61→LIKE 两档，`store:13` 过期注释 + ADR-0026/design-06/plan 宣"三档"。修复：全部改为"两档实现、trigram-CJK 未实现→后置 P10"、删过期注释。
- **`memory_written.source`** 误用 `kind.value` → 抽 `contracts.memory.source_for_write`（L0，store/reduce 共用），emit 真实 `MemorySource`。
- **Deep Dream 无界重试**：ADR-0025 宣"transient 重试 3 次"却无实现。修复：`_call_distill` 有界重试、耗尽上抛（不静默吞）；测试 transient×2→第3次成功 + 耗尽抛。
- **D③ 命名测试缺失**：补 `test_p4_memory_single_writer.py`（加载 AST 守卫断 capabilities/policy/surfaces 直连具体 store 判红）。`PolicyView.memory` 无生产填充者（loop 有意不填以免耦合）→ plan §11 记 P5/P7 backlog。
- 复跑质量门：**412 passed / 5 skipped**（+7 审计修复测试），全守卫 self-test 判红、protocol 20 types lockstep、lint-imports 4 kept。

### Fixed (P2 adversarial audit round, 2026-10-16 — closes `docs/audit/P2-review-2026-10-15.md` NO-GO)
All four blocking findings were reproduced by hand before fixing, and each is now pinned by a test:
- **Tool panics escaped the kernel**: `loop.py` called `tool.execute()` with no shield, so a raising tool (or an unwired `ProcessRunner`/`ArtifactStore`) crashed the run and left the call stuck open. The Harness now wraps every tool call in `asyncio.wait_for` + `except Exception` → `ToolResult(status="error")`, while `CancelledError`/`KeyboardInterrupt`/`SystemExit` still propagate (`test_p2_tool_fault_isolation.py`).
- **`FinalizeRun` left dangling `tool_use`**: a `failed` terminal didn't backfill open calls, breaking the pairing invariant I1 and guaranteeing a 4xx once P3 replays the context to a provider. Both terminal paths now backfill with distinct `note` text and continuous seq allocation (`test_reduce_finalize_pairing.py`).
- **Bundled short flags were mis-classified as read-only**: `sed -ni` reads as `-n`+`-i` (in-place write) to a shell, but the parser compared the whole token against the write-flag set, so under job/partial + `full_auto` an in-place file edit could skip the approval floor entirely. Flags are now expanded before comparison, and spacing no longer changes a security decision (`test_bundled_short_flags_are_expanded`).
- **`PermissionCtx.denylist` was a fake control plane**: the engine only consulted hard-coded constants, so adding a path had no effect despite ADR-0014 claiming otherwise. It now participates as its own evaluation step (union with built-in defaults; cannot weaken them), and ADR-0014 gained an implementation addendum describing exactly this.
Also fixed: Harness-armed deadlines for non-process tools (a `sleep(30)` tool previously ran to completion and reported success); `TIMED_OUT` now actually produced instead of being flattened into `error`; `enforce_read_only` / `protected-root` / Windows junction-escape branches covered by real tests (junction escape now **verified**, no longer UNVERIFIED); `check_output_budgets --self-test` can now prove red; AST guard no longer misses `from questor import <layer>`; `wrap_shell` seam exists and is refused by every backend; dead `ToolSpec` fields annotated `NOT enforced until P#`; process output previews now cut on valid UTF-8 boundaries.

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
