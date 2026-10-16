# 贡献指南

谢谢你想参与 Questor！项目现在处于**设计先行、逐步实现**阶段，请先读 `docs/`（尤其 `VISION.md`、`ROADMAP.md`、`design/HARD-CONSTRAINTS.md`）。

## 开发环境

- Python 3.13，依赖用 **uv** 管理（不要直接用 pip）。
```bash
uv sync                 # 建 .venv 并安装 core 依赖
uv run questor --help   # 运行（P1 起可用）
uv run ruff check .     # lint
uv run pytest           # 测试
```
- extras（默认不装，按需）：`uv sync --extra im|voice|browser|docs`。

## 工作方式（重要）

- **设计先行**：改动若触及分层/契约，先看并在必要时更新对应 `docs/design/*`；难回退的决策记一条 `docs/adr/*`。
- **每个改动可验证**：编译 + 测试 + lint + 冷导入 + 不破 `HARD-CONSTRAINTS` 红线；"跑不通不提交"。
- **小步提交**，Conventional Commits（`feat/fix/refactor/chore/docs/test:`，英文）。

## 代码注释规范（**中文**）

标识符、日志消息、API 名保持英文；**注释与 docstring 一律用中文**。（AGENTS §5.6）

1. **文件/模块头**（必写）：一句话职责 + 属于哪一层（L0–L7）+ 允许 import 什么。
   ```python
   """turn 循环的阶段流水线：把一次 run 拆成可单测的 phase。L2 Kernel。

   只依赖 contracts / state / providers 端口；禁止 import policy、surfaces 的具体实现（HARD C1/C14）。
   """
   ```
2. **公开类 / Port / 函数都要中文 docstring**：做什么 · 怎么用 · 依赖什么 · **不变式与前后置条件** · **失败语义**（抛/返回/降级）。复杂或公开接口补参数与返回说明。
3. **写"为什么"，不写"是什么"**：非显然的决策、绕坑、权衡处必须注释；并就地引用依据：
   `ADR-0005`、`HARD C2`、`docs/design/02-event-protocol.md §10`、`参照 wuu internal/loopdriver/contract.go:14-76`。
4. **这些位置必须有注释**：权限判定分支、fail-closed 处、取消/回滚路径、事件是否落库的边界、并发/gate/租约代码、以及**任何改造自参考项目的代码**（注明来源与许可，AGENTS §4.5）。
5. **禁止裸 `TODO`**：每条 TODO/FIXME 要带上下文 + 归属的 Phase 或 ADR；`raise NotImplementedError` 处写明"P几实现"。
6. **别注释自明代码**（`i += 1  # 加一` 是噪音）；**改了行为就同步改注释**——过期注释按文档缺陷处理（§5.5 活文档）。
7. 不提交：大块被注释掉的死代码（除非注释说明为何保留）、未标来源/许可的复制代码。

> **注释不合格 = 该改动未完成**（AGENTS §5 DoD）；评审会按上述抽查。

## 分层红线（别越过）

内层只依赖 `contracts` + 注入端口；`kernel` 不 import `policy/surfaces/providers` 具体实现；只有 `Command` 改状态、`Event` 不反哺；策略只读状态视图。CI（分层守卫/冷导入）会挡住越界。

## 提交流程（分支策略见 [ADR-0012](./docs/adr/0012-branch-policy.md)）

**现阶段（自 2026-10-16 起）—— B 案**（分支策略切换记录见 ADR-0012 末尾）：
- **一律走分支 + PR**：从 `main` 切分支 → 小步细粒度提交 → 开 PR（用模板 + DoD 自检）→ **required checks 绿才能合**；维护者也不再直推 `main`。
- 内部可先保持“单人无 reviewer 自批合并”；门禁靠的是 **CI 的 blocking job**（`boundaries`：分层守卫 / 冷导入 / 协议漂移 / 守卫 self-test），不是人工 review。
- 不得 force-push 到 `main`；不得绕过钩子（`--no-verify`）。

> 诚实边界：GitHub 侧把 `boundaries` 设为 required status check、并关掉“管理员绕过”这两项设置需维护者手动完成（见 ADR-0012 切换记录）。在该设置落地前，不直推 `main` 是靠约定而非强制——不要把它当成“技术上拦得住”。

Bug 用 issue 模板；安全漏洞**不要开公开 issue**，见 SECURITY.md。

## AI 辅助

本项目接受 AI 辅助开发；重大设计决策与验收由维护者负责。

## 行为准则

见 CODE_OF_CONDUCT.md。
