# Questor 计划 3（P3）· 持久化 + 断点续传 · 开发计划（已实施）

> 用途：P3 的开工基线、任务分解与收尾回填。
> 阶段口径：[`ROADMAP.md`](../ROADMAP.md) §1(P3)/§1.5；工程红线：[`HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md) C1–C18。
> 契约：[`design/01`](../design/01-state-model.md) §5/§9/§12/§13、[`design/02`](../design/02-event-protocol.md) §4/§10、[`design/04`](../design/04-turn-loop.md) §7；决策：[`adr/0005`](../adr/0005-state-storage.md)/[`0011`](../adr/0011-seq-semantics.md) + 本阶段新增 [`adr/0020`](../adr/0020-durable-write-gate-and-log-authority.md)/[`0021`](../adr/0021-cross-process-resume.md)/[`0022`](../adr/0022-dual-cursor-watermark.md)；实扒：[`references/R03`](../references/R03-state-persistence.md)。
> 分支：`feat/p3-persistence-resume`（基于已合入 main 的 P2 `1f5c171`）。

## 0. 定位与不可突破原则

**一句话**：P3 不是"多存几个字段"，而是把 P2 已存在但**半接线**的事件溯源/快照/重放零件，接成一条能被**真实 kill/重启**与**真实 socket**复现的闭环，并落地 design/01 §13 / design/02 §10 / R03 承诺、且是 P5/P7/P8/P9/P10 不返工的正确性前置项。

固定四条轴：
1. **单一权威**：`event_log` = 耐久事件唯一真相（客户端 `after_seq` 重放 + 审计）；`checkpoints` = 权威状态快照；落库顺序先 append 后 snapshot（ADR-0020）。
2. **续跑正确性优先**：resume 在进入 provider 前必须补齐/重派所有未闭合 `tool_use`，绝不把半截 tool_use 喂回 provider（Anthropic/OpenAI 4xx）。
3. **fail-closed**：未知 store schema 版本、丢失/过期审批、崩溃遗留未批调用一律拒绝或显式闭合，绝不静默放行/半重建。
4. **真机证据**：OS 级子进程 kill→`--resume`、真 uvicorn+httpx 的 `after_seq` 重连必须实测；不可复现处标 UNVERIFIED。

**开工前基线**：P2 经对抗审计闭环后合入 main（`1f5c171`，PR #19）。P3 分支起点复跑全质量门：**345 passed / 5 skipped**、ruff clean、lint-imports 4 kept、六守卫 self-test 全 PASS、verify_p0 ALL PASS。

## 0.5 Peer-Repo 扫描（AGENTS §4.5，来源 R03 实扒）

| 能力 | 扫描仓（`file:line`） | 结论 | 复用/改造 · 许可 |
|---|---|---|---|
| 事件溯源 log 权威 + 派生 index | DeepCode `core/sessions/store.py:1-24`；`core/persistence/event_repository.py:21-122` | 改造 | log 权威、先 append 后 snapshot、损坏回退（ADR-0020） |
| 双游标（per-run seq + 全局 watermark） | DeepCode `event_repository.py:21-56,89-112`；wuu 全局 HeadSeq | 改造 | `event_log.gseq` + `watermark`/`replay_global`（ADR-0011/0022） |
| checkpoint 写门截断 closed_prefix | CowAgent `step_writer.py:53-64,128-144` | 部分采纳 | closed_prefix 用于识别在途集，不截断 durable（HITL 需保留，见 §6 偏差） |
| 悬空 user-turn 修复 | hermes `hermes_state_rewind.py:67-71` | 自写 | 本项目 reduce 形状不同；rebuild 未闭合调用经 reduce 回填 |
| 恢复不重复副作用 = 幂等投递 claim | hermes `hermes_state_common.py:582-609`；wuu `claimAgentResultDelivery` | 改造（轻量） | v1 以 tool_call_id + seq_result + OPEN 状态判重派；完整 claim 留 P9 |
| append 按稳定 uid 去重 | CowAgent `step_writer.py:22-25`；DeepCode `core/sessions/transcript.py:82-100` | 改造 | message.id/tool_call_id 幂等键；submit 键 `submit:{run_id}:{turn}` |
| JSON 禁 NaN/Inf + tz-aware UTC | DeepCode `serde.py:10-45` | 复用（已实现） | store `_dumps`、`require_aware` 已落实 |
| schema 单一 authority + 幂等 DDL + BEGIN IMMEDIATE | hermes `hermes_state_schema.py:1348-1365`、`801-816` | 改造 | `_SCHEMA` 唯一 authority + `meta(store_schema_version)` fail-closed |

> 前端能力（无：P3 不含 UI）。桌面订阅 + SSE 重连的 UI 侧在 P7；P3 只保证服务端 `after_seq`/resync 契约在真 socket 成立。

## 1. 目标与可验证判据（DoD）—— 全部达成

1. **真 kill 续跑**：OS 级子进程 kill 后 `python -m questor --resume <run_id>` 续到唯一终态、不重复副作用（`test_p3_kill_resume.py`，Windows 实测）。
2. **真 socket after_seq 不丢不重**：真 uvicorn + httpx，断开带 `Last-Event-ID` 重连，durable 尾无缺口无重复、终态恰一条（`test_p3_sse_reconnect.py`，实测过）。
3. **durable 永不喂半 tool_use 给 provider**：checkpoint 保完整态；resume 在 provider 前 settle 未闭合调用（`test_p3_rebuild_resume.py` 配对断言）。
4. **log 权威 + snapshot round-trip**：`check_replay_determinism.py` 断言 `snapshot+tail == continuous reduce`（self-test 能判红）。
5. **双游标落地**：per-run `seq` + 全局 `gseq` watermark 互不混用（`test_store.py` 双游标 + catch-up）。
6. 既有 P0–P2 全绿；新守卫 self-test 判红；ruff/lint-imports/AST/protocol/secret/output/durability 全绿。

收尾质量门（Windows 本机）：**361 passed / 5 skipped**，ruff clean，lint-imports 4 kept，六 + replay 共七守卫 self-test 全 PASS。

## 2. 任务清单（T0–T18，均完成）

- [x] **T0** 切 `feat/p3-persistence-resume`（P2 已入 main）；复跑全质量门 GO。
- [x] **T1–T3** 前置 [ADR-0020](../adr/0020-durable-write-gate-and-log-authority.md)/[0021](../adr/0021-cross-process-resume.md)/[0022](../adr/0022-dual-cursor-watermark.md) + `docs/adr/README` 索引 + design/01 §5/§9、design/02 §4 活文档引用。
- [x] **T4** `contracts/ports.py`：StorePort 纯增量 `watermark`/`replay_global`/`checkpoint_seq`/`list_unfinished_runs`（不改既有签名/信封，C6）。
- [x] **T5** `providers/store_sqlite.py`：全局 `gseq` 列 + `runs` 记账 + `meta` 版本 fail-closed + append-before-snapshot 注释。
- [x] **T6–T7** `test_store.py`：双游标、跨 run catch-up、schema 版本判红、崩溃重开一致性。
- [x] **T8–T9** `kernel/loop.py`：稳态补点 `auto`/`pre_tool`/`post_tool` checkpoint；抽 `_execute_tool`（普通 turn 与 resume 共用）。
- [x] **T10** `kernel/recovery.py::rebuild_run`：快照 + seq 对齐 head + 闭过期审批；`resume_run` 薄封装后兼容。
- [x] **T11** `kernel/durability.py::resume_and_drive` + loop `_resume_settle_open_calls`/`_resume_wait_for_approval`/`_resume_execute_call`：幂等 re-dispatch（AWAITING 等原 request、READY/RUNNING 补执行、PENDING/VALIDATED 重走权限）。
- [x] **T12** surfaces：`__main__` 组合根注入 `SQLiteStore`（surfaces 不 import 具体 store）；`CliSurface(store=…)` 常规路径落库 + `resume`；CLI `--resume`/`--list`；HTTP `POST /runs/{id}/resume`（经 RunController 注册回 inbox）。
- [x] **T13** `test_p3_kill_resume.py`：跨连接 + OS 子进程 kill→`--resume`，断言未批危险写不落盘。
- [x] **T14–T15** `test_p3_sse_reconnect.py`（真 socket）+ `test_bus.py` 缝合去重/ delta 不占 durable seq；dev 依赖加 `uvicorn`+`httpx`。
- [x] **T16–T17** `scripts/check_replay_determinism.py`（+CI `boundaries` 步骤）+ `test_p3_durability.py`（durable 无旁路、live 永不入库、rebuild 幂等）。
- [x] **T18** 本文 + CHANGELOG + ROADMAP §1(P3 ✅)；死字段 `# NOT enforced until P#`（ToolSpec parallel_safe/orchestrator/barrier/available 已在 P2 审计闭环时标注）。

## 3. 契约与红线自检

- 触分层/契约：**是** → T1–T3 ADR 先行；`StorePort` 仅加方法（C6 不破信封/关联键/终止序）。
- C2/C16 单写者：resume 仍由唯一 loop 经 RunController 串行 reduce；surfaces 不直 reduce。
- C5/I3：delta 继续不落 `event_log`；写门只识别在途集、不截 durable。
- C7/C13：未闭合调用经 reduce（RecordToolResult/FinalizeRun）闭合；rebuild 对终态幂等、不产第二条终态。
- C14/C4：surfaces 只持 `StorePort` 抽象；`SQLiteStore` 仅在组合根 `__main__` 构造（AST/import-linter 复现判红）。
- C15：新增 `check_replay_determinism` self-test 能判红 + fail-on-empty，并作为 `boundaries` 独立 blocking job 的一步。
- 事件协议：无新增外部 type（仍 19），`check_protocol_schema --check` 通过。

## 4. 测试与回归

- 单元：`test_bus`（缝合去重、delta 不占 seq）、`test_store`（双游标/版本 fail-closed/崩溃重开）。
- 集成：`test_p3_rebuild_resume`（rebuild+resume 幂等、AWAITING/PENDING 安全）、`test_p3_durability`（落库边界）、`test_p3_kill_resume`（跨连接 + OS 子进程）、`test_p3_sse_reconnect`（真 socket）；P0–P2 全量不回归。
- 守卫：`check_replay_determinism --self-test`、`lint-imports`、AST/protocol/secret/output/verify_p0 全绿；Windows 真机 leg。
- 诚实边界：真 LLM 流式（无 `LITELLM_API_KEY`）、seatbelt/bwrap 实机、真分布式 exactly-once 仍标 UNVERIFIED（后置 P9/P10）。

## 5. 落地风险 & 缓解

| 风险 | 触发 | 缓解 |
|---|---|---|
| resume 重跑有副作用工具 | 崩溃在 result 落库与 post_tool 快照之间 | at-least-once：仅重派仍 OPEN 的调用；三处稳态补点把窗口收到"至多重跑一个工具"；真 exactly-once（claim/lease）后置 P9 |
| resume 绕过权限 | 直接执行未批准的 PENDING 调用 | `_resume_settle_open_calls` 对 PENDING/VALIDATED 强制重走 `_handle_tool_call`（含权限/floor），测试断言无人批准即 deny、目标文件不落盘 |
| 半 tool_use 喂回 provider | 快照含未闭合调用且未补齐 | provider-first 循环前 `turn = run.turn` 后先 settle 所有 OPEN；`check_replay_determinism` + 配对断言守 |
| 真 socket 测试在 CI 不稳定 | 端口/时序竞态 | 本机必真跑；固定 loopback + 就绪轮询；起不来则 `skip` 标 UNVERIFIED，不 fake |

## 6. 收尾（活文档回填）

- **实现期设计修正（重要）**：ADR-0020 初稿主张"写门截断 `context.items` 到 closed_prefix"，实现时发现它会抹掉**必须跨重启续跑的 `awaiting_approval` 稳态**（`test_p2_hitl_resume` 断言其存活）。按"全局最优"改为：**完整权威快照（含未闭合调用与审批）+ 派发侧补齐**（resume 在 provider 前 re-dispatch/settle），`closed_prefix` 仅用于识别在途集。ADR-0020 已就地修正并保留修正说明。
- 偏差回填 ADR：ADR-0020/0021/0022（本阶段新增决策）。
- 更新：ROADMAP §1(P3 ✅)/§1.5；CHANGELOG `[Unreleased]` Added — P3。
- 集成方式：P3 分支待走 PR（远端 main 强制 PR，ADR-0012 B 案）；本仓 agent 无网络，PR 由维护者在 GitHub 侧创建。

## 7. 对抗审计（`docs/audit/P3-review-2026-10-16.md`）闭合记录

逐项独立复核后的处置（接受/纠正）：
- **A1/G1（快照回退未建 + 注释谎称）→ 已修**：`rebuild_run` 现按新→旧逐一尝试快照、损坏项回退次近完好快照、**无一完好则 fail-closed 抛 `NoIntactCheckpointError`**（无快照才返回 `None`）；`store_sqlite` 头注释改为"快照权威状态、损坏回退次近完好快照"。**架构纠偏**：审计 §6-1 方案 (a)"从 `event_log` reduce 重建 Domain_State"与 **C5** 冲突（log 存的是输出事件/投影，不可反哺状态），故采用 (b) 回退完好快照 + fail-closed，未采用 (a)。测试：`test_rebuild_falls_back_to_previous_intact_checkpoint`、`test_rebuild_fail_closed_when_all_checkpoints_corrupt`。
- **B1（真 socket 测试不 hermetic）→ 已修**：httpx 客户端 `trust_env=False` + 子进程 `NO_PROXY` loopback，不再被系统代理劫成 502。
- **C-卫生（快照缺 `allow_nan=False`）→ 已修**：`_checkpoint` 序列化加 `allow_nan=False`；`test_checkpoint_snapshot_rejects_nan` 钉住。
- **E2（版本闸门无消费者）→ 已修**：`EventServer.stream`/`/events` 透传 `X-Questor-Contract-Version` 到总线；`test_http_stream_version_gate_emits_resync_then_stops` 钉住。
- **A2/E1（`recovery_pointers` 无生产者/缺 CoveredHash/未标后置）→ 已标注**：`domain_state` 明确 `NOT filled until P4/P10（压缩）`，CoveredHash 校验锚点随压缩定义。
- **A3（`pending` 列写了不读）→ 已标注**：`_checkpoint` 说明 `pending` 仅供诊断/审计，权威回退靠快照 ledger。
- **F1/F2/F3（peer-scan 路径/行号）→ 已修**：`store.py`→`core/sessions/store.py`；`transcript.py`→`core/sessions/transcript.py`；`hermes_state_schema.py:1348-1367`→`1348-1365`。
- **审计 check #6（`driver_id`/`driver_version`）→ 显式后置**：非 P3 声称项；属策略/驱动版本化（design/05 可插拔），归 **P9**。`contract_version` 已在快照 round-trip fail-closed（`snapshot.py`），store `meta` 版本闸门已建。
