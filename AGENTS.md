# AGENTS.md — Questor Signpost

Route to the right file, then read the doc that owns the decision. Behavioral rules are **not**
here: §0–§6 of the old file moved verbatim to [docs/CONVENTIONS.md](./docs/CONVENTIONS.md).
Priority: user instruction → [ARCHITECTURE](./docs/ARCHITECTURE.md) → [docs/adr](./docs/adr)
→ [docs/architecture](./docs/architecture) → [docs/plan](./docs/plan) → elsewhere. The rulebook's
own §5.5 still cites the pre-reset doc set (`docs/design/`, `docs/ROADMAP.md`, `docs/pitfalls.md`);
those files now live under `docs-pre-reset-v1/` — see the 勘误 block at the top of CONVENTIONS.md.
Never work from memory: these links are the truth, and they move.

## 顶层结构

```
src/questorharness   engine: contracts → platform → config → providers / execution →
                     runtime → engine → capabilities → commands → surfaces → bootstrap,
                     plus plugins (extension layer) and the appearance leaves
src/questor          product composition root: gateway, groups, personal memory
docs/architecture    STRUCTURE (intent) · GRAPH (generated graph) · TREE (generated tree)
                     · NAMESPACES (registry) · MIGRATION · APPEARANCE
tests                unit / integration / e2e / ci (guard contracts) / fixtures/baseline
```

Package edges, cycles, most-imported files and over-budget files exist only in
[GRAPH.md](./docs/architecture/GRAPH.md) and [TREE.md](./docs/architecture/TREE.md). Both are
generated; drawing them by hand is a red build.

## 依赖铁律

`.importlinter` owns the rules; CI's `guards` job keeps every contract KEPT:

- `layers`
- `plugins-stay-an-extension-layer`
- `engine-app-boundary`
- `capabilities-are-leaf`
- `lower-layers-do-not-import-capabilities`
- `product-uses-public-face`
- `config-is-leaf`
- `providers-are-adapters`
- `surfaces-are-thin`
- `command-families-are-leaf`

Before adding an edge, read GRAPH.md's 冻结的间接入口 section: the five
`capabilities → execution` edges and the `providers.sandbox` pair are registered
exceptions, and one more is a failure.

## 路由表

| 想改什么 | 去哪里 |
| --- | --- |
| 系统提示词与技能清单 | `src/questorharness/capabilities/context/prompts/context.py` |
| 压缩与微压缩 | `src/questorharness/capabilities/context/compact` |
| 工具注册表与能力索引 | `src/questorharness/capabilities/tools/registry.py` |
| 工具能力声明本体 | `src/questorharness/capabilities/tools/base.py` |
| 权限判定与策略 | `src/questorharness/capabilities/policy` |
| swarm 权限同步 | `src/questorharness/runtime/swarm/permission_sync.py` |
| 回合循环 | `src/questorharness/engine/query.py` |
| 工具执行与结果处理 | `src/questorharness/engine/tool_execution.py` |
| 工具携带式元数据 | `src/questorharness/engine/tool_metadata.py` |
| 斜杠命令注册 | `src/questorharness/commands/registry.py` |
| 事件与消息协议 | `src/questorharness/contracts/domain/events.py` |
| 配置模型与环境变量 | `src/questorharness/config/settings_models.py` |
| 会话存储与快照 | `src/questorharness/platform/session_storage.py` |
| 命令行入口 | `src/questorharness/cli.py` |
| 运行时装配根 | `src/questorharness/bootstrap/runtime.py` |
| 桌面 / 后端宿主 | `src/questorharness/bootstrap/hosts/backend_host.py` |
| 渠道适配（飞书 / QQ） | `src/questorharness/surfaces/channels` |
| 产品网关与群策略 | `src/questor/gateway/runtime.py` |
| 名字是否重名 | `docs/architecture/NAMESPACES.md` |
| 门禁都跑什么 | `scripts/check.py` |

## 全局禁令与命令

- 行为守则、注释规范、Git 纪律、完成定义：只在 [docs/CONVENTIONS.md](./docs/CONVENTIONS.md) 维护。
- 结构红线（1500 行、30 文件扇出、禁用名、门面零逻辑、命名空间唯一、文档不撒谎）由
  `scripts/guards` 机械执行，不靠自觉；每条都能构造违规判红。
- 本地一条命令跑完全部阻断门禁：`uv run python scripts/check.py`（pre-commit 走 `--fast`，CI 走全量）。

## 第一个 PR

1. 用上面的路由表定位文件，改前先 `uv run python scripts/check.py --fast` 看清基线。
2. 只改请求触及的东西；行为变更必须先有一个红用例，模型可见面变更看
   `scripts/ci/prompt_surface.py --check` 与 `tests/fixtures/baseline/tool_metadata_golden.json`。
3. 提交前跑 `uv run python scripts/check.py` 与 `uv run pytest -q`；提交信息用 Conventional
   Commits，subject 小写开头；未获授权不 push。

---
**完整行为守则（§0–§6 原文）在 [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)。**
