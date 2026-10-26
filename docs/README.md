# 文档索引

先按"你是谁"选入口，再按"想干什么"找页。

## 按读者分流

| 我是… | 从这里开始 |
| --- | --- |
| 第一次听说这个项目 | 根目录 [README](../README.md) → [快速开始](guides/quickstart.md) |
| 想把它跑起来用 | [安装](guides/install.md) → [快速开始](guides/quickstart.md) → [故障排查](guides/troubleshooting.md) |
| 想接 MCP / 桌面 / 网关 | [集成](integrations/README.md) · [桌面版](guides/desktop.md) |
| 想看它怎么跑起来的 | [内部原理](internals/README.md) |
| 要改代码 / 提 PR | [CONTRIBUTING](../CONTRIBUTING.md) → [架构说明](ARCHITECTURE.md) → [行为守则](CONVENTIONS.md) |
| 要查一个具体值 | [参考手册](reference/README.md) |
| 想知道某个决策为什么这么定 | [ADR 索引](adr/README.md) |

## 按文档性质（Diátaxis）

不物理重排目录——生成物路径与 AGENTS 路由表都写死在现有位置上。用语义映射达到同样的分流效果：

| 性质 | 回答 | 位置的现有目录 |
| --- | --- | --- |
| 教程 | "带我走一遍" | [guides/](guides/README.md) 里的 quickstart、install |
| 操作指南 | "我要做某件事" | [guides/](guides/README.md) 里的 desktop、troubleshooting、testing |
| 参考 | "查确切的值与参数" | [reference/](reference/README.md) |
| 解释 | "为什么这样设计 / 它如何运转" | [internals/](internals/README.md)、[architecture/](architecture/README.md)、[adr/](adr/README.md)、[plan/](plan/README.md) |

## 目录清单

| 路径 | 内容 | 主要读者 |
| --- | --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 当前仓库布局、依赖方向、运行时数据目录 | 全体 |
| [CONVENTIONS.md](CONVENTIONS.md) | 行为守则 §0–§6（逐字存档）+ 路径勘误 | 贡献者 |
| [PRIVACY_AND_DIAGNOSTICS.md](PRIVACY_AND_DIAGNOSTICS.md) | 数据落盘、出站行为、诊断与脱敏 | 用户、报告问题的贡献者 |
| [architecture/](architecture/README.md) | 目标结构、关系图、目录树、命名空间、迁移 | 架构相关改动 |
| [adr/](adr/README.md) | 架构决策记录 | 做不可逆决策的人 |
| [guides/](guides/README.md) | 教程与操作指南 | 用户、新人 |
| [internals/](internals/README.md) | 机制原理（turn / 事件 / 权限） | 读代码前的人 |
| [integrations/](integrations/README.md) | 对外集成（MCP 等） | 集成方 |
| [operations/](operations/README.md) | CI 与运维（门禁清单、作业拆分） | 维护者 |
| [plan/](plan/README.md) | 分阶段施工台账与形态映射 | 维护者 |
| [reference/](reference/README.md) | CLI、环境变量、配置字段 | 全体 |

`architecture/GRAPH.md`、`architecture/TREE.md`、`architecture/NAMESPACES.md` 是**生成物**，
由 `scripts/` 下的生成器产出；手改会红构建。

## 语言策略

- **新文档一律中文**；存量英文文档（`ARCHITECTURE.md`、`architecture/`、`adr/0001-0008`、`operations/ci.md`）
  在实质修改时顺手转为中文，不做无意义的全量翻译。
- 不建 `en/` 平行目录：单人维护下双语漂移的成本高于收益。
- 标识符、命令、路径保持原文，不翻译。

## 文档也是被守卫的

| 机制 | 作用 |
| --- | --- |
| `scripts/guards/check_doc_cross_refs.py` | 校验相对链接与反引号里的仓库路径；扫描 `docs/` 与根目录文档 |
| 可达性 | `docs/` 下每个 md 必须能从本页**沿链接走到**；新增文档不登记索引就判红 |
| `<!-- known-stale-refs: ... -->` | 文件头 30 行内的逐条登记，且是**收缩式**：链接修好后必须删登记，否则报错 |
| `scripts/guards/check_agents_md_size.py` | 限制根 `AGENTS.md` 的体积，防止它变回大杂烩 |
| `uv run python scripts/check.py` | 本地跑完全部门禁（含以上两项与自测） |

改文档和改代码一样：先让守卫变绿，再提交。

## 历史文档

v1 时代的 110 个文件已在 W10 离开仓库，仓内只留指针
[docs-pre-reset-v1/README.md](../docs-pre-reset-v1/README.md)。`CONVENTIONS.md` 顶部有
旧路径到活路径的对照表——读到 §5.5 之类引用旧文档树的地方，按那张表换算。
