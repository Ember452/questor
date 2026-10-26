# 贡献指南

谢谢你想参与 Questor。核心能力栈已实现，项目处于 alpha 形态演进期；改动前请先读
[架构说明](docs/ARCHITECTURE.md)、[行为守则](docs/CONVENTIONS.md) 与相关 [ADR](docs/adr/README.md)。

## 开发环境

- Python **3.13** 是开发与 CI 实际验证的版本；`pyproject.toml` 里 `requires-python` 声明的
  `>=3.10` 只是未经验证的下限，别把 3.10–3.12 当成受支持矩阵。依赖用 **uv** 管理（不要直接用 pip）。
- 桌面与 Web 端需要 Node 24，见 [桌面版指南](docs/guides/desktop.md)。

```bash
uv sync                           # 建 .venv 并安装 core 依赖
uv sync --extra dev               # 追加测试、lint、mypy、import-linter 等开发依赖
uv run python -m questor --help   # 用法与环境变量族（不建库、不起 REPL）
uv run questor                    # 交互 TUI（等价于 python -m questor；管道/CI 自动降级为行式 REPL）
uv run ruff check .               # lint
uv run pytest                     # 测试（unit + integration；e2e 需显式开启）
```

已安装的 console script 有四个：`questor`（产品应用）、`questorharness`（引擎）、
`oh` 与 `openh`（引擎的兼容别名）。产品入口与引擎入口不是同一套命令，区别见
[CLI 参考](docs/reference/cli.md)。

可选依赖只有 `dev` 一组。历史上列过的语音 / IM extras 已随 P6 阶段移出路线图而作废，
当前不存在 `voice`、`im`、`browser`、`docs` 等 extras，`uv sync --extra voice` 会直接失败。

## 工作方式（重要）

- **设计先行**：改动若触及分层或契约，先看并在必要时更新 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
  与 [docs/architecture/](docs/architecture/README.md)；难回退的决策记一条 [ADR](docs/adr/README.md)。
- **每个改动可验证**：编译 + 测试 + lint + 冷导入 + 不破分层红线；"跑不通不提交"。
- **小步提交**：Conventional Commits（`feat/fix/refactor/chore/docs/test:`，英文、subject 小写开头）。
- **文档同刀改**：行为变更与文档更新同一个改动；过期文档按缺陷处理（[CONVENTIONS](docs/CONVENTIONS.md) §5.5）。

## 代码注释规范（**中文**）

标识符、日志消息、API 名保持英文；**注释与 docstring 一律用中文**（[CONVENTIONS](docs/CONVENTIONS.md) §5.6）。

1. **文件/模块头**（必写）：一句话职责 + 属于哪一层（L0–L7）+ 允许 import 什么。
   ```python
   """turn 循环的阶段流水线：把一次 run 拆成可单测的 phase。L2 Kernel。

   只依赖 contracts / state / providers 端口；禁止 import policy、surfaces 的具体实现（HARD C1/C14）。
   """
   ```
2. **公开类 / Port / 函数都要中文 docstring**：做什么 · 怎么用 · 依赖什么 · **不变式与前后置条件** · **失败语义**（抛/返回/降级）。
3. **写"为什么"，不写"是什么"**：非显然的决策、绕坑、权衡处必须注释；就地引用本仓依据：
   `ADR-0005`、`HARD C2`、[docs/architecture/STRUCTURE.md](docs/architecture/STRUCTURE.md) 的对应小节。
4. **这些位置必须有注释**：权限判定分支、fail-closed 处、取消/回滚路径、事件是否落库的边界、并发/gate/租约代码。
5. **禁止裸 `TODO`**：每条 TODO/FIXME 要带上下文 + 归属的 Phase 或 ADR；`raise NotImplementedError` 处写明"P几实现"。
6. **别注释自明代码**；**改了行为就同步改注释**——过期注释按文档缺陷处理。
7. 不提交大块被注释掉的死代码（除非注释说明为何保留）。

> **注释不合格 = 该改动未完成**；评审会按上述抽查。

## 分层红线（别越过）

内层只依赖 `contracts` + 注入端口；`kernel` 不 import `policy/surfaces/providers` 的具体实现；
只有 `Command` 改状态、`Event` 不反哺；策略只读状态视图。规则本体在 `.importlinter`，
由 `uv run lint-imports` 与 CI 的 `guards` 作业机械执行，不靠自觉。

## 门禁与提交流程

**一律走分支 + PR**：从 `main` 切分支 → 小步细粒度提交 → 开 PR（用模板 + DoD 自检）→
**required checks 绿才能合**。维护者也不直推 `main`，不 force-push `main`，不绕过钩子（`--no-verify`）。

本地一条命令跑完全部阻断门禁：

```bash
uv run python scripts/check.py          # 全量：结构守卫 + lint + 测试
uv run python scripts/check.py --fast   # pre-commit 档，跳过慢检查
```

`make` 目标（`guards` / `lint` / `test` / `ci`）是同一批步骤的别名，Windows 上没有 `make`
时直接用上面的 Python 入口。门禁清单与 CI 作业拆分见 [docs/operations/ci.md](docs/operations/ci.md)。

Bug 用 issue 模板；安全漏洞**不要开公开 issue**，见 [SECURITY.md](SECURITY.md)。

## 文档改动

- 新文档写**中文**；存量英文文档在实质修改时顺手转为中文，不做无意义的全量翻译。
- 文档里的相对链接与反引号路径都会被 `scripts/guards` 校验，死链会让 CI 变红；
  短期无法修的历史坏链只能在文件头用 `<!-- known-stale-refs: ... -->` 逐条登记。
- **新页必须登记进索引**：`docs/` 下每个 md 都要能从 [docs/README.md](docs/README.md)
  沿链接走到，否则可达性守卫会判红。没人能走到的页等于没写。
- 文档索引与读者分流的唯一入口是 [docs/README.md](docs/README.md)。

## AI 辅助

本项目接受 AI 辅助开发；重大设计决策与验收由维护者负责。

## 行为准则

见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
