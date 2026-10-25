# ADR 0006: serve 宿主与统一线协议

- Status: Accepted
- Date: 2026-10-24
- Deciders: Questor maintainers

## Context

客户端拓扑定为三张嘴、一份契约（ADR-0005 Updated 2026-10-24）：终端 REPL、
Electron（`apps/desktop`）与浏览器（`apps/web`）。现状却是每个客户端一份专用
宿主与私有协议（React backend 的 OHJSON stdio、Node Ink 直连），每加一个客户端
就要复制一份状态投影与输入处理。

参照仓库 **Reasonix**（Go 语言，不在本仓内）已经以同构方案解决了这个问题；
其关键先例经维护者 2026-10-24 逐条亲验，行号在 [plan 02 的参考地图](../plan/02-studio-serve-host.md)。
本 ADR 只借**思路与协议形态**，不抄 Go 实现。

## Decision

1. **一份契约、两种传输**。同一组 serve 路由：
   - **终端 REPL**：进程内装配 `RuntimeBundle`，路由挂在**内存 transport** 上——
     不开任何端口、无凭据、主机名从不解析（Reasonix `tui_command.go:25-33`
     先例：无端口即无可被攻击的认证面）。相比"REPL 起子进程再连 socket"：
     无启动开销、无真空期、无认证面。
   - **Studio / Web**：同一组路由挂**回环 TCP + 凭据五件套**（Reasonix
     `main.go:300-348`、`host.js:151-167` 先例）：① 仅监听 127.0.0.1 的随机
     端口；② 一次性 launch credential（≥32 字节随机，**永不出自配置、永不
     落盘**）；③ 凭据经 HttpOnly cookie 种植；④ Host 校验 + **仅改状态方法
     （POST/PUT/PATCH/DELETE）的 Origin 校验**，hostname 必须是 127.0.0.1——
     浏览器同源 GET（fetch/EventSource）往往不发 Origin，对所有方法强校验会把
     `/events`、`/history` 全拦成 403；GET 靠 Host + SameSite=Strict cookie 防护；
     ⑤ 父进程租约——宿主父进程退出即服务失效。
2. **帧模型**。事件下行 = SSE：单调 `seq` + `Last-Event-ID` 双通道恢复
   （`eventstream.go:66,89`）+ watermark 心跳帧（`:361`）+ droppable 可丢
   分类——进度类可丢、事实类不可丢（`broadcaster.go:39-43`）+ `/events/mux`
   复用单连接（`hub_mux.go:267-269`）。命令上行 = POST + **refusal code**
   （客户端按码分支，不解析自由文本错误）。

   > **帧集口径（2026-10-24）**：36 是参照仓的帧数，**不是本仓目标**。本仓契约以
   > **protocol/app-wire.schema.json** 的实际帧集为准（阶段 1 为 13 帧，全部有引擎来源），
   > 新增帧只加不改。
3. **对齐声明（不是新的一致性决定）**。传输层 `seq` 是传输的，不是会话事实
   流的；SSE 重放是**有界尾巴**，不是事件溯源；durable spine 仍未立项
   （STRUCTURE §11）。交付语义 = **at-least-once + seq 去重幂等**——恰是
   §11 已批准的一致性模型，本 ADR 不修改它，也不新开一致性 ADR。
4. **TS 镜像即契约**。`apps/web` 侧的 wire 类型文件头注释声明
   "this file is the contract, not a convenience shape"（Reasonix
   `port/wire.ts` 原则），并配 `frontend_contract_test` 同款守卫进
   `tests/ci`——镜像与引擎侧定义漂移即红。

   > **更新（2026-10-24，由 ADR-0007 §4 取代本节实现）**：意图不变，**实现方式作废**。
   > 手写镜像 + 正则守卫已证为弱守卫（Reasonix 的 `frontend_contract_test` 实测为单向、
   > 文件缺失即 `Skipf`、靠 `compared >= 10` 兜底）。现行实现为**单 schema + 双侧
   > codegen**：**protocol/app-wire.schema.json** 为唯一真源，TS 与 Python 两侧生成、
   > 两侧 `--check` 进 `scripts/check.py`。
5. **实现口径**。Python / aiohttp 表达；`contracts/domain/events.py` 的
   StreamEvent（7 种，2026-10-24 实测勘误：原误记 8 种）到 wire 帧的映射由本仓自定；**aiohttp 是本 ADR 唯一
   新增依赖**，进入依赖树须过 layout/structure 基线。
6. **设计法典随契约走**。`TOKENS.md` / `LAYOUT.md` / `tokens.css`（Reasonix
   `styles/` 先例，329 / 1591 / 279 行实物）移植进仓作为设计真源；关键交互
   （如 ApprovalCard）对齐实现；design-qa 检查进 guards。
7. **客户端拓扑登记**：见 [ARCHITECTURE](../ARCHITECTURE.md) 的"客户端拓扑"
   一节。`apps/web` 与引擎之间是 **HTTP 关系，不是 import 边**——分层阶梯
   与 `.importlinter` 不因宿主扩充而变化。

## Alternatives considered

- **WebSocket**。双向全双工，但重连、恢复、代理穿透都要自造；SSE + POST 的
  恢复模型已被参照实现完整验证。拒绝。
- **JSON-RPC**。请求/响应范式对单向事件流是错配，事件推送还得在其上再发明
  一层。拒绝。
- **全量 codegen**（8k 行级全量 schema 生成）。当前只有一个前端消费者，
  镜像文件 + 守卫测试已覆盖漂移；前端多到手工同步成为痛点时再升级，不预先
  建层（STRUCTURE §0-7）。现在拒绝。
- **OHJSON 扩展**。在 stdio 专用协议上继续加能力，等于把 backend_host 越焊
  越死，与瘦客户端方向相反。拒绝并判死（删除时点归 ADR-0005 Updated）。

## Consequences

- 判死清单（frontend/terminal（阶段 2 已删除）、`backend_host` + OHJSON、`react_launcher`、
  `--backend-only`）与删除红线归 ADR-0005 Updated 2026-10-24；阶段推进与
  验收标准归 `docs/plan/02-studio-serve-host.md`。
- `bootstrap/hosts` 收缩后，宿主面只剩 serve 装配与进程内入口；`surfaces`
  契约不变。
- aiohttp 进入依赖树；StreamEvent→wire 映射表成为新的模型可见面之一，
  变更须过 prompt-surface 同款金标思路。
- 引擎对标得出的 P0–P5 功能路线图不受本 ADR 影响，照旧推进。

## Verification

- `tests/ci` 守卫：wire 镜像漂移判红（对齐 `frontend_contract_test` 形态）。
- 删除刀红线：`rg "OHJSON|backend_host" src` = 0（全文见 ADR-0005 Updated）。
- 阶段验收：阶段 1 = 进程内 transport 上以 curl/脚本驱动完整回合；
  阶段 2 = 同刀删旧 + 红线 + 基线重录（plan 02）。
