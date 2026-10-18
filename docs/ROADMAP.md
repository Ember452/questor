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
| **P5 Skills / MCP** | 技能加载 + MCP 接入 | P3（仅适配器 stub 可早；完整需账本/持久化） | 丢一个 SKILL.md 即生效；挂一个 MCP server 出工具 | [plan/05](./plan/05-p5-skills-mcp.md) ✅（PR #143 `114fb0f` + 对抗审计加固 PR #144 `290375e` 已合入 main；真 stdio 子进程 roundtrip / 断连恢复实测；真远程 MCP server 端到端标 UNVERIFIED） |
| ~~**P6 多模态 / 语音**~~ | **已整阶段移除**（[ADR-0036](./adr/0036-p6-dropped-from-roadmap.md)）：语音 + 图像全砍，不再占阶段编号；日后按 L5 provider / L6 surface 接缝作按需扩展回归 | — | — | 无（`plan/06` 从未开工） |
| **P7 桌面壳（Tauri）** | Web UI 订阅事件协议 | P1（可早接） | 桌面窗口跑通 **P1–P5** 全部能力（§1.5 已按现实上修，原"P1-P4"是旧口径），断线能重连 | [plan/07](./plan/07-p7-desktop-shell.md) ✅（对抗审计 NO-GO → 逐条加固，PR #145 `b2361ff` 已合入 main；**v1 = P0-P4 + P7 能力面凑齐**；仍 UNVERIFIED：真开窗口/像素渲染、全量 `tauri build` 安装介质、真远程 MCP、真 LLM——详 §1.5 P7 备注 ③） |
| **P8 多 agent / 子 agent + DAG** | 编排引擎、DAG 依赖 | P4 | 两 agent 协作完成一任务；DAG reduce 校验通过 | plan/08；[ADR-0037~0042]（分支 `feat/p8-multi-agent-dag`，未合 main） |
| **P9 对外 + 插件宿主** | OpenAI 兼容 API；cordis 式 DI/热插拔（策略注册表/热替换/AB 详 `design/05-policy.md`，在此落） | P7 | 外部 OpenAI 客户端能调；能力可热插拔不崩内核 | plan/09 |
| **P10 加固** | 可恢复压缩 / 评测回归网 / observability | P3起持续 | 任务级回归网跑通；压缩不丢事实召回；追踪面板基于事件流 | plan/10 |

> 顺序不是死板线性：P1→P2→P3 是主干必经；P4-P10 里 P7(桌面) 可提前接、P10 贯穿后期。每 Phase 的"进 v1/后做"见 §2。
> **P6 已整阶段移除**（[ADR-0036](./adr/0036-p6-dropped-from-roadmap.md)）：v1 后的既定序列 = **P8 → P9 → P10**；编号**不重排**（P7-P10 作为锚点已散布于 ADR/审计/交付报告/分支名）。

### 1.5 Phase 落地备注（约束写备注、上表保持简洁）
- **P0**：只产**接口桩(stub)**，无业务逻辑、**不能跑 Agent 任务**；可跑从 P1 起（R5）。
- **P2**：v1 主干**串行工具**；`parallel_safe` 仅 schema 占位，**完整并行已移出 P5、待专门并行化 Phase（ADR-0029）**（R7）。
- **P5**：进入条件以 **P3**（MCP 调用需账本/持久化）；早期可只做**适配器 stub**（R小文本）。**新增前置：日志骨架刀 2 已合入（ADR-0027）**——B①–B⑧ 为其进入条件；且 P5 的 `plan/05` §0 扫描表**必须含"MCP server stderr 重定向到独立文件 + spawn 侧注入 `run_id`（文件名或首行标记）"决策**（`contextvar` 不跨进程、不能继承 `bind`，详 DESIGN §16.4），不假装骨架能解决子进程关联。
- **P7**：“可早接”=**只做极简调试面板、仅消费外部事件协议**，**禁止把业务/状态/校验下沉到 Shell**（R1）。前端**尽量改造参考项目已有 UI 代码**（**同栈优先：DeepCode Tauri v2 `web`+`src-tauri` + EvoFlow `evopanel`(Tauri+pnpm)**；GenericAgent(tauri)、Cow/wuu/hermes 的 Electron 前端可迁 Tauri；hermes `web`/`ui-tui` 与 wuu `clients/` 参照），**仓库列表以 `project-main/` 目录当下为准、写计划前重看**，复用后仍守“瘦客户端、零业务下沉”（AGENTS §4.5）。
  - **P7 落地备注（2026-10-17，分支 `feat/p7-desktop-shell`）**：① **DoD 口径按现实上修为“跑通 P1–P5 全部能力”**（P5 Skills/MCP 已合入 `290375e`，原表“P1-P4”是旧口径）。② 已落地并**机器验证**：sidecar serve 生产入口（`surfaces/serve.py`，loopback `127.0.0.1:0` + generation bootstrap，ADR-0032）、带外投影收口为 **bus 级一条只读订阅**（ADR-0033，正面收 `plan/05` §0.4 缺口）、协议 TS codegen + 漂移 `--check`（ADR/`check_protocol_schema` 三处 lockstep）、`node_updated`/`tool_completed`/`message_completed`(final_text，D-P7-C 选型①) 的 **additive** 定形（ADR-0034/0035）、TS 瘦客户端（SSE `ThreadEventStream` + `CommandClient`，vitest 12 绿）、`check_thin_client` 瘦客户端守卫（进独立 blocking `boundaries`）、`verify_release_bundle` 结构门 + sidecar 窄锁、**Rust `desktop/sidecar` 监管核心（generation 栅栏 `Fence`/`two_phase_shutdown`/`fail_all`/loopback `wait_ready` + 真子进程强杀测试，`cargo test` 8 绿）**、端到端能力矩阵（真 uvicorn+httpx，脚本化 provider，`test_p7_desktop_e2e`）。③ **UNVERIFIED / 未做（诚实边界）**：**Tauri 壳已搭并本地编译验证**（`desktop/src-tauri`：复用 `questor-sidecar`、`cargo check` Finished + `cargo test` 2 passed；spawn `--serve` 子进程、读 bootstrap、webview 指 loopback 端、退出走 `two_phase_shutdown`；tauri.conf.json 锁 CSP、capabilities 不授 fs/shell）。**已验新增**：Vite 薄客户端 app（`tsc`+`vite build` 产 dist）、sidecar `create_app` 挂静态伺服（TestClient 验 / 返回首页）、Windows **Job Object 杀进程树**（裸 kernel32 FFI，真子进程 `cargo test` 绿）、**PyInstaller onedir 冻结 + `verify_release_bundle --verify-runtime`**（启动冻结 exe、无系统 Python，/run→/events 实跑全流）。**仍 UNVERIFIED**：真开窗口/像素渲染（需显示）、全量 `tauri build` 桌面 bundle（需 `@tauri-apps/cli`+WebView2+vite 产物链）、真远程 MCP server 端到端、真 LLM、在途半条 live-delta 文本恢复——本机无头不跑真窗口，未伪造（cargo/WebView2/pyinstaller 均可用且已实测）。详 `docs/plan/07-p7-desktop-shell.md` §8 偏差回填。
- **P4**：记忆走 **Command→Reduce→StorePort**、算法作可插拔策略不耦合 Kernel；**依赖 P3、不提前做**（R3）。**P4 落定修正**：① daily 生产者 = 显式 `WriteMemory` + run-完成边界 flush（压缩丢弃→L2' 蒸馏活路随 `disable_compaction=True` 后置 P10，ADR-0025）；② `PolicyView.memory` 自动填充会耦合进 L2 内核、违"换策略不动 loop"，故 P4 的 DoD④ 由可插拔 `MemoryStrategyConfig` + `memory_search` 工具承载，policy 仅作 L4 消费 `view.memory` 的接缝示例。
- **P8**（分支 `feat/p8-multi-agent-dag`；[ADR-0037](./adr/0037-dag-validation-scope-in-p8.md)~[ADR-0042](./adr/0042-peer-event-additive-shape.md)）：子 agent=**独立 Run**（同进程 asyncio、`assigned_run_id` 关联、跨 run 只经 Command）；`delegate` 工具走既有工具生命周期（权限/沙箱/超时复用），子树取消经 `Cancel(owner)` **不硬杀**；DAG **只做 reduce 内依赖校验**（拓扑调度器后置，ADR-0037）。**已机器验证**：两 run 协作端到端（`test_p8_two_run_collaboration`）、非法 DAG 拒+不崩、子权限⊆父、fan-out gate、快照 round-trip/幂等、peer 事件三处 lockstep（22 类型）。**UNVERIFIED/后置**：真 LLM/真开窗口驱动多 agent、**跨进程 exactly-once**（claim/delivery_state 账本归 P9，ADR-0021/0038）、工具 reader/writer gate（显式再推后，ADR-0039）。详 `plan/08` §8。
- **P9**：因 P6 已移除（ADR-0036），OpenAI 兼容面收到 `image_url` / `input_audio` 等非文本 content part 或语音类请求时，必须**归一化拒绝**（明确的 provider 能力不支持错误，走 ADR-0028 故障归一终态）——**绝不崩、绝不静默降级成纯文本继续跑**；写进 `plan/09` 前置门。
- **P10**：横切 concern——**轻量可观测/错误栈从 P1 就落**（**已由日志骨架刀 2 落地，ADR-0027**：双通道 + `LogEntry` + 脱敏/节流/关联 id/按日文件面；此前 ROADMAP 373 文件规划里 observability **零配额**是它欠债到 P4 之后的结构性原因，本行起记其文件配额归口）；追踪面板 / `questor logs` 消费命令 / OTel/metrics / `--log-payload` preview 实装随**刀 3**（DESIGN §14）；完整可恢复压缩、回归评测套件后期（R4）。
- **契约占位在前期**：MCP/子agent 的 ToolSpec/事件 type/state 字段，**P0-P2 先写 draft/unimplemented 占位**（`kind=subagent` 确已落 `contracts/state_schema.py:138`），别回头改 02/03 造成破坏性变更（R2）。**多模态占位从未落地、也无需补**——P6 已随 [ADR-0036](./adr/0036-p6-dropped-from-roadmap.md) 移除；旧文档（`delivery/P1-completion-report.md:110`、`plan/01:44,112`）声称已占位，与 `contracts/events.py:251-273`（20 个 `EventType` 无一多模态类）不符，由该 ADR 就地记账、历史报告不回改。

## 2. v1 范围建议（最优：先把"可长期演进的核心"做扎实，重且不确定的后置）
- **进 v1（P0-P4 + P7）**：harness 内核（循环/状态/事件/命令）、LiteLLM 多模型、核心工具 + 三态权限 + 受限沙箱、持久化/断点续传、**记忆三层+Deep Dream**、Tauri 桌面把 UI 立起来。理由：这是"个人 agent 能不能真用 + 架构承重墙"，晚做=重构。
- **v1 后（P5 已完 → P8 → P9 → P10）**：Skills/MCP、多 agent/DAG、OpenAI 兼容/插件宿主、评测网加固。理由：都是"挂在已稳接缝上的扩展"，晚做只加不改。**多模态/语音不在序列内**（ADR-0036 整阶段移出）：它是最容易后加的一层，遇到真实需求时按 `design/02 §6/§7` 只加事件 `type`、L5 加 provider、大载荷复用 ADR-0019，不动内核。
- 唯一要现在就预留、不实现的：**事件 `type` 占位 + 任务树 `kind=subagent` 字段**（P8 接进来时不用改协议/状态）。

## 2.5 P1 原型验证优先级（先证设计自洽，别一次做全）
1. **单 turn、串行工具、关闭并行**（`parallel_safe` 仅占位，完整并行→专门并行化 Phase，ADR-0029）；
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
- **节点 C｜v1（P0-P4+P7）**：完整 Tauri 桌面版，对外正式 Release。→ **阶段条件已满足**（P7 已合入 `b2361ff`）；实际发布仍需先消掉"全量 `tauri build` 安装介质 + 真开窗口验收"两项 UNVERIFIED（§1.5 P7 备注 ③）。
> 不必等 v1 全做完才开源；P1 即可放出最小原型。

## 5. 路线图变更规则（防指南针腐化）
- 只调**阶段内实现细节** → 不改本文件，改对应 `plan/NN-*.md`；
- 改**阶段顺序 / 增删 Phase / 功能跨阶段移动** → **先记一条 ADR**（权衡理由），再改本路线图。
