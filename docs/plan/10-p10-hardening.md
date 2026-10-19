# Phase 10 详细计划 — 加固：可恢复上下文压缩 / observability 刀 3 / 评测回归网

> 起手**必读**：[`AGENTS.md §0/§1/§2/§3/§4.5/§5/§5.5/§5.6/§6`](../../AGENTS.md) · [`docs/ROADMAP.md §1/§1.5/§2/§2.5/§5`](../ROADMAP.md) · [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)（现场核 = **C1–C20**）· [`docs/plan/_TEMPLATE.md`](./_TEMPLATE.md)
> **§0 未填完 = 本 Phase 计划未就绪、不能开工**（ROADMAP §0 硬门槛）。
> **基线**：`main` HEAD = `cfc3004`（含 P8/P9 已合入；现场 `git rev-parse main` 实核）。下一个 ADR 编号 = **0048**。
> **性质**：本 Phase 横切三个较独立子系统（A 可恢复压缩 / B observability 刀 3 / C 评测回归网）+ 卫生面 D。READ-ONLY 规划轮只落本文、不改代码；实现须经两路对抗评审（Blocker/Major 全关）后另建 worktree `questor-p10-hardening`（分支 `feat/p10-hardening`），每条 TDD 先红后绿、细粒度原子提交、commit/push 逐次征询。

---

## 0. Peer-Repo 扫描（AGENTS §4.5 硬门禁；现场重列 `project-main/` 逐仓扫）

**现场重列（2026-10-19 实 `Get-ChildItem`）**：工作区根 `d:\DEVELOP\Project-main` 下主项目 `questor/` + 参照仓 **12 个**：`hermes-agent-main / wuu-main / DeepCode-main / CowAgent-master / MetaGPT-main / cordis-main / EvoFlow-main / autogen-main / crewAI-main / OpenManus-main / GenericAgent-main / Agent-S-main`（新仓自动纳入，非固定清单）。**ADR-0031**：全体参照作者已授权复用、免署名，但**许可仍逐仓现场核**（见下条许可列）。开工当天逐行重验 `file:line` 仍有效（P3 审计 F 类 stale 引用教训）。

| 能力 | 扫描仓（`file:line`） | 结论（复用/改造/自写） | 说明 · 许可/署名注意 |
|---|---|---|---|
| 压缩触发阈值单一真源 | wuu `internal/agent/adaptive_compact.go:99`（`reactiveCompactTarget`）；`internal/agent/loop_compact_threshold_test.go`（"proactive threshold prefers budget value，loop 消费 verbatim、不重推窗口数学，trigger/trace/UI 不漂移"） | 改造 | I2 内核决定 + 单一预算源口径由此立；questor 阈值取 `Budget`/context-window 估算，loop 只消费不重算 |
| 压缩头尾保护 + 中间摘要 + 工具输出先剪 | hermes `agent/context_compressor.py:1-2`（"cheap auxiliary model summarizes middle turns，head/tail protected，tool-output pruning first"）；`context_compressor_summary.py`、`micro_compaction.py`、`native_compaction.py` | 改造 | questor 采"保头（system+首个 user）/保尾（token 预算）/中段进 summary"；工具全文先走 ADR-0019 artifact 指针再剪 |
| 压缩不丢事实召回（回复锚/用户轮锚） | hermes `agent/conversation_compression_reply_anchor.py:1`（`_ensure_compressed_keeps_last_assistant_reply`，#118900）；`_ensure_compressed_has_user_turn`；`compression_marker.py`（`elide_middle`） | 改造 | 映射 questor 不变式：压缩后最新可见 assistant 回复与每个 user 轮必留活区；孤儿 tool_use 严禁（C19） |
| `covered_hash` 恢复锚算法（剔除易变字段） | wuu `internal/agent/compaction_note.go:20-21`（`CoveredMessages int`/`CoveredHash string`）、`:74-75`（"stable semantic hash…thread-local sequence and tool-ledger addresses" 被剔除）；`compaction_lineage_journal.go` | 改造 | 已有 `contracts/memory.py::RecoveryPointer(seq_from,seq_to,covered_hash)`+`matches()`；P10 落**生产者**：canonical 覆盖区内容哈希、剔除 per-run seq 与 tool_call_id（ADR-0024 原述同源） |
| 压缩/裁剪的 lease/水位交互 | hermes `agent/context_compressor.py:385-395`（"lease-less watermark"、prune/micro-compaction 不持压缩 lease 即 abort）；wuu `internal/appserver/turn_execution_lease.go`、`thread_lifecycle_lease.go` | 参考（形状） | 印证本 Phase 张力：压缩写锚与 event_log 裁剪/回收必须序列化；questor 用单写者 + `BEGIN IMMEDIATE`，非 lease |
| compaction × tool_call 配对 | DeepCode `core/agent_runtime/compaction.py`；`tests/test_compaction_tool_call_budget.py`、`test_compaction_memory.py`、`test_compaction_retry_memo.py` | 改造 | C19 配对方程：压缩只能在 `closed_prefix` 内截断（`state/checkpoint.py:12`），尾窗未闭合 tool_use 原样保留 |
| `questor logs` 诊断命令（sources/scan/timeline、可分享时间线） | EvoFlow `backend/packages/harness/evoflow/cli/commands/logs.py`、`observability/agent_trace_load.py`、`config/observability_config.py`、`gateway/routers/observability.py` | 自写（许可禁搬码） | **EvoFlow = PolyForm Noncommercial 1.0.0**（现场核 `EvoFlow-main/LICENSE`）：**只读设计、零搬码**；命令交互形状作 §14 消费命令参照 |
| 协议留内、sink 可独立发布、配置容器注入 | cordis `packages/core/src/logger.ts`（`Message`/`Exporter`/`_resolveConfig`/`bufferSize`） | 参考（形状） | cordis = **MIT**（现场核 `cordis-main/LICENSE`）；已在 ADR-0027/刀 2 采其形状，刀 3 不引新依赖 |
| 结构化事件即日志行（agent 身份自动带） | autogen `python/packages/autogen-core/src/autogen_core/logging.py`（`LLMCallEvent`/`EVENT_LOGGER_NAME`）、`autogen_agentchat/.../\_events.py`、`autogen_core/_telemetry/` | 取设计 | autogen = CC-BY-4.0（按任务口径取设计不搬码）；带外投影行自描述风格参照 |
| metrics/OTel 观测形状 | hermes `agent/context_compressor_telemetry.py`、`conversation_compression_telemetry.py`；wuu `internal/appserver/plugin_turn_observer.go` | 参考 | 第三方 sink 由引入它的适配器治理（pitfalls #4/C20）；内核九文件零依赖不破 |
| 评测任务级回归网 + persistence conftest | hermes `evals/toolperf_abeval/ab_eval.py`、`evals/postmortem/review_probes/*.py`；DeepCode `eval/swebench/evaluate.py`；既有 `tests/evals/test_p4_memory_eval.py`（本仓雏形） | 改造 | questor eval 采本仓既有形状（`SQLiteMemoryStore`+确定性 distiller+`ScriptedProvider`）扩面；swebench 作任务级 pass 判据参照 |
| 记忆检索协同（压缩→L2' 蒸馏 / embedding 持久化） | GenericAgent `memory/reflect*`；MetaGPT `document_store`；本仓 `memory/{distill,chunker,search,sync}.py` | 改造 | ADR-0025 蒸馏桥、ADR-0024 covered_hash fail-closed 为真源；embedding/trigram-CJK 判据见 §2「不做」 |
| 跨进程 exactly-once / 单写者（观测投影收口） | wuu `internal/agentcontrol/worker_execution_lease.go`；hermes `agent/stream_delivery.py`、`stream_single_writer.py`；本仓 `surfaces/http_sse.py` | 改造 | pitfalls #5 带外双投收口为 bus 级一处只读订阅（ADR-0033 形状），刀 3 落地 |

> **许可逐仓核结论**：cordis=MIT、wuu/hermes/DeepCode/CowAgent/MetaGPT/autogen=可复用改造（ADR-0031 免署名）、**EvoFlow=PolyForm Noncommercial 1.0.0→仅参照设计禁搬码**、GenericAgent/Agent-S/OpenManus/crewAI 作对照。**"自写"必须有原因**：`CompactContext` reduce 分支 / `covered_hash` 生产者 / bus 级投影收口为本项目契约特有（单写者 + 事件溯源 + C20 零原文），无外部实现可直接搬运。

---

## 1. 目标与可验证判据（DoD）

**进入条件**：对齐 ROADMAP §1（P10 进入条件 = "P3 起持续"）；现场基线 `main=cfc3004` 含 P8/P9 已合。三子系统代码面基本不重叠（A=kernel/state/contracts，B=observability/surfaces，C=tests/evals/scripts，D=providers/StorePort），可并行开工；唯 **C 依赖 A+B 稳定**、**D 依赖 A**（GC 与 `recovery_pointers` 强耦合）。

**DoD（可复现行为；区分「已验证」/「UNVERIFIED」，绝不把未验证写进已验证）**：

- **DoD-A 压缩不丢事实召回（已验证，确定性）**：给定一条早于压缩点注入的事实（`WriteMemory`/用户轮），触发一次真实压缩后——
  1. 被丢弃原文区间的 `recovery_pointers` 必携 `covered_hash` 且能 `matches()` 校验通过（原文从 append-only `event_log` 按 durable seq 回读）；篡改该区间历史 → 读回 **fail-closed 拒绝**（ADR-0024）；**摘要文本存于 `Domain_State.summary`、随 checkpoint 持久（回放不重算）**；
  2. 压缩后 `context.items` 内**每个 `tool_use` 都有配对 `tool_result`**（`closed_prefix` 内截断、尾窗保留，C19/ADR-0028 关卡前必过）；
  3. 最新可见 assistant 回复与每个 user 轮仍在活区（不被折进 summary，hermes 锚改造成果）；
  4. **回放确定性**：`check_replay_determinism.py` 含压缩 fixture 的 (full-reduce) == (snapshot + `compact_applied`/`baseline_seq` 尾重放)，`--self-test` 能判红；
  5. `compact_started`/`compact_applied` 事件 additive、`v` 不 bump、四处 lockstep 全绿、protocol schema 对新 type 有 `$defs` 快照。
- **DoD-B 追踪面板/消费面基于事件流（已验证，旁路只读）**：
  1. `python -m questor logs` 读**按日 JSONL 主干 + `event_log` 权威**按 `run_id+seq` 合并成时间线，`--timeline` 出 md+json；命令**全程只读、绝不写库/改状态**；损坏行跳过并计入 `malformed_lines`；
  2. **带外投影收口为 bus 级一处只读订阅**（pitfalls #5/刀 2 偏差 #4）：开 2 个并发 `/events` 订阅者跑同一 run，主干日志每 `seq` **恰一行**（判红样例：退回逐消费者投影 → 翻倍）；
  3. `--log-payload`/`QUESTOR_LOG_PAYLOAD=truncate:N` 实装：preview **仅**写独立 `llm-<date>.jsonl` 通道（开启即 `llm_file=True`）、必过脱敏、**有界截断 N**、主干 `questor-<date>.jsonl` **零原文**不变（`check_projection_whitelist --self-test` 仍判红、`_DATA_KEYS` 不得新增载荷键）；非 `truncate:N`/`off` 值仍拒绝启动；
  4. usage **per-run→session 聚合**为**读侧投影**：源取**持久化的 `run_completed.usage`**（`reduce.py:399` 发射、非 `LIVE_ONLY`、落 `event_log`），跨 run 经 `replay_global`/`gseq` watermark 汇总，`questor logs --totals` 出总花费；**不改内核、不落第二真相**（ADR-0041/C13）。⚠ **裁决修正（评审 MAJ-4）**：`usage_delta ∈ LIVE_ONLY`（kernel/events.py:31-33）**不入库且生产路径从不发射**——聚合**绝不可依赖 `usage_delta`**，只能用 durable `run_completed.usage`。
- **DoD-C 任务级回归网（已验证，CI 无 key/无网络确定性；真 LLM 标 UNVERIFIED）**：
  1. 一条 scripted-provider（`providers/fake.py::ScriptedProvider`）驱动的 eval 套件在 CI **无 `LITELLM_API_KEY`、无外网**下跑出**确定性** pass-rate/token/cost 判据，回归阈值（pass-rate ≥ 钉定基线、逐指标不劣化）；
  2. 反假绿：注入"压缩丢事实"或"投影双投"变异 → eval 必判红（`--self-test`/突变验证）；
  3. **真 LLM 端到端 = UNVERIFIED**：本机不跑真 key 的压缩摘要质量/多模态/远程面，**绝不写进 DoD 已验证**（承 P4/P5/P7/P9 诚实边界）。
- **DoD-D 卫生面回收（已验证，保守可达性）**：
  1. **只回收过期/已释放的 `run_lease` 行 + 超 TTL 未 ack 的 in-flight claim**（瞬态、可安全重取）；未知 `store_schema_version` 仍 fail-closed。⚠ **裁决修正（评审 BLK-2）**：**绝不裁剪已 acked 的 delivery 行**——投递视图从 `event_log` 重建（ADR-0047），而 `event_log` 本 Phase 不裁（见 D③），裁掉 acked 幂等键会在 rebuild 时重新 claim→双投，恰破 exactly-once；acked delivery 行的回收与 `event_log` 裁剪**绑定后置**；
  2. artifact **孤儿 GC**：只删"不被**任何**保留事件/检查点引用"的孤儿（写失败/崩于写与发事件之间，内容寻址去重安全）。⚠ **裁决修正（评审 MAJ-7）**："terminal-run session cleanup" 因 D③ 不裁 `event_log` → 终态 run 的 `tool_completed.artifact_ref` 恒在库、其 artifact 永不可安全删——**真正的 session 级 artifact 回收与 `event_log` 裁剪绑定后置**，P10 只做孤儿扫描，**不虚称 session cleanup**；
  3. **event_log 裁剪显式不做**（与 `recovery_pointers` 指向 append-only 区间、与单真相 ADR-0020 直接冲突）——登记后置理由（见 §2、ADR-0050）。

**贯穿质量门**：全量 pytest 零回归（基线现场 `uv run pytest -q` 记录 passed/skipped 数）、ruff clean + Clippy 门禁（Rust 侧若动）、`lint-imports` 既有契约 kept、冷导入逐模块、protocol schema 对既有 type 零 diff、Windows 真机 leg、UTF-8 锁定不崩（cp936 宿主，承既有 memory）。

---

## 2. 本 Phase 不做（范围纪律，硬边界）

1. **不做跨机/分布式**（C12/天花板条）：exactly-once 单机多进程已在 P9/ADR-0047 落；跨主机租约/共识/排序不纳入。
2. **不把业务/状态/校验下沉 Shell**（C14/ADR-0007）：追踪面板 = 事件协议瘦客户端，`questor logs` 是 surfaces 读命令，均零业务下沉。
3. **事件/状态 additive、不 bump `v`**：新 `compact_*` type、可选字段、`CompactionConfig` 皆只增；破坏性变更一律后置 + 另 ADR。
4. **工具 reader/writer gate + 真并发派发 → 再次显式后置独立并行化 Phase**（ADR-0029/0039 悬置的裁决，见 §矛盾 5）：本 Phase **不读取** `parallel_safe`/`barrier` 改派发，执行仍严格串行 + 回发前配对（C19）。债由 ADR-0051 点名 owning phase、绝不留"注释说 P# 其实没人做"。
5. **不做 `event_log` 主干裁剪**：压缩 `recovery_pointers` 指向 append-only 区间、回放依赖 log 权威（ADR-0020），裁剪与二者直接冲突；只回收**派生视图**（claim/lease）与**非权威 artifact**（见 DoD-D）。
6. **不接真 LLM 端到端进 DoD**：eval 网用 scripted provider 出确定性判据；真 key 摘要质量/embedding 检索效果、真窗口渲染 = UNVERIFIED。
7. **不为 P10 造 speculative infra**（§2 简洁）：不预建 metrics 后端、不预建远程 sink、不预铺分布式压缩。⚠ **裁决修正（评审 MAJ-6）**：**OTel/metrics exporter 移出本 Phase**——它与 ADR-0027 D8「日志内核 stdlib-only、零新依赖」相左，且**不在 P10 DoD**（DoD 只要求追踪面板基于事件流 + `logs` 命令 + preview）；ROADMAP §1.5 虽列其随刀 3，但按 YAGNI 推到真需求 + 独立 ADR 再开；原计划 **TB5 删除**，仅保留「`trace_id` 作普通键进 `fields`」接缝（DESIGN §1 非目标，已存）。
8. **不"顺手把 P6 多模态加回"**（ADR-0036 整阶段移除）；非文本 content 归一拒绝仍归 P9/ADR-0044。
9. **embedding 持久化 / trigram-CJK 检索 / rerank-热度**（design/06 §2/§6 后置项）：本 Phase **仅在压缩把事实挤入检索时暴露其缺口**，但**不实现**——`sync()` 全量重建清空 `memory_chunks.embedding` 的坑，另立检索质量 Phase 处理；eval 网据实降级关键词-only 判据（承 `test_p4_memory_eval.py`）。
10. **Deep Dream 生产者、dreams 不进索引**（ADR-0025/0026）：本 Phase 只把压缩→L2' `distill` 写路径接活（DoD-A 桥），不改蒸馏原子性纪律。

---

## 3. 前置门：ADR-0048 起（先 ADR、后代码，ROADMAP §5 / HARD C11/C16）

> **T0 = ADR 门**：任一子系统动契约/跨阶段前，先落对应 ADR；未过对抗评审不得开工代码。ADR 编号现场续接 0048。

- **ADR-0048 · 可恢复上下文压缩转正**：新增内核内部 `CompactContext` Command（经 controller→reduce 单写，C2/C16）；`reduce` 内 fold→`summary`、置 `compaction_floor`、**截断前**写 `recovery_pointers(seq_from,seq_to,covered_hash)`（fail-closed 生产者，ADR-0024 转正）；`compact_started`/`compact_applied` additive 事件 + `baseline_seq` 栅栏（design/02 §10）；`pre_compact` 检查点（design/01 §5）；`LoopPolicy.compaction: CompactionConfig`（取代 `disable_compaction=True`，policy.py:89）+ 阈值单一真源（I2，advise 仅 advisory）；压缩不得孤儿化 open tool_use（C19/`closed_prefix`）；L2' `distill` 桥（ADR-0025）。**评审回填的硬定义**：① **摘要文本属 `Domain_State` 权威、随 checkpoint 持久**，`compact_applied` 只带 `{baseline_seq, covered_from, covered_to, summary_bytes}`——**回放从快照恢复 summary、绝不重跑摘要器**（否则 provider 摘要路径破回放确定性，BLK-1）；② **【二轮 MAJ-8】reduce 纯函数**：摘要/`covered_hash`/新 floor/`recovery_pointers` 均由 loop 侧（可插拔摘要策略）算好后**随 `CompactContext` 命令负载携带**，reduce 只纯校验+纯应用、**不在 reduce 内计算摘要/哈希**；③ `recovery_pointers.seq_from/seq_to` = 被逐消息区间的 **durable `event_log` seq** 边界，原文**从 append-only `event_log` 回读**（与 §2.5 不裁 log 决策强耦合），`covered_hash` = 对该 seq 区间消息内容规范化哈希、**剔除 per-run seq 与 tool_call_id 等易变字段**（wuu compaction_note.go:74-75，MAJ-1）；④ **迭代压缩**：新摘要 = fold(前摘要 + 新逐出区)，`recovery_pointers` 只追加不改写旧锚（MAJ-2）；⑤ `baseline_seq` 为**栅栏提示**供渲染侧重折上下文视图；因 log 完整，`after_seq` 回放仍有效，**不强制 resync**（仅游标越界/版本不符才走既有 `resync_required`，MAJ-3）。**被否**：out-of-band 直改 `context.items`（违 C2）；策略发强制压缩命令（违 I2）；截断先于写锚（fail-open 丢原文不可恢复）；回放重跑摘要（破确定性）。
- **ADR-0049 · observability 刀 3 落地边界**：`questor logs` 只读消费命令（主干 JSONL + `event_log` 合并、`--timeline`、`--totals`）；带外投影**收口 bus 级一处只读订阅**（pitfalls #5/ADR-0033，消刀 2 偏差 #4 的逐消费者双投）；`--log-payload=truncate:N` preview 三闸（显式授权 + 独立通道 + 有界截断，C20 不越界款）；usage session 聚合 = 读侧投影非第二真相（取 durable `run_completed.usage`、**不用 never-emitted 的 `usage_delta`**，ADR-0041/C13/MAJ-4）；`questor logs` 命令自身只读、开 store 不得取写锁/不触发自身 GC。**本 Phase 不引 OTel/metrics**（移出，见 §2.7/MAJ-6）。**被否**：metrics/trace 落第二存储；把 preview 写进主干；内核 import OTel SDK；用 usage_delta 聚合。
- **ADR-0050 · 卫生面回收边界**：claim/delivery/lease 账本回收**限过期/已释放 lease + 超 TTL 未 ack 的 in-flight claim**（派生瞬态视图可安全重取）；**不裁已 acked delivery 行**（与 `event_log` 不裁绑定，否则 rebuild 重 claim→双投破 exactly-once，BLK-2）；artifact **孤儿 GC**（仅删不被任何事件/检查点引用者；真 session 级回收与 `event_log` 裁剪绑定后置，MAJ-7）；**`event_log` 主干裁剪显式后置**并点名与 `recovery_pointers`/单真相/回放权威的冲突理由。**被否**：裁 event_log 破坏压缩恢复与回放权威；裁 acked delivery 行；虚称 session artifact cleanup。
- **ADR-0051 · 工具并行 gate 再后置登记**：把 ADR-0029/0039 的"P10 或独立"悬置**收口为"独立并行化 Phase（post-P10，未立项）"**；同步 HARD C19 `:108`/ADR-0039 措辞；不"悄悄没人做"。**被否**：塞进 P10 叠高 blast radius（ADR-0039 被否选项 1）。

---

## 4. 子任务清单（目标 · 涉及层 · 依赖 · 验证[判红用例] · commit 粒度）

> 每条 **TDD 先红后绿**；"字段存在≠gate/接线存在"式真依赖显式点名；一任务一原子 commit（英文 Conventional Commits、**标题小写动词开头**，CI pr-lint 拦大写）。

### Lane A · 可恢复压缩（kernel / state / contracts）

- [ ] **TA1 `CompactContext` Command + `reduce` 分支**。涉及层：L0 `contracts/events.py`（新内部 Command）、L1 `state/reduce.py`/`state/domain_state.py`。依赖：ADR-0048。**真依赖点名**：`Context.compaction_floor/summary/recovery_pointers` 字段**已存在**（domain_state.py:39-41）但 **`reduce` 无任何压缩分支**（现场核：reduce 无 compact 处理）——字段存在≠归约存在。**【二轮 MAJ-8】reduce 纯函数铁律**：摘要文本与 `covered_hash`/新 `floor`/`recovery_pointers` 均由 **loop 侧（可插拔摘要策略，非 provider in-reduce）算好后随 `CompactContext` 命令负载携带**；reduce 只做**纯校验（配对/`closed_prefix`/锚非空）+ 纯应用**（将携带值写入新 `Domain_State`）——**绝不在 reduce 内计算摘要/哈希**（否则 reduce 不纯、`pre_compact` 快照尾重放含该命令时破回放确定性）。**判红用例**：① `reduce` 收到 `CompactContext` 若截断范围越出 `closed_prefix`（会孤儿化 open tool_use）→ 拒 + 发 error 事件、状态不变；② 命令负载缺 `covered_hash`/summary → 拒；③ 写锚后被篡改覆盖区原文 → `RecoveryPointer.matches()` 读回 fail-closed；④ **同一 `CompactContext` 命令两次 reduce 结果逐字相等**（纯函数性）。commit：`feat(state): fold compacted region into command-carried summary with fail-closed recovery anchors via CompactContext`。
- [ ] **TA2 `compact_started`/`compact_applied` additive 事件四处 lockstep**。涉及层：L0 `contracts/events.py`（`EventType` + `EXTERNAL_EVENT_FIELDS`）、`protocol/event.schema.json`、TS codegen、`scripts/check_protocol_schema.py`。依赖：ADR-0048。**真依赖点名**：现 `EventType` 22 类**无 `compact_*`**（现场核 events.py:309-331），design/02 §2/§10 仅纸面提及——须实落。`compact_*` 定为**内部事件投影出外部精简集**（`compact_applied` data 仅 `{baseline_seq, covered_from, covered_to, summary_bytes}`，无正文，C18/C20）。**判红用例**：schema/enum/白名单/TS 四处任一缺 `compact_*` → `check_protocol_schema --check` 红；既有 22 类零 diff。commit：`feat(contracts): add compact_started/applied events, additive without bumping v`。
- [ ] **TA3 `baseline_seq` 栅栏入快照/回放**。涉及层：L1 `state/snapshot.py`（v3 已承 `recovery_pointers`）、`kernel/recovery.py`。依赖：TA1/TA2。**判红用例**：重放遇 `compact_applied` → 上下文以 `baseline_seq` 为重写栅栏重建，`(snapshot+尾重放)` 权威骨架 == 连续 reduce（并入 TA6）。commit：`feat(state): carry baseline_seq compaction fence through snapshot and replay`。
- [ ] **TA4 `CompactionConfig` 取代 `disable_compaction` + loop 安全点触发**。涉及层：L0 `contracts/policy.py`（`LoopPolicy.disable_compaction=True`→`compaction: CompactionConfig|None`）、L2 `kernel/loop.py`（turn 边界安全点、`_checkpoint("auto")` 之后挂压缩；`pre_compact` 补点）。依赖：TA1/TA3、ADR-0048。**真依赖点名**：`_checkpoint(run, kind)` 现仅被 `"final"/"auto"/"post_tool"/"pre_tool"` 调用（现场核 loop.py:299/382/699/730），**`pre_compact` 从未发射**——kind 存在≠补点存在。阈值取 `Budget`/context-window 估算单一源（wuu 阈值口径），`RequestCompactHint`/`AdviseCompact` **仅 advisory**（内核不被强制，I2）。**判红用例**：达阈值未触发压缩 → 事实被挤爆窗口判红；未达阈值误触发 → 判红；策略发 hint 但内核配置 `enabled=False` → 不压缩（advise 不越权）。commit：`feat(kernel): trigger recoverable compaction at turn-boundary safe point behind CompactionConfig`。
- [ ] **TA5 摘要生产者（确定性启发式默认可跑 + provider 摘要可选门）+ L2' 蒸馏桥**。涉及层：L2 `kernel/loop.py`、L3 `memory/distill.py`（复用 `__main__._HeuristicDistiller` 形状，无 LLM 确定性）。依赖：TA1/TA4。**判红用例**：默认启发式摘要不触网、结果确定（eval 可复现）；开 provider 摘要走注入端口、失败不崩宿主（C19/ADR-0028 归一）；**provider 摘要产物定稿后写进 `Domain_State.summary`、随 checkpoint 持久，回放只恢复不重算（承 ADR-0048 BLK-1）**；压缩丢弃区经 `WriteMemory(distill=被压区,covered_from/to/hash)` → daily（ADR-0025 桥转正，正文只放浓缩、I3）。commit：`feat(memory): deterministic summary producer and L2' distill bridge on compaction`。
- [ ] **TA6 `check_replay_determinism.py` 扩压缩 fixture（含 `--self-test` 判红）**。涉及层：scripts、tests。依赖：TA1–TA5。**判红用例**：新增含 `CompactContext`/`compact_applied`/`baseline_seq` 的 fixture，(full-reduce)==(snapshot+尾重放)；`--self-test` 截断尾/破坏配对/篡改覆盖区必判红；fail-on-empty 保持。commit：`test(ci): extend replay-determinism guard with compaction fixtures`。
- [ ] **TA7 C19 配对不变式专项测试（压缩后回发前必成对）**。涉及层：tests/integration。依赖：TA1/TA4。**判红用例**：压缩发生在窗口内仍有未回填 tool_use 时，压缩区只截 `closed_prefix` 前、尾窗保留；`_stream_turn` 关卡前历史恒成对（`test_pairing_gate_and_provider_fault.py` 同款源码级"调用点唯一且关卡在请求前"守卫延伸）。commit：`test(integration): compaction never orphans open tool_use before the pairing gate`。

### Lane B · observability 刀 3（observability / surfaces）

- [ ] **TB1 带外投影收口 bus 级一处只读订阅**。涉及层：L6 `surfaces/http_sse.py`/`surfaces/cli.py`、`kernel/events.py`（`InProcessEventBus.add_observer`）。依赖：ADR-0049。**真依赖点名**：刀 2 偏差 #4——`log_envelope` 现挂**逐消费者**（`cli._stream`），多 surface 共享总线即翻倍（pitfalls #5 明列"任何新增 surface 都会再踩一次"）。**【二轮 MAJ-9】覆盖面**：收口必须覆盖 **CLI 直驱 + `http_sse` + OpenAI 兼容三生产者**（刀 2 只测了 CLI 路径、HTTP 侧带外投影曾未覆盖）；不能只把 observer 挂在 `InProcessEventBus` 而 CLI 走 legacy 直驱绕过它——否则收口后 CLI/兼容侧反而丢投影。**判红用例**：开 2 个并发 `/events` 订阅者跑同一 run，主干每 `seq` 恰一行；**三生产者路径各跑一遍、逐生产者投影行数与消费者数量无关**；退回逐消费者投影 → 判红（`test_p7_out_of_band_projection.py` + P9 canary `test_p9_*` 三消费者各投一次延伸）。commit：`fix(observability): collapse out-of-band projection to one bus-level read-only observer across all producers`。
- [ ] **TB2 `python -m questor logs` 只读消费命令**。涉及层：L6 surfaces（组合根新入口）、依赖 DESIGN §14。依赖：TB1/ADR-0049。**判红用例**：命令全程**只读**（不建 store 写路径、不改状态）；主干查询走 `event_log` 权威、JSONL 作账本外旁路、按 `run_id+seq` 合并；损坏行跳过并计 `malformed_lines`；`--timeline` 出 md+json；`--list` stdout 洁净纪律不破（G-L10）。commit：`feat(surfaces): read-only questor logs consumption command`。
- [ ] **TB3 `--log-payload`/`QUESTOR_LOG_PAYLOAD=truncate:N` preview 实装**。涉及层：L6 `surfaces/_assembly.py`（消 `reject_unimplemented_payload` 现拒绝非 off 的分支，_assembly.py:43-51）、L5 `providers/litellm_adapter.py`（产 preview）、`observability/sink_file.py`（`llm_file=True` 门）。依赖：ADR-0049、承 TB2。**判红用例**：① preview **只**写 `llm-<date>.jsonl`、主干 `questor-<date>.jsonl` 零原文不变（`check_projection_whitelist --self-test` 保持 `_DATA_KEYS` 不新增载荷键）；② preview 必过 `redact.py`；③ 有界截断 N、超 N 不溢出；④ 非法值仍拒绝启动（`truncate:abc`→SystemExit）。**允许进 preview 的键定死**：仅 `arguments_preview`/`response_preview`（LLM 适配器作用域），**绝不进主干、绝不进 `_DATA_KEYS`**（D4 零原文）。commit：`feat(observability): bounded llm-lane preview behind explicit grant`。
- [ ] **TB4 usage per-run→session 聚合（读侧投影）**。涉及层：L6 surfaces + StorePort 读（`replay_global`/`watermark`）。依赖：TB2/ADR-0049、ADR-0041。**源定死（评审 MAJ-4）**：聚合 **durable `run_completed.usage`**（`reduce.py:399`），**不依赖 `usage_delta`**（∈LIVE_ONLY、不入库、生产路径从不发射）。**判红用例**：`questor logs --totals` 基于 `gseq` watermark 跨 run 汇总各 run `run_completed.usage` token/cost；**零内核写、不落第二真相**（断言不新增持久表/不改 per-run 权威）。commit：`feat(surfaces): session usage totals as a run_completed read projection over gseq`。
- [ ] ~~**TB5 metrics/OTel exporter**~~ → **已删（评审 MAJ-6）**：与 D8 stdlib-only 相左、不在 P10 DoD；移出至 §2「不做」，真需求 + 独立 ADR 再开（仅保留 `trace_id` 作普通键进 `fields` 的既有接缝）。

### Lane C · 评测回归网（tests/evals / scripts / CI）

- [ ] **TC1 确定性 eval 套件（scripted provider，无 key/无网络）**。涉及层：tests/evals、`providers/fake.py`、pyproject（`evals` marker）、`.github/workflows`。依赖：**A+B 稳定**（须能测"压缩不丢事实召回"与"投影不双投"）。**真依赖点名**：既有 `test_p4_memory_eval.py` 已是"写→检索→distill→再检索"确定性形状但只覆盖记忆；扩为任务级套件——含压缩 fact-recall（DoD-A①）、SSE+CLI+OpenAI 三消费者各投影一次（承 P9 canary `test_p9_*`）。**判红用例**：无 `LITELLM_API_KEY`/断网跑绿；脚本化 provider 注入经组合根（与 loop 测同款）。指标：pass-rate/token/cost。⚠ **反假绿（评审 MAJ-5）**：eval **必专测压缩路径本身**，没有启发式 distiller 天然保留事实的混淆——事实放于会被逐出的**中段**（非 head/tail 保护区），断言其经 `recovery_pointers`/`summary` **回读命中**（`memory_search` 或 covered_hash 校验读）；突变="去掉写锚生产" → 必红；与 TA1 单元级（纯 `reduce`）分层不混。commit：`test(evals): deterministic task-level regression net on scripted provider`。
- [ ] **TC2 回归阈值钉定 + 反假绿**。涉及层：tests/evals、CI job。依赖：TC1。**判红用例**：pass-rate 基线钉进仓库（阈值不劣化）；注入"压缩丢事实"或"投影双投"变异 → eval 必红（突变验证，承 memory"新判据须 stash 突变证红"）；eval lane **独立、先非阻塞**（承 G-L7 夜间/独立形状），稳定后再议是否提阻塞。真 LLM 端到端单列 `UNVERIFIED`、**不进阻塞、不写进已验证**。commit：`test(ci): pin eval regression thresholds and mutation-proof against fake-green`。

### Lane D · 卫生面回收（providers / StorePort）

- [ ] **TD1 claim/delivery/lease 账本裁剪**。涉及层：L5 `providers/store_sqlite.py`、`contracts/ports.py`（增量 `prune`/`reclaim` 方法）。依赖：ADR-0050、承 ADR-0047。**真依赖点名**：P9 加 claim/delivery/lease 账本**只增不回收**（现无 prune/delete 方法，现场核 ports.py 无 gc）——账本无界增长。**判红用例**：裁剪只删 acked 且过 horizon 的 delivery 行 + 过期/已释放 lease；派生视图可安全回收、不碰 `event_log`；未知 `store_schema_version` fail-closed 不放松。commit：`feat(store): reclaim acked delivery and expired lease rows`。
- [ ] **TD2 artifact 孤儿 GC + terminal-run session cleanup**。涉及层：L5 `providers/artifact_store.py`（现**无 GC/read 方法**，仅 `put_text/put_bytes`，现场核）。依赖：TA1/ADR-0050。**判红用例**：只删"不被任何保留事件/检查点/未完成 run 引用"的孤儿 artifact；内容寻址去重 → 删前确认无其它 run 引用同 digest；terminal 且不在 `list_unfinished_runs` 的 session 才可 cleanup；**绝不删活跃 `recovery_pointers`/未裁事件所引 artifact**。commit：`feat(store): reachability-safe artifact GC and session cleanup`。
- [ ] **TD3 `event_log` 裁剪后置登记（无代码）**。产出：ADR-0050 内点名理由 + `docs/pitfalls.md`/ROADMAP §1.5 回填——压缩恢复与回放权威要求 append-only 不裁。commit：并入 T0/ADR-0050（文档 commit）。

### T-final · 全量回归与收尾（活文档）

- [ ] **TZ1 全量质量门**：`uv run pytest -q` 零回归 + 新用例、ruff、`lint-imports` 契约 kept、protocol schema 既有 type 零 diff、`check_*` 全 `--self-test` 判红 + fail-on-empty、冷导入逐模块、Windows 真机 leg、UTF-8 锁定。commit：`test(p10): full regression and dod assertions across all four lanes`。
- [ ] **TZ2 活文档回填**（AGENTS §5.5）：ROADMAP §1.5 P10 备注（三子系统落定 + observability 配额兑现）、CHANGELOG `[Unreleased]`、design/01 §5/§13、design/02 §10、design/06 §6、`docs/log/{DESIGN,PLAN}.md`（刀 3 状态）、`docs/pitfalls.md` 若新增架构陷阱、`STRUCTURE.md` S7（OTel 适配器若落）。commit：`docs(p10): backfill living docs and close blade-3 hooks`。

---

## 5. 契约与红线自检（C1–C20 逐条 + 协议只增核验 + 顺带发现登记）

### 5.1 逐条对照 HARD-CONSTRAINTS（现场数以文件为准 = C1–C20）
- **C1/C14 分层方向**：压缩只在 L1/L2、观测在 observability/surfaces、回收在 providers/store；`kernel` 不 import policy/surfaces 实现；OTel 若落必在九文件**之外**的适配器（G-L1 内核零依赖不破）。□触分层 → ADR-0048/0049/0050 先行。
- **C2 单写者+COW**：压缩 = `CompactContext` Command→reduce→新 State，**绝不 out-of-band 直改 `context.items`**（TA1 判红③锁死）；投影只读订阅不改 bus 持久化路径。
- **C3/C13 视图 vs 快照 / 单真相**：`pre_compact` 补点走既有 `save_checkpoint`；追踪面板/`logs`/usage 聚合**全部从 `event_log` 读侧派生、不落第二真相**（DoD-B/DoD-D）。
- **C5/C6 事件内外分层只增**：`compact_*` additive、`v` 不 bump、未知 type 静默忽略（错误类除外）；四处 lockstep（TA2）。
- **C7/C10 终止与回滚**：压缩不引入第二终止路径；provider 摘要失败经 C19/ADR-0028 归一、不带崩宿主、已发事件不撒销。
- **C8/C18 有界**：`covered_hash`/`recovery_pointers` 有界、preview 有界 N、`compact_applied` data 无正文；artifact 走 ADR-0019 指针不塞全文。
- **C11 谨慎演进**：`CompactionConfig` 新字段 additive；不动已锁接缝。
- **C12 非分布式**：跨机后置；本 Phase 单机。
- **C15 守卫可信**：所有新守卫 `--self-test` 能判红 + fail-on-empty + `boundaries` 独立 blocking job；新 `check_*`（eval determinism / preview 键）注册进同 job。
- **C16 Command Inbox 唯一写入口**：`CompactContext` 经 controller 串行消费，surfaces 不得直接 reduce。
- **C17 权限/floor 优先**：压缩不改权限；`_settle_open_calls` 补执行仍照走 ask/floor，绝不绕过审批。
- **C19 回发前配对关卡 + 不崩宿主 + 不是并行通行证**：压缩只在 `closed_prefix` 内截、尾窗保留（TA7 专项）；工具并行 gate **不在本 Phase 读 `parallel_safe`**（矛盾 5）。
- **C20 观测面非第二载体（含"不越界"款）**：preview 采 C20 明许的"**显式授权 + 独立通道 + 有界截断**"三闸（TB3）；主干 `_DATA_KEYS` 不新增载荷键、D4 零原文不变；`peer_*` 承 ADR-0042 **不进投影白名单**（若刀 3 要进须另评，plan 待拍板 D-6 现场重决）。
- **C4/C9**：压缩→L2' 蒸馏经 `WriteMemory`→reduce→`MemoryStorePort`（C4）；无新权限面。

### 5.2 协议只增核验
- `compact_started`/`compact_applied`：只加 `type` + 可选 `data` 字段，**不破信封 `{v,seq,run_id,turn?,ts,type,data}`、不动关联键 `{run_id,turn,tool_call_id,card_id,item_id}`、不动终止序**（design/02 §1/§6/§10）。`check_protocol_schema --check` 既有 type 零 diff + 新 type `$defs`（`additionalProperties:false`、`maxLength` 定死）。

### 5.3 顺带发现登记（现场实读所得，不"顺手改")
1. **守卫脚本现场数 = 12、非 11**：`check_{cross_run_no_bypass,desktop_csp,layering_ast,log_kernel_isolation,openai_compat_schema,output_budgets,projection_whitelist,protocol_schema,replay_determinism,secret_projection,thin_client,thread_leak}.py`。任务描述"11 守卫"与现场差一——按现场为准，`boundaries` blocking job 实注册 Python 侧子集（`desktop_csp`/`thin_client` 属桌面 lane）。登记不擅改，交付报告据实写。
2. **`FileSystemArtifactStore` 文档与实现不符**：docstring 称"按 run 隔离"（artifact_store.py:20-21），但落盘路径 = `root/{digest}{suffix}`、**run_id 未进路径**（仅校验安全标识）→ TD2 GC 的"session cleanup"不能靠路径按 run 删（内容寻址本就跨 run 去重）。TD2 据"引用可达性"而非"按 run 目录"实现 GC；此处"文档声称 vs 实现"偏差回填 ADR-0050/CHANGELOG，不回改历史。
3. **`Checkpoint.kind` 无枚举强校验**：`pre_compact` 仅注释列举（state_schema.py:279）。本 Phase 靠 loop 只发合法 kind + reduce fail-closed 兜，不新增 enum（避免破 draft 字段，C11）。
4. **`reduce` 完全不处理 `RequestCompactHint`**（advisory 现被丢）：符合 I2"仅建议不强制"；TA4 明确"内核读压力信号但不被 hint 强制"，advise 语义不破。
5. **`usage_delta` 为"已声明、已进外部白名单、但生产路径从不发射"的死类型**（现场核：contracts/events.py:321 + kernel/events.py:63 定字段 + projection.py:35 live-only 丢弃，但全 `src/` 无发射点）——驱动本 Phase 一度误将其定为聚合源（评审 MAJ-4 纠正为 `run_completed.usage`）。登记不擅改；若日后启用需先补发射+入 durable。

---

## 6. 测试与守卫扩面

- **单元**：`reduce(CompactContext)` 截断范围/写锚/fail-closed 三判例（TA1）；`RecoveryPointer.matches()` 篡改判红；`CompactionConfig` 阈值单源计算（TA4）；启发式摘要确定性（TA5）；preview 有界+脱敏（TB3）；projection 键不新增（TB3）。
- **集成**：压缩后回发前配对（TA7）；`test_p7_out_of_band_projection` 扩双订阅恰一行（TB1）；`--log-payload` 端到端主干零原文 canary（真子进程 grep，承 `test_log_zero_plaintext.py`）；`questor logs` 只读 canary（跑前后 store 快照不变）。
- **evals 任务级**（DoD-C）：`tests/evals/` 扩面，`pytest -m evals` 独立选；scripted provider、无 key/断网；含压缩 fact-recall + 三消费者投影一次；pass-rate/token/cost + 阈值钉定 + 突变反假绿。
- **守卫扩面**：
  - `check_replay_determinism.py` **+ 压缩 fixture**（TA6，`--self-test` 判红）。
  - `check_protocol_schema.py` 对新 `compact_*` 的 enum/$defs/白名单/TS 四处 lockstep（TA2）。
  - `check_projection_whitelist.py` **确认 preview 键不进 `_DATA_KEYS`**（TB3 判红：加载荷键即红）。
  - **新守卫**（据实命名并入 `boundaries`）：eval determinism（同输入两次跑 eval pass-rate 逐指标一致，防时序漂移）；GC reachability（断言不删活跃 `recovery_pointers`/未裁事件所引 artifact）。
  - `check_log_kernel_isolation.py` 若日后再落 OTel 适配器须证内核九文件仍 stdlib-only（本 Phase 不引 OTel，见 §2.7）。
- **冷导入 + 静态**：`import questor.observability`/各新模块逐个冷导入；`lint-imports` 既有契约（含第五内核隔离契约）kept。
- **locale / 跨平台编码钉宿**：所有 subprocess 读 `encoding="utf-8"`；CLI 用户可见输出 ASCII 化（承 memory「用户可见输出 ASCII 化」+ cp936 崩溃教训）；`questor logs` 渲染非 UTF-8 字符不 `UnicodeEncodeError`；Windows 门控用例标 `[非阻塞·夜间]`（承 G-L7）。

---

## 7. 落地风险 & 备选

| 风险 | 触发条件 | 缓解 | 备选 |
|---|---|---|---|
| 压缩裁掉 `recovery_pointers` 指向的原文 | 与 event_log 裁剪/GC 同 Phase 误接 | 本 Phase **不裁 event_log**（§2.5）；GC 只删非权威 artifact 且引用可达（TD2 判红） | 现在裁 → 否（破坏恢复与回放权威，ADR-0050 点名） |
| 压缩孤儿化 open tool_use | 中段折叠吞掉未回填 tool_use | 只在 `closed_prefix` 内截、尾窗保留；TA7 专项 + `_stream_turn` 关卡守 | 靠"模型当轮不并行"赌运气 → 否（C19 原述） |
| 压缩非确定性 → 回放漂移 | summary 走真 LLM、结果不可复现 | 默认启发式确定性摘要（TA5）；provider 摘要仅可选门且**产物写进 `Domain_State.summary` 随 checkpoint 持久、回放只恢复不重算**（BLK-1）；`check_replay_determinism` 压缩 fixture | 回放重跑摘要器 → 否（provider 路径不可复现） |
| preview 把 prompt 抄进主干 | preview 误写 trunk 或进 `_DATA_KEYS` | 三闸（独立 llm 通道 + 有界 + 脱敏）+ `check_projection_whitelist --self-test` 判红 + 真子进程 canary | 默认 2000 字 preview（DeepCode 型）→ 否（D4 破） |
| 带外投影仍双投 | 新 surface 又各自 `log_envelope` | TB1 收口 bus 级一处只读订阅 + 双订阅恰一行判红 | 逐消费者投影 → 否（pitfalls #5） |
| eval 用真 LLM 冒充已验证 | 无 key 环境跑不出确定性 | scripted provider 确定性判据；真 LLM 单列 UNVERIFIED、不进阻塞 | 真 LLM 进 DoD → 否（"未验证冒充已验证"） |
| OTel 破坏内核零依赖 | 内核 import OTel SDK | **本 Phase 不引 OTel**（移出至 §2.7/MAJ-6）；日后若落则 sink 只在九文件外适配器、`check_log_kernel_isolation` 守 | 内核直接引 → 否（G-L1 红） |
| usage 聚合退化成第二真相 | 聚合结果落新表 | 读侧 `gseq` 投影、每次现算（DoD-B④）| 物化 session 总额表 → 否（C13） |
| GC 误删活跃 artifact | 内容寻址跨 run 去重、按 digest 删 | 删前全量可达性扫描；TD2 判红 | 按 run 目录删 → 否（去重下错删） |
| 裁 acked delivery 行破 exactly-once | delivery 视图从永不裁剪的 `event_log` 重建、rebuild 重 claim | **只回收 lease/超 TTL in-flight claim、不裁 acked delivery 行**（BLK-2，绑 event_log 裁剪后置） | 按 horizon 裁 acked → 否（双投） |
| session artifact cleanup 虚标 | 不裁 event_log → 终态 run 事件所引 artifact 永不可删 | P10 只做孤儿扫描；session 级回收绑 event_log 裁剪后置（MAJ-7） | 虚称 session cleanup → 否（不可安全落地） |
| eval 假绿（启发式天然留事实混淆压缩召回） | distiller 全量保事实、压缩坏也绿 | TC1 专测中段事实经 recovery_pointers/summary 回读；突变"去写锚"必红（MAJ-5） | 只测 distiller 保留 → 否（未测压缩路径） |
| ADR-0042 "D-6 peer 事件进不进刀 3 日志"未决 | 观测面白名单扩不扩 | 开工前置门明确拍板（默认**不进**，多 agent 排障看事件流；要进另评） | 默认全进 → 否（C20） |
| reduce 不纯致压缩回放漂移（二轮 MAJ-8） | pre_compact 快照尾重放含 CompactContext、reduce 内重算摘要/哈希 | 摘要/锚由 loop 侧算好随命令携带、reduce 纯应用；TA1 判红④（同命令两次 reduce 逐字相等） | reduce 内算摘要 → 否（不纯、破确定性） |
| 投影收口只盖 CLI、兼容/HTTP 侧丢（二轮 MAJ-9） | observer 只挂一条总线、其余生产者走直驱 | TB1 覆盖三生产者 + 逐生产者行数守恒判红 | 只收口 bus 一侧 → 否（刀2 偏差#4 重现） |

---

## 8. 收尾与开工前置门

### 8.1 收尾（活文档，AGENTS §5.5）
- [ ] 偏差回填 ADR-0048~0051 与各 design/*（reality-wins：如 artifact 路径文档不符、守卫数 11→12）
- [ ] ROADMAP §1.5 P10 备注（四 lane 落定 + observability 配额兑现）
- [ ] CHANGELOG `[Unreleased]`（Added：可恢复压缩/刀 3 消费面/回归网/卫生回收；Fixed：投影双投收口；provenance 注）
- [ ] `docs/log/{DESIGN,PLAN}.md` 刀 3 状态收口（§14 命令、§12 preview、偏差 #4 消解）
- [ ] `docs/pitfalls.md` 若实现中撞出跨子系统架构陷阱则据实补（普通 bug 走 Issue `Fixes #N`）
- [ ] §0 表行号终检（交付前防 stale）+ 许可逐仓复核

### 8.2 开工前置门（缺一不可）
1. **本文 §0 peer-scan 表在开工当天逐行重验 `file:line` + 逐仓 LICENSE 复核**（ROADMAP §0 硬门槛：§0 未填=不可开工）。
2. **两路对抗评审 Blocker/Major 全关**：① 契约完备/不变式破坏/压缩确定性/第二真相；② 范围漂移/安全边界/载荷外泄到观测面/eval 假绿/真并发 blast radius（承 memory"对抗式验收审计员工作纪律"）。**本计划已过两轮对抗评审**（首轮 2 Blocker+7 Major、二轮回归自查 2 Major：reduce 纯函数 MAJ-8、投影覆盖面 MAJ-9）——均已在正文回填关闭；开工前允许评审再提新 Blocker/Major 则回本文修订后重审。
3. **ADR-0048~0051 先行落档**（T0 先 ADR、后代码，ROADMAP §5）。
4. **worktree 隔离**：`d:\DEVELOP\Project-main\questor-p10-hardening`、分支 `feat/p10-hardening`，从最新 `main` 切（承"多窗口切分支提交落错分支"教训，禁主工作区切分支）。
5. **push/merge 逐次征询**：每次 commit/push 须经用户当轮明确许可（AGENTS §6）；PR-only（ADR-0012），**本地合用 merge commit、不 squash**；push 前走 L3 深度安全评审（观测面涉凭据/隐私）。

### 8.3 commit 规范
- 标题 `feat:/fix:/test:/docs:` **小写动词开头**（CI pr-lint 拦大写/中文）；正文述真实工程动作、不伪造时间/作者；每任务一原子 commit（见 §4 各条 commit 文案）。

---

## 附：七处真矛盾裁决一览（决策完备，供对抗评审直击）

1. **范围切分**：**一份 plan/10**、按依赖排序分 **A/B/C/D 四 lane** 交付；判据=三子系统代码面基本不重叠可并行，但 C（eval）依赖 A+B 稳定、D（GC）依赖 A。每 lane 可独立交付并 merge（A 独立兑现"压缩不丢事实召回"、B 兑现"追踪面板基于事件流"、C 兑现"任务级回归网"、D 卫生）。
2. **可恢复压缩硬不变式**：内核决定（I2，advise 仅 advisory）；`CompactContext` 经 Command→reduce→durable（禁 out-of-band，C2/C16）；**截断前**写 `recovery_pointers(covered_hash)` fail-closed（ADR-0024 转正）；只在 `closed_prefix` 内截、尾窗保留（C19）；发 `compact_started/applied`+`baseline_seq` 栅栏；`pre_compact` 补点；回放确定性（`check_replay_determinism` 压缩 fixture）；阈值单源 + `CompactionConfig` 取代 `disable_compaction`；摘要默认确定性启发式（可复现）、provider 摘要可选门；L2' 蒸馏桥转正。**【评审回填】**摘要属 `Domain_State` 权威随快照持久、**回放不重算**（BLK-1）；`recovery_pointers` = durable `event_log` seq、原文从 log 回读（MAJ-1）；迭代压缩只追锚（MAJ-2）；`baseline_seq` 不强制 resync（MAJ-3）；**摘要/锚由 loop 侧算好随 `CompactContext` 携带、reduce 纯应用不重算（二轮回填 MAJ-8）**。
3. **observability 刀 3**：追踪/`logs`/usage 聚合**全部读 `event_log`、旁路只读、零第二真相**（C13/C20）；投影收口 bus 级一处只读订阅（pitfalls #5）；usage 聚合取 durable `run_completed.usage`（**不用 never-emitted `usage_delta`**，MAJ-4）；**OTel/metrics 移出本 Phase**（破 D8 stdlib-only、不在 DoD，MAJ-6）；`--log-payload` preview 三闸（显式授权+独立 llm 通道+有界截断），**主干零原文不变、`_DATA_KEYS` 不新增载荷键**。
4. **eval 网确定性 vs 真 LLM**：CI 无 key/无网络以 `ScriptedProvider` 出确定性 pass-rate/token/cost；回归阈值钉进仓库 + 突变反假绿；真 LLM 端到端单列 **UNVERIFIED、绝不写进已验证**；provider 注入经组合根；eval lane 独立先非阻塞、稳定再议提阻塞。
5. **工具 reader/writer gate + 真并发**：**再次显式后置独立并行化 Phase（post-P10，未立项）**，ADR-0051 点名 owning phase、同步 HARD C19 `:108`/ADR-0039 措辞；不叠 C19 串行配对的高 blast radius；不"注释说 P# 其实没人做"。
6. **卫生面归位**：**进**——lease/TTL 账本回收（**不裁 acked delivery**，BLK-2）+ artifact **孤儿** GC（**不做 session cleanup**，MAJ-7）+ usage **读 `run_completed.usage`** 投影聚合（TB4/MAJ-4）；**再后置**——`event_log` 主干裁剪 + acked delivery 回收 + session 级 artifact 回收（三者绑定，与 `recovery_pointers`/单真相冲突，ADR-0050 点名理由）。
7. **范围纪律**：见 §2「本 Phase 不做」十条（不跨机/不下沉 Shell/additive 不 bump `v`/不造 speculative infra/不加回 P6/不做工具真并发/不裁 event_log/真 LLM 不进 DoD/embedding-trigram 另 Phase/不改蒸馏原子性纪律）。
