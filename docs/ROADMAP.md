# Questor 全局路线图（把控发展，不写阶段内细节）

> 用途：**全局把控项目向"最终高可用"演进**。这里只定阶段顺序与**每阶段的可验证判据**；
> 每个阶段**开工前另写一份详细计划** `docs/plan/NN-<phase>.md`（本文件不含细节，避免与快速演进的现实脱节）。
> 设计骨架在 `docs/design/`（00 分层 / 01 状态 / 02 事件 / 03 工具 / 04 循环）与 `docs/adr/`。

## 0. "写到什么程度可以开始开发"
满足即开工 Phase 1：
1. 关键接缝**有纸面契约**：分层(00) + 状态模型(01, draft) + 事件协议(02) + 工具接口(03) + 循环骨架(04) —— 五道接缝各一份，**不必字段全钉死**（字段按 C11 后锁）；`05-policy`/`06-memory` 为**纵深文档**（策略/记忆，非门槛）。
2. 工程红线( HARD-CONSTRAINTS) + ADR 定稿，团队/未来窗口能照它自检。
3. **本路线图存在** + **Phase 1 有一份详细计划**。
4. 每 Phase 的 `docs/plan/NN-*.md` 起手 **§0 peer-repo 扫描表填全**（[AGENTS §4.5](../AGENTS.md) + [`docs/plan/_TEMPLATE.md`](./plan/_TEMPLATE.md)）—— 未填不算可开工。
> 之后每个 Phase 开工前补它自己的 `plan/NN-*.md`——"全局粗、阶段细、边做边校"。

## 1. 阶段总览（纵切优先，Phase 多切、每个可验证）

| Phase | 目标 | 进入条件 | **可验证判据（DoD）** | 详规 |
|---|---|---|---|---|
| **P0 设计骨架** | 五接缝契约 + ADR + 红线 | — | 能照文档搭出**可编译的接口骨架**（stub 全绿、import-linter 边界通过） | [plan/00](./plan/00-design-skeleton.md)；[交付报告](./delivery/P0-completion-report.md) ✅ |
| **P1 最小可跑循环** | 单模型 + `read` 一个工具 + 流式 + 取消 | P0 | 终端里"问一句→流式答一句"，能中途取消且状态/事件一致 | [plan/01](./plan/01-p1-minimal-loop.md)；[交付报告](./delivery/P1-completion-report.md) ✅ |
| **P2 工具 + 权限 lite** | 文件/shell 核心工具集 + 三态权限 + json-schema 校验 + capability floor | P1 | 危险操作触发 `ask`；`deny`/敏感路径不可越；非法参数被拒；审批/取消/超时幂等可恢复 | [plan/02](./plan/02-p2-tools-permission.md) ✅（ADR-0013-0019 已实现；[P2 交付报告](./delivery/P2-completion-report.md)；**已合入 main**：PR #19，`1f5c171`，2026-10-16） |
| **P3 持久化 + 断点续传** | 事件溯源 + 快照 + resume | P2 | kill 进程后重启能续跑/回放；`after_seq` 重连不丢不重 | [plan/03](./plan/03-p3-persistence-resume.md) ✅（ADR-0020-0022 已实现；分支 `feat/p3-persistence-resume`：真 OS 进程 kill→`--resume` + 真 uvicorn SSE `after_seq` 重连实测通过） |
| **P4 记忆 v1（灵魂）** | 短期 → 三层 + Deep Dream + 检索（详 `design/06-memory.md`） | P3 | 跨会话记住并检索到一件事；夜间蒸馏产出 | [plan/04](./plan/04-memory-soul.md) ✅（ADR-0023~0026 已实现；分支 `feat/p4-memory-soul`：DoD①②③④⑤ 集成测试通过、405 passed；真 LLM/embedding 与压缩生产者后置 P10 标 UNVERIFIED） |
| **P5 Skills / MCP** | 技能加载 + MCP 接入 | P3（仅适配器 stub 可早；完整需账本/持久化） | 丢一个 SKILL.md 即生效；挂一个 MCP server 出工具 | plan/05 |
| **P6 多模态 / 语音** | 图/文件；语音**全走 LiteLLM** | P3 | 发图能识别；语音 ASR/TTS 通 | plan/06 |
| **P7 桌面壳（Tauri）** | Web UI 订阅事件协议 | P1（可早接） | 桌面窗口跑通 P1-P4 全部能力，断线能重连 | plan/07 |
| **P8 多 agent / 子 agent + DAG** | 编排引擎、DAG 依赖 | P4 | 两 agent 协作完成一任务；DAG reduce 校验通过 | plan/08 |
| **P9 对外 + 插件宿主** | OpenAI 兼容 API；cordis 式 DI/热插拔（策略注册表/热替换/AB 详 `design/05-policy.md`，在此落） | P7 | 外部 OpenAI 客户端能调；能力可热插拔不崩内核 | plan/09 |
| **P10 加固** | 可恢复压缩 / 评测回归网 / observability | P3起持续 | 任务级回归网跑通；压缩不丢事实召回；追踪面板基于事件流 | plan/10 |

> 顺序不是死板线性：P1→P2→P3 是主干必经；P4-P10 里 P7(桌面) 可提前接、P10 贯穿后期。每 Phase 的"进 v1/后做"见 §2。

### 1.5 Phase 落地备注（约束写备注、上表保持简洁）
- **P0**：只产**接口桩(stub)**，无业务逻辑、**不能跑 Agent 任务**；可跑从 P1 起（R5）。
- **P2**：v1 主干**串行工具**；`parallel_safe` 仅 schema 占位，**完整并行后置 P5**（R7）。
- **P5**：进入条件以 **P3**（MCP 调用需账本/持久化）；早期可只做**适配器 stub**（R小文本）。
- **P7**：“可早接”=**只做极简调试面板、仅消费外部事件协议**，**禁止把业务/状态/校验下沉到 Shell**（R1）。前端**尽量改造参考项目已有 UI 代码**（**同栈优先：DeepCode Tauri v2 `web`+`src-tauri` + EvoFlow `evopanel`(Tauri+pnpm)**；GenericAgent(tauri)、Cow/wuu/hermes 的 Electron 前端可迁 Tauri；hermes `web`/`ui-tui` 与 wuu `clients/` 参照），**仓库列表以 `project-main/` 目录当下为准、写计划前重看**，复用后仍守“瘦客户端、零业务下沉”（AGENTS §4.5）。
- **P4**：记忆走 **Command→Reduce→StorePort**、算法作可插拔策略不耦合 Kernel；**依赖 P3、不提前做**（R3）。**P4 落定修正**：① daily 生产者 = 显式 `WriteMemory` + run-完成边界 flush（压缩丢弃→L2' 蒸馏活路随 `disable_compaction=True` 后置 P10，ADR-0025）；② `PolicyView.memory` 自动填充会耦合进 L2 内核、违"换策略不动 loop"，故 P4 的 DoD④ 由可插拔 `MemoryStrategyConfig` + `memory_search` 工具承载，policy 仅作 L4 消费 `view.memory` 的接缝示例。
- **P10**：横切 concern——**轻量可观测/错误栈从 P1 就落**；完整可恢复压缩、回归评测套件后期（R4）。
- **契约占位在前期**：MCP/子agent/多模态的 ToolSpec/事件 type/state 字段，**P0-P2 先写 draft/unimplemented 占位**，别等 P5/P6 回头改 02/03 造成破坏性变更（R2）。

## 2. v1 范围建议（最优：先把"可长期演进的核心"做扎实，重且不确定的后置）
- **进 v1（P0-P4 + P7）**：harness 内核（循环/状态/事件/命令）、LiteLLM 多模型、核心工具 + 三态权限 + 受限沙箱、持久化/断点续传、**记忆三层+Deep Dream**、Tauri 桌面把 UI 立起来。理由：这是"个人 agent 能不能真用 + 架构承重墙"，晚做=重构。
- **v1 后（P5/P6/P8/P9/P10）**：Skills/MCP、语音多模态、多 agent/DAG、OpenAI 兼容/插件宿主、评测网加固。理由：都是"挂在已稳接缝上的扩展"，晚做只加不改。
- 唯一要现在就预留、不实现的：**事件 `type` 占位 + 任务树 `kind=subagent` 字段**（P8/P6 接进来时不用改协议/状态）。

## 2.5 P1 原型验证优先级（先证设计自洽，别一次做全）
1. **单 turn、串行工具、关闭并行**（`parallel_safe` 仅占位，完整并行→P5）；
2. 跑通 SubmitMessage → turn 循环 → ProposeAction 调工具 → tool_completed → run_completed；
3. 验证三条异常路径：取消 / 工具被 deny / PolicyPort 返非法意图（不崩）；
4. 验证 SSE 断线 + `after_seq` 续传；
5. 验证简单 checkpoint 断点恢复（无并行）。
> **MCP / 子 agent / 并行工具全部后置**；先把上面最小集跑绿，即证明整套设计无逻辑漏洞。

## 3. 维护规则
- 本文件只随**阶段增删/顺序变化**更新；细节改动进各 Phase 的 `plan/NN-*.md`。
- **实现前扫描复用（写每份 `plan/NN-*.md` 时必做）**：实现某能力前，先扫 `project-main/` 其余项目找已验证实现（**扫全、别只翻几个**）；**以 `project-main/` 目录当下实际存在的仓为准、新加自动纳入**（上次刷新含 12 个：hermes-agent/wuu/DeepCode/CowAgent/MetaGPT/cordis/**EvoFlow**/autogen/crewAI/OpenManus/**GenericAgent**/Agent-S；**计划时重新 `Get-ChildItem` 复核**）。更优者**改造复用**、不为省篇幅缩范围；计划里逐能力记「扫了哪些仓 · `file:line` · 结论(复用/改造/自写 · 为什么)」。复用须守分层(C1/C14)与许可署名。详见 [AGENTS §4.5](../AGENTS.md)。
- 每 Phase 收尾：回填"实际 vs 计划的偏差"到 `docs/adr/`（新决策）或对应 design 文档，保持路线图不腐。

## 4. 对外发布里程碑（附加标记，不改技术阶段/顺序）
- **节点 A｜P0 完成**：仅架构文档开源（design/adr/roadmap），面向硬核开发者，无运行码；
- **节点 B｜P1 完成**：最小可运行原型（终端 Demo）开源，拿第一批真实反馈；
- **节点 C｜v1（P0-P4+P7）**：完整 Tauri 桌面版，对外正式 Release。
> 不必等 v1 全做完才开源；P1 即可放出最小原型。

## 5. 路线图变更规则（防指南针腐化）
- 只调**阶段内实现细节** → 不改本文件，改对应 `plan/NN-*.md`；
- 改**阶段顺序 / 增删 Phase / 功能跨阶段移动** → **先记一条 ADR**（权衡理由），再改本路线图。
