# Questor 分层与边界（架构地图）

> 本文件是 [`VISION.md`](../VISION.md) §3 的**细化**（不另立门户、不与之冲突：VISION 是母文档，本文把"四层"展开成可落地的分层与接口契约）。
> 目的：回应"分层会不会太简陋 / 太死"——用文件夹里 6 个真实项目的分层做参照，给出一版**够细、又不把自己框死**的架构地图。纯设计文档，不含实现。

---

## 1. 先看真实项目怎么分层（证据）

| 项目 | 它把系统切成这些层（读实际目录） | 关键分层纪律 |
|---|---|---|
| **DeepCode** `core/` | `domain` / `application` / `harness(permissions·sandbox·approval)` / `loop` / `events` / `providers` / `persistence` / `observability` / `plugins` / `skills` / `mcp` / `sessions` / `team` / `network` / `config` | **"harness = pure mechanism：只做决策与封装，绝不碰模型/UI；执行点在 kernel 与工具执行器"**（`core/harness/__init__.py:10-13`）；权限三态 allow/ask/deny + 敏感路径不可覆盖 denylist |
| **hermes** `agent/` | `conversation_loop` + `turn_*`（阶段）+ `_LoopState`（显式状态对象）+ `context_compressor`（压缩子系统）+ `credential_pool`/`error_classifier`/`background_review`；`gateway/` `tui_gateway/` `hermes_cli/`（多前端）+ `providers/` | 一轮 = 显式阶段流水线，**状态对象是阶段间唯一接口**；传输面(gateway/cli)与运行时分离 |
| **wuu** `internal/` | `appserver`(HTTP/JSON-RPC 面) / `agentcontrol`(spawn·lease·mailbox 编排) / `agent`(loop·stream_runner·tool_runtime·compaction) / `providers` / `context` / `compact` / `agentthread` / `activity` / `clients` | **编排、运行时、传输、provider 各一层**；审批(`approvefor`)是独立缝；租约/并发在 runtime |
| **CowAgent** | `channel`(传输) / `bridge`(契约DTO + 装配，两层混合) / `agent`(protocol循环·tools·memory·prompt·skills·permission·workspace) / `models` / `common` | 三层事件协议；契约叶子(context/reply)与装配(agent_bridge)本应分层却混在一个目录（我们引以为戒） |
| **MetaGPT** | `roles` / `actions` / `environment` / `memory` / `llm` / `document_store` / `context`(消息总线) | 角色-行为-环境三段 + 消息总线下沉为框架内核 |
| **cordis** | `core`: `Context`/`Registry`(DI)/`Fiber`(生命周期)/`events`/`service` + `hmr`/`loader`/`include` | **"服务声明依赖 + 生命周期(setup/dispose) + 可热重载"** 的宿主层——与 agent 逻辑正交 |

**结论**：成熟项目都不是"4 层"，而是**约 6-8 个纵向职责层 + 若干横向设施**，且都遵守一条铁律——**内层定义接口、外层实现；内层永不 import 外层。**

---

## 2. Questor 分层（细化版）

自上而下 = 外层到内层；**依赖只能指向更内层**（内层不知道外层存在）。

```
L7  Shell/UI        Tauri 桌面 · Web · （未来移动）          ← 只消费事件协议
L6  Surfaces/传输    事件协议服务端(HTTP/SSE/WebSocket) · OpenAI兼容API · IM · CLI
L5  Ports 端口+适配器  ProviderPort(→LiteLLM) · StorePort(→SQLite/向量库) · Clock · Id
L4  Policy/Agent层   规划·ReAct · 反思 · 记忆策略 · 提示词    ← 可插拔，只读状态快照→返回意图
L3  Capabilities     工具注册表 · Skills · MCP · 子agent编排(agentcontrol 式 spawn/lease/mailbox)
L2  Kernel/Harness   turn 循环驱动 · 工具路由 · 调度 · 压缩 · 持久化/断点 · 事件广播 · 权限沙箱
L1  Domain/State     核心状态模型(上下文·任务树·工具调用账本·断点·权限上下文·错误栈) —— 纯数据+不变式
L0  Contracts        跨层共享的"词表"：状态 schema · 事件类型 · 工具规格 · 各 Port 接口 —— 最稳定
────────────────────────────────────────────────────────
横向 Cross-cutting： Config · DI/插件宿主(cordis式 Fiber) · Observability/日志 · 权限引擎(三态)
```

要点：
- **L0 Contracts 是解耦的地基**：L4 策略、L6 传输、L7 UI 全都只认 L0 的类型，彼此不直接依赖——这就是"改了不牵全身"的根。
- **L2 Kernel = pure mechanism**（照 DeepCode 纪律）：只调度、判权限、写状态、发事件；**永不 import 模型或 UI**——模型调用走 L5 ProviderPort，UI 走 L6/L7。
- **L4 策略可换**：ReAct/规划/记忆策略是注册进内核的"策略插件"，换算法只动 L4。
- **权限/沙箱/审批**（L2+横向）：三态 allow/ask/deny、敏感路径不可覆盖、HITL 审批、命令沙箱(平台后端 + 优雅降级) —— 单独缝，别散落。

### 谁能写状态（呼应"边界要在状态模型里定死"）
| 状态块 | 唯一写者 | 读者 |
|---|---|---|
| 会话上下文 | Kernel(经策略意图) | 策略/传输 |
| 任务树 | Kernel 调度器 | 策略/UI/断点 |
| 工具调用账本 | Kernel 工具路由 | UI/持久化/策略 |
| 断点标记 | Kernel 持久化 | 恢复器/UI |
| 权限上下文 | 权限引擎 | Kernel/工具执行器 |
| 错误栈 | Kernel（各阶段 catch→归一） | 传输(错误事件)/可观测 |

（瞬态通道：取消/进度/在途 delta —— **不进 L1 状态**，走 L2→L6 的事件流。）

---

## 3. 分层怎么"不框死"（回应"约束太死"）

分层是**依赖纪律**，不是牢笼。每条边界都做成**可插拔的注册点 + 只增不改的契约**：

| 你想换/加的 | 通过哪个缝 | 动几层 |
|---|---|---|
| 换/加**模型供应商** | L5 `ProviderPort` + LiteLLM 配置 | 0 层核心改动 |
| 换**Agent 算法**(ReAct→ToT→…) | L4 策略注册表 | 只 L4 |
| 加**工具/技能/MCP** | L3 注册表（运行时可增，工具面热更冻结） | 只 L3 |
| 加**前端**(桌面/Web/移动/IM) | L6 一个 surface + 消费 L0 事件类型 | 不碰内核 |
| 加**事件** | L0 只增不改 + "未知即忽略" | 不协调 |
| 能力**热插拔**（后期） | 横向 DI/插件宿主(cordis式 Fiber 生命周期) | 不动 loop |

三条防"框死"的元规则：
1. **依赖倒置**：内层(L0-L2)定义接口，外层(L3-L7)实现；方向永远是"外层依赖内层"。
2. **每层对上层暴露最小 Port**，不暴露实现细节（UI 只见事件协议，Kernel 只见 ProviderPort）。
3. **演进只在契约层发生**：新能力优先表达为"新事件/新策略/新工具/新适配器"，而非改内核。

---

## 4. 与 VISION §3 的关系
VISION 的四层（Agent/Harness/Provider/Shell）是本文的**粗粒度投影**：
```
Agent层        → L4  (+ 部分 L3)
Harness        → L1+L2 (+L0 contracts)
Provider/Store → L5
Shell/前端     → L6+L7
```
两份文档不冲突，VISION 保持"是什么"，本文补"切几层、边界怎么定、怎么不框死"。

## 5. 未决（写下一份前可先聊定）
- L4 策略与 L2 内核的**接口粒度**：策略返回的是"单个工具意图"还是"一段计划 DAG"？（决定任务树形状）
- 权限模型 v1 要不要三态+沙箱，还是先只做"工具白名单"后补。
- L6 传输：桌面走 Tauri event 还是统一 WebSocket（影响断线重连/续传设计）。
- 多 agent 编排(L3) 进不进 v1。

> 下一份文档：`docs/design/01-state-model.md`（L1 核心状态模型 schema，把 §2 的"谁能写"落成字段级定义）。
