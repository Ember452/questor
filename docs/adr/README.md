# ADR 索引（架构决策记录）

> ADR = 记录**重要且难以回退**的设计决策：为什么这么定、否掉了哪些备选、留下什么后果。
> 母文档是 [`../VISION.md`](../VISION.md)；细节契约在 [`../design/`](../design/)；这些 ADR 是"为什么"的历史账。
> 状态：✅已接受 / 🚧待定 / ↩️已取代。

| # | 决策 | 状态 |
|---|---|---|
| [0001](./0001-from-scratch-not-port.md) | 从零自研，questor 为全新仓库（放弃移植 CowAgent 路线） | ✅ |
| [0002](./0002-tech-stack.md) | 技术栈：Python 运行时 + Tauri v2 桌面 + LiteLLM 模型层 + Python sidecar | ✅ |
| [0003](./0003-layering.md) | 八层分层 + 依赖倒置 + Harness = pure mechanism | ✅ |
| [0004](./0004-state-mutation-model.md) | 状态变更模型：单写者 + Command/Event + 只读视图(COW) | ✅ |
| [0005](./0005-state-storage.md) | 状态存储：事件溯源为主 + turn 边界轻量快照为辅 | ✅ |
| [0006](./0006-permission.md) | 权限三态决策一等 + 沙箱后端可插拔 | ✅ |
| [0007](./0007-transport.md) | 传输：统一 HTTP+SSE，Tauri 内嵌 webview（非私有协议） | ✅ |
| [0008](./0008-evolution-strategy.md) | 演进策略：接缝早锁字段后锁；v1 只森林、DAG/远程/分布式预留 | ✅ |
| [0009](./0009-policy-pluggable.md) | 策略可插拔：run 内快照冻结、热替换=新 run、AB 按 fingerprint | ✅ |
| [0010](./0010-error-classification-layer.md) | 错误分类=纯函数进 contracts、重试/fallback 编排=Kernel | ✅ |
| [0011](./0011-seq-semantics.md) | seq 语义：per-run 逻辑序 + 全局物理序（两游标） | ✅ |
| [0012](./0012-branch-policy.md) | 分支/推送策略：**2026-10-16 已切换到 B = 全量 branch + PR**（门禁是 CI blocking job，非人工 review） | ✅ |
| [0013](./0013-run-command-inbox.md) | Run 级 Command Inbox：外部审批/取消/模式变更均经 Kernel 串行入口 | ✅ |
| [0014](./0014-permission-context-authoritative.md) | PermissionCtx 唯一真源；权限引擎改纯函数 | ✅ |
| [0015](./0015-sandbox-capability-floors.md) | OS capability floor 高于 mode；无写围栏不得静默放行 | ✅ |
| [0016](./0016-tool-lifecycle-approval-identity.md) | ToolCall 完整生命周期 + ApprovalRequest 幂等标识 | ✅ |
| [0017](./0017-platform-shell-ir.md) | Shell dialect 化 IR；Windows PowerShell 一等支持 | ✅ |
| [0018](./0018-harness-owned-process-runner.md) | 子进程执行由 Harness ProcessRunnerPort 唯一拥有 | ✅ |
| [0019](./0019-bounded-artifact-projection.md) | 大输出有界 artifact envelope；写失败不回落原文 | ✅ |
| [0020](./0020-durable-write-gate-and-log-authority.md) | 耐久 checkpoint：完整快照 + 派发侧补齐 + log/snapshot 双权威 | ✅ |
| [0021](./0021-cross-process-resume.md) | 跨进程续跑协议：快照+重放尾+回填修复+幂等 re-dispatch | ✅ |
| [0022](./0022-dual-cursor-watermark.md) | 双游标物化到 StorePort：per-run 逻辑 seq + 全局物理 watermark | ✅ |
| [0023](./0023-memory-subsystem-placement.md) | 记忆子系统定位：跨层独立子系统包 `memory/`（非 L7）；落库经独立 `MemoryStorePort`+`memory.db` | ✅ |
| [0024](./0024-memory-contract-evolution.md) | 记忆契约演进：typed `WriteMemory` + `memory_written` 事件 + `recovery_pointers` covered_hash + 快照 v3 | ✅ |
| [0025](./0025-memory-distill-atomicity.md) | Deep Dream 离线蒸馏的单写者边界与原子性纪律 | ✅ |
| [0026](./0026-memory-retrieval-bounded-projection.md) | 混合检索栈（rank-normalize 融合/时间衰减/降级）与有界投影 | ✅ |
| [0027](./0027-observability-logging-foundation.md) | 日志骨架：双通道 + LogEntry 中间表示 + 零原文载荷 + 按日切 + 主动降级（补债，实现见 `docs/log/` 刀 2） | ✅ |
| [0028](./0028-pairing-gate-and-provider-fault-normalization.md) | 回发前配对关卡（provider 请求唯一闸口）+ provider 故障归一终态；接上 ADR-0010/plan-01 T4 的错误归一 | ✅ |
| [0029](./0029-parallel-tools-deferred-beyond-p5.md) | `parallel_safe`/`barrier` 从 P5 移出、推迟到专门的并行化 Phase（P5 执行严格串行）；修正 ADR-0028「并行归 P5」一句 | ✅ |
| [0030](./0030-adopt-official-mcp-sdk.md) | MCP 客户端采用官方 `mcp` Python SDK（stdio transport）；依赖随首个真连接提交落地，env/凭据/账本/配对仍在 Harness | ✅ |
| [0031](./0031-reference-repo-reuse-no-attribution.md) | 参考仓复用已获全体作者授权；取消文件内 provenance/许可标记要求（P0–P5 既有记录保持不变，仅面向未来）；同步修订 AGENTS §4.5/§5.6 + CONTRIBUTING | ✅ |
| [0032](./0032-p7-sidecar-serve-and-process-boundary.md) | P7 sidecar serve 接线与进程边界（D-P7-B）：HTTP+SSE loopback `127.0.0.1:0` + generation bootstrap；具体 store 装配留组合根 `__main__ --serve`、`surfaces/serve` 不 import store 实现（补 ADR-0007 落地细节） | ✅ |
| [0033](./0033-p7-bus-level-out-of-band-projection.md) | 带外投影收口为 bus 级只读订阅（D-P7-A）：一 run 恰投一份、删 `cli._stream` 逐消费者 `log_envelope`；协议零 diff、九内核零依赖不破（收口 plan/05 §0.4 缺口） | ✅ |
| [0034](./0034-p7-reconnect-message-completed-final-text.md) | 断线重连在途文本恢复 = `message_completed` additive 有界 `final_text`（D-P7-C 选型①）：定稿正文进 durable 事件帧、`after_seq` 重放自足恢复、单一真源不另开 /transcript 第二读面；有界+artifact 溢出、不进投影白名单；半条在途 delta 标 UNVERIFIED | ✅ |
| [0035](./0035-p7-additive-tool-event-and-node-shape.md) | 工具事件 additive `preview`/`artifact_ref`/`truncated` + `node_updated` 定形（T7/T11）：只加可选字段不破 type/关联键/版本、三处 lockstep、C20 白名单不含原文 | ✅ |
| [0036](./0036-p6-dropped-from-roadmap.md) | **P6（多模态/语音）整阶段从路线图移除**：语音+图像全砍、编号不重排；v1 后序列 = P8→P9→P10；逆转路径定为 L5 provider + L6 surface 接缝上的按需扩展（复用 ADR-0019 有界载荷）；P9 新增非文本请求体归一化拒绝判据；核实多模态事件 `type` 占位从未落地（旧文档误记） | ✅ |
| [0037](./0037-dag-validation-scope-in-p8.md) | I6 语义修订 + P8 的 DAG 启用范围：拆开"reduce 校验/拓扑调度器/fan-in 恢复"，P8 只落**依赖校验**（无环/悬空/自环/终态唯一，在 reduce 内 I1）+ 读侧就绪判定；拓扑调度器与 `edge_kind/path/depth`、`WAITING_CHILDREN` 后置；快照 schema 保持 v3、fail-closed 不放松；细化 ADR-0008 DAG 条款 | ✅ |
| [0038](./0038-subagent-as-independent-run.md) | 子 agent 本体 = **独立 Run**（同进程 asyncio 多 run、经 `assigned_run_id` 关联）：跨 run 通信一律 Command→reduce（无旁路直写）；seq 走两游标、快照各落、`--resume` 用 `list_unfinished_runs`；取消=冻结子树经 `Cancel(owner)` 不硬杀；exactly-once v1=**at-least-once+去重键**（claim 账本后置 P9、跨机属 C12）；载荷走 artifact 指针 | ✅ |
| [0039](./0039-parallel-gate-attribution-recut.md) | 并行 gate 归口再决（收 ADR-0029 悬置）：**子代理 fan-out admission gate 落 P8**（run 级、wuu spawn_slot reservation）；**工具 reader/writer gate + 真并发派发显式再推后**（P10 或独立 Phase）；执行仍严格串行、不读 `parallel_safe`/`barrier` 改派发 | ✅ |
| [0040](./0040-child-permission-inheritance-narrowing.md) | 子权限继承收缩（**fail-closed、子⊆父永不放大**）：`denylist` 只扩大、`rules⊆父`、`mode` 不继承（子默认 default）、floor 同 OS 不放宽；子 ask 归子自审、`request_id` 前缀 `child_run_id` 跨 run 幂等；策略层无裸句柄（hermes 子集判据） | ✅ |
| [0041](./0041-fanout-budget-and-runaway-control.md) | fan-out 预算与失控终止：`max_parallel_children`(默认4)/`max_tree_depth`(默认1) reservation 防超发；usage 归 per-run 不汇聚父（聚合归 P10）；超限终止序 E2 取消>安全>超时>预算、父耗尽递归 Cancel 子树 | ✅ |
| [0042](./0042-peer-event-additive-shape.md) | 事件 additive：`peer_started`/`peer_ended` 定形（20→22 type、**不 bump `v`**）；只带关联键+有界 status+`result_ref` 指针、无正文；`node_updated` 白名单不扩；三处 lockstep + C20 不进投影白名单；兑现 design/02 §7 生长场景 | ✅ |
| [0043](./0043-openai-compat-projection-adapter.md) | OpenAI 兼容 = **投影适配器**：入站经 Command Inbox（C16）、出站只读投影成 OpenAI SSE（design/02 §9 X5/§10 映射表）；**wire 单一真源=独立 `openai_compat.schema.json`+`contracts/openai_wire.py`、questor `v` 不 bump**；**无原生续传=断连即取消**；带外零双投（承 ADR-0033）；**独立鉴权外部 API lane**（对 ADR-0032 分道 scoping、opt-in 非 loopback + 强制 API-key fail-closed + 保守权限 C17） | ✅ |
| [0044](./0044-non-text-content-normalize-reject.md) | 非文本/语音 content part **归一化拒绝**（承 ADR-0036 决策5）：surface fail-fast 返 HTTP 400 OpenAI error（不起 run、不崩、不静默降级）+ defense-in-depth 走 ADR-0028 归一 `run_failed`；additive `ErrorKind.UNSUPPORTED_MODALITY`；README/VISION 诚实"仅文本模态" | ✅ |
| [0045](./0045-policy-registry-and-run-policy-ref.md) | `PolicyRegistry` 落 **L4 `policy/registry.py`**（进程内、kernel 不 import、组合根解析注入保 C1）：trust project>user>system、错误二分 Unknown/Broken 留名、fail-open 默认+WARN（C10）；发现=固定名册无磁盘 HMR；`Run.policy_ref`+`run_started.policy_ref` additive 不 bump `v`；热替换=新 run、AB 按 fingerprint（design/05 §6 落地） | ✅ |
| [0046](./0046-capability-hot-plug-host.md) | 能力热插拔宿主：**不移植 cordis TS 容器**，只薄 `PluginLifecycle(init/teardown)`+`PluginHost` 熔断护栏（C10）复用已存 tools/skills/mcp 注册点；热插只影响下一 `freeze_for_run`、活 run 面不变；`tools_changed` = **live-only 告警**（入 `LIVE_ONLY`、不占 seq、由 loop 在 generation bump 处发）；无磁盘 HMR（C12） | ✅ |
| [0047](./0047-cross-process-claim-delivery-run-lease.md) | 接回 P8（ADR-0021/0038 后置）：`StorePort` 增量 `claim/delivery_state/ack` + 单机多进程 `run_lease`（epoch）；投递视图**从事件重放重建、不第二真相**（C13/C15）；真接 `ReportChildTerminal`；两真 OS 子进程共享 SQLite 端到端验单机多进程（DoD⑦ 已验证）、**跨机=UNVERIFIED C12 天花板** | ✅ |
| [0048](./0048-recoverable-context-compaction.md) | P10：**可恢复上下文压缩转正**——内核触发（I2、advise 仅 advisory）、`CompactContext` Command→reduce→durable（C2/C16，reduce 纯函数不重算摘要/哈希）、只截 `closed_prefix`（C19 不孤儿化 open tool_use）、截断前写 `recovery_pointers(seq_from,seq_to,covered_hash)` fail-closed（原文从 durable event_log 回读、迭代只追锚）、`compact_started/applied` additive 不 bump `v` + `baseline_seq` 栅栏（不强制 resync）、`pre_compact` 补点、`LoopPolicy.disable_compaction`→`CompactionConfig`、L2' 蒸馏桥转正（ADR-0024/0025 生产者落地） | ✅ |
| [0049](./0049-observability-blade3-consumption.md) | P10：**observability 刀 3**——`questor logs` 只读消费命令（event_log 主干 + 旁路 JSONL 按 run_id+seq 合并、零第二真相）；带外投影收口 bus 级一处只读订阅（消 ADR-0033/刀2 偏差#4 双投、覆 CLI+HTTP+OpenAI 三生产者）；`--log-payload=truncate:N` preview 三闸（显式授权+独立 llm 通道+有界截断，主干零原文不变、不进 `_DATA_KEYS`）；usage 聚合取 durable `run_completed.usage`（不用 never-emitted `usage_delta`）；**OTel/metrics 移出本 Phase**（守 D8 stdlib-only） | ✅ |
| [0050](./0050-p10-hygiene-reclamation.md) | P10：**卫生面回收边界**——`event_log` 主干裁剪**显式后置**（与 recovery_pointers/回放权威/`--resume` 冲突）；claim/delivery/lease 回收**限过期已释放 lease + 超 TTL 未 ack claim**、**不裁 acked delivery 行**（绑 event_log 裁剪、否则 rebuild 重 claim 破 exactly-once）；artifact **仅孤儿 GC**（可达性、内容寻址去重），session 级回收绑 event_log 裁剪后置；登记 artifact store docstring-实现不符（以实现为准） | ✅ |
| [0051](./0051-tool-parallel-gate-deferred.md) | P10：**工具 reader/writer gate + 真并发派发从 P10 悬置再次收口为独立并行化 Phase（post-P10、未立项）**；终结 ADR-0029/0039 三轮"P10 或独立"模糊措辞（先有 ADR 才动 HARD C19/ADR-0039 文案，ROADMAP §5）；执行仍严格串行 + 回发前配对（C19/ADR-0028），不读 `parallel_safe`/`barrier` 改派发；子代理 fan-out gate（ADR-0041）正交不受影响 | ✅ |
| [0052](./0052-permission-profile-preset-vocabulary.md) | OPT-3/OPT-4：**L0 新增 profile 词汇**——mode 词表（值/协议顺序/宽松度序）落 `contracts/profile.py`，5 处 Python 侧字面集改为引用它；`normalize` 严格精确（未知/None → default、不抛、不做大小写/别名映射）；`permission_preset_for(profile)` 只携带**收紧**旋钮、结构上不可能放宽 capability floor（C9/C17）；`protocol/event.schema.json` 仍是 wire 真源、`commandClient.ts` 本轮零改动 | ✅ |

> **0027 已落地**（原为日志骨架刀 2 预留号）：详 [`../log/DESIGN.md`](../log/DESIGN.md) §17、[`../log/PLAN.md`](../log/PLAN.md) 刀 2。

## 模板
```
# ADR-000N: 标题
- 状态：✅/🚧/↩️（日期）
- 背景：为什么要做这个决定
- 决策：定了什么
- 后果：正面 / 代价 / 需持续守的约束
- 备选(被否)：其它选项 + 为何不选
- 关联：VISION/00-layering/01-state-model/HARD-CONSTRAINTS 对应处
```
