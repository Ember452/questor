# ADR 0005: UI 宿主正典——Electron + React 作为唯一 UI

- Status: Accepted
- Date: 2026-10-22
- Deciders: Questor maintainers

## Context

当前仓内同时存在两套终端 UI：

- `frontend/terminal`：Node Ink（`ink` 5 / `react` 18 / `tsx`），打包时以 force-include 注入 `questorharness/_frontend`；
- `src/questorharness/ui`：11 个 Python 模块，依赖 `textual` 与 `prompt-toolkit`，被 18 处 import。

同时产品路线要求 Electron 桌面端（`apps/desktop` + `apps/web`），并且 personal / coding 两种模式要共用同一套 run/session。三套 UI 意味着三份状态投影、三份输入/快捷键/主题实现，以及两条打包链。

## Decision

1. `apps/web`（React）是唯一 renderer；`apps/desktop`（Electron main/preload）只是它的宿主。
2. 终端体验若保留，只作为**瘦客户端**：复用同一套 Transport（HTTP/SSE/IPC）与 envelope，不复制业务、不复制状态投影；**不建 `surfaces/terminal/`**。
3. `frontend/terminal`、`src/questorharness/ui`、`themes/`、`keybindings/`、`vim/`、`output_styles/` 在 Phase 1 **冻结**（不搬、不新增功能），Phase 2 用单独 PR 移除。
4. 移除顺序固定为：先解耦（把 CLI 编排从 `ui/` 抽出，保证 `questorharness --help` 与 run 路径不依赖 ui）→ 再删模块 → 再删依赖（`textual`、`prompt-toolkit`）→ 最后删 `frontend/terminal` 与 wheel force-include。
5. `surfaces` 只保留 http / sse / ipc / gateway / channels。

## Alternatives considered

- **保留 Ink 作为长期终端**。拒绝：它已经是一个独立 renderer，需要独立的协议客户端与主题系统；在 Electron 之外再养一份长期 UI，成本高于收益。
- **保留 Python textual UI 并迁到 `surfaces/terminal`**。拒绝：它会和 `apps/web` 争抢同一份状态投影，且 `textual` / `prompt-toolkit` 会把表现层依赖带进引擎 wheel。
- **两套终端都保留**。拒绝：三套 UI 的状态一致性无法验证，E2E 成本按 UI 数量线性增长；“无 GUI 环境”用瘦客户端满足，不再写第二套 renderer。

## Consequences

变得更容易：

- 只有一份 renderer，protocol codegen 只服务一个消费者；
- 引擎 wheel 不再包含 `_frontend` 与 `textual` / `prompt-toolkit`；
- personal / coding 的 UI 差异由 `profile.ui` 能力位驱动，不需要两套实现。

变得更难 / 必须接受：

- Phase 2 要处理 18 处 `ui` import 与 CLI 编排解耦，属于行为保持类改动，必须用基线五项护航；
- 移除终端后，“无 GUI 服务器上的交互体验”会退化；确有需要时用瘦客户端补，不恢复第二套 renderer。

## Verification

- Phase 1 结束时：改动文件不包含 `ui/`、`themes/`、`keybindings/`、`vim/`、`output_styles/`、`frontend/terminal`。
  - 例外（2026-10-22 实测）：`ui/*.py` 的 **import 行** 必须随被搬包改写（`ui/runtime.py`、`ui/backend_host.py`、`ui/app.py`、`ui/textual_app.py`、`ui/protocol.py` 共 18 行，涉及 api / auth / mcp / permissions / tools / sandbox）。本条的“不包含”指 **不搬迁、不改行为**；只改 import 路径行。
- Phase 2 移除后：
  - `rg "questorharness\.ui|prompt_toolkit|textual" src` 为 0；
  - `uv run questorharness --help` 与 `uv run python -m questor --help` 输出逐字不变；
  - wheel 内不再有 `questorharness/_frontend`；
  - 基线五项（MIGRATION §3.1）逐项不变。
