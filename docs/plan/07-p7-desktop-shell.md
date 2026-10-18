# Phase 7 详细计划 — 桌面壳（Tauri）

> 起手**必读**：[`AGENTS.md §4.5/§5/§5.5/§5.6/§6`](../../AGENTS.md) · [`docs/ROADMAP.md §1/§1.5/§2/§2.5/§4`](../ROADMAP.md) · [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)（**C1–C20 全量**，本仓 `290375e` 现场数=20 条）· [`docs/pitfalls.md`](../pitfalls.md)（第 2 条"事件被节流合并"直接命中带外投影）· [`docs/STRUCTURE.md`](../STRUCTURE.md)（§3 桌面结构 / S5 进程边界 / S6 surfaces 零业务 / S7 observability 依赖方向 / §9 sidecar 三段式 + verify-release-bundle）· [`docs/plan/_TEMPLATE.md`](./_TEMPLATE.md) · [`docs/plan/05-p5-skills-mcp.md §0.4`](./05-p5-skills-mcp.md) 与 [`docs/audit/P5-review-2026-10-17.md §6`](../audit/P5-review-2026-10-17.md)（**已知缺口：sidecar 带外投影未覆盖，收口点=bus 级只读订阅**——P7 必须正面处理）· ADR [`0007`](../adr/0007-transport.md)/[`0011`](../adr/0011-seq-semantics.md)/[`0012`](../adr/0012-branch-policy.md)/[`0013`](../adr/0013-run-command-inbox.md)/[`0014`](../adr/0014-permission-context-authoritative.md)/[`0016`](../adr/0016-tool-lifecycle-approval-identity.md)/[`0019`](../adr/0019-bounded-artifact-projection.md)/[`0020`](../adr/0020-durable-write-gate-and-log-authority.md)/[`0027`](../adr/0027-observability-logging-foundation.md)（**含"复审修正"节**）/[`0028`](../adr/0028-pairing-gate-and-provider-fault-normalization.md)/[`0030`](../adr/0030-adopt-official-mcp-sdk.md)
> **§0 未填完 = 本 Phase 计划未就绪、不能开工**（ROADMAP §0 硬门槛 / AGENTS §4.5 peer-scan gate）。
>
> **性质：READ-ONLY 规划。** 本文只落这一份文档，**不改任何代码、不建分支、不 commit、不 push**。实现需用户**逐轮明确许可**（AGENTS §6：`git commit`/`git push` 每次都要 ask-and-yes）。

---

## 0. 基线确认 + Peer-Repo 扫描（硬门槛）

### 0.0 基线（2026-10-17 实测，非凭记忆）

开工前用 `git` 与文件系统核实，结果如实记录：

| 项 | 实测值 | 证据 |
|---|---|---|
| 目标仓（唯一 git 仓） | **`d:\DEVELOP\Project-main\questor`** | 其余 `questor-fix-tasklist`/`-log-foundation`/`-p5-hardening`/`-p5-skills-mcp` **均非 git 仓**（`git -C <dir> rev-parse` → `fatal: not a git repository`，无 `.git`）→ 排除出兄弟仓扫描 |
| 当前分支 | **`main`** | `git rev-parse --abbrev-ref HEAD` |
| HEAD 短 hash | **`290375e`** | `git rev-parse --short HEAD` |
| **#142 / #143 / #144 是否已合入 main** | **全部已合入** | `290375e (HEAD -> main, origin/main) Merge pull request #144 from Ember452/fix/p5-hardening`；`114fb0f Merge pull request #143 …feat/p5-skills-mcp`；`eb1da31 Merge pull request #142 …fix/p2-tasklist-oem-decode`；P5 审计提交 `29821de docs(audit): P5 adversarial acceptance review …` 在 #144 合并内 |
| 红线区间 | **C1–C20（现场数=20 条，含 C20；C6 有"折叠/合并同罪"例外款延伸）** | `docs/design/HARD-CONSTRAINTS.md:110-115`（C20 存在）、`:42`（C6 例外延伸）、末段"评审口径 C1-C20"（`:122`）；C20 明文"不禁止 P7/P10 在显式授权 + 独立通道 + 有界截断下开 preview" |
| `docs/pitfalls.md` | **存在**（可观测性分区 4 条） | `docs/pitfalls.md:1-81` |
| 事件协议单一真源 | **已存在** `protocol/event.schema.json`（20 type，含 `$defs` + `if/then`） | `protocol/event.schema.json:15-39`、`:64-238`；`protocol/README.md:1-28` |
| **文档计数不一致（P7 须校正）** | `EventType` 实为 **20**，但 `protocol/README.md:18` 写 "19"、`plan/05 §1.2` 写 "21"、P5 审计写 "20" | `src/questor/contracts/events.py:251-273`（20 个 `EventType`，`:34` 枚举）；真源以代码 + `scripts/check_protocol_schema.py --check`（`_contract_types()` 取 `EventType` 全量）为准 |
| `desktop/` | **不存在**（无任何脚手架） | `git ls-files 'desktop/*'` 空；`Get-ChildItem -Recurse -Directory -Filter desktop` 空 |
| sidecar/HTTP serve 入口 | **未接线**：`__main__.py` 仅 REPL/`--resume`/`--list`/`--dream`；`EventServer`/`create_app` 有类但无生产入口跑 uvicorn | `src/questor/__main__.py:94-146`；`surfaces/http_sse.py:58-203`；全仓 grep `uvicorn`/`--serve` 在非测试码零命中 |
| 带外投影消费者现状 | `log_envelope` **仅挂在 CLI 单消费者** | `surfaces/cli.py:264`（`_stream` 内调用）；`surfaces/http_sse.py:148-158`（`stream` 出 SSE 帧但**不投带外日志**） |

> **结论**：**本计划基线 = `main` @ `290375e`**。#142（`eb1da31`）/#143（`114fb0f`）/#144（`290375e`，内含审计 `29821de`）已合入 → **C20 / `docs/pitfalls.md` / MCP / Skills 均为当前有效基线的一部分**，P7 在其约束下规划（而非照"可能不存在 C20"的旧基线）。`protocol/event.schema.json` **已存在并已被 `check_protocol_schema.py` 守**，故 P7 不是"引入协议真源"，而是"在其上做 TS codegen + 防漂移 --check"。桌面/sidecar 全为**新面**（`desktop/` 空、无 serve 入口）。

> **GATE-0 开工重验（2026-10-17，据实更新，非凭记忆）**：开工当天现场重跑 `git`/文件系统，逐项核对上方 §0.0/§0.1 全部成立——
> - 当前分支 `main`、HEAD **`759918a`**（= `290375e` 基线之上仅多一条**文档提交**"docs(plan): add P7 …"，未动任何代码 → §0.0 代码相关结论全部沿用）；`git status` 干净、与 `origin/main` 同步；#142/#143/#144 均在 `git log` 历史内（`eb1da31`/`114fb0f`/`290375e`）。
> - §0.0 现场重列 `project-main/` 排除 `questor*`/`.ruff_cache` = **12 仓**，与 §0.1 一致，无新增参考仓。
> - 现状代码真源逐条命中：`kernel/events.py`（LIVE_ONLY `:31-33`、`EXTERNAL_EVENT_FIELDS` `:43-64`、`MESSAGE_COMPLETED={message_id}` `:48`、`TOOL_COMPLETED={tool_call_id,status}` `:51`、`NODE_UPDATED=None` `:55`、first-writer-wins `:108-111`）；`surfaces/cli.py:264` 逐消费者 `log_envelope`；`surfaces/http_sse.py:148-158` `stream()` 出 SSE **不投带外日志**（缺口坐实）；`surfaces/_assembly.assemble_logging()` 在位；`observability/projection.log_envelope()` 在位；`desktop/` 与 `surfaces/serve.py` 均**不存在**（P7 从零建）；`EventType` 真数 **20**（`protocol/README.md` 旧写 "19" 待 T3 校正）。
> - **peer-scan file:line 重验**（§0.2 承重两条）：DeepCode `sidecar.rs` 实存 **715** 行（审计复校修正：先前 `Measure-Object -Line` 少计），`generation:AtomicU64` `:112,123`、`prepare_for_start`/`SIDECAR_ALREADY_RUNNING` `:287,296`、两级关闭 `force_kill`+`fail_all("SIDECAR_STOPPED")` `:221,273-275` **全部命中**（verdict 维持"改造=搬形状、换 HTTP+SSE"）；DeepCode `threadEventStream.ts` 游标去重 `sequence<=cursor :34`/`==cursor+1 :38`/"Streamed text is not in that log" `:8` 命中；文件实为 **83** 行（原计划写的 `:47-82` 区间封顶到 ~`:77`，不影响结论，仅按思路参照）。
> - **开工当场发现的落点修正（reality-wins，先行记 ADR-0032）**：`scripts/check_layering_ast.py` 的 `FORBIDDEN_IMPORTS["surfaces"]` **明禁** `questor.providers.store_sqlite`/`store_memory_sqlite`/`subprocess`。故 T1 原述"`serve.py`（surfaces）装配 `SQLiteStore`/`SQLiteMemoryStore`"若照搬会判红。**定案**：具体 store 实例化留在**组合根 `__main__.py --serve` 分支**（与 REPL 同构、本就 import 具体适配器），`surfaces/serve.py` 只**接收注入**的 server/store + 跑 uvicorn（bind `127.0.0.1:0`、读实际端口、写 generation bootstrap），不 import 具体 store（守 S6/C4/AST 守卫）。

### 0.1 现场重列 `project-main/`（新增自动纳入，排除本仓自身）

以 `Get-ChildItem -Directory` 当下为准（2026-10-17）。**参考源 = 12 仓**；**排除** `questor`（本仓）与 `questor-fix-tasklist`/`questor-log-foundation`/`questor-p5-hardening`/`questor-p5-skills-mcp`（本仓快照目录，非独立参考源）与 `.ruff_cache`：

`hermes-agent-main · wuu-main · DeepCode-main · CowAgent-master · MetaGPT-main · cordis-main · EvoFlow-main · autogen-main · crewAI-main · OpenManus-main · GenericAgent-main · Agent-S-main`

**LICENSE 核对（本轮实读各仓 LICENSE 首行）**：

| 仓 | 许可 | 搬码边界 |
|---|---|---|
| **DeepCode** | **MIT**（`LICENSE:1-3` "MIT License / Copyright (c) 2025 …HKU"） | 复用=改造思路；**按原作者意愿，不在本仓文件内留任何来源标记/署名**（代码直接并入本仓）；**P7 前端同栈优先源** |
| **GenericAgent** | **MIT**（`LICENSE:1-3`） | 同上；桌面 tauri 壳可改造 |
| **wuu** | **MIT**（`LICENSE:1-3`） | 同上；`clients/` TS 重连/存储/桥可参照 |
| **CowAgent** | **MIT**（`LICENSE:1-3`） | 同上；Electron 前端 + `EventSource` 客户端可迁 Tauri |
| **hermes** | **MIT**（`LICENSE:1-3`） | 同上；SSE/桌面 e2e 桩与 sidecar 监管形状参照 |
| MetaGPT / cordis / crewAI / OpenManus | **MIT**（承 `plan/05 §0.1` 本轮未再触及其码） | 同上 |
| autogen | 文档 `LICENSE` = **CC-BY-4.0**（Attribution）；代码 `LICENSE-CODE` = **MIT** | 仅搬代码（MIT），搬文档/图需署名 |
| Agent-S | **Apache-2.0** | 兼容，保留 NOTICE/专利条款意识 |
| **EvoFlow** | 上游 **PolyForm Noncommercial 1.0.0**（`LICENSE:1-5` "Required Notice: Copyright 2026 景银泰 (EvovexAI) … polyformproject.org/licenses/noncommercial/1.0.0"）；**原作者已授权使用（含 `evopanel` 码）** | **可复用 `evopanel` 实现**；**原作者明确要求：不在本仓文件内留任何原项目标记/署名**（代码并入本仓，不标 provenance） |

> **所有 `file:line` 均为「扫描快照（2026-10-17），开工当天必重验」**（§0 行号 stale 是本项目 P3 审计 F 类已知教训；`plan/05 §0.1` 同样钉此纪律）。
>
> **署名口径（使用者 + 全体参考仓作者授权，2026-10-17）**：`project-main/` 下**所有参考仓作者均已同意本项目使用其代码，且不要求任何来源标记/署名**——故 P7 复用/改造参考实现时**不标 provenance、不写上游声明、CHANGELOG 不列来源**，并入后按本仓普通代码书写。`AGENTS.md §4.5/§5.6` 与 `CONTRIBUTING.md` **已于 2026-10-17 同步修订**为该口径（保留分层/端口与"优先改造非照抄"两条 guardrail），规则书与本计划一致（详见 [`ADR-0031`](../adr/0031-reference-repo-reuse-no-attribution.md)）。

### 0.2 逐能力扫描表（**每能力 ≥2 仓**）

| 能力 | 扫描仓（`repo:path:line`，扫描快照） | 结论 | 说明 · 许可/署名注意 |
|---|---|---|---|
| **① Tauri v2 壳 + Web 瘦客户端结构 + sidecar 子进程生命周期（拉起/就绪探测/端口/崩溃重启/优雅关闭）** | DeepCode `desktop/src-tauri/src/sidecar.rs:132-225`（`start()`：`generation.fetch_add` 计数、`Command::new` spawn + `Stdio::piped`、`initialize` 握手带 `STARTUP_TIMEOUT`、失败即 `mark_crashed`+`force_kill`）、`:236-239`（`restart()`=shutdown→start）、`:241-285`（**两级优雅关闭**：`shutdown` RPC `SHUTDOWN_REQUEST_TIMEOUT`=3s → 轮询 `child.try_wait()` 至 `SHUTDOWN_EXIT_GRACE`=35s → `force_kill()` → `fail_all("SIDECAR_STOPPED")` 使**在途 pending 全 fail**）、`:287-311`（`prepare_for_start`：reap 已退子进程 / 拒双起 `SIDECAR_ALREADY_RUNNING`）、`:112,123`（`generation: AtomicU64`）；`desktop/src-tauri/tauri.conf.json:31-38`（`bundle.resources` 把 onedir 产物映射为 `app-server/`）；GenericAgent `frontends/desktop/src-tauri/src/lib.rs:7,21`（Rust `std::process::{Child,Command,Stdio}` + `static BRIDGE_PROCESS: Mutex<Option<Child>>`）、`:442-467`（bundle 内嵌 `bundle_python()`：冻结解释器随包，非系统 Python）；EvoFlow `evopanel/src-tauri/src/commands/boot_cycle.rs:206-212`（`mark_sidecar_spawn(pid, port)`）、`:214-224`（`mark_sidecar_liveness(port, ok, wait_ms)` **端口就绪探测**）、`:104-115`（`apply_boot_cycle_env` 把 boot-cycle id 注入子进程 env）、`app_server.rs:217,376`（亦 stdio_rpc、无 HTTP server） | 改造 | 采 DeepCode 生命周期**形状**：`generation` 栅栏陈旧连接、两级优雅关闭、`restart`/`fail_all` 防撕裂、bundle 内嵌解释器。**关键差异（契约不兼容，只搬形状不搬传输）**：DeepCode 用 **stdio JSON-RPC** sidecar（`initialize`/`shutdown` 走 stdin/stdout），本仓铁律是 **HTTP+SSE**（ADR-0007 / STRUCTURE S5：Rust↔Python 仅 HTTP+SSE、**禁进程内直调**）→ 就绪探测从 stdin `initialize` 改为**轮询 127.0.0.1 临时端口 + 首帧 SSE**。EvoFlow `evopanel`（**原作者已授权使用**）：`mark_sidecar_liveness` 的端口存活探测正好佐证本仓 D-P7-B 的"轮询 127.0.0.1 端口"就绪判定（替代 DeepCode stdin `initialize`）；boot-cycle env 注入与本仓 run_id 注入文件名同属"跨进程显式关联"。改造/复用处不标 provenance（全体作者授权、见 §0.1 口径注） |
| **② 仅消费事件协议的 SSE 客户端（`after_seq` 重连、seq 去重、live-only delta 不入库、乱序按 `seq`/`tool_call_id` 归组、终态帧终止渲染）** | DeepCode `desktop/src/app/threadEventStream.ts:30-44`（`receive()`：`event.sequence<=cursor` 丢弃=**去重**、`==cursor+1` 连续投递、否则 `recover()`）、`:47-82`（`replayThreadHistory {after:cursor}` 从 durable log 补齐、注释 L5-9 明确 **"Streamed text is not in that log"**——live delta 不在 durable）；CowAgent `desktop/src/renderer/src/api/client.ts:323`（`new EventSource('/stream?request_id=…')` 带 token 的浏览器 SSE 客户端）、`channel/web/static/js/chat/send.js:875`（`new EventSource`）；hermes `apps/desktop/e2e/core/provider.ts:142`（真 `Content-Type: text/event-stream` 的 e2e 桩，供断线重连判据复用） | 改造 | 采 DeepCode 的 **seq 游标连续投递 + gap→recover 从 durable 重放**（与本仓 `kernel/events.py:135-165` `subscribe(after_seq)` 的"durable 先重放后跟实时、live 不做 seq 去重"完全同构）。**P7 正面处理硬缺口**：本仓 `text_delta/reasoning_delta` 属 `LIVE_ONLY`（`kernel/events.py:31-33`）永不入库，且 `message_completed` 对外仅 `{message_id}`（`kernel/events.py:48`）→ **重连后无法从 durable 恢复在途文本**（DeepCode 注释亦证此限制）。落点见 §0.3-D-P7-C。CowAgent/wuu `clients/lib/connection.ts` 的重连退避形状参照。MIT |
| **③ HITL 审批面板 + 工具卡（有界 preview + artifact 指针，绝不把远程/工具原文或凭据搬进前端）** | DeepCode `desktop/src/features/execution/ApprovalCard.tsx:64-116`（`onRespond(approvalId, decision)` **按 id 回执**、pending 外只显决策；`requestArguments` 对 args **`slice(0,4000)` + `… truncated`** L32-46）；DeepCode `desktop/src/generated/app-server.ts:562`（`ArtifactReadParams{artifactId}`）、`:738,843-863,908,1218`（`artifact/list`/`artifact/read` + `truncated: bool`）+ `desktop/src/features/workbench/useCodeWorkbench.ts:167`（`state.file.truncated` 才按需读全文）；GenericAgent `frontends/tests/test_tauri_security_contract.py:22-61`（前端安全契约：CSP `object-src 'none'`/无 `unsafe-inline`、`connect-src` 无 `*`/无远程 origin、capabilities 锁定） | 改造 | 审批：本仓 `approval_request{request_id,…}`（`contracts/events.py:55-71`，`request_id` 在 `:63`）已具 `request_id` 幂等锚，面板只经 `/approvals/{id}/resolve` 投 `ResolveApproval`（C16）；决策域仅 `allow|deny`（`protocol/event.schema.json:146` `approval_resolved.decision` enum）。工具卡：**本仓当前 `EXTERNAL_EVENT_FIELDS[TOOL_COMPLETED]={tool_call_id,status}`（`kernel/events.py:51`）无 preview/artifact_ref** → P7 需 **additive** 扩 `preview`/`artifact_ref`/`truncated`（走 §0.3 ADR + `check_protocol_schema` 保持 lockstep），复用 C18 `providers/artifact_store.py` + ADR-0019（**projection 失败绝不回退原文**）。前端安全门采 GenericAgent 的 CSP/capabilities 锁定测试形状。MCP 网络围栏使远程工具仅在有围栏下执行（`plan/05 §8.3`），面板对 DENY 展示但配对不撕裂（C19）。MIT |
| **④ Python→exe 冻结：sidecar 三段式（更窄依赖 + PyInstaller onedir + bundle.resources + verify-release-bundle）** | DeepCode `desktop/scripts/build-sidecar.py:3-7`（**onedir 非 onefile** 理由："onefile 每次启动解包到新临时目录、macOS 重校验每个嵌入库；persistent 资源目录**无需系统 Python**"）、`:24-38`（`BUNDLED_DATA`）+ `:39-45`（`REQUIRED_IMPORTS` 窄集）、`desktop/sidecar-requirements.{in,lock}`（比根依赖**更窄**的锁）；`desktop/scripts/verify-release-bundle.py:31-46`（`--verify-runtime` **导入探针**：跑冻结二进制断言 `ok`/关键模块真在）、`:49-66`（资源树断言"**恰一个** app-server 二进制"=fail-on-empty + NOTICE 齐全）+ `app_server/runtime_install.py:19`（不可变 onedir 拷贝）；EvoFlow `backend/packaging/windows/pyi_rth_evoflow_stdio.py`（Windows stdio 运行钩子，import uvicorn 前修 stdio）+ `scripts/preflight-build-check.py`（打包前缺模块门，60–90 分钟 PyInstaller+Tauri CI 前拦截）（**已获授权使用**）；CowAgent `config.py:889`（`sys._MEIPASS`，Electron+PyInstaller 桌面→可迁 Tauri 形状） | 改造 | 采 DeepCode 三段式整套：`desktop/sidecar-requirements.{in,lock}`（**dev 与打包依赖分两份锁**，比 `pyproject` 窄）→ PyInstaller **onedir**（非 onefile，正是"发布态回退系统 Python"风险的解）→ `tauri.conf.json bundle.resources` 打进包 → 发布前 `verify-release-bundle`（导入探针 + **本仓特有** initialize/shutdown RPC smoke over HTTP + 恰一个二进制 fail-on-empty）。EvoFlow 的 Win stdio 钩子/preflight（**已获授权**）可直接采其"缺模块预检 + Windows 特化"实现；不标 provenance。MIT |

> **前端同栈优先源 = DeepCode（Tauri v2 `web`+`src-tauri`）；EvoFlow `evopanel` 已获授权可复用**（上游 PolyForm NC）。GenericAgent（Tauri）、Cow/wuu/hermes（Electron 可迁 Tauri）为第二梯队参照。改造/复用后仍守"UI 只消费事件协议、零业务下沉"（AGENTS §4.5 / C14 / ADR-0007）；**复用代码不留来源标记（见 §0.1 口径注）**。

### 0.3 必须钉死的三条 P7 前置决策（落成设计，不留口号）

**D-P7-A — 带外投影收口 = bus 级只读订阅（正面处理 P5 §0.4 缺口）。**
- **现状**：`observability/projection.log_envelope` 仅在 `surfaces/cli.py:264`（CLI `_stream` 消费者）调用；HTTP sidecar 路径（`surfaces/http_sse.py:148-158`）出 SSE 帧但**不落带外日志**。证据：`plan/05 §0.4`（"HTTP sidecar 路径的带外投影暂未覆盖"）+ P5 审计 §6（"HTTP sidecar 带外投影 = UNVERIFIED"）。
- **定案**：在**组合根**（新 `--serve` 入口 / `surfaces.serve`）为 `InProcessEventBus` 挂**一条只读订阅者**，统一对**所有 surface**（CLI/HTTP/桌面）做 `Envelope→LogEntry` 投影；**同步删除 `cli._stream` 里的 `log_envelope` 调用**，改由这一处订阅覆盖。
- **为什么"一处订阅"而非"每消费者各调"**：逐消费者调 `log_envelope` 是 P5 遗留的双投影隐患——一个 run 若既有桌面 SSE 订阅者又有 CLI 打印者，同一条 Envelope 会被投两次进主干日志（违 **C6 折叠/合并同罪**、**C20 观测面第二载体**、`pitfalls.md #2`"事件被节流合并/形状错配"）。bus 级一处只读订阅从根上保证**每条 Envelope 恰投一份**，与 surface 数量无关。
- **不破坏协议**：只读旁路，**不新增事件 type、不改关联键/终止序**（`check_protocol_schema --check` 零 diff）。
- **判据（§4）**：给定 sidecar 路径跑真 run，按 `run_id` 从主干 `questor-<date>.jsonl` 能定位事件类带外行；同 run 用 CLI 路径跑，带外行**恰一份**（多挂一个 surface 订阅者不增份）——把 `log_envelope` 重新塞回逐消费者 → 用例红。

**D-P7-B — sidecar 传输与就绪探测：HTTP+SSE，禁进程内直调，generation 栅栏。**
- Rust 壳把 Python harness 作为**独立 sidecar 进程**，二者**仅经 HTTP+SSE 事件协议**通信（ADR-0007 / STRUCTURE S5），**严禁 Rust 进程内直调 Python** 或引入私有 Tauri event 协议。
- **端口**：OS 分配的 `127.0.0.1` 临时口（`uvicorn` bind `127.0.0.1:0` 后读实际端口），经 Rust 注入 URL / bootstrap 文件交 webview；**绝不 bind `0.0.0.0`**（本地 IPC，无网络出口；呼应 C12"日志/内核不上网"精神在桌面侧的延伸）。
- **就绪探测**：Rust 侧轮询该端口的健康/首帧 SSE 作为 ready（替代 DeepCode 的 stdin `initialize`），超时即 `mark_crashed`+kill+restart。
- **generation 防陈旧连接**：沿用 DeepCode `sidecar.rs:112,134` 的 `generation` 计数——每次 restart 自增，旧 SSE 流/旧 RPC 回执带旧 generation 一律栅栏丢弃，防"重启后陈旧连接写新 run"。

**D-P7-C — 重连文本恢复（live-only delta 不可重放的正面处理）。**
- **事实**：`text_delta`/`reasoning_delta` 属 `LIVE_ONLY`（`kernel/events.py:31-33`），只转发不入库；`subscribe(after_seq)` 仅重放 durable（`kernel/events.py:147-153`）。当前 durable 对外表示（`message_completed`→`{message_id}`、`run_completed`→`{usage,exit_reason}`）**不含文本**（`kernel/events.py:48,60`）。故**断线重连会丢在途未收尾的可见文本**，且 DeepCode 注释亦证实"streamed text 不在 durable log"。
- **定案（二选一，均走 ADR，开工前定）**：① 对 `message_completed`/`run_completed` **additive** 加有界 `final_text`（或 `item_id` 归属），令重连可从 durable 帧恢复该消息文本；或 ② 新增**只读** `GET /runs/{id}/transcript`（从 `event_log`/checkpoint 重建，属 surfaces 转发、不改 state、不违 S6）。选①须守 C18 有界 + C13（派生态不回写成第二真相）；选②须守只读、不进 reduce。
- **未定案前**：重连"在途文本恢复"端到端标 **UNVERIFIED**（诚实边界），DoD②只保证 **durable 事件不丢不重**，delta 尽力而为。
- **✅ 开工定案（2026-10-17，GATE-1 / ADR-0034）= 选型①**（用户取向：面向超大型多端项目、长远最优、不计工作量）：`state/reduce.py:107` 发 `MESSAGE_COMPLETED` 时把定稿正文写入 durable 事件帧（additive 有界 `final_text` + `item_id`，超限 `truncated`+`artifact_ref`，复用 ADR-0019 工具卡纪律），令 `after_seq` 重放对**所有 surface/客户端**自足恢复定稿文本；**不另开 `GET /transcript` 第二读契约**（守 C15 单一真源）。`message_completed` 仅在定稿边界产生，**未定稿的半条在途 delta 仍补不回→标 UNVERIFIED**。落点：`contracts/events.py:48` + `protocol/event.schema.json` `$defs.message_completed` + `--self-test` fixture 三处 lockstep；`final_text` **不进 `projection._DATA_KEYS`**（C20）。

### 0.4 已知观测缺口（承 `plan/05 §0.4`，P7 收口）

- P5 明记："`log_envelope` 在 `cli._stream` 消费点调用，未改为 bus 级订阅……HTTP sidecar 路径的带外投影暂未覆盖"，并把收口点写死为 **bus 级只读订阅**、挂到"刀 3 / P7 桌面调试真需求触发"。**本 P7 即以 D-P7-A 收口该缺口**，不再顺延。
- **不受此缺口影响的面**：MCP server stderr 独立文件（`mcp-stderr-<run_id>.log`，D-16.4-A/B）由 spawn 侧直接落盘、文件名带 `run_id`，仍是 sidecar 场景最可靠的 MCP 排障面——P7 不改它，只补事件带外行。

### 0.5 既有约定/接缝的沿用（不得重造）

- **命名**：远程工具 `mcp_<server>_<tool>`、suffix 权限匹配（`plan/05 §0.5`，`capabilities/mcp/README.md`）——桌面只是展示层，不改命名。
- **传输面**：`surfaces/http_sse.py` 已实现 `/run`·`/cancel`·`/approvals/{request_id}/resolve`·`/permissions`·`/resume`·`/events/{run_id}`（`http_sse.py:161-202`），命令一律经 `RunRegistry.submit(..., source, idempotency_key)` 进 **Command Inbox**（C16，`run_control.py:52-81`）。桌面**复用这些端点**，不新造写入口。
- **投影白名单**：`kernel/events.py:43-64` `EXTERNAL_EVENT_FIELDS` 是外部载荷唯一门；additive 扩字段须同时进 `protocol/event.schema.json` 的 `$defs`（`check_protocol_schema` 要求 enum/`$defs`/branch 三处 lockstep）。
- **subagent/DAG 属 P8、并行属专门并行化 Phase（ADR-0029）**：P7 不触碰。

---

## 1. 目标与可验证判据（DoD）

**目标（ROADMAP §1 P7 行）**：Web UI 订阅事件协议——把桌面（Tauri 壳 + Web 瘦客户端 + Python sidecar）立起来，作为 v1（P0-P4+P7，ROADMAP §2）对外 Release 的门面（§4 节点 C）。

### 1.1 进入条件

- **依赖 P1（可早接，ROADMAP §1）**：主干 P1→P2→P3 必经已完成；P4 记忆、P5 Skills/MCP 已合入 main（`290375e`）。因 P5 已在基线内，**能力面按 P1–P5 验证**（ROADMAP §1 原写"P1-P4"属旧口径，§6 更新 §1.5 备注时说明现实）。
- **协议真源已在位**：`protocol/event.schema.json` + `check_protocol_schema` 守卫已具备（§0.0），P7 直接在其上加 codegen，无需引入 schema 本身。
- **带外投影缺口收口**：以 D-P7-A 落地（不再挂账）。

### 1.2 DoD（写成可复现行为，不是"完成感"；靠 mock 得出的一律标 UNVERIFIED）

- **① 桌面窗口跑通 P1–P5 全部能力**（脚本化 provider 驱动、真 HTTP+SSE）：问答流式（`text_delta` 上屏）；取消（`/cancel`→`run_cancelled`、pending tool 回填闭合，C7）；危险操作 ask→面板 allow/deny（`approval_request`/`ResolveApproval`，非交互/断连 fail-closed deny，C16/C17）；记忆检索（`memory_search` 工具结果 + `memory_written` 有界回执上屏，不显原文）；Skills 生效（`QUESTOR_SKILLS_DIR` 丢合法 `SKILL.md` → 注入 system prompt，transcript 可观察行为变化）；MCP 工具列出与调用（`mcp_<server>_<tool>` 工具卡出现 + 结果；无网络围栏时展示 DENY 但配对不撕裂，C17/C19）。
- **② 断网/SSE 断开 → `after_seq` 重连不丢不重**：durable 事件按 `seq` 游标**恰重放一次**（无 dup、无 gap）、终态帧终止渲染；真 `uvicorn`+`httpx` 跑，非 mock（在途 live delta 恢复按 D-P7-C，未定案部分标 UNVERIFIED）。
- **③ sidecar 崩溃可检测并重启、pending 全 fail 不撕裂状态**：真 kill sidecar 进程树 → Rust 侧 reader EOF/exit 检测 → `generation++` → restart → 经 `/resume`+`after_seq` 重挂 SSE；崩溃时在途 run 由 C7 回填 + C19 配对关卡 + ADR-0021 re-dispatch-before-provider 保证不留悬空 `tool_use`；generation 栅栏使陈旧连接的写不得污染新 run。
- **④ 瘦客户端零业务下沉**：`desktop/web`/`src-tauri` 只"收 Command + 投事件"，**绝不在 Rust/JS 里算状态/权限/校验/折叠事件**（S5/S6/C14/C17）；由机器守卫兑现（§4），非口头。
- **⑤ sidecar 带外投影以 bus 级只读订阅收口**（D-P7-A）：桌面/sidecar 路径的事件类带外行进主干日志、带 `run_id`；**协议 schema 零 diff**。

---
## 2. 子任务清单

> 每条：**目标 · 涉及层 · 依赖 · 验证方式 · commit 粒度**。commit/push 均需用户逐轮明确许可（AGENTS §6）。落点守分层（C1/C14/S5/S6）：桌面=L7 `desktop/`，sidecar 传输面=L6 `surfaces/`，additive 契约=L0 `contracts/`+`protocol/`；kernel 不 import 桌面/sidecar 具体实现。

- [ ] **T0 · 前置 ADR 门（触及分层/契约先记 ADR，AGENTS §5.5 / ROADMAP §5）**：目标=动代码前把本 Phase 的架构级决策落 ADR——① sidecar HTTP+SSE serve 接线（新 L6 面 + 进程边界，可能补 ADR-0007 落地细节）；② 工具事件 additive `preview`/`artifact_ref`/`truncated`（改 `contracts`/`protocol` 事件形状，D-P7-C 与工具卡）；③ D-P7-C 重连文本恢复选型①/②其一；④ 桌面/sidecar 分层守卫扩面。涉及层=L0 docs/adr。依赖=§0.3 定案。验证=每条改 `contracts`/分层/事件形状的子任务开工前对应 ADR 已到位（§3 前置门）。commit=`docs(adr): P7 sidecar/protocol/observability decisions (ADR-before-code)`。**门槛**：ADR 未到位 → T1/T2/T7/T11 不得开工。
- [ ] **T1 · sidecar serve 入口（D-P7-B）**：目标=新增生产入口把 `EventServer` 挂上 uvicorn：调 `surfaces._assembly.assemble_logging()`（**不自配、共用组合根唯一装配口径**，`__main__.py:94-98` 同构）→ 装配 `SQLiteStore`/`SQLiteMemoryStore` + `CliSurface` + `EventServer` → `uvicorn` bind `127.0.0.1:0` → 读实际端口 + 生成 `generation` 并写 bootstrap（供 Rust 注入 webview）。涉及层=L6 `surfaces/serve.py`（新）+ 组合根 `__main__.py`（加 `--serve`）。依赖=无（P1–P5 端点已在位）。验证=headless 起进程：`GET /`/健康端点通、`POST /run` + `GET /events/{run_id}` 收 `text_delta`→终态帧；冷导入 `import questor.surfaces.serve`。改造自 DeepCode `tauri.conf.json:6-11`（beforeBuildCommand 拉 sidecar）+ GenericAgent `lib.rs:442-467`（bundle 内嵌解释器）。commit=`feat(surfaces): add HTTP+SSE sidecar serve entry (loopback, ephemeral port, generation bootstrap)`。
- [ ] **T2 · bus 级只读带外投影（D-P7-A，收口 P5 §0.4）**：目标=在 serve 入口/组合根为 `InProcessEventBus` 挂**一条只读订阅者**做 `log_envelope`，覆盖所有 surface；**删除 `surfaces/cli.py:264` 的逐消费者 `log_envelope`**。涉及层=L2 `kernel/events.py`（订阅面）+ L6 surfaces + L1 `observability/projection.py`（复用，不改九内核文件）。依赖=T1。验证=§4「单投判据」：sidecar run 事件类带外行带 `run_id` 落主干；CLI run 恰一份（多挂订阅者不增份）；把 `log_envelope` 塞回逐消费者 → 用例红。commit=`fix(observability): project events out-of-band via a single bus-level subscriber (sidecar coverage; closes plan/05 §0.4 gap)`。
- [ ] **T3 · 协议 codegen TS + CI `--check` 防漂移（C15）**：目标=由 `protocol/event.schema.json` 生成 TS 事件类型到 `desktop/web/src/generated/event.ts`（`json-schema-to-typescript`），加 `check:protocol` 脚本——`--check` 比对已生成文件与 schema 输出、不一致退出码非零；顺带校正 `protocol/README.md:18` stale 的 "19"→20（真源=代码）。涉及层=构建/CI + `desktop/web`。依赖=无（schema 已在位）。改造自 DeepCode `desktop/scripts/generate-protocol.mjs:1-27`（`compileFromFile`+`--check` staleness）。验证=`--check` 在改 schema 未 regen 时判红；`--self-test`/fixture 证其能判红判绿；codegen 产物 banner "AUTO-GENERATED … DO NOT EDIT"。commit=`feat(protocol): generate TS event types from event.schema.json with drift --check`。
- [ ] **T4 · SSE 瘦客户端**：目标=`desktop/web` 消费事件协议——`after_seq`/`Last-Event-ID` 重连、`seq` 去重、live `text_delta`/`reasoning_delta` 按 `item_id` upsert 缓冲、乱序按 `seq`/`tool_call_id` 归组、**终态帧（`run_cancelled`/`run_failed`/`run_completed`）终止渲染并停流**；未知 type 静默忽略**除错误类**（`run_failed`/`warning`/`resync_required` 必出声，`protocol/README.md:10-13`）。涉及层=L7 `desktop/web`（纯前端）。依赖=T3。改造自 DeepCode `threadEventStream.ts:30-82` + CowAgent `client.ts:323`。验证=§4「真 uvicorn+httpx 断线重连」+ 版本闸门收 `resync_required` 即停。commit=`feat(desktop/web): SSE client consuming event protocol with after_seq reconnect`。
- [ ] **T5 · 命令提交经 Command Inbox（C16，禁 surfaces 直接 reduce/改 state）**：目标=桌面**只**经 HTTP 端点投 Command：`POST /run`·`/runs/{id}/cancel`·`/runs/{id}/approvals/{request_id}/resolve`·`/runs/{id}/permissions`·`/runs/{id}/resume`（`http_sse.py:161-202`，`source="desktop"`）；**绝不在 Rust/JS 造第二写入口、绝不直连 store/reduce**。涉及层=L7 web + L6 surfaces。依赖=T1/T4。验证=契约测试覆盖重复/终态后提交/队满 receipt（`run_control.py:59-81`、`contracts/inbox.py`）在 UI 正确呈现；`check_layering_ast` 证 surfaces 未 import `state.reduce`/store 实现（`check_layering_ast.py:54-59`）。commit=`feat(desktop/web): drive run via Command Inbox endpoints only`。
- [ ] **T6 · HITL 审批面板**：目标=`approval_request`→面板，用户决策投 `ResolveApproval(decision=allow|deny)`，**带 `request_id` 幂等**（同 request 同决策 no-op、异决策被拒、resolved/expired/cancelled 不翻案，ADR-0016/`contracts/events.py:74-92`）；**非交互/断连 fail-closed deny**（对齐 `cli.py:_approve` 的 `interactive=False→deny`）。涉及层=L7 web + L6。依赖=T4/T5。改造自 DeepCode `ApprovalCard.tsx:64-116`（按 id 回执 + args `slice(0,4000)` 有界）。验证=request_id 幂等 e2e；迟到/过期 resolve no-op；SSE 断开期间审批 → deny 闭合。commit=`feat(desktop/web): HITL approval panel (request_id idempotent, fail-closed)`。
- [ ] **T7 · 工具卡展示（有界 preview + artifact 指针，C18/C20）**：目标=工具卡显示有界 `preview` + `artifact_ref` 指针 + `status`，**全文经 artifact 指针按需读**（不整块塞事件流）；**远程/工具原文与凭据绝不进前端与观测面**。涉及层=L7 web + L0 `contracts`/`protocol`（additive：`tool_completed` 现 `{tool_call_id,status}` 缺 preview/artifact_ref，`kernel/events.py:51`）+ L6（可选只读 `GET /artifacts/{id}`）。依赖=T0（ADR）/T4。改造自 DeepCode `app-server.ts:562,738,843-863`（`artifact/read`+`truncated`）+ `useCodeWorkbench.ts:167`（truncated 才读全文）；复用本仓 C18 `providers/artifact_store.py` + `surfaces/_output.py` envelope + ADR-0019。验证=`check_protocol_schema --check` additive 后三处 lockstep + 零破坏；preview 有界断言；artifact 写失败→error + 有界 preview（绝不回退原文）；MCP/内置工具结果不入日志第二份（C20 + `check_projection_whitelist`）。commit=`feat(desktop/web): tool cards with bounded preview + artifact pointer`。
- [ ] **T8 · sidecar 三段式构建 + verify-release-bundle + generation + 两级优雅关闭**：目标=`desktop/sidecar-requirements.{in,lock}`（比 `pyproject` **更窄**）→ PyInstaller **onedir（非 onefile）**冻结 sidecar → `tauri.conf.json bundle.resources` 打进包 → Rust supervisor（采纳 DeepCode 形状：`generation` 栅栏、`start`/`restart`、两级优雅关闭 `shutdown` 请求→grace 轮询→`force_kill`、崩溃 `fail_all` 使 pending 全 fail）→ 发布前 `scripts/verify-release-bundle.py`（**导入探针** + **initialize/shutdown RPC smoke over HTTP** + **恰一个** sidecar 二进制 fail-on-empty + 无系统 Python 回退）。涉及层=L7 `desktop/src-tauri` + 构建脚本。依赖=T1。改造自 DeepCode `sidecar.rs:132-311` + `build-sidecar.py:3-45` + `verify-release-bundle.py:31-66`；Win stdio 钩子/preflight 复用 EvoFlow（**已获授权**）。验证=`verify-release-bundle` 在"回退系统 Python / 0 或 >1 二进制"时判红；真 kill 进程树崩溃重启集成（Windows Job Object，防孤儿）；两级 shutdown 超时后 `force_kill` 生效。commit=`feat(desktop): sidecar three-stage build + supervisor (generation, two-phase shutdown, fail-all) + verify-release-bundle`。
- [ ] **T9 · 分层守卫扩到 desktop/sidecar 新面（C14/C15，守卫必须可信）**：目标=① `.importlinter` 增契约：`serve` 归 L6、桌面/sidecar 不得被 kernel import；② `check_layering_ast` 纳入 `surfaces.serve`（继续禁 surfaces import `state.reduce`/store 实现）；③ **新守卫「瘦客户端禁业务」**：静态扫 `desktop/web/src` 不得含 reduce/权限求值/事件折叠等业务 token、事件类型仅可 `import` 自 `generated/`（codegen 产物）；④ **CSP/capabilities 锁定测试**（仿 GenericAgent `test_tauri_security_contract.py:22-61`：无 `unsafe-inline`、`connect-src` 无 `*`/远程 origin）；⑤ 全部带 `--self-test` 判红 + **fail-on-empty**（扫不到文件≠通过，`check_layering_ast.py:181-183`）+ 作为**不依赖 change-classifier 的独立 blocking CI job**（`boundaries`，C15/ADR-0012）。涉及层=构建/CI + `scripts/`。依赖=T1–T4。验证=`--self-test` 能判红；空扫描 fail-on-empty；独立 job 不被语言 lane 门控。commit=`test(guards): extend layering/thin-client/protocol-drift guards to desktop + sidecar (self-test + fail-on-empty)`。
- [ ] **T10 · S7 内核零依赖不破**：目标=T2 的 bus 级投影订阅者落 `surfaces`/组合根，**不改 observability 九个内核文件**（`entry`/`scope`/`redact`/`exporter`/`sink_*`/`bridge`/`pipeline`/`configure` 零 `questor.*` 依赖，`.importlinter:62-83`），`projection.py` 仍是唯一 `import contracts` 的适配层。涉及层=L1 observability / L6 surfaces。依赖=T2。验证=`scripts/check_log_kernel_isolation.py --self-test`（G-L1/G-L2）绿且能判红；冷导入内核文件不拉 `questor.*`。commit=`chore(observability): keep log-kernel zero-dependency while adding bus-level projection subscriber`。
- [ ] **T11 · 补实 P0–P5 draft 契约占位（R2，避免破坏性变更）**：目标=`node_updated` 现 `data=None`（透传、未定形，`kernel/events.py:55`、`protocol/event.schema.json:161-164`）→ **additive** 定形其 `$defs`；确保不破任何已发布 `type`/关联键（`CORRELATION_KEYS` `run_id/turn/tool_call_id/card_id/item_id`，`contracts/events.py:23-25`）/终止序。涉及层=L0 contracts/protocol（审慎，C6/C11）。依赖=T0。验证=`check_protocol_schema --check` 三处 lockstep + 零破坏；`--self-test` fixtures 覆盖新形。commit=`feat(contracts): finalize draft event-data placeholders additively (protocol zero breaking)`。
- [ ] **T12 · 桌面端到端能力脚本化 provider 驱动（DoD① 复现）**：目标=`EchoProvider`/脚本化 fake provider + tmp `QUESTOR_SKILLS_DIR` + 复用 `tests/support/mcp_demo_server.py`（真 stdio 假 server），经**真 HTTP+SSE**驱动桌面客户端跑穿 P1–P5 能力（问答/取消/ask-deny/记忆/Skills/MCP），断言在 reducer/store 侧（非像素级）。涉及层=L7 tests + L6/L2。依赖=T1–T7。验证=能力矩阵逐条绿；**真 LLM / 真远程 MCP server / 真打包桌面**端到端标 **UNVERIFIED**（诚实边界，不用 fake 冒充真机）。commit=`test(desktop): scripted-provider end-to-end across P1-P5 capabilities over real HTTP+SSE`。

> **尾注**：并行工具执行属专门并行化 Phase（ADR-0029，承 `plan/05 §2.0`），P7 不引入；子 agent/DAG 属 P8；OpenAI 兼容/插件宿主属 P9。P7 只做"极简调试面板 + 仅消费事件协议"（ROADMAP §1.5）。

---

## 3. 契约与红线自检

- **触及分层/契约？☑ 是（先记 ADR 再动，T0）** —— 新增 sidecar serve L6 面与进程边界（D-P7-B）、工具事件 additive 字段 + 可选只读 artifact/transcript 端点（改 `contracts`/`protocol` 事件形状，T7/T11）、bus 级投影 seam（L2/L6/L1，T2）、协议 codegen（构建）、新 L7 桌面层、分层守卫扩面 → **前置 ADR**（§6 硬门槛）。纯前端展示/消费端点若不动 `contracts`/分层/事件形状则免 ADR。
- **逐条对照 C1–C20（现场数=20，全量非重点）**：

| 红线 | P7 勾对结论 |
|---|---|
| **C1** 分层依赖方向 | 桌面=L7、serve=L6、additive 契约=L0；kernel 不 import 桌面/sidecar 实现（`.importlinter`/`check_layering_ast`）。✅ |
| **C2** 单写者+不可变视图 | 桌面只投 Command（`ResolveApproval`/`Cancel`/`SetPermissionMode`）；绝不改 Domain_State；派生态不回写。✅ |
| **C3** 视图 vs 快照 | 桌面不改快照策略；`--resume`/rebuild 复用 P3 既有。✅ |
| **C4** Store 读写过接口 | 桌面经 serve→`EventServer` 持 `StorePort` 抽象（`http_sse.py:61-67`），无裸句柄。✅ |
| **C5** Command/Event 分离 | 输入=Command 经 inbox；输出=Event 投影；**事件绝不反哺状态**；**协议 schema 零 diff**（additive only）。✅ |
| **C6** 事件内外分层+版本（含折叠/合并同罪 `:42`） | bus 级只读订阅**每条恰投一份**、不多消费者各投（D-P7-A）；错误类事件桌面必出声（`protocol/README.md:10-13`）；带外投影不折叠/合并（`pitfalls.md #2`）。✅ |
| **C7** 终止权在 Harness | 取消经 `/cancel`→`Cancel`→reduce 回填 pending tool（`cli.py`/`http_sse.py:113-122`），非 out-of-band 硬杀 sidecar 内 run；sidecar 进程级 kill 是**跨进程 teardown**、run 态由 reduce 收尾。✅ |
| **C8** 工具执行边界 | 参数校验/权限/沙箱/超时全在 Harness；桌面零校验下沉。✅ |
| **C9** 权限三态+沙箱可插拔 | 审批面板 allow/ask/deny；`approval_mode` 只收紧不放宽、unknown→deny。✅ |
| **C10** 插件生命周期+故障隔离 | sidecar 崩溃→Rust `fail_all`+restart（DoD③）；先推部分事件后回滚/错误事件桌面不得误解为"抹掉已推事件"（C10 评审补 `:61`）。✅ |
| **C11** 状态模型谨慎演进 | additive 定 `node_updated`/preview 字段；不破接缝；破坏性才 bump `v`。✅ |
| **C12** 远程策略预留非现在 | 桌面=本地 loopback IPC（`127.0.0.1`），**无网络 exporter**；不把一切序列化。✅ |
| **C13** `event_log` 唯一真相+终态唯一 | 前端展示的是投影，**派生态不回写成协议字段**；一 run 恰一终态（`kernel/events.py:108-111` first-writer-wins）。✅ |
| **C14** 结构边界机器守（S1–S7） | 新面（serve/桌面/带外订阅）均有 `.importlinter` + `check_layering_ast` + 瘦客户端/协议守卫（T9）。✅ |
| **C15** 外部契约单一真源+守卫可信 | `protocol/event.schema.json` 单一真源 → codegen TS → CI `--check` 防 Python↔Rust↔TS 三处漂移；每条守卫带 `--self-test`+fail-on-empty+独立 blocking job（T3/T9）。✅ |
| **C16** Command Inbox 唯一外部写入口 | 桌面经端点投 Command；surfaces 禁直 `reduce`/store/权限引擎（`check_layering_ast.py:54-59`）。✅ |
| **C17** PermissionCtx/capability floor 优先于 mode | 权限全在 Harness，**前端零业务下沉**；MCP `NETWORK` 无 `fences_network`→fail-closed DENY 不因 `full_auto` 放宽（`plan/05 §8.3`）；凭据/远程原文不进前端。✅ |
| **C18** ToolCall 生命周期+输出有界 | `tool_started` 唯一由 `MarkToolRunning` 产生（`contracts/events.py:104-113`）；审批带 `request_id` 幂等；工具/远程输出**有界 preview + artifact ref**（T7），禁旁路直抄。✅ |
| **C19** 回发前配对关卡+provider 故障不崩宿主 | sidecar 崩溃/重启时在途 `tool_use` 经回填 error/timed_out 闭合、不破唯一 provider 调用点关卡（`plan/05` T4/T5 机理，`kernel/loop.py`）；BaseException 继续上抛。✅ |
| **C20** 观测面不得成为载荷第二载体 | bus 级带外投影只读旁路（`projection.py` 白名单键，`scripts/check_projection_whitelist.py` 守）；桌面工具卡 preview/artifact **不进日志第二份**；远程/凭据不入观测面；MCP stderr 独立文件不变。✅ |

- **进程边界 S5**：Rust↔Python **仅 HTTP+SSE**（`127.0.0.1`），**严禁进程内直调 Python**、禁私有 Tauri event 协议（ADR-0007）。
- **surfaces 零业务 S6**：serve/桌面只"收 Command + 投事件"，业务/状态/校验不下沉（`http_sse.py:1-9` 既有纪律，T9 机器守）。
- **observability 方向 S7**：`kernel → observability` 允许、反向禁止、九内核文件零 `questor.*` 依赖（T10 不破）；带外投影订阅者属适配/组合根旁路。
- **事件协议自检**：只增字段（additive）？是。不破信封/关联键/终止序？是（C5/C13/C11）。additive 扩字段须 `check_protocol_schema` enum/`$defs`/branch 三处 lockstep。

---
## 4. 测试与回归（**§2 每条子任务都有对应判红用例**）

> TDD：先写判红用例再实现（AGENTS §6 / §4）。前端**不重复测内核逻辑**，只测**瘦客户端契约消费**。任何"已覆盖"若靠 mock 得出 → 标 **UNVERIFIED**。

### 4.1 守卫族（全部要求 `--self-test` 能判红 + fail-on-empty，作独立 blocking `boundaries` job）
- `lint-imports`（`.importlinter` 新契约 kept，含 serve 归 L6、桌面/sidecar 不被 kernel import）——T9/T10。
- `check_layering_ast --self-test`（含 `surfaces.serve`；surfaces 禁 import `state.reduce`/store 实现；空扫描 `scanned==0` 判红，`check_layering_ast.py:181-183`）——T9。
- `check_protocol_schema --check`（**additive 后** enum/`$defs`/branch 三处 lockstep、零破坏）+ `--self-test`（拒 over-field/missing-required/oversized）——T3/T7/T11。
- **新 codegen `--check`**（TS↔schema 新鲜度）：改 `event.schema.json` 不 regen → 退出码非零；`--self-test`/fixture 证其能判红——T3。
- **新瘦客户端守卫 `--self-test`**：`desktop/web/src` 含业务 token（reduce/权限/事件折叠）或直接 import 非 `generated/` 事件类型 → 判红；干净样板 → 绿——T9/T4。
- **CSP/capabilities 锁定测试**（仿 GenericAgent `test_tauri_security_contract.py:22-61`）：`unsafe-inline`/`connect-src *`/远程 origin 出现即判红——T9。
- `check_log_kernel_isolation --self-test`（G-L1/G-L2：九内核文件零 `questor.*`，S7 不破）——T10。
- 冷导入 `uv run python -c "import questor.surfaces.serve"`；`ruff check .` clean。

### 4.2 sidecar 构建与生命周期
- **`verify-release-bundle`**（T8）：**导入探针**（跑冻结 sidecar 断言关键模块真在）+ **initialize/shutdown RPC smoke over HTTP** + **恰一个** sidecar 二进制（0 或 >1 判红，fail-on-empty）+ 断言**无系统 Python 回退**（仿 DeepCode `verify-release-bundle.py:31-66`）。**判红**：删 sidecar 目录/塞两个二进制/探针导入失败 → 红。
- **崩溃重启集成**（T8，DoD③）：真起 sidecar → 真 kill **进程树**（Windows Job Object）→ Rust reader 检测 → `generation++` → restart → `/resume`+`after_seq` 重挂；断言在途 pending 经 `fail_all` 全 fail、run 由 reduce 闭合不留悬空。**判红**：陈旧 generation 连接试图写新 run → 被栅栏丢弃。**真机不可复现（无桌面 CI）标 UNVERIFIED**。

### 4.3 SSE 断线重连（**真 HTTP+SSE，非 mock**）
- 真 `uvicorn` 起 serve + 真 `httpx` 客户端（承 P3 `feat/p3-persistence-resume` 实测形状）：跑到中途断开 → 带 `after_seq`/`Last-Event-ID` 重连 → 断言 **durable 事件恰重放一次**（无 dup、无 gap）、终态帧停流（T4，DoD②）。
- **带外投影单投判据**（T2）：sidecar 路径跑真 run，按 `run_id` 从主干 `questor-<date>.jsonl` 定位事件类带外行；再挂一个 surface 订阅者 → 带外行**不增份**；把 `log_envelope` 塞回逐消费者 → 红。**真进程 grep canary**（不测 `LogEntry` 构造，`pitfalls.md #1` 纪律③）。
- 版本闸门：客户端 `x-questor-contract-version` 不匹配 → 只收一条 `resync_required` 即停（`http_sse.py:198-200`、`kernel/events.py:139-142`）。
- 在途 live delta 恢复（D-P7-C）：定案前标 **UNVERIFIED**；定案①/②后补对应判据。

### 4.4 HITL / 工具卡 / 命令入口
- 审批 `request_id` 幂等 e2e（T6）：同 request 同决策 no-op、异决策拒、resolved/expired 不翻案；SSE 断开期间审批 → fail-closed deny 闭合（`contracts/events.py:74-92`）。
- 命令入口 receipt（T5）：重复/终态后提交/队满 → receipt 正确呈现（`run_control.py:59-81`、`contracts/inbox.py`）。
- 工具卡有界（T7）：preview 有界断言；`artifact_ref` 指针；artifact 写失败→error + 有界 preview（**绝不回退原文**，ADR-0019）；远程/工具原文与凭据不入事件全载荷/日志（C18/C20 + `check_projection_whitelist`）。

### 4.5 端到端能力矩阵（T12，脚本化 provider）
- 问答流式 / 取消 / ask-deny / 记忆检索（`memory_written` 无原文） / Skills 生效（tmp 目录） / MCP 列出与调用（复用 `tests/support/mcp_demo_server.py` 真 stdio 假 server）经真 HTTP+SSE 逐条绿；**真 LLM / 真远程 MCP / 真打包桌面 = UNVERIFIED**。

### 4.6 流程与安全门
- 细粒度英文 Conventional Commits（AGENTS §6）；每次 commit/push **逐轮**用户明确许可；**push/开 PR 前先走 L3 深度安全评审**——重点：桌面/sidecar 新面、凭据/远程输出不入前端与观测面、发布供应链（PyInstaller/bundle 依赖窄锁）。

> **自检矩阵（T→判红用例）**：T0→ADR 到位门（动 `contracts`/分层前 ADR 必存在，§3 前置门）；T1→headless serve + 冷导入；T2→带外投影单投 canary（多订阅者不增份）；T3→codegen `--check` 改 schema 未 regen 判红；T4→真 uvicorn+httpx 断线重连不丢不重 + `resync_required` 停；T5→surfaces 禁 reduce/store 守卫 + receipt 契约；T6→审批 `request_id` 幂等 + 断开 fail-closed deny；T7→工具卡 preview 有界/artifact 指针/不回退原文/不入日志第二份；T8→`verify-release-bundle`（探针+恰一个+无系统 py）+ 真 kill 崩溃重启；T9→守卫族 `--self-test` 判红 + fail-on-empty + 独立 job；T10→`check_log_kernel_isolation --self-test`（S7 不破）；T11→`check_protocol_schema --check` additive 零破坏；T12→P1–P5 能力矩阵逐条。**每条均有判红用例**。

---

## 5. 落地风险 & 备选

| 风险 | 触发条件 | 缓解 | 备选 |
|---|---|---|---|
| **业务/校验偷偷下沉到壳**（破 S6/C17） | 图省事在 Rust/JS 里算状态/权限/折叠事件 | T9 瘦客户端守卫（禁业务 token + 仅 import `generated/`）+ 独立 blocking job；前端只投 Command（T5） | 靠人 review 每个 UI PR → 否（不可扩展、无机制） |
| **sidecar 生命周期竞态/孤儿进程** | 崩溃/关闭留悬挂子进程、双起、重启竞态 | T8 Rust supervisor 采纳 DeepCode `sidecar.rs`：`prepare_for_start` reap-or-refuse 双起、**Windows Job Object 杀进程树**、`generation` 栅栏、两级优雅关闭 `force_kill` 兜底 | 裸 `child.kill()` 单进程 → 否（Windows 子进程树残留） |
| **协议漂移（Python↔Rust↔TS 三处各写）** | TS/Rust 手抄事件形状、悄悄分叉 | T3 单一 `event.schema.json` → codegen TS + `--check` 防漂移 + `check_protocol_schema` 三处 lockstep | 各端各写类型 → 否（C6"只增不改"三处各守必崩，C15 明禁） |
| **带外投影双重订阅**（破 C6 折叠/合并同罪、C20 第二载体） | bus 级订阅已加、`cli._stream` 的 `log_envelope` 忘删 | T2 明确**删**逐消费者调用 + §4.3 单投 canary（多挂订阅者不增份） | 保留双调用靠去重 → 否（`pitfalls.md #2`：签名看不见区分信息） |
| **发布态回退系统 Python** | sidecar 冻结不完整、跑起来用宿主 py | T8 PyInstaller **onedir 非 onefile**（DeepCode `build-sidecar.py:3-7`）+ `verify-release-bundle` 导入探针断言自包含 | onefile / 依赖宿主 venv → 否（每次解包重校验 + 破坏"无系统 Python"） |
| **断线重连丢帧/重帧** | `after_seq` 游标处理错、慢消费者背压丢帧 | T4 seq 连续投递 + gap→durable 重放；背压丢帧出声可 resync（`kernel/events.py:129-130`）；真 uvicorn+httpx 判据 | 客户端自造 seq → 否（与总线游标语义分叉，ADR-0011） |
| **live-only delta 不可重放致在途文本缺失** | 重连时未收尾消息文本无 durable 表示 | D-P7-C：additive `final_text`（选①，守 C18/C13）或只读 `/transcript`（选②）；未定案标 UNVERIFIED | 假装重连能补齐 delta → 否（DeepCode 注释亦证 durable log 无 streamed text） |
| **工具/远程原文或凭据进前端/观测面**（破 C18/C20/C17） | 工具卡/日志整份搬远程输出、env 值 | T7 有界 preview + artifact 指针、`check_projection_whitelist`、MCP stderr 独立文件不变、CSP `connect-src` 无远程 origin（T9） | 全量透传输出到前端 → 否（第二载体 + 前端泄漏面） |
| **复用不留来源标记（已定案）** | 复用参考仓码（DeepCode/GenericAgent/wuu/CowAgent/hermes = MIT；EvoFlow 上游 PolyForm NC）——**全体原作者均已授权使用且不要求署名**，并入本仓不标 provenance/许可声明 | `AGENTS.md §4.5/§5.6` 与 `CONTRIBUTING.md` **已于 2026-10-17 同步修订**为该口径；发布件不列 `audit-licenses` 来源；已记 [`ADR-0031`](../adr/0031-reference-repo-reuse-no-attribution.md)（本改动属贡献约定、非分层/契约） | 继续标 provenance → 否（违全体作者明确要求，且与已修订的 rulebook 冲突） |
| **transport 混淆（DeepCode stdio vs questor HTTP+SSE）** | 误按 DeepCode stdio `initialize` 搬进 questor | D-P7-B 明写：只搬生命周期形状，就绪探测换 HTTP/首帧 SSE（ADR-0007/S5） | 引入私有 Tauri event 协议 → 否（ADR-0007 已否，多端不复用） |
| **§0 行号 stale** | 参考仓上游漂移 | 开工当天重验每条 `file:line`（§0.1 纪律） | 信旧行号直抄 → 否 |

---

## 6. 收尾（活文档，AGENTS §5.5）

- [ ] **偏差回填** `docs/adr/` 或 `docs/design/*`：实现与本文偏差 → reality-wins 写回本文"实现偏差回填"节（执行期新增 §8）+ 相应 design。
- [ ] **先记 ADR 再动代码**（T0）：① sidecar serve 接线/进程边界（补 ADR-0007 落地细节）；② 工具事件 additive 字段 + 只读 artifact/transcript 端点（改 `contracts`/事件形状）；③ D-P7-C 选型；④ 桌面/sidecar 分层守卫扩面。§3 前置门。
- [ ] 更新 **`ROADMAP.md §1.5` P7 备注**：把 DoD 口径"P1-P4"按现实说明为"P1–P5（P5 已合入 `290375e`）"；确认"极简调试面板 + 仅消费事件协议 + bus 级只读订阅收口"落地。
- [ ] **`CHANGELOG.md [Unreleased]` 追加**：只写本仓自己的桌面壳/sidecar 能力变更；**不列任何参考仓来源/provenance/许可注**（全体原作者已授权使用且不要求署名；DeepCode/GenericAgent/wuu/CowAgent/hermes/EvoFlow 均按此处理）。`AGENTS.md §4.5/§5.6` 与 `CONTRIBUTING.md` **已于 2026-10-17 同步修订**为该口径（见 §0.1 口径注、§5 风险行）。
- [ ] **`docs/STRUCTURE.md` §3/§9 同步**：`desktop/`（src-tauri+web）、`surfaces/serve`、`sidecar-requirements`、codegen `--check`、`verify-release-bundle`、`.importlinter`/`check_layering_ast` 新契约扩且带 `--self-test`+fail-on-empty（C15）。
- [ ] **新增架构级易复发陷阱 → `docs/pitfalls.md`**（跨子系统+高理解成本+会再踩才进；普通 bug 走 Issue）。候选：① "带外投影逐消费者调用 = 多 surface 双投，收口只能 bus 级一处只读订阅"；② "live-only delta 不进 durable → 重连文本恢复需显式 additive 帧或只读 transcript，不能假设 after_seq 补齐 streamed text"（若实测坐实）。
- [ ] **`docs/design/02-event-protocol.md` 等**：若 additive 扩字段（preview/artifact_ref/final_text/node_updated 定形）→ **就地修订** + 保持 locked/draft 标记诚实（C11）。
- [ ] **§0 表行号终检**（交付前防 stale）。

---

## 7. 文末诚实自检（逐问如实回答）

**Q1 · §0 是否逐能力 ≥2 仓、带 `file:line`、"改造/自写"给原因、排除本仓目录、各仓许可（含 EvoFlow evopanel 授权使用状态）已核？**
- ✅ 逐能力 ≥2 仓：① Tauri/sidecar 生命周期（DeepCode `sidecar.rs`+GenericAgent `lib.rs`+EvoFlow `boot_cycle.rs:206-224`）；② SSE 客户端（DeepCode `threadEventStream.ts`+CowAgent `client.ts`+hermes e2e 桩）；③ 审批/工具卡（DeepCode `ApprovalCard.tsx`+`app-server.ts` artifact+GenericAgent CSP 契约测试）；④ 三段式（DeepCode `build-sidecar.py`/`verify-release-bundle.py`+EvoFlow `pyi_rth`/`preflight`+CowAgent `sys._MEIPASS`）。每条带 `repo:path:line` 且标"扫描快照 2026-10-17，开工当天重验"。
- ✅ "改造"均给理由：核心是 **transport 契约不兼容**（DeepCode stdio JSON-RPC vs questor HTTP+SSE，ADR-0007/S5）→ 只搬生命周期/打包/客户端**形状**，就绪探测与传输层重设计（D-P7-B）。
- ✅ 排除本仓：§0.1 明确排除 `questor` 及 `questor-fix-tasklist`/`-log-foundation`/`-p5-hardening`/`-p5-skills-mcp`（本轮实测**均非 git 仓**，`fatal: not a git repository`）。
- ✅ 全体参考仓作者授权：`project-main/` 下所有参考仓（含 `LICENSE:1-5` 为 **PolyForm Noncommercial 1.0.0** 的 EvoFlow evopanel）**作者均已同意本项目使用其代码、且不要求任何来源标记/署名**。§0.1/§0.2/§5/§6/本行口径统一为"可复用 + 不标 provenance"，且 `AGENTS.md §4.5/§5.6` 与 `CONTRIBUTING.md` **已于 2026-10-17 同步修订**为该口径，规则书与本计划一致。

**Q2 · C1–C? 是否逐条勾对（现场数实际条数）？**
- ✅ 现场数=**C1–C20**（`HARD-CONSTRAINTS.md:110-115` 证 C20 存在、末段"评审口径 C1-C20" `:122`），§3 表格 **C1–C20 全量逐条**，无遗漏、无照抄旧区间。

**Q3 · P5 遗留的 sidecar 带外投影缺口是否落成明确设计（收口点 bus 级只读订阅）而非口号？**
- ✅ D-P7-A 落成明确设计：现状证据（`cli.py:264` 单消费者调用 vs `http_sse.py:148-158` 不投）+ 定案（组合根一条 bus 级只读订阅 + **删**逐消费者调用）+ 为什么一处（多 surface 双投违 C6/C20/`pitfalls #2`）+ 协议零 diff + §4.3 单投 canary 判据；T2 落子任务。承 `plan/05 §0.4`/P5 审计 §6 明确收口，不再顺延。

**Q4 · 瘦客户端零业务下沉 / 进程边界是否作为硬约束逐子任务体现？**
- ✅ S5/S6/C17 贯穿：T1（HTTP+SSE 禁进程内直调）、T5（只经 Command Inbox）、T6/T7（前端无权限/校验、MCP floor 在 Harness）、T9（瘦客户端禁业务守卫 + CSP 锁定 + 独立 blocking job）、§3 S5/S6/S7 专条、§5"业务下沉"风险行。非只 DoD④ 一句口号。

**Q5 · §2 每条子任务是否都有 §4 判红用例？有无 mock 冒充未标注？**
- ✅ §4.6 自检矩阵逐一对应 T0–T12；断线重连/带外投影/崩溃重启都要求**真 uvicorn+httpx / 真进程 grep canary / 真 kill 进程树**，非 mock。
- ✅ 无 mock 冒充：真 LLM/真远程 MCP/真打包桌面/在途 live delta 文本恢复（D-P7-C 未定案部分）均显式标 **UNVERIFIED**（§1.2/§4.2/§4.3/§4.5/T8/T12）。

**Q6 · 基线 commit 是否记入 §0？**
- ✅ §0.0 记入 **本计划基线 = `main` @ `290375e`**，并证 #142（`eb1da31`）/#143（`114fb0f`）/#144（`290375e`，内含审计 `29821de`）已合入 → **C20（`HARD-CONSTRAINTS.md:110-115`）/`docs/pitfalls.md`/MCP/Skills 均存在**，P7 在其约束下规划；并记 `protocol/event.schema.json` 已在、`desktop/` 不存在、无 `--serve` 入口、`EventType`=20（`protocol/README.md:18` "19" stale 须校正）等现场事实。

> **诚实边界**：本文为 READ-ONLY 规划，只落此文档，未改代码/未建分支/未 commit/未 push。所有 `file:line`（本仓与参考仓）为 2026-10-17 扫描快照，开工当天必重验；真机桌面打包、真 sidecar 崩溃重启、真远程 MCP server 端到端、以及未定案的在途 live-delta 文本恢复均标 **UNVERIFIED**，不用 fake 冒充真机。

---

## 8. 实现偏差回填（reality-wins，执行期追写；AGENTS §5.5）

> 开工分支 `feat/p7-desktop-shell`。以下为实现与本文/设计的偏差与定案，按“现实胜”回写。

- **T1 serve 落点修正（已记 ADR-0032 + 本文 §0.0 GATE-0）**：`check_layering_ast.py` FORBIDDEN_IMPORTS[surfaces] 禁 `providers.store_sqlite`/`store_memory_sqlite`/`subprocess` → 具体 store 实例化留**组合根 `__main__.py --serve`**，`surfaces/serve.py` 只接注入 server + 跑 uvicorn + 写 bootstrap，不 import 具体 store。本文原 T1 “serve.py 装配 SQLiteStore” 描述按此修正。
- **D-P7-C 定案=选型①**（非②/非未定）：`message_completed` additive 有界 `final_text`+`item_id`（≤ 8192 字，`truncated` 标志），单一真源不另开 `/transcript`。未定稿半条 live-delta 仍 **UNVERIFIED**。详 ADR-0034。
- **`check_protocol_schema` 一处 doc/code 偏差修正（T11 发现）**：`project()` 对 `EXTERNAL_EVENT_FIELDS` 值为 `None`/未列类型实际是**丢弃**（非注释所说的“原样透传”）；node_updated 定形同时改正了该注释。
- **T6 合入 T5 客户端**：审批面板的**行为契约**（request_id 幂等、fail-closed deny）由服务端既有测试 + `commandClient.resolveApproval`（decision 域锁 allow|deny）覆盖；React 面板像素渲染属 webview（UNVERIFIED）。
- **T8 分两步：监管核心已落+cargo 验证；壳/打包 UNVERIFIED**。已做：sidecar 三段式步骤①窄锁 `desktop/sidecar-requirements.{in,lock}`（`uv pip compile` 实产）+ `scripts/verify_release_bundle.py`（结构门 self-test 判红/绿）+ **Rust `desktop/sidecar` crate**（零依赖生命周期核心：generation 栅栏 `Fence`、`two_phase_shutdown`、`fail_all`、loopback `wait_ready`；`backend.rs` 接真 `std::process::Child` 并**真子进程**跑通强杀兜底；`cargo test` 8 passed）**。已接上 **Tauri v2 壳 `desktop/src-tauri`**（复用 `questor-sidecar`：setup bump generation → spawn `--serve` → 读 bootstrap → webview 指 loopback 端 → ExitRequested 走 `two_phase_shutdown`；tauri.conf.json 锁 CSP、capabilities 不授 fs/shell）：本机 `cargo check` Finished + `cargo test` 2 passed。**已验新增**：Vite 薄客户端 app（`tsc`+`vite build` 产 dist）+ `create_app(server, static_dir)` 挂静态伺服（TestClient 验 / 返回首页）+ Windows **Job Object 杀进程树**（`StdProcess` 裸 kernel32 FFI，真子进程 `cargo test` 绿）+ `build-sidecar.py` PyInstaller onedir 冻结 + `verify_release_bundle --verify-runtime`（启动冻结 exe、无系统 Python，/run→/events 实跑全流）。**仍 UNVERIFIED**：真开窗口/像素渲染、全量 `tauri build` 桌面 bundle（需 `@tauri-apps/cli`+WebView2+vite 产物链）——本机无头不跑真窗口（cargo/WebView2/pyinstaller 均已实测可用）。
- **T9 CSP/capabilities 锁定（已补）**：`src-tauri`/`tauri.conf.json`/`capabilities/` 已建→`scripts/check_desktop_csp.py` 实装（扫 CSP：禁 script-src unsafe-inline、强制 object-src 'none'、connect-src 仅 loopback；禁 fs/shell/http 能力），fail-on-empty + `--self-test` 判红，已进 `boundaries`；实扫当前壳 0 违规。
- **脚本命名**：本文 `verify-release-bundle` → 实文件 `scripts/verify_release_bundle.py`（下划线，与仓内其他守卫一致）。
- **DoD 能力面**：按 §1.1 现实验 P1–P5（P5 已合入）；e2e 用脚本化 provider，真 LLM/真远程 MCP/真打包 = **UNVERIFIED**。
- **§4.5 verdict 与现实的偏差（诚实标注）**：§0.2 将前端定为“改造（DeepCode React）”，实际 shipped `desktop/web` 是**自写 vanilla-TS**（无 React，未搬 `ApprovalCard.tsx` 组件树）；SSE 游标/两级关闭的**形状**确参照 DeepCode，但 UI 组件未搬。理由：本 Phase 交付以“仅消费协议 + 可验证”为先，框架选型非铁律；如后续要真“改造”DeepCode React，另开子任务。
- **对抗式审计后加固（`docs/audit/P7-review-2026-10-17.md` NO-GO → 修复）**：已修 §6-1 resolve_sidecar(env→packaged→dev、不写死 python)+bundle+staging；§6-2 ci-desktop lane；§6-3 clippy/fmt 绿；§6-4 字段级漂移两道门；§6-6 会话 token + 真 `/shutdown` + 崩溃检测/重启决策原语；§6-7 MCP 接进 sidecar 路径；§6-8 resync 分因 + stream_end；§6-9 e2e 划域。仍待：真开窗口/全量 `tauri build`/真远程 MCP/真 LLM（环境受限，UNVERIFIED）。
