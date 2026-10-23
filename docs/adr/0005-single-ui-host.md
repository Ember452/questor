# ADR 0005: UI 宿主正典——Electron + React 作为唯一 UI

- Status: Accepted
- Date: 2026-10-22
- Updated: 2026-10-23（执行完毕：Python textual UI 已删除）
- Deciders: Questor maintainers

## Context

当前仓内同时存在两套终端 UI：

- `frontend/terminal`：Node Ink（`ink` 5 / `react` 18 / `tsx`），打包时以 force-include 注入 `questorharness/_frontend`；
- `src/questorharness/bootstrap/hosts`：Python IPC 宿主，历史上依赖 `textual` 与 `prompt-toolkit`。

同时产品路线要求 Electron 桌面端（`apps/desktop` + `apps/web`），并且 personal / coding 两种模式要共用同一套 run/session。三套 UI 意味着三份状态投影、三份输入/快捷键/主题实现，以及两条打包链。

## Decision

1. `apps/web`（React）是唯一 renderer；`apps/desktop`（Electron main/preload）只是它的宿主。
2. 终端体验若保留，只作为**瘦客户端**：复用同一套 Transport（HTTP/SSE/IPC）与 envelope，不复制业务、不复制状态投影；**不建 `surfaces/terminal/`**。
3. 进程装配的归属：
   - 组合根在 `src/questorharness/bootstrap/runtime.py`；
   - 进程宿主在 `src/questorharness/bootstrap/hosts`（stdio / React backend / 启动器）；
   - `src/questorharness/surfaces` 只放面向 renderer 的适配器（当前只有 `channels`），**不再承载进程宿主**。
4. Python textual UI 与 `prompt-toolkit` 依赖已移除：
   - 删除 `textual_app.py`、`output.py`、`input.py`、`permission_dialog.py`；
   - `pyproject.toml` 不再声明 `textual` 与 `prompt-toolkit`；
   - `scripts/guards/check_layout.py` 阻止它们通过 import 回到 `src/`。
5. `surfaces` 只保留 channels；宿主归 `bootstrap/hosts`。

## Alternatives considered

- **保留 Ink 作为长期终端**。拒绝：它已经是一个独立 renderer，需要独立的协议客户端与主题系统；在 Electron 之外再养一份长期 UI，成本高于收益。
- **保留 Python textual UI 并迁到 `surfaces/terminal`**。拒绝：它会和 `apps/web` 争抢同一份状态投影，且 `textual` / `prompt-toolkit` 会把表现层依赖带进引擎 wheel。
- **把 IPC 宿主放进 `surfaces/`**。拒绝（2026-10-23 修正）：宿主必须装配组合根，依赖方向是 `bootstrap > surfaces`；放在 `surfaces/` 会让 `surfaces-are-thin` 契约只能覆盖子集，等于这一层没有守卫。
- **两套终端都保留**。拒绝：三套 UI 的状态一致性无法验证，E2E 成本按 UI 数量线性增长；“无 GUI 环境”用瘦客户端满足，不再写第二套 renderer。

## Consequences

变得更容易：

- 只有一份 renderer，protocol codegen 只服务一个消费者；
- 引擎 wheel 不再包含 `_frontend`、`textual`、`prompt-toolkit`；
- `surfaces-are-thin` 契约覆盖整个 `surfaces` 包，而不是一个子目录；
- personal / coding 的 UI 差异由 `profile.ui` 能力位驱动，不需要两套实现。

变得更难 / 必须接受：

- 移除终端后，“无 GUI 服务器上的交互体验”会退化；确有需要时用瘦客户端补，不恢复第二套 renderer。
- 宿主与组合根同处 `bootstrap`，该包行数会随宿主能力增长；文件预算由 `check_layout.py` 守住单文件上限。

## Verification

- Phase 1 结束时：改动文件不包含 `themes/`、`keybindings/`、`vim/`、`output_styles/`、`frontend/terminal`。
- Phase 2 移除后（2026-10-23 实测）：
  - `rg "questorharness\.ui|prompt_toolkit|textual" src` 为 0；
  - `uv run questorharness --help` 与 `uv run python -m questor --help` 输出逐字不变；
  - wheel 内不再有 `questorharness/_frontend`；
  - 基线五项（MIGRATION §3.1）逐项不变。
