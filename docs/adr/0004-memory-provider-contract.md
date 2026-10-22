# ADR 0004: Memory Provider Contract

- Status: Accepted (design; implementation deferred to Phase 3)
- Date: 2026-10-22
- Deciders: Questor maintainers

## Context

questor 要同时支持个人 agent 与编码 agent。两者在“记什么、什么时候召回、写回纪律、作用域”上不同，但底层存储/检索可以复用。外部项目（mem0、Hindsight、自研 memory）也希望接入，而不是被要求改写成 questor 的形状。

参考项目给出了三种做法：

- **内建**：Codex 的 `memories/read` + `memories/write` 两条流水线、Reasonix 的 `state/memory` 域模型、Claude Code 的 `MEMORY.md` + 主题文件 + Dream 整理；
- **外部服务 + 适配器**：Hindsight 的 `retain/recall/reflect` + banks + MCP；mem0 的 `agent-plugin-core` + 每宿主 adapter + manifest + conformance；
- **扩展钩子 + 工具 + 提示词注入**：Pi 的 extension API；mem0 的 Pi/Claude 插件通过 `before_agent_start` / `agent_end` / hooks + MCP 接入。

三者各有问题：内建不可插；外部服务有网络、超时、作用域、双写风险；扩展钩子没有宿主级作用域/事务。questor 需要“内建的一致性 + 外部的可插拔”。

当前仓库还没有 `MemoryPort`。`memory/` 是 13 个平铺文件，`services/` 里还有 memory 相关逻辑；如果先把某套 memory 写进 loop，再想换 provider，会重演 `services/` 的分叉。

## Decision

1. **三层分离**：`Policy`（宿主策略）→ `MemoryPort`（契约）→ `Provider`（外部实现）。personal/coding 的差异在 Policy，不在 Provider。
2. **宿主拥有真相与作用域**：当前真相载体是会话快照（**不预设事件溯源**）；memory 是派生索引；provider 不拥有领域真相、不改领域状态、不进内核。
3. **`MemoryPort` 最小核心**：`start/stop/health/capabilities/write/search/get/forget`；`consolidate/rebuild` 是可选 `MemoryMaintenancePort`，由 `Capabilities` 声明。
4. **Manifest + entry point 注册**：provider 包声明 `id/contract/version/factory/config_schema/requires`；宿主通过 `questor.memory` entry point 发现；contract 不匹配启动即失败。
5. **作用域由宿主构造**：`MemoryScope` 为 `global/user/project/session/run`；模型不能自己指定 global；global 必须由配置或用户显式授权。
6. **失败语义固定**：召回 fail-open（超时/500/限流 → 空 + 指标 + 熔断）；写入 outbox（不阻塞 turn）；provider 崩溃可重启/重放；`required=true` 的 profile 才在启动时 fail-closed。
7. **写入可重放**：`write` 必须带幂等键；outbox + tombstone；`forget` 后 rebuild 不得复活。
8. **预算与安全**：top_k/max_chars/max_tokens/p95_budget_ms 四道闸；写入前 redaction；召回内容是不可信数据；文件 provider 防 symlink/path traversal，HTTP provider 防 SSRF。
9. **先 File 后外部**：Phase 3 先实现 `NullMemory` + `FileMemory`（`MEMORY.md` + 主题文件），再 SQLite，再接 mem0/Hindsight/自研 adapter。
10. **runtime 不认 memory**：`runtime/turn` 只调 `ContextAssemblerPort` / `TurnSettlerPort`；memory 是 `capabilities/context` 与 `capabilities/memory` 的贡献者。
11. **conformance 是准入条件**：scope 隔离、幂等、预算、删除/墓碑、失败注入、重启/重放、旧记录可读、p95 预算，全部通过才允许注册。
12. **上线四步**：conformance → shadow（只读对比）→ canary（5% session）→ cutover（旧 provider 保留一个版本窗口）。

详细契约、代码形状、失败表和验证矩阵见 [MEMORY.md](../architecture/MEMORY.md)。

## Alternatives considered

- **只做 Pi 式扩展钩子**。拒绝：没有宿主级作用域/事务/幂等；插件各自实现，长期会分叉。
- **只做 Codex 式内建 memory**。拒绝：不可插；换 provider 要改宿主；外部项目无法复用。
- **只做外部服务（Hindsight/mem0）**。拒绝：个人桌面端需要本地优先；网络/超时/隐私/离线场景不可接受。
- **在 `runtime` 里直接调 `MemoryPort`**。拒绝：runtime 会重新认识 memory，模式差异会漏进循环；应由 context assembler / turn settler 承担。
- **让 provider 拥有事件流或领域状态**。拒绝：第二真相；回放/审计/迁移都会崩。
- **让模型自选 global scope**。拒绝：跨项目/跨用户泄漏；scope 必须由宿主构造。
- **同步远程召回**。拒绝：一次网络抖动就阻塞 turn；必须 timeout + circuit breaker + fail-open。
- **一次性支持所有 provider**。拒绝：先 Null/File/SQLite 证明契约，再上外部 adapter；避免“抽象先行、实现滞后”变成“抽象先行、永远不落地”。

## Consequences

变得更容易：

- 外部 memory 项目只写 adapter，不改宿主；personal/coding 复用同一 provider，只换 Policy。
- 换 provider 不影响 `runtime`、`kernel`、`surfaces`；回滚是配置级操作。
- 失败可定位：召回/写入/整理/启动各有明确语义与指标。
- 记忆可审计：每条 hit 有 citation，写入有幂等键与 tombstone。

变得更难：

- 需要维护 `MemoryPort` + conformance + adapter 映射；短期成本高于“直接在 loop 里写一个 memory”。
- provider 的能力差异需要 `Capabilities` 协商；UI 要处理 `ready/declared/absent` 三态。
- 文件 provider 需要处理原子写、锁、索引重建、symlink/path traversal。
- Phase 3 才能落地；Phase 1/2 只能先留目录与 Port，不能提前写实现。

必须保留的不变式：

- provider 不 import `kernel` / `runtime` / `capabilities`；只依赖 `contracts`。
- `runtime` 不 import `capabilities.memory`；只认 `ContextAssemblerPort` / `TurnSettlerPort`。
- 事件流是唯一真相；memory 是派生索引，必须可审计。
- 召回失败不阻塞 turn；写入失败进 outbox；`forget` 后不得复活。
- 模型不能自选 global scope；global 必须显式授权。

## Verification

- tests/conformance/memory/（随第一个 provider 创建）：CRUD、幂等、scope 隔离、预算、删除/墓碑、失败注入、重启/重放、旧记录可读、p95 预算。
- 基线对比：同一事件输入 + 同一 query 得到可解释的命中差异（旧 provider 与新 provider 的 shadow 对比）。
- shadow：新 provider 只读，与旧 provider 对比同一 query 的命中，不写。
- canary：按 profile/session 灰度 5%，配置一键回滚。
- import-linter / AST：provider 不得 import `kernel/runtime/capabilities`；runtime 不得 import `capabilities.memory`（这些边在对应目录创建后的下一个 PR 里加）。
- 布局守卫 check_layout（待建）：目录扇出与文件尺寸；memory 相关目录创建后才适用。
