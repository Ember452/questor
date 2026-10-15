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
