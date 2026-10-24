# ADR 0007: 前端基座与契约 codegen（DeepCode 骨架 + Reasonix 对话面）

- Status: Accepted
- Date: 2026-10-24
- Deciders: Questor maintainers

## Context

ADR-0005 定了唯一 renderer 与 Electron 壳，ADR-0006 定了 serve 宿主、SSE+POST、36 kind
与凭据五件套。两者都没有回答一个问题：**`apps/web` 的代码从哪里来**。计划 02 原稿写的是
"Reasonix `desktop/frontend-next` 整树 vendor"，本 ADR 修正这个选择。

实测（2026-10-24，两侧均为仓内/仓外真实目录读取，非估计）：

- Reasonix `desktop/frontend-next`：1,325 个 ts/tsx、133,778 行；675 个测试文件 / 63,476 行；
  `app.css` 322 KB + `studio.css` 214 KB，**1,262 个全局唯一类选择器**；i18n 约 450 KB 且
  **只有英文**；`port.ts` **285 个方法** / 47 KB；`wire.ts` 52 个 interface；88 个 UI 文件属于
  cloud / peers / graph / 地图 / 浏览器 dock 等 questor 永远不会有后端的域；服务端为 Go
  （`internal/frontend/serve`：198 个非测试文件 / 24,762 行）。
- DeepCode `desktop/`：174 个 ts/tsx、37,130 行；43 个测试文件 + playwright `web.spec.ts`；
  26 个 CSS 文件 / 6,936 行 + `tokens.css` 20 KB；`protocol/app-server.schema.json` 176 KB
  经 `json-schema-to-typescript` 生成 **src/generated/app-server.ts**，由 `check:protocol` 守卫；
  **src/rpc/** 有 `browserRuntime` 与 `tauriRuntime` **两个 Transport 实现**；`i18n.ts` 内置
  zh-CN（226 条）；服务端是 Python + aiohttp（`app_server/service.py`、`websocket.py`、
  `browser_auth.py`、`dispatcher.py` 71 KB）。
- 结构与本仓意图文档吻合：`docs/architecture/STRUCTURE.md` §7 已规定
  `apps/web/{src/app, src/features, src/shared, src/generated}`、"Transport 的第二个实现与
  HttpTransport 共用同一套 Command/Event envelope"、"feature 之间零引用"。DeepCode 的目录
  形状逐条对应，差异只有两处：Transport 实现（WebSocket → SSE）与目录名（`platform/` → `shared/`）。
- 规则冲突必须显式裁决：`docs/CONVENTIONS.md` §4.5 要求"the merged code carries no external
  source/license/attribution marker"。整树 vendor 与该条冲突；不开作用域例外，计划与守则自相矛盾。

## Decision

1. **基座 = DeepCode `desktop/`**：骨架、`features/` 垂直切片、状态与控制器
   （`workspaceState` / `useWorkspaceController` / `threadEventStream` / `replayThreadHistory`）、
   CSS Module 体系、工程链（eslint / tsc / vitest / playwright / license audit）。
2. **对话面与设计法典 = Reasonix**：Say / Tool / Approval / Ask / Compaction 五张对话卡，
   连同其 CSS 类块与测试逐刀搬迁；`TOKENS.md` / `LAYOUT.md` 作为视觉真源。token 变量层
   **迁移而非覆盖**：实测 DeepCode 69 个变量与 Reasonix 128 个**只重叠 1 个**
   （`--shadow-float`），覆盖会让骨架 68 个变量失效；做法是两套并存 + 别名映射表 +
   `var()` 未定义守卫（归计划 02 §4b-6）。
3. **传输 = ADR-0006**（SSE + POST + 凭据五件套 + 父租约），**不采用** DeepCode 的
   WebSocket。**src/rpc/contracts.ts** 的 `ClientRuntime` 接口保留，`browserRuntime.ts`
   重写为 SSE 实现；Tauri runtime 不进入本仓。
4. **契约真源 = 单份 JSON Schema，双侧 codegen**。`protocol/app-wire.schema.json`（手写，
   36 kind，只加不改）是唯一真源；TS 侧用 `json-schema-to-typescript` 生成
   **protocol/_gen/app-wire.ts**（分支一先落在仓根，4a 复制到 `apps/web/src/generated/`），
   Python 侧用仓内生成器产出 **serve/wire_types.py**；两侧都带 `--check` 并进入
   `scripts/check.py`。手写镜像文件与正则比对守卫作废（ADR-0006 §4 的意图保留，实现升级）。
5. **§4.5 作用域例外**：vendored 代码只允许存在于 `apps/`（非 Python 宿主层）；`src/`
   内仍受 §4.5 约束。归属义务：保留上游 `LICENSE` 原件、仓根 `THIRD_PARTY_NOTICES.md`
   增条目、`apps/web/VENDOR.md` 记录**禁区清单**与每个文件/目录的归属（vendored / owned /
   已裁）。**不记上游谱系**：基线 = 该目录首次原样提交的 commit（用户裁决 2026-10-24）。
6. **目录改名到 STRUCTURE §7 字面**（`platform` → `shared`，`components` → `shared/ui-kit`），
   作为独立一刀，43 个既有测试即改名验收。
7. **顺序纪律**：先让"骨架 + 真实 wire"跑通可用闭环（临时对话渲染器），再逐卡替换；
   临时渲染器必须在卡片搬迁最后一刀**同刀删除**。

## Alternatives considered

- **Reasonix 整树 vendor（原计划）**：设计成熟度最高、测试最多，但规模 3.6 倍、纯英文、
  契约由 Go 派生、88 个无后端入口；对话卡之外的 1,000+ 文件对 questor 是负资产。
  拒绝作基座，保留作卡片与设计法典来源。
- **CowAgent `desktop/`**：Electron + Python 同构，但 0 个前端测试、无契约 codegen。
  只借 Windows 端口保留区与进程管理片段。
- **hermes `apps/desktop`（3,660 文件 / 697,885 行）、wuu `desktop`（758 / 201,160）、
  deer-flow `frontend`（1,013 / 175,616，Next.js SSR）、evopanel（2,586 / 554,488）**：
  体量 20–70 万行，或 SSR 与 loopback SPA 拓扑冲突。拒绝。
- **自写前端**：与"界面零自设计 + 复用优先"冲突；5 张对话卡的交互密度不可能在合理工期内
  自研到位。拒绝。
- **手写 TS 镜像 + 正则守卫（替代双侧 codegen）**：上游 `frontend_contract_test.go` 的实测
  形态是**单向**（只查 TS 声明了 wire 未发的字段）、文件缺失即 `Skipf`、靠 `compared >= 10`
  兜底，覆盖不到请求侧与反向漂移。拒绝。

## Consequences

- 变得容易：AI 工作面从 13.4 万行降到 3.7 万行；中文一等公民（ZH_CN 226 条）；契约漂移由
  `--check` 机械拦截；阶段 1/3 的服务端对齐参考从 Go 换成**同语言同框架**实现。
- 变得难 / 必须接受：DeepCode 视觉成熟度低于 Reasonix，需在 4b-6 把设计法典**迁移**进
  DeepCode 的 token 体系（别名映射，非覆盖）；`apps/` 成为 vendored 区，永久需要
  `VENDOR.md` 与“与首刀 commit 的 diff”守卫；
  WebSocket 路径（`rpc/tauriRuntime.ts`、`app_server/websocket.py`）不得进入 questor 传输层。
- 保留不变：ADR-0005 的 Electron 壳；ADR-0006 的 SSE/POST/五件套/36 kind/at-least-once + seq 去重。

## Verification

- **tests/ci/test_wire_codegen.py**：改 schema 不改生成物 → 红；改生成物不改 schema → 红；
  生成物声明 schema 不存在的字段 → 红；生成物缺 schema 存在的字段 → 红。
- vendored 区守卫：`apps/web` 与**首刀 commit** 的差异必须出现在 `VENDOR.md` 的禁区/已改
  清单，否则红。
- 契约穷尽性：新增 kind 未在 `wire.py` / `cardSlots` / 功能可见性映射表任一登记 → 守卫红；
  `cardSlots` 用判别联合 + `never` 穷尽，缺槽位 = `tsc` 红。
- 持久化兼容：settings / 会话快照带 `schemaVersion`，读旧写新；新版读不了 v1 fixture → 红。
- 传输红线：`rg "new WebSocket" apps/web/src` = 0。
- 可用闭环：真实引擎驱动 submit → 流式 → 工具 → 审批 → 快照 → 恢复，且 `apps/web`
  可单独在浏览器跑（`STRUCTURE.md` §7）。
