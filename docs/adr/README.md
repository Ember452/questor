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
