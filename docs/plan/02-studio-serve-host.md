# 计划 02：Studio / serve 宿主与统一线协议

- Status: Active（2026-10-24 立项；同日依真实代码复检重写。**同日二修：前端基座由「Reasonix
  整树 vendor」改为「DeepCode 骨架 + Reasonix 对话面」，契约改为单 schema 双侧 codegen**，
  见 [ADR-0007](../adr/0007-frontend-base-and-contract-codegen.md)）
- 决策依据：[ADR-0005 Updated](../adr/0005-single-ui-host.md)（客户端拓扑与判死清单）、
  [ADR-0006](../adr/0006-serve-host-and-wire-protocol.md)（一份契约两种传输、帧模型）、
  [ADR-0007](../adr/0007-frontend-base-and-contract-codegen.md)（前端基座、契约 codegen、
  CONVENTIONS §4.5 作用域例外）
- 参照系（三参照，不再单指一仓）：**结构/骨架 = DeepCode `desktop/`**（Python 服务端同构、
  37,130 行、契约由 schema 生成）；**对话面与设计法典 = Reasonix**（五张对话卡 +
  TOKENS.md/LAYOUT.md/tokens.css）；**传输与安全 = ADR-0006**（SSE + POST + 凭据五件套）。
  两侧实测数字见 §1b；行号经维护者 2026-10-24 逐条亲验，见文末参考地图。刻意不抄：
  Reasonix 的 Go 服务端实现、DeepCode 的 WebSocket 传输与 Tauri 壳、DeepCode 的 P0–P5
  功能路线图；serve 的层位由本仓 `docs/architecture/STRUCTURE.md` 决定（bootstrap 顶层）。
- 基线：`c52101a`（`main`，Merge PR #219）。开工前按 §1 复测，任一不符先停。
- 纪律：**两分支制**（§0）；commit 与 push 需用户当轮明确授权；每阶段
  `uv run python scripts/check.py` 全绿；**复用优先**（§2 复用红线）；**不偷工减料**
  （`docs/CONVENTIONS.md` §0）——验收真实执行留痕，禁止"应该能过"；**全局最优与完整性铁律**
  （§0.5）——禁止因体量大而半读半写、禁止低于计划预期的实现；后端阻塞走
  中断-上报-授权（§3）。

---

## 0. 怎么用与分支制

1. 开工前重跑 §1 基线采集比对；不符先停。
2. 按阶段序推进，阶段内红/绿验收不因分支合并而放松；前一阶段绿验收不过不进下一阶段。
3. 每阶段结束回填 §7 总验收表，注明 commit。
4. 触发 §6 任一停工症状，先停手诊断，禁止加豁免绕过。
5. §8 开放问题只能由用户裁决；执行 agent 不得代答。
6. **两分支制**：阶段 1–3 → 分支 feat/studio-serve（引擎侧：契约 schema、双侧 codegen、
   REPL 切换、回环 TCP）；阶段 4–6 → 分支 feat/studio-web（前端侧：apps/web vendor、
   Electron 壳、质量门）。**合入顺序锁**：feat/studio-serve 在 4a 绿之前不合入 `main`
   （阶段 2 删 Ink 之后、`apps/web` 可用之前，产品不能只剩 REPL）。
7. **中断-上报-授权**：出现"因后端（字段/事件/依赖等）限制而不得不降级或不优"的局面，
   立即中断当前阶段并按 §3 上报；**经用户同意的后端修改不限规模**。
8. **开工前复用检索（义务，不是可选）**：每阶段动手写代码之前，先到 **DeepCode（骨架 /
   组件 / 工程链主参照）** 与 **Reasonix（对话卡 / 设计法典主参照）** 中检索该阶段要做的
   **每个**界面、组件、机制；进程/打包类问题按需查 hermes、CowAgent。能复用或微调复用的
   直接搬，检索结论（找到了什么 / 用了什么 / 为何不用）记入该阶段 PR 描述。§1b 与参考地图
   只登记**已知**复用点，阶段级检索是每次开工的第一动作。
9. **零视觉自设计，允许 IA 自设计**：界面风格、布局、按钮、图标、交互模式**一律不自行
   设计**；但**信息架构（导航层级、首屏、空态、分区）由 questor 自己裁决**——视觉可抄，
   结构必须自己定。视觉来源三序：① DeepCode 骨架内现成组件（已 vendor）；② Reasonix 对话
   卡与 tokens（骨架没有时）；③ 才允许新造——必须登记"为何两者皆无"并单独让用户过目。
   视觉真源 = Reasonix TOKENS.md / LAYOUT.md / tokens.css，参数不改（vendored 纪律）。
10. **形态是数据，不是分支**：personal / coding 等形态由 `profile` 描述（人设 + 模型 + 技能目录
    + 工具白名单 + `ui.capabilities`）；前端页面从**页面注册表**生成，卡片按 capability 门控。
    **禁止在组件里写形态判断**（`if (mode === "personal")`）——那是两套前端的第一行代码（§6-20）。

## 0.5 全局最优与完整性铁律（用户 2026-10-24 指令）

> 本节效力高于本计划的任何局部省事做法。它与 `docs/CONVENTIONS.md` §0（Completeness）、§1
> （long-term value）同源，但把"不偷懒"落成**可验收的交付物**，而不是态度。

1. **全局最优优先**：任何"局部最省"的方案，若损害长期结构（分层/契约/可维护性/可替换性），
   一律不采用。做选择时必须在 PR 描述里给出**至少两个方案的对照**（更省的那个为什么不够、
   更彻底的那个为什么不选）——只给结论不给对照 = 未完成。
2. **长视野三问**（动手前答，答不出先停）：①五年后这段代码还在吗？②不做的代价由谁承担？
   ③是否把成本推给未来（stub / 降级 / 临时件 / "以后优化"）？推给未来的，必须同时登记
   **删除时点**与**判红证据**（§3 中断机制、4b 的 throwaway 纪律）。
3. **读全，禁止抽样**：改任何文件前读**完整文件**与其**所有生产调用点**；"文件太长只读了前
   N 行"、"只看了主路径"、"grep 到一处就动手"均视为违规。引用证据必带 file:line。
4. **写全，禁止低于计划预期**：计划写"每屏/每卡/每条用例"就是**逐项**，不是"大部分"；
   计划写"端到端"就不是"happy path + TODO"。任何减配（少一个 kind、少一个形态、少一条判红、
   少一个端点、把实现换成 stub）都属停工症状（§6-24）。
5. **规模不是理由**：以"改了太多文件 / 工作量大 / 时间不够"为由缩减范围——停，按 §3 上报
   由用户裁决，**不得自行降配**。
6. **每阶段必须提交三张对账表**（缺一即未完成，进 PR 描述）：
   - **条目对账**：本阶段计划条目 → 实现位置 / commit（遗漏数必为 0）；
   - **影响面对账**：被改文件的上下游调用点清单（谁调用它、它调用谁、哪些改了、哪些为何不改）；
   - **判红对账**：计划声明的判红用例数量 == 实际实现数量，且每条能真实复现为红。
7. **半做形态清单（穷举，出现即停）**：只读前半段就下结论；只改直连调用点忽略间接调用；
   只实现正常路径不处理失败/取消/并发；只写测试名不写断言；把"每屏/每卡"做成"多数屏/
   多数卡"；用 stub/TODO 顶替计划要求的实现；用"应该能过"代替真实运行。
8. **违规判定与后果**：由对抗式验收按证据判（file:line、命令 + 输出、diff 统计）；发现一次
   即回滚该刀并从红用例重做，**不得以"后续补"结案**。

## 1. 基线（`c52101a` 实测，2026-10-24）

### 1a. 仓库事实

| # | 事实 | 值 | 采集方式 |
|---|---|---|---|
| B1 | 分支/工作区 | `main`，已跟踪文件干净 | `git status` |
| B2 | 引擎事件类型数 | **7**：`AssistantTextDelta`/`AssistantTurnComplete`/`ToolExecutionStarted`/`ToolExecutionCompleted`/`ErrorEvent`/`StatusEvent`/`CompactProgressEvent`（frozen dataclass，含 9 相位 Literal）。**勘误：ADR-0006 §5 与本计划旧版写"8 种"，与实测不符** | 读 `src/questorharness/contracts/domain/events.py` |
| B3 | 事件 id 字段 | **零**——wire id 全部在适配层铸造 | 同上 |
| B4 | 服务端依赖 | 无 aiohttp；`httpx` 仅客户端；`rich` 已在 | 读 `pyproject.toml` |
| B5 | 旧 UI 链（阶段 2 删除对象） | frontend/terminal（阶段 2 已删除）（ink 5/react 18/tsx）；src/questorharness/bootstrap/hosts/backend_host.py（阶段 2 已删除）、`react_launcher.py`、`protocol.py`、`app.py` 的 `run_repl` | `ls` + 读文件 |
| B6 | backend_host 消费者 | `src/questorharness/api.py:13,138`（re-export `run_backend_host`）；`src/questor/runtime.py:13,45` | `grep -rn "backend_host\|OHJSON" src` |
| B7 | prompt_surface 基线 | 4 份：channel/cli/cron/desktop | `ls tests/fixtures/baseline/prompt_surface` |
| B8 | apps/ 注册 | `docs/architecture/STRUCTURE.md:5,40,138,447,452,468`；:468 明文"apps/web 必须能单独在浏览器跑" | 读 STRUCTURE |
| B9 | 一致性硬边界 | STRUCTURE §0.2+§11：快照真源；durable spine 未立项；at-least-once+幂等 | 同上 |
| B10 | events.py 尾注 | `# questor: allow R7 -- until W8 adds the mirror test`（与计划 01 的 W8 交叉，见 §9） | 读文件 |

### 1b. 复用资产清查（写代码前必须先看；复用是红线不是建议）

实测基线（2026-10-24，逐目录读取，非估计）：**Reasonix `frontend-next` = 1,325 个 ts/tsx /
133,778 行 + 675 个测试文件 / 63,476 行 + 536 KB 全局 CSS（1,262 个唯一类选择器）+
纯英文 i18n**；**DeepCode `desktop/` = 174 个 ts/tsx / 37,130 行 + 43 测试 + 26 个 CSS
Module / 6,936 行 + 内置 zh-CN（226 条）**。这个差距是 ADR-0007 换基座的直接依据；
Reasonix 只保留"对话卡 + 设计法典"两项复用价值。

| # | 资产 | 事实（已验证行号/行数） | 复用方式 |
|---|---|---|---|
| B11 | **一行提交链** `handle_line` | `src/questorharness/bootstrap/runtime.py:604`：命令分发（`bundle.commands.lookup` + `lookup_skill_slash_command`）→ 系统提示重建 → 引擎提交 → 快照；渲染器全注入（`print_system` / `render_event: StreamRenderer` / `clear_output`）；`_run_engine_turn` 在 `:569` | 阶段 1 的 /submit 与阶段 2 的 REPL **直接复用同一条链**：各注入一个 StreamRenderer（serve 注入 wire 发帧器；REPL 注入 rich 渲染器） |
| B12 | StreamRenderer 注入点 | `src/questorharness/bootstrap/runtime.py:51`：`Callable[[StreamEvent], Awaitable[None]]` | 两端渲染器都实现此协议 |
| B13 | 三模态回调链 | `build_runtime` 收 `permission_prompt`（`runtime.py:288,418`）；backend_host 以 `self._ask_permission`/`_ask_question`/`_ask_edit_approval` 三个 Future 回调接入（`backend_host.py:105-107`） | **Future 模式移植**（非重新发明）：serve 的 approval/ask 端点与 REPL 终端问答按此形状实现，backend_host 删除时随迁 |
| B14 | 会话读写 | `src/questorharness/platform/session_storage.py`：`save_session_snapshot`/`load_session_snapshot`/`list_session_snapshots`/`load_session_by_id`/`export_session_markdown` | /history 与会话列表端点直调，不新写存储 |
| B15 | 斜杠命令注册表 | `src/questorharness/commands/registry.py:61,88,111`：`lookup_skill_slash_command`/`register_builtin_commands`/`create_default_command_registry` | REPL 与 /complete 直用；命令语义零重写 |
| B16 | 事件→JSON 先例 | `src/questorharness/bootstrap/hosts/app.py:235-265`：print 模式 `stream-json` 已有 StreamEvent→JSON 分支 | **微调复用**：wire 帧编码器从这里长出 |
| B17 | **DeepCode 骨架**（基座） | `DeepCode-main/desktop/`：174 个 ts/tsx / 37,130 行；43 个测试 + `e2e/web.spec.ts`；**src/** 下的 app / features / components / platform / rpc / styles / generated（15 个 features 垂直切片：automations / execution / extensions / goal / inspector / management / mcp / navigation / plugins / presets / settings / skills / thread / workbench / workflows） | 阶段 4a **整树 vendor**（骨架）；目录改名到 STRUCTURE §7 字面 |
| B18 | DeepCode 对话 UI（可用闭环的底） | `features/thread/TurnBlock.tsx` 17.3 KB、`ReasoningBlock.tsx`、`ThreadConversation.tsx`、`conversationModel.ts`；`features/execution/Composer.tsx` 26.5 KB、`ModelPicker.tsx` 15.6 KB、`ApprovalCard.tsx` | 4a 直接跑通可用闭环（登记 throwaway）；4b 逐卡替换后**同刀删除** |
| B19 | DeepCode 契约 codegen（关键手法） | `protocol/app-server.schema.json`（176.8 KB，手写真源）→ `desktop/scripts/generate-protocol.mjs` → **src/generated/app-server.ts**（47.9 KB）；`check:protocol` 用 `--check` 断陈旧 | 阶段 1 照此建立 questor 的 `protocol/app-wire.schema.json` + **双侧**生成器 |
| B20 | DeepCode 双 Transport | **src/rpc/contracts.ts**（`ClientRuntime` 接口）+ `browserRuntime.ts`（WS，19.2 KB）+ `tauriRuntime.ts`（7.1 KB）；服务端 `app_server/service.py:108` 装配 `WebSocketTransport`，`browser_auth.py` 用 `Sec-WebSocket-Protocol` 传会话 | `contracts.ts` 保留；`browserRuntime`（WS）**由 `sseRuntime` 取代**；`tauriRuntime` 与 `app_server/websocket.py` **不搬** |
| B21 | DeepCode 中文与样式体系 | **src/app/i18n.ts**（14.5 KB）内置 `ZH_CN` 226 条 + 按 `navigator.language` 切换；26 个 CSS Module / 6,936 行；`styles/tokens.css` 20.2 KB + `tokens.test.ts` | 阶段 4 直用；4b-6 用 Reasonix tokens 覆盖 token 层 |
| B22 | DeepCode 工程链 | `desktop/package.json`：`lint`(eslint) / `typecheck`(tsc) / `test`(vitest) / `test:web`(playwright) / `audit:licenses` / `build:sidecar` / `check:tauri` | 阶段 4a 全量接入 `scripts/check.py` 的 frontend lane 与 CI 新 job |
| B23 | **Reasonix 对话卡**（唯一要搬的前端部分） | `ui/cards/`：`SayCard.tsx` 13.4 KB、`ToolCard.tsx` 19.5 KB、`ApprovalCard.tsx` 15.5 KB、`AskCard.tsx` 15.5 KB、`CompactionCard` 系列；配套 `*.test.tsx`（如 `NoticeCard.test.tsx` 17.3 KB） | 4b 逐刀搬迁：组件 + CSS 类块 + i18n key + 测试 |
| B24 | Reasonix 设计法典 | `styles/TOKENS.md` 19.9 KB / `LAYOUT.md` 102 KB / `tokens.css` 13.2 KB；`styles/*.test.ts`（读 `app.css ?raw` 的 token/间距/字体栈守卫） | 4b-6 覆盖 DeepCode token 层；守卫测试同搬 |
| B25 | Reasonix 契约与宿主先例（只读思路） | `internal/contract/eventwire/kinds.go`（36 kind）、`wire.go`、`frontend_contract_test.go`（**单向 + `Skipf` + `compared>=10`**，故不可直接照抄为守卫）；`internal/frontend/serve/{broadcaster,eventstream,hub,routes}.go`；`desktop/electron/src/host.js,main.js`；`cli/tui_command.go`（进程内 transport） | 阶段 1/3 翻译**语义**（Go 实现不进仓）；阶段 5 壳照抄 |
| B26 | CowAgent 进程管理片段 | `CowAgent-master/desktop/`：111 文件 / 32,931 行、**0 个前端测试**；`python-manager` 类模块含 Windows 端口保留区逻辑 | 阶段 5 只借端口保留 / 进程监护片段，不借骨架 |
| B27 | **hermes 的 profile 体系（形态参照）** | `hermes_cli/profiles.py:1048 list_profiles` / `:1377 create_profile`；`ProfileInfo{name,path,is_default,gateway_running,model,provider,has_env,skill_count,alias,distribution_*,description}`；前端 `/api/profiles` + `$activeGatewayProfile` 驱动设置/技能/工具/模型作用域 | 阶段 1 建 `profiles/` bundle 的同构参照（**只译语义**） |
| B28 | **CowAgent 个人形态 UI** | renderer 组件：`AgentSelector` / `AgentScopeSelect` / `ChannelTeamSelect` / `ContextUsageDonut` | personal 形态首批页面/控件的来源（页面注册表） |
| B29 | 工具按 profile 过滤（本仓已有） | `capabilities/policy/checker.py:102`（显式拒绝）与 `:105`（`allowed_tools`）；`capabilities/tools/registry.py` 的 `read_only_tools` | 阶段 1 把 `allowed_tools` 接到 profile 上，**不改引擎** |

## 2. 终态、三参照与复用红线

```text
Python 引擎（QueryEngine / RuntimeBundle / handle_line 提交链 / StreamEvent 7 类）
        │ 复用注入点：StreamRenderer + 三模态回调
serve 宿主（bootstrap/hosts/serve/：wire + broadcaster + eventstream + routes + host + authority）
        │ 契约唯一真源：protocol/app-wire.schema.json（36 kind，只加不改）
        ├── 双侧 codegen：serve/wire_types.py（--check）＋ apps/web/src/generated/app-wire.ts（--check）
  ┌─────┼──────────────────────────┐
  │内存 transport            回环 TCP + SSE（凭据五件套）
  │（不开端口/无凭据）               │
终端瘦客户端 REPL            apps/web（DeepCode 骨架 + Reasonix 对话卡）
(handle_line + rich 渲染器)          │
                            apps/desktop Electron 壳（spawn 引擎）
```

- **三参照**：**结构/骨架 = DeepCode** `desktop/`（目录形状与 `docs/architecture/STRUCTURE.md`
  §7 的 `app/features/shared/generated` 逐条对应，差异仅两处：Transport 实现与 `platform`→
  `shared` 目录名；Python 服务端 `app_server/` 作为同语言对齐参考）；**对话面/设计 = Reasonix**
  （五张对话卡 + TOKENS.md/LAYOUT.md/tokens.css）；**传输/安全 = ADR-0006**（SSE + POST +
  五件套 + 父租约）、**文件组织 = ADR-0006/Reasonix `internal/frontend/serve`**（broadcaster /
  eventstream / routes 分文件对齐，只译语义不搬代码）。
- **前端三层分区（这张表就是 `apps/web/VENDOR.md` 的分类与守卫白名单）**：

| 层 | 内容 | 归属 | 允许改动 | 升级方式 |
|---|---|---|---|---|
| 骨架层 | **src/app**、**src/features/***、**src/shared/ui-kit**、**src/shared/transport**、`styles/`、`package.json`+lock、`scripts/` | vendored（DeepCode） | 仅限 VENDOR.md 禁区/已改清单内的条目 | 与首刀 commit 的 diff（不跟上游） |
| 契约层 | `protocol/app-wire.schema.json` → 两侧 `generated/` | owned（questor 真源） | schema 只加不改；生成物**禁手改** | 改 schema + 重新生成 |
| **形态层** | `profile` bundle（人设/模型/技能/工具白名单）+ `profile.ui` 能力位 + 页面注册表 + `cardSlots` 门控 | owned | 自由；**不得在被依赖层里插形态判断** | 新增形态 = 新增 bundle + 注册项，不动已有页 |
| 对话面 | 五张对话卡 + `shared/theme/tokens.css` | vendored（Reasonix） | 参数不改；类块搬迁需登记 | 与 4b 首刀 commit 的 diff（不跟上游） |
| 自写层 | 导航 IA / 首屏 / 空态、渠道 / 任务 / 团队 / 记忆召回页、questor 专属 kind | owned | 自由，但视觉参数取自上一层 | 不涉及 |

- **CONVENTIONS §4.5 作用域例外**（ADR-0007 §5）：vendored 代码**只允许存在于 `apps/`**；
  `src/` 内仍适用"合并代码不携带外部来源/许可标记"。归属义务：保留上游 LICENSE 原件 +
  仓根 `THIRD_PARTY_NOTICES.md` + `apps/web/VENDOR.md` 的逐目录归属与上游快照标识。
- **复用红线**：判定序 = 直接复用 > 微调复用 > 新写。§1b 资产必须先尝试复用；确需新写的，
  PR 描述必须说明"为何既有资产不能复用"；绕过 `handle_line` 自写提交链、绕过
  session_storage 自写存储，一律视为违规（停工症状 §6-6）。**裁剪红线**：`apps/web` 内
  任何与 pristine 快照的差异都必须能在 VENDOR.md 里查到条目与理由，查不到即失控 fork（§6-15）。
- **缺字段四手法**（判据=前端是否需要拿字段回传操作引擎）：铸造（id 类，适配层造号+pending
  表）/派生（计数、掐表、直通、9 相位→三帧）/空态（`checkpointTurn:false` 等）/改引擎（需
  回传路由时加可选字段）。**上位规则**：任何一法导致降级或不优，不得自行选择——走 §3 上报。

### 功能可见性映射表（按 产品×形态 分表；本文件只收录 coding 形态）

**规则**：questor 每一个用户可感知的功能，必须在下表有一行——要么有界面载体，要么显式登记
"暂不暴露"（由用户裁决，执行 agent 不得默默省略）。**"引擎有、界面无"的功能黑洞是本计划的
验收红线**。本表随阶段回填（阶段 1 落初版核对，4a 逐端点核对，4b 逐屏验收），与启动扇出表
并列维护。

**分表规则（一个产品两种形态的承重规则）**：映射表是**产品契约**，不是通用契约。
实文件：**docs/plan/mapping/questor-coding.md**（本表迁徙地，阶段 1 落）与
**docs/plan/mapping/questor-personal.md**（阶段 4a 建空壳，首批页面待 §8 裁决）。kind 覆盖
守卫按 `profile.ui.capabilities` 选择当前形态的表校验：某 kind 在当前形态登记为 absent 则
必须在当前表里有"不展示"行，否则红。
初版基于 2026-10-24 引擎探索事实（39 工具 / 16 命令族 / 各能力域）：

| questor 功能 | 界面载体 | 复用来源（§0 三序） |
|---|---|---|
| 对话流 / 流式回复 / 思考 | Transcript 卡片流（SayCard） | Reasonix 原样 |
| 取消当前回合（Stop） | Composer 停止按钮 → `turn_done{cancelled}` | 阶段 1 `/cancel` 端点；按钮取自 DeepCode `Composer` |
| 提交队列 / 插话（followup / steer） | 无独立界面 | **初版登记：暂不暴露**（引擎单回合无队列；要开先走 §3） |
| 工具执行可视化（fs/shell/web/media…） | ToolCard 原位展开 + diff/输出面板 | Reasonix 原样 |
| 权限审批（三态+敏感路径拦截） | ApprovalCard 三档按钮 | Reasonix 原样 |
| 工具提问 AskUserQuestion | AskCard（单选/多选/自填） | Reasonix 原样 |
| 压缩进度（auto/manual/reactive × 9 相位） | CompactionCard + MeterRail 上下文环 | Reasonix 卡片 + Context 仪表 |
| 项目记忆 / 个人记忆（写入、召回、auto-dream） | RememberCard + Settings 记忆页 | Reasonix RememberCard；个人记忆语义微调 |
| 技能（SKILL.md 发现/调用/清单） | Composer ChipMirror 芯片 + /skill + Settings 技能页 | Reasonix 原样 |
| 插件（六类工件、启停、安装） | Settings 扩展页 | Reasonix PluginsPage 形态 |
| MCP 服务器（连接/认证/工具桥接） | Settings MCP 页 + Metrics 的 Mcp 面板 | Reasonix 原样 |
| 模型 / Provider / profiles 档位切换 | 模型 Picker + Settings 连接页 | Reasonix Picker/ConnectionSettings；profiles 档位微调 |
| 推理强度（effort/passes） | 推理强度四格条 Picker | Reasonix 原样 |
| 权限模式（默认/PLAN/FULL_AUTO） | Policy 三档菜单（Ask/Auto/YOLO） | Reasonix 原样（语义映射） |
| Plan 工具 / TodoWrite | PlanGate + Metrics 的 Plan 面板 | Reasonix 原样 |
| 上下文用量 / 缓存命中 / 费用 | MeterRail（上下文环/费用/隐藏金额） + Metrics Cost/Cache | Reasonix 原样 |
| 会话快照（保存/恢复/列出/按 id 加载/导出 md） | Sidebar 会话树 + /resume | Reasonix 会话树；导出入口微调 |
| 斜杠命令（16 族）+ 技能回退 | CompletionMenu 补全 + /help | Reasonix 补全菜单；命令集为 questor 内容 |
| Cron 四工具（创建/列表/启停/删除） | Metrics 的 Jobs 面板 | Reasonix Jobs；cron 语义微调 |
| autopilot 自动巡检 | Jobs 面板（后台任务） | Reasonix Jobs 微调；**初版登记：暂不暴露**（用户裁决） |
| 后台异步 agent（AgentTool/task_manager） | DeckChips + Agents 面板 | Reasonix 原样 |
| swarm / team（队友、worktree、权限上抛） | Agents 面板 + DeckChips | Reasonix 子代理卡微调；team 生命周期需**新增 kind** |
| coordinator 协调模式 | 阶段标记（只读展示） | **初版登记：暂不暴露**（用户裁决） |
| 渠道会话（飞书/QQ gateway） | Sidebar 机器区段（只读展示 session_key） | questor 特有，**新增**（首版只读） |
| 沙箱（Docker 配置与状态） | Settings 沙盒页 + Policy | Reasonix 沙盒页微调 |
| 视觉输入（图像块/多模态降级） | Composer 附件 chips + 图片卡 | Reasonix 原样 |
| 诊断 / doctor / 配置展示 | Settings 版本与日志页 | Reasonix 原样 |
| git 工作区（分支/worktree 切换） | WorktreeChip / BranchChip + Workbench 改动页 | Reasonix 原样 |

**表的读法（两栏合并后）**："Reasonix 原样" 指**交互与视觉形态**的来源；实际落地载体优先用
**DeepCode 骨架内的同名区域**（Settings / Inspector / Composer / navigation），只有五张对话卡
直接搬 Reasonix 组件。新造任何一项前，先按 §0-9 的三序登记。

**已登记"暂不暴露"**：autopilot、coordinator、提交队列/插话（followup/steer，首版）；
**需新增 kind**：swarm/team 生命周期、渠道会话标识。多客户端并发（REPL + 浏览器 + 桌面
同时在线）不是界面功能而是**传输语义**：阶段 3 必须给出单写者租约与审批归属规则，否则同
一个 approval id 可被两个客户端各答一次。此四处是 §3 中断-上报-授权的预定触发点——实现时
若发现需要引擎侧字段，先上报。

## 3. 中断-上报-授权机制（后端阻塞）

- **触发**：因引擎侧（字段/事件/依赖等）缺失，前端侧唯一可行解属于降级或不优——包括但不限于
  stub 掩盖引擎真实能力、铸造 id 阉割 UI 功能、字符串解析/特例硬编码绕过、为不改引擎而丢信息、
  契约映射失真；
- **动作**：中断当前阶段，向用户报告四件事——根因（引擎具体缺什么）、影响范围（哪些阶段/
  任务/界面）、候选方案对比（前端绕过的长期代价 vs 改后端的代价与规模）、执行建议；
- **裁决**：用户决定。**经同意的后端修改不限规模**（含大规模重构），照常走红绿验收、基线刷新
  与必要 ADR；
- **默认禁止**：未经此机制交付任何降级实现；也禁止"先降级以后再优化"——以后不会被优化，
  只会被遗忘。

## 4. 阶段

### 阶段 1：契约冻结 + 双侧 codegen + 进程内 serve

**新建**：**protocol/app-wire.schema.json**（仓根，手写，36 kind，逐帧对照 B25 的
`kinds.go`/`wire.go`；ADR-0006 只加不改）+ **scripts/codegen/gen_wire_py.py**（schema →
**src/questorharness/bootstrap/hosts/serve/wire_types.py**，带 `--check`）+ 
**scripts/codegen/gen_wire_ts.mjs**（schema → `apps/web/src/generated/app-wire.ts`，
`json-schema-to-typescript`，带 `--check`；阶段 1 先生成到 `protocol/_gen/app-wire.ts`
供守卫使用，阶段 4a 落位到 `apps/web`）+ **src/questorharness/bootstrap/hosts/serve/**
子包——**__init__.py**、**wire.py**（帧编码，自 B16 的 stream-json 分支微调重构，类型取自
`wire_types.py`）、**broadcaster.py**（seq / 可丢 / 8MB 有界重放 / watermark，语义对照
`broadcaster.go`）、**eventstream.py**（SSE + Last-Event-ID 双通道 + attach≠resume，对照
`eventstream.go`）、**routes.py**（框架无关 async 处理函数；aiohttp 只做薄适配；`/rt/r1/`
前缀第一天对齐）+ **authority.py**（单写者租约：一个 bundle 同时只允许一个 active turn，
被拒方得到 `turn.busy` refusal code）+ **host.py**（装配：build_runtime 复用 + 内存
transport——不开端口、无凭据）；测试 **tests/unit/bootstrap/hosts/serve/**、黄金帧
**tests/fixtures/serve_wire/**（逐 kind 一例）、**tests/ci/test_wire_codegen.py**、**tests/ci/test_kind_coverage.py**（schema 的 kind 集合
== `wire.py` 映射集合 ∪ 映射表「暂不展示」allowlist；4b 起再并入 `cardSlots` 第三集合）、
**tests/ci/test_persistence_version.py**（settings / 会话快照带 `schemaVersion`，读旧写新）、
**tests/fixtures/persistence/v1/**（一份真实旧版文件）、**tests/e2e/test_serve_host_smoke.py**。
按 AGENTS.md 新开包流程登记。
**形态底座（本阶段只做数据与契约，不做界面）**：**src/questorharness/profiles/**（`__init__.py`
带 `__all__`、`model.py`：`ProfileInfo{name, path, description, model, provider, skill_dirs,
plugin_roots, allowed_tools, ui_capabilities, is_default}`、`loader.py`：`list_profiles()` /
`load_profile()` 从 `profile.yaml` 读）+ **src/questor/profiles/**（产品侧 bundle：coding /
personal 两份 `profile.yaml`）+ `/rt/r1/profile` 端点（返回
`{id, name, description, ui:{capabilities:{page_id: ready|declared|absent}}}`）。`allowed_tools`
经 `build_runtime` 传入 policy（B29），**不改引擎**。同构参照 B27，只译语义。
**两个新包均按 AGENTS.md 新开包流程登记**（`__init__.py` 带 `__all__` + 包 AGENTS.md + 路由表
行 + `--refresh-baseline --reason`）——与 serve 子包同规格，不得只建目录。
**复用强制项**：/submit = `handle_line` 注入 wire 发帧器；/history = B14 直调；
approval / ask = B13 Future 模式移植；/cancel = 持有 turn 任务句柄取消，落
`turn_done{cancelled}`；**/submit 幂等** = 客户端带 `clientRequestId`，适配层做 TTL 去重
（至少覆盖一次重试窗口），重复提交返回同一回合而不是开第二个；**profile 选择** =
`build_runtime(active_profile=...)` + `allowed_tools` 注入；`/profile` 直读 loader，不新写存储。
**动作**：映射表落地（附录）；droppable 分类表；refusal code 常量；启动扇出盘点（取
DeepCode **src/rpc/contracts.ts** 的 `ClientRuntime` 方法清单与 Reasonix `port.ts`
285 方法的并集，逐端点"实现 / stub"登记成表随本计划维护）；功能可见性映射表初版核对
（§2 逐行对照引擎现状，确认无功能黑洞）；勘误 ADR-0006 §5 "8 种"→7（随本阶段提交）；
映射表迁到 **docs/plan/mapping/questor-coding.md** 并建 **docs/plan/mapping/questor-personal.md**
空壳（只登记"待裁决"行，不预设功能）。
**验收绿**：进程内 transport 上脚本驱动完整回合（提交→事件流→快照），不依赖任何网络端口；
黄金 fixture round-trip 稳定；映射表覆盖 7 类事件；**并发判红用例**：并行两次 submit，
第二次得到 `turn.busy`（不得静默排队，也不得双写）；**幂等判红用例**：同一
`clientRequestId` 连发两次 → 只产生一个回合，第二次拿回同一 turn id；`gen_wire_py --check`
与 `gen_wire_ts --check` 双绿；kind 覆盖守卫绿；持久化版本守卫绿（v1 旧文件可读）；
`/profile` 的 capabilities 与分表一致，且两个 profile 的 `allowed_tools` 可枚举、互不相同
（判红：personal 形态下 coding 专属工具仍可见）。
**验收红**：改任一 kind 字符串/字段名 → fixture 测试红；可丢帧不编号用例红；改 schema
不改生成物（两侧任一）→ 红；手改生成物 → 红；schema 新增 kind 但两侧映射与映射表均未
登记 → kind 覆盖守卫红；打开 v1 旧版 settings 报错 → 持久化版本守卫红。

### 阶段 2：终端 REPL 瘦客户端 + 删除刀（同一刀）

**前置核查**：①src/questorharness/bootstrap/hosts/protocol.py（阶段 2 已删除） 是否只服务 backend_host；
②`src/questor/runtime.py:45` 的产品交互场景是否真实需要 REPL 入口。
**新建**：**src/questorharness/bootstrap/hosts/terminal_client.py**（内存 transport 客户端 +
rich StreamRenderer + 三模态终端问答，B13 模式；Ctrl-C → `/cancel`，与浏览器 Stop 同一端点）。
**复用强制项**：REPL 主循环 = `handle_line` 注入 rich 渲染器（与 /submit 同链）；斜杠命令 =
B15 registry 零重写；单写者租约复用阶段 1 的 `authority.py`。
**动作**：`app.py` 的 `run_repl` 改调 terminal_client；**同刀删除**：frontend/terminal/（阶段 2 已删除）、
`backend_host.py` + OHJSON、`react_launcher.py` + React TUI 启动路径、`--backend-only`、
`api.py:13,138` re-export、`src/questor/runtime.py:13,45` 改造；appearance 四包（themes/
keybindings/vim/output_styles）按 REPL 实际渲染需求裁决；`prompt_surface/desktop.txt` 移除；
doctor/help/structure/tool_metadata 基线重录；MIGRATION 加条目；ARCHITECTURE 依赖图摘掉
legacy 节点。
**验收绿**：REPL 日常可用（流式/审批/斜杠）；`rg "OHJSON|backend_host" src` = 0 且
`rg "react_launcher|--backend-only" src pyproject.toml` = 0；TREE/GRAPH 重生成 `--check` 绿；
`check.py` 全绿。**验收红**：回插一个 OHJSON 字符串 → 红线复验红。

### 阶段 3：回环 TCP 宿主 + 凭据五件套 + 多客户端语义

**动作**：host.py 增回环模式——仅监听 127.0.0.1 随机端口；一次性 launch credential（≥32 字节，
永不出自配置、永不落盘）；HttpOnly cookie 种植；Host+Origin 校验（hostname 必须 127.0.0.1）；
父进程租约。dev 允许 `--serve-no-auth`（默认五件套）。**多客户端**：broadcaster 支持 N 个
订阅者（REPL + 浏览器 + 桌面同时在线）；approval / ask 的 Future 表带**归属声明**，非发起
客户端回 `approval.not_owner`，已被结算再答回 `approval.already_settled`；turn 句柄只属于
`authority.py` 的持有者，其他客户端只能 attach 观察。
**验收绿**：浏览器可访问（为阶段 4 预演）；五件套各有一条判红测试（错误来源连接必须被拒）；
**多客户端判红**：两个客户端同时对同一 approval id 作答 → 第二个得到 `already_settled`；
非持有者 `/cancel` → `turn.not_owner`。

### 阶段 4：apps/web 基座（4a 可用闭环 + 4b 逐卡替换）

**前置核查**：①`tests/fixtures/baseline/structure.json` 扫描范围是否覆盖 `apps/`（收录，或
显式豁免 vendored 树并写理由）；②vendored 基线 = 本刀（原样复制）的**单独 commit**；
此后“我们改了什么”只由 `git diff <该 commit> -- apps/web` 回答，**不记上游标识、不跟上游
合并**（已决）；③`apps/web` 的依赖方案：`apps/web` 自带 `package-lock.json`（**包管理器固定
为 npm**，不引入第二套 lock）。

#### 4a：基座落地与可用闭环（先能跑，再好看）

**新建**：**apps/web/**（整树复制 DeepCode `desktop/` 的 `src/`、`package.json` + lockfile、
`index.html`、vite/tsconfig、`e2e/`、`scripts/`；**不搬** `src-tauri/` 与
`rpc/tauriRuntime.ts`；**第一刀零修改**）、**apps/web/VENDOR.md**（**禁区清单** + 逐目录归属 + 首刀基线 commit）、
仓根 **THIRD_PARTY_NOTICES.md**（MIT 版权声明）、**tests/ci/test_vendor_pristine.py**
（与首刀 commit 的差异必须出现在 VENDOR.md 的禁区/已改清单内）、
**apps/web/src/shared/transport/sseRuntime.ts**（SSE + POST 实现 `ClientRuntime`）、
**apps/web/src/app/wireBoot.ts**（只调用扇出表内端点）、`protocol/app-wire.schema.json` →
`apps/web/src/generated/app-wire.ts` 落位。

**动作（按序，每步一刀）**：
1. 复制 + `VENDOR.md` + NOTICE；`npm ci`（DeepCode 用 npm，仓内是 `package-lock.json`，
   不是 pnpm）；`npm test` 绿（43 个测试）。
2. **接门**：`eslint` / `tsc --noEmit` / `vitest` / `vite build` 进 `scripts/check.py` 的
   `frontend` lane 与 `.github/workflows/ci.yml` 新 job；同步 `docs/operations/ci.md` 的
   Jobs 一节。**先绿再动结构**。
3. **改名到 STRUCTURE §7 字面**：**src/platform** → **src/shared**、**src/components** →
   **src/shared/ui-kit**、**src/rpc** → **src/shared/transport**；43 个测试即改名验收。
4. **换契约**：删 **src/generated/app-server.ts** 与 `shared/transport/browserRuntime.ts`
   （WS，改名后的位置），接入 `generated/app-wire.ts` 与 `sseRuntime.ts`；`contracts.ts` 的
   `ClientRuntime` 接口保留；`rg "new WebSocket" apps/web/src` = 0。
5. **字段预检**：用最小渲染（不搬样式）把五张卡所需帧字段逐个打到屏上：`text`/`message`/
   `usage`、`tool_dispatch`/`tool_result`/`tool_progress`、`approval_request`、`ask_request`、
   `compaction_started/progress/done`、`turn_started`/`turn_done`。任一字段缺失 → §3 上报，
   **此刀不绿不进 4b**。
6. **可用闭环**：DeepCode 原生 `TurnBlock`/`Composer` 驱动真实回合（提交→流式→工具→审批→
   快照→恢复）；临时对话渲染器登记为 **throwaway**（4b-6 同刀删除）。
7. **骨架补齐（可用性两块，实测 DeepCode 骨架缺）**：①按**卡片边界**包 `ErrorBoundary`
   （一张卡 throw 只降级该卡，不许整屏白）；②transcript 列表虚拟化（骨架无 virtualizer，
   实测 0 处），以 10k 条消息为基线留滚动与内存数值。
8. **形态接线（页面注册表 + profile.ui）**：新建 **apps/web/src/pages/registry.ts**（每页声明
   `{id, capability, title, component}`；导航 / 命令面板 / 快捷键 / 搜索**全部从注册表生成**，
   禁止硬编码路由）+ **apps/web/src/app/capabilityGate.tsx**（按 `/profile` 返回的
   `ready|declared|absent` 决定渲染 / 置灰 / 隐藏）。**不建 personal 空壳页**：personal 五个
   page id 只写在 `personal/profile.yaml` 的 `ui.capabilities` 里作 `declared`（入口不出现）；
   门控用 coding 侧真实页验证（将 `inspector` 置 absent → 导航与命令面板同步消失）；
   守卫：`registry` 的 page id 必须出现在当前 profile 的 capabilities 里，否则红。
   **新增页面的四步**（写进 **apps/web/docs/ADDING_A_PAGE.md**）：①`registry.ts` 加一条
   `{id, capability, title, component}`；②当前 profile 的 `ui.capabilities` 加同名 key（初始
   `declared`，实现完改 `ready`）；③若消费新 kind → schema 加 kind（只加不改）+ 两侧重新生成
   + `cardSlots` 补槽位；④形态映射表加行。**id 稳定性**：page id 一入 git 即视为契约——
   **只增不改名、不删除**；下线/替换用 `absent` 并在映射表登记，别名期至少一个 minor 版本。

**验收绿**：`apps/web` 单独在浏览器跑（STRUCTURE :468），真实引擎驱动完整对话 + 审批 +
取消；frontend lane 全绿；pristine 守卫绿；`VENDOR.md` 覆盖全部 vendored 目录；
**tests/fixtures/baseline/prompt_surface/studio.txt** 落地（脚本不支持 studio 宿主则记录、另开刀）；
**错误隔离判绿**：手动 throw 一张卡 → 仅该卡显示降级位，其余可用；**虚拟化判绿**：10k 条
消息滚动不掉帧，数值入基线；**形态判绿**：改 `/profile` 的 capabilities → 导航 / 命令面板 /
卡片同步变化，且 `rg "mode ===|isPersonal" apps/web/src` = 0。
**验收红**：改一只 vendored 文件未登记 VENDOR.md → 红；`new WebSocket` 残留 → 红；临时渲染
器未登记 throwaway → 红；扇出表之外的端点被调用致 404 → 停（§6-5）；功能黑洞未登记 → 停
（§6-11）。

#### 4b：逐卡替换（一次一张，每张一刀）

**新建**：`apps/web/src/shared/ui-kit/<Card>/`（五张卡）与 `apps/web/src/app/cardSlots.ts`
（按帧 kind 分发；**分发用判别联合 + `const _: never = frame` 穷尽**：新增 kind 不补槽位 =
`tsc` 红；**每个槽位带 `capability?: string`**，当前形态为 absent 时不渲染——这是**显式不展示**，
不是兜底；运行时兜底只允许映射表里"暂不展示"的 allowlist kind，其余不得兜底）。首刀同时把
`cardSlots` 作为第三集合接入 **tests/ci/test_kind_coverage.py**。

**每刀固定动作**：从 Reasonix `ui/cards/` 搬组件 → 从 `app.css` 只搬它用到的**类块**（按类名
定位，不整表复制）→ 搬对应 `*.test.tsx` 与 i18n key → 接 `cardSlots` → **同刀删除**
DeepCode 原本渲染该 kind 的路径。顺序按用户可见价值：Say → Tool → Approval → Ask → Compaction。

**验收绿/红（每张卡）**：绿 = 该卡由真实事件驱动（golden fixture 回放 + 一次真跑）+ 截图
对齐 tokens + 该卡测试进 frontend lane；红 = 旧渲染路径仍在（`rg` 探针）→ 红。

#### 4b-6：删临时件 + 设计法典覆盖

**动作**：删 `TurnBlock` 临时渲染分支；**token 层迁移（不是覆盖）**——实测 DeepCode 的 69 个
CSS 变量与 Reasonix 的 128 个**只重叠 1 个**（交集 = `--shadow-float`），直接覆盖会让骨架
68 个变量全部失效、样式裸奔。做法：①两套并存于 **src/shared/theme/**（`tokens.deepcode.css` /
`tokens.reasonix.css`）；②建**变量别名映射表** **src/shared/theme/alias.css**（旧名 → 新名，
69 个逐一登记；无对应语义的保留原值并标"无对应"）；③逐组件迁移，迁移完的组件才可删旧变量；
④新守卫 **tests/ci/test_css_vars.py**（扫 `apps/web` 内所有 `var(--x)`，未在定义集出现即红）；
`TOKENS.md` / `LAYOUT.md` 入 `apps/web/docs/`；搬 `styles/*.test.ts` 的 token/间距/字体栈守卫；
删除未登记 kind 的**通用兜底分支**，只保留 allowlist 白名单分支；删除任何 `mode` / `isPersonal`
类形态判断残留（`rg` 探针）；Reasonix 的 `ui-census`
不引入（其"无死 UI"判定由 frontend lane + 扇出表 + 映射表 + kind 覆盖守卫替代）。
**验收绿**：临时渲染器在代码路径中不存在；token 守卫绿（含 alias 表覆盖全部 69 个旧变量）；
明暗 × 宽窄截图矩阵入库；kind 覆盖守卫三集合（schema ↔ wire.py ↔ cardSlots/allowlist）全绿。
**验收红**：残留 fallback 分支 → 红；新增 kind 未加 `cardSlots` 条目 → `tsc` 红；
任一 `var(--x)` 未定义 → `test_css_vars` 红；alias 表漏登记一个旧变量 → 红；
tokens 与 Reasonix 原值不一致且未登记 → 红。

### 阶段 5：apps/desktop Electron 壳 + 长期运行验收

**新建**：**apps/desktop/**（electron main/preload；packaging/：electron-builder + NSIS + 签名
占位 + PyInstaller **onedir** spec 与启动冒烟〔拒绝 onefile〕）。
**动作**：spawn `python -m questorharness --studio-host` → stdout 握手校验（token≥32、
127.0.0.1）→ loadURL 前种 HttpOnly cookie → stdin 父租约；无边框+自绘窗控；托盘/badge/关闭到
托盘/单实例/powerguard；Windows 端口保留区防御（借用 B26 片段）。**updater 必须带回滚**：
新版本启动失败 → 切回上一版本目录（不原地覆盖）。
**验收绿**：打包产物双击全流程可用；杀壳→引擎退（父租约）；杀引擎→壳重启；updater 回滚
用例可重现；**soak**：8 小时间断回合后 RSS / 句柄 / SSE 连接数不增长（带数值基线）。
**验收红**：握手拒绝坏 token / 非回环 hostname 用例红；回滚失败 → 红。

### 阶段 6：design-qa 质量门

**动作**：perf 最小集（tiers/contrast、budget、narrow）+ 截图矩阵（明暗 × 1280×720/390×844）
+ `data-action` 惯例；接入 `scripts/check.py`（自证能红）。关键交互（ApprovalCard 等）逐项
对齐 `LAYOUT.md`；宽度分档（narrow）必须在窄窗口真实生效。
**验收绿/红**：改坏一个对比度 token → CI 红；矩阵截图入库。

### 后置池（不排期，按需立项）

mux 多 pane、手机配对、扩展 structured UI、CUA、主题包 Python 注入端、品牌与文案替换（中文
已是一等公民，剩余为品牌词）、REPL 渲染增强、额外卡片（RememberCard / MeterRail / Jobs /
Agents）在五卡之后逐张评估。
**已从中移除**："vendored 巨石 CSS 拆分"——DeepCode 是 CSS Module，本身已分文件。

### 附录：StreamEvent → wire 帧映射表（阶段 1 初版，逐阶段回填）

帧的**字段定义**只在 `protocol/app-wire.schema.json`；本表只描述映射手法与来源，不重复字段表
（两边各写一份就是漂移的起点）。

| 引擎侧 | wire 帧 | 手法 | 备注 |
|---|---|---|---|
| （submit 到达） | `turn_started{authoredTurn,msgIndex,via,attachments}` | 铸造+派生 | msgIndex=适配层计数；attachments=[] 空态 |
| `AssistantTextDelta.text` | `text` | 直通 | droppable |
| `AssistantTurnComplete{message,usage}` | `message` + `usage` | 直通 | ConversationMessage→wire 文本块映射 |
| `ToolExecutionStarted{tool_name,tool_input}` | `tool_dispatch` | 铸造 toolCallId | partial:false（引擎无参数流式） |
| `ToolExecutionCompleted{...}` | `tool_result` | 铸造关联 | 同 toolCallId |
| （回合结束） | `turn_done{cancelled,outcome,checkpointTurn,workDurationMs,receipt,readiness,err}` | 派生 | checkpointTurn 常量 false（引擎 P1 后变真，前端零改） |
| permission_prompt 回调 | `approval_request{id,tool,subject}` | 铸造 | `/approve{id}` 查 Future 表（B13 模式） |
| `ErrorEvent{message,recoverable}` | `notice` / `turn_done.err` | 映射 | |
| `StatusEvent{message}` | `notice` | 映射 | droppable |
| `CompactProgressEvent{phase×9,...}` | `compaction_started/progress/done` | 派生 | 9 相位→三帧映射写在 wire.py；compact_failed 归处阶段 1 定 |
| （questor 特有：swarm/渠道） | 新增 kind | 追加 | 契约只加不改 |

## 5. 每刀纪律（沿用计划 01）

- 行为变更先红用例；模型可见面（StreamEvent→wire 映射）变更看 prompt-surface 同款金标思路。
- 每刀开工前先在本刀 PR 里列**条目清单**（逐条可勾选）；收刀时按 §0.5-6 三张表逐条对账，
  **清单上的条目不得合并、不得省略**；实际改动超出清单也要补登（防止"顺手多改"与"隐形成本"）。
- 每阶段开工第一动作 = §0-8 复用检索（**DeepCode → Reasonix** → 按需 hermes/CowAgent），
  结论入 PR 描述；界面元素受 §0-9 零视觉自设计三序约束（IA 自定）。
- 每阶段同一刀完成 TREE/GRAPH/`--refresh-baseline --reason "plan02 阶段 <n>: ..."`；结构红线
  （行数/扇出/禁用名/门面零逻辑）照常生效。
- 阶段 4 起，`apps/web` 的 eslint / tsc / vitest / build 随 `scripts/check.py` 的 `frontend`
  lane 同一刀跑完；**只跑 Python 侧门禁就报绿 = 违规**。
- aiohttp 是 ADR-0006 唯一新增依赖；进入依赖树须过 layout/structure 基线。
- 排版约定同计划 01：反引号=已存在，加粗=待创建。

## 6. 停工症状（出现即停，先修门）

1. 契约 codegen 守卫红了想"先跳过"——禁止。
2. 想改既有 kind/字段名——停，回 ADR-0006 补变更记录并经用户批准。
3. 想在阶段 2 之前删 frontend/terminal（阶段 2 已删除） 或 backend_host 链——禁止，时点锁死阶段 2。
4. vendored 树想顺手重构/拆分——禁止，第一刀零修改（4a-3 的目录改名是**已登记的一刀**，
   不属于顺手重构；其他拆分在后置池）。
5. 启动扇出表之外的端点被调用致 404——停，先补表再实现。
6. serve 想绕过 `handle_line` 自写提交链、绕过 session_storage 自写存储——复用红线，停；
   确有理由必须新写，先走 §3 上报。
7. stub 想变"临时真实现"——停，转正必须过映射表 + 契约守卫（`gen_wire_* --check`）并
   移出扇出表。
8. 为让前端跑通写补丁式绕过（字符串解析/假字段/硬编码/静默丢信息）——§3 触发，停，上报。
9. 偷工减料任何形态：跳红验收、"应该能过"、验收不留痕、stub 不入表、报问题只给结论不给
   证据——禁止（CONVENTIONS §0）。
10. 未经 §0-8 的开工前复用检索就开写界面/机制，或自行设计任何**视觉元素**（风格、布局、
    按钮、图标、交互）——停；界面元素只能来自 §0-9 的三序来源，新造必须先登记并让用户过目。
11. 引擎有、界面无的功能未登记"暂不暴露"——功能黑洞，停，补功能可见性映射表或上报。
12. 临时渲染器（DeepCode `TurnBlock` 的对话分支）未在 4b-6 删除却进了阶段 5——停。
13. `apps/web` 内出现 WebSocket 传输（`new WebSocket`、`tauriRuntime` 残留）——停，
     ADR-0006/0007 已定 SSE。
14. 4a 的字段预检未绿就一次性搬五张卡——停，那是把两个未知量同时引入。
15. `apps/web` 文件与**首刀基线 commit** 有差异但不在 VENDOR.md 的禁区/已改清单内——停，
    先登记归属与理由。
16. 用"界面先糊上去以后再接线"制造 stub 堆积——§3 触发，停。
17. 新增 kind 未在 `wire.py`、`cardSlots`、映射表三处任一登记，却用通用兜底渲染遮过去——
    禁止；kind 覆盖守卫必须红。
18. 新增持久化字段而不升 `schemaVersion`、或读不了上一版文件——停，持久化版本守卫必须红。
19. 卡片未包错误边界、或 transcript 未虚拟化就交付 4b / 阶段 5——停（实测骨架两者皆缺）。
20. 组件里出现形态判断（`mode ===`、`isPersonal`、按 profile 分支渲染不同结构）——停；
    形态差异只能经 `profile.ui` + 页面注册表 + capability 门控表达。
21. 新增页面未进 `pages/registry.ts`（导航 / 命令面板靠手改）——停。
22. 新增 profile 却没写 `profile.yaml` / 没改 `allowed_tools`（两个形态工具面一样）——停。
23. 直接把一套 token 变量"覆盖"到另一套（不建别名映射、不跑 `var()` 守卫）——停；
    实测两套变量交集仅 1 个，覆盖等于把骨架样式删干净。
24. 以"文件太长 / 工作量大 / 时间不够"为由只读一半、只写一半，或交出**低于计划预期**的
    实现——停，按 §3 上报，不得自行降配（§0.5-4/5）。
25. 缺三张对账表（条目 / 影响面 / 判红）就宣布阶段完成——未完成（§0.5-6）。
26. 把计划里的"逐项"（每屏/每卡/每条用例）做成"大部分"，或用 stub/TODO 顶替——停。
27. 页面未声明 capability 就进 `registry`；或把已有 page id 改名 / 删除（应改 `absent`）——停。

## 7. 总验收表（每阶段回填）

| 阶段 | 分支 | 绿验收 commit | 红验收 commit | 备注 |
|---|---|---|---|---|
| 1 | feat/studio-serve | | | 契约 schema + 双侧 codegen + 并发/幂等判红 + kind 覆盖 + 持久化版本 + **profile 底座（bundle + `/profile`）**；含 ADR-0006 勘误 |
| 2 | feat/studio-serve | | | 删除刀 + `/cancel` |
| 3 | feat/studio-serve | | | 五件套 + 多客户端语义 |
| 4a | feat/studio-web | | | 基座 + 接门 + 换契约 + 字段预检 + 可用闭环 + ErrorBoundary/虚拟化 + **页面注册表/capability 门控** |
| 4b-1…5 | feat/studio-web | | | 五张卡，每张一刀；`cardSlots` 穷尽（缺槽位 = `tsc` 红） |
| 4b-6 | feat/studio-web | | | 删临时渲染器 + tokens 覆盖 |
| 5 | feat/studio-web | | | 壳 + updater 回滚 + soak |
| 6 | feat/studio-web | | | design-qa |

**填写规则**："绿验收 commit"只有在 §0.5-6 的三张对账表（条目 / 影响面 / 判红）齐备时才可填；
任一表缺失，该阶段视为**未完成**（不是"稍后补"）。对照表本身随 PR 描述存档。

## 8. 已决与开放问题

**已决（2026-10-24，用户裁决）**：

- **不设上游快照标识**。vendored 代码入仓即本仓资产；基线 = `apps/web` 首次原样提交的那个
  **单独 commit**，`git diff <commit> -- apps/web` 就是“我们改了什么”。MIT 义务只有
  `THIRD_PARTY_NOTICES.md` 的版权声明，与上游 commit 无关；`VENDOR.md` 的职责是
  **禁区清单**（哪些文件不许改、哪些是我们改的、为何），**不是上游谱系账本**。
- **不建 personal 空壳页**。`declared` 态的本义就是“已声明、未就绪→入口不出现”；personal
  五个 page id 只写在 `personal/profile.yaml` 的 `ui.capabilities` 里，`pages/registry.ts`
  只登记真实存在的页面；门控用 coding 侧真实页验证（将 `inspector` 置 absent → 导航消失）。
- **personal 首批 page id = `chat` / `persona` / `memory` / `schedule` / `channels`**。
  这是**首批注册集，不是上限**：页面可随功能增量新增，新增不改本计划，只走 4a-8 的四步
  （注册表 + `ui.capabilities` + 必要时的 schema kind + 映射表）。
- **插话队列**：契约先留 `queued` 状态位（`/submit` 忙时可返回 `queued`，`authority.py` 预留
  1 个 pending 槽），**行为实现后置**到 personal 首批。
- **导航容量规则**：一级导航固定 ≤7 项；超出归入“更多 / 设置”分组。新增页面优先并入既有
  分组，**不得为单页新开一级入口**。

**开放（执行 agent 不得代答）**：

1. appearance 四包去留——阶段 2 裁决。
2. `src/questor/runtime.py:45` 产品 REPL 入口去留——阶段 2 前置核查后裁决。
3. `protocol.py` 若含 backend_host 之外内容，拆分方案——阶段 2 前置核查后定。
4. studio 宿主 prompt_surface flavor 时机（4a 或顺延）。
5. ADR-0006 §5 "8 种"勘误提交时点（默认随阶段 1，用户可提前）。
6. 4b 之后是否追加 RememberCard / MeterRail / Jobs / Agents 四卡（默认后置池）。
7. 中文术语表（渠道 / 任务 / 团队 / 记忆召回 / 快照）定稿时点——建议 4a 之前。

## 9. 与计划 01 及引擎功能线的协调

1. 本线新增文件改变计划 01 的 B1/B7 等读数——只经 `--refresh-baseline --reason` 刷新，禁止手改。
2. `events.py` 尾注（B10）指向计划 01 的 W8 镜像测试；本线的双侧 codegen（ADR-0007 §4）
   覆盖面更广。合流时由用户裁决：保留 codegen 单一实现，W8 若已落地则收敛为对 codegen 的调用，
   尾注随之摘除。
3. 引擎功能线（P0 快赢、P1 崩溃韧性）并行不冲突；P1 落地后 `checkpointTurn` 从 false 变真，
   前端零改。
4. 渠道线（飞书/QQ）不经 serve 宿主，本线不触碰 `src/questorharness/surfaces/`。
5. `docs/ARCHITECTURE.md` 的"客户端拓扑"一节在 4a 落位时补一行：`apps/web` 基座 =
   DeepCode 骨架 + Reasonix 对话面（ADR-0007），避免拓扑文档与实物脱节。
6. 双形态由 ADR-0008 落地：`profile.ui` 与 `STRUCTURE.md` §7 边界 5 同源——改一处必须同刀改
   另一处；`src/` 内仍不得出现形态判断。

## 10. 非目标

- **不**做 Go 单二进制分发（questor 用 PyInstaller + Electron，参照 hermes/DeepCode）。
- **不**抄 Reasonix 的 Go 内部实现，只读思路与协议形态（服务端为语义翻译，非复制代码）。
- **不**采用 WebSocket（ADR-0006 已否），**不**采用 Tauri 壳（ADR-0005 §3 已否）。
- **不** vendor Reasonix 整树：只取五张对话卡 + 设计法典（ADR-0007）。
- **不**做 Next.js / SSR（apps/web 是 loopback 上的纯 SPA）。
- **不**做 cloud / peers / market / 地图 / 内置浏览器 dock 等**本引擎没有后端**的界面
  （已裁与待裁清单记在 `apps/web/VENDOR.md`）。
- **不**引入 Reasonix 的 `ui-census` 分析器（用 frontend lane + 扇出表 + 映射表替代）。
- **不**做两套 renderer / 两套导航：形态差异只在 profile 数据、页面注册表与 capability 门控。
- **不**在 Python 引擎里写形态分支：个人形态 = 另一份 profile bundle + 另一套工具/技能目录。
- **不**立项 durable spine / 事件溯源（STRUCTURE §11 未变；传输 seq ≠ 会话事实流，重放是
  有界尾巴）。
- **不**做分布式高可用（单用户本地应用，永久负收益）。
- **不**改动 DeepCode 对标得出的 P0–P5 功能路线图。

## 参考地图

### Reasonix（传输语义 / 设计法典 / 对话卡；行号经维护者 2026-10-24 亲验）

| 先例 | 位置 | 借什么 |
| --- | --- | --- |
| SSE 恢复双通道 + watermark | `eventstream.go:66,89,361` | Last-Event-ID 恢复与心跳帧 |
| droppable 可丢分类 | `broadcaster.go:39-43` | 进度可丢、事实不可丢 |
| /events/mux 复用 | `hub_mux.go:267-269` | 单连接多流复用（后置池） |
| 回环监听 + 随机端口 | `main.go:300,304,327` | ListenLoopback |
| 一次性凭据 | `main.go:348` | "never read from configuration and never persisted" |
| HttpOnly cookie | `main.js:52,187,282` | 凭据种植 |
| Host + Origin 校验 | `host.js:151-167` | token≥32、hostname 必须 127.0.0.1 |
| 父进程租约 | `main.go:327` 附近 | 父退即失效 |
| 进程内 transport | `tui_command.go:25-33` | 同一组路由、主机名从不解析、无认证面 |
| 契约守卫（反面样本） | `frontend_contract_test.go` | 单向 / 文件缺失即 `Skipf` / `compared>=10` 兜底——**不照抄**，改用双侧 codegen（ADR-0007 §4） |
| 设计法典 | `styles/TOKENS.md`(329 行) / `styles/LAYOUT.md`(1591 行) / `tokens.css`(279 行) | 设计真源可移植 |
| 服务端结构镜像源 | `internal/frontend/serve/`（serve.go/routes.go/eventstream.go/broadcaster.go/hub.go） | 阶段 1 文件组织对齐 |

### DeepCode（骨架 / 契约 codegen / 工程链；实测 2026-10-24）

| 先例 | 位置 | 借什么 |
| --- | --- | --- |
| 单 schema → 生成 TS + `--check` | `protocol/app-server.schema.json`（176.8 KB）→ `desktop/scripts/generate-protocol.mjs` → **src/generated/app-server.ts**（47.9 KB） | 阶段 1 双侧 codegen 的直接手法 |
| 双 Transport 共用一套 envelope | **src/rpc/contracts.ts** + `browserRuntime.ts` + `tauriRuntime.ts` | `ClientRuntime` 接口保留，只换实现（WS→SSE） |
| 对话壳与控制器 | `features/thread/{TurnBlock,ReasoningBlock,ThreadConversation,conversationModel}`；`features/execution/{Composer,ModelPicker,ApprovalCard}` | 4a 可用闭环 + 4b 临时渲染器 |
| 状态与会话回放 | `app/workspaceState.ts`(17.1 KB) / `useWorkspaceController.ts`(32.7 KB) / `threadEventStream.ts` / `replayThreadHistory.ts` | 直用（已 vendor） |
| 中文 i18n | `app/i18n.ts`（ZH_CN 226 条，`navigator.language` 自动切） | 直用 |
| 样式体系 | 26 个 CSS Module / 6,936 行 + `styles/tokens.css`(20.2 KB) + `tokens.test.ts` | 直用；token 层由 Reasonix tokens 覆盖 |
| 工程链 | `lint` / `typecheck` / `test` / `test:web`(playwright) / `audit:licenses` / `build:sidecar` | 4a 全量接进 `check.py` + CI |
| 同语言服务端参考 | `app_server/{service,host,dispatcher,peer,browser_auth}.py`（aiohttp） | 阶段 1/3 对齐参考（**不搬 WebSocket 传输**） |

### 形态参照（一个产品两种形态：hermes / CowAgent / 业界）

| 先例 | 位置 | 借什么 |
| --- | --- | --- |
| profile = 目录 bundle + 角色描述 | `hermes-agent-main/hermes_cli/profiles.py`（`ProfileInfo` 含 `description`、model/provider、skill_count） | 阶段 1 `profiles/` 的模型形状 |
| profile 作用域的前端切换 | hermes `apps/desktop` 的 `client.ts`（`/api/profiles` + `$activeGatewayProfile`） | `/profile` 端点的消费方式（设置/技能/工具随 profile） |
| 个人形态 UI 控件 | CowAgent `desktop/src/renderer/{AgentSelector,AgentScopeSelect,ChannelTeamSelect,ContextUsageDonut}` | personal 首批页面与控件来源 |
| 模式 = 角色 + 工具组（业界） | Roo Code custom modes | "形态是数据 + 能力位"的参照；**不是**代码分支 |
