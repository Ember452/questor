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
| [0020](./0020-durable-write-gate-and-log-authority.md) | 耐久写门（durable 永不半 tool_use）+ log 权威顺序 | ✅ |
| [0021](./0021-cross-process-resume.md) | 跨进程续跑协议：快照+重放尾+回填修复+幂等 re-dispatch | ✅ |
| [0022](./0022-dual-cursor-watermark.md) | 双游标物化到 StorePort：per-run 逻辑 seq + 全局物理 watermark | ✅ |

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
