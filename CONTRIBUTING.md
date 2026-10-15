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

## 分层红线（别越过）

内层只依赖 `contracts` + 注入端口；`kernel` 不 import `policy/surfaces/providers` 具体实现；只有 `Command` 改状态、`Event` 不反哺；策略只读状态视图。CI（分层守卫/冷导入）会挡住越界。

## 提交流程

1. 从 `main` 切分支 → 2. 小步提交 → 3. 本地 `uv run ruff` + `uv run pytest` 绿 → 4. 开 PR（用模板）→ 5. 等 CI。
Bug 用 issue 模板；安全漏洞**不要开公开 issue**，见 SECURITY.md。

## AI 辅助

本项目接受 AI 辅助开发；重大设计决策与验收由维护者负责。

## 行为准则

见 CODE_OF_CONDUCT.md。
