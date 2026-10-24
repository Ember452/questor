# 计划 02：Studio / serve 宿主与统一线协议

- Status: Active（2026-10-24 立项）
- 决策依据：[ADR-0005 Updated](../adr/0005-single-ui-host.md)（客户端拓扑与判死清单）、
  [ADR-0006](../adr/0006-serve-host-and-wire-protocol.md)（一份契约两种传输、帧模型、TS 镜像）
- 参照系：Reasonix（Go，不在仓内；行号经维护者 2026-10-24 逐条亲验，见文末参考地图）
  与 DeepCode（P0–P5 功能路线图独立保留，本计划不改动它）

## 目标一句话

三张嘴（终端 REPL / Electron / 浏览器）吃**同一组 serve 路由**：REPL 走进程内
transport（不开端口、无凭据），Studio/Web 走回环 TCP + 凭据五件套；旧宿主
（OHJSON / backend_host / react_launcher / Node Ink / `--backend-only`）在 REPL
验收通过的同一刀内删除。

## 阶段

### 阶段 1：契约与进程内 serve

- `RuntimeBundle` 进程内装配；serve 路由 + wire 帧 + SSE（单调 `seq` /
  `Last-Event-ID` 双通道 / watermark 心跳 / droppable 分类 / mux 复用）+
  POST 命令 + refusal code；全部挂在**内存 transport** 上（无端口、无凭据）。
- StreamEvent（8 种）→ wire 帧的映射表落地。
- **验收**：进程内 transport 上以 curl / 脚本驱动完整回合（提交 → 事件流 →
  快照），不依赖任何网络端口。

### 阶段 2：终端 REPL 瘦客户端 + 删除刀（同一刀）

- REPL 作为瘦客户端上线：消费同一契约，零业务、零状态投影。
- **同刀删除**（判死清单，ADR-0005 Updated）：`frontend/terminal/`、
  `backend_host.py` + OHJSON 协议、`react_launcher.py` + `hosts/app.py` 的
  React TUI 启动路径、`--backend-only`。
- **验收**：
  - `rg "OHJSON|backend_host" src` = 0；`rg "react_launcher|--backend-only" src pyproject.toml` = 0；
  - TREE / GRAPH / `gen_structure_baseline --refresh-baseline --reason`、
    `prompt_surface/desktop.txt`、`doctor.txt`、help 基线同一刀重录；
  - MIGRATION 加删除条目；ARCHITECTURE 依赖图摘掉 legacy 节点。

### 阶段 3：回环 TCP 宿主 + 凭据五件套

- 仅监听 127.0.0.1 的随机端口；一次性 launch credential（≥32 字节随机，
  永不出自配置、永不落盘）；HttpOnly cookie 种植；Host + Origin 校验
  （hostname 必须 127.0.0.1）；父进程租约（父退即失效）。
- **验收**：`apps/web` 能单独在浏览器跑（STRUCTURE §8）；Electron 只是它的
  host；五件套各有一条判红测试（错误来源的连接必须被拒）。

### 阶段 4：TS 镜像即契约 + 守卫

- `apps/web` 侧 wire 类型文件，头注释声明 "this file is the contract, not a
  convenience shape"。
- `tests/ci` 守卫：镜像与引擎侧定义漂移即红（对齐 Reasonix
  `frontend_contract_test` 形态）。
- **验收**：改引擎侧帧定义而不改镜像 → CI 红；改镜像而不改引擎 → CI 红。

### 阶段 5：设计法典与质量门

- `TOKENS.md` / `LAYOUT.md` / `tokens.css` 移植进仓为设计真源；关键交互
  （ApprovalCard 等）对齐实现；design-qa 检查进 guards。
- **验收**：design-qa 在 `check.py` 里有一条可判红的自测；文档终验与
  路线图收口。

## 每刀纪律（沿用计划 01）

- 行为变更先红用例；模型可见面（StreamEvent→wire 映射）变更看 prompt-surface
  同款金标思路。
- 每阶段同一刀完成 TREE / GRAPH / `--refresh-baseline --reason`；
  结构红线（行数 / 扇出 / 禁用名 / 门面零逻辑）照常生效。
- aiohttp 是 ADR-0006 唯一新增依赖；进入依赖树须过 layout / structure 基线。

## 非目标

- **不**做 Go 单二进制分发（questor 用 PyInstaller + Electron，参照
  hermes / DeepCode）。
- **不**抄 Reasonix 的 Go 内部实现，只读思路与协议形态。
- **不**立项 durable spine / 事件溯源（STRUCTURE §11 未变；传输 seq ≠ 会话
  事实流，重放是有界尾巴）。
- **不**改动 DeepCode 对标得出的 P0–P5 功能路线图。

## 参考地图（Reasonix，行号经维护者 2026-10-24 亲验）

| 先例 | 位置 | 借什么 |
| --- | --- | --- |
| SSE 恢复双通道 + watermark | `eventstream.go:66,89,361` | Last-Event-ID 恢复与心跳帧 |
| droppable 可丢分类 | `broadcaster.go:39-43` | 进度可丢、事实不可丢 |
| /events/mux 复用 | `hub_mux.go:267-269` | 单连接多流复用 |
| 回环监听 + 随机端口 | `main.go:300,304,327` | ListenLoopback |
| 一次性凭据 | `main.go:348` | "never read from configuration and never persisted" |
| HttpOnly cookie | `main.js:52,187,282` | 凭据种植 |
| Host + Origin 校验 | `host.js:151-167` | token≥32、hostname 必须 127.0.0.1 |
| 父进程租约 | `main.go:327` 附近 | 父退即失效 |
| **进程内 transport（本轮新发现）** | `tui_command.go:25-33` | 同一组路由、主机名从不解析、无认证面 |
| TS 镜像即契约 | `port/wire.ts` 头注释 + `frontend_contract_test.go` | "the contract, not a convenience shape" + 守卫测试 |
| 设计法典 | `styles/TOKENS.md`(329 行) / `styles/LAYOUT.md`(1591 行) / `tokens.css`(279 行) | 设计真源可移植 |
