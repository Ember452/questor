# AGENTS.md — Questor 路标

先路由到正确的文件，再读拥有该决策的文档。行为守则**不在**这里：旧文件的 §0–§6
已原样迁至 [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)。
优先级：用户指令 → [ARCHITECTURE](./docs/ARCHITECTURE.md) → [docs/adr](./docs/adr)
→ [docs/architecture](./docs/architecture) → [docs/plan](./docs/plan) → 其他。守则自身的
§5.5 仍引用重置前的文档集（蓝图、路线图、坑位清单与 design 目录）；这些文件已在 W10
离开仓库——路径对照表见 [CONVENTIONS](./docs/CONVENTIONS.md) 顶部的勘误块，归档指引见
`docs-pre-reset-v1/README.md`。

对外文档（安装、命令、环境变量、原理）在 [docs/README.md](./docs/README.md) 的读者分流页，
不在这里重复。
永远不要凭记忆工作：这些链接才是事实，而且它们会移动。

## 顶层结构

```
src/questorharness   引擎：contracts → platform → config → providers / execution →
                     runtime → engine → capabilities → commands → surfaces → bootstrap，
                     另有 plugins（扩展层）与五个表现层叶子包
src/questor          产品组合根：gateway、groups、personal memory
apps/                规划中的非 Python 宿主：web（唯一 renderer）+ desktop（Electron 壳），见 ADR-0006
docs/architecture    STRUCTURE（意图）· GRAPH（生成的关系图）· TREE（生成的目录树）
                     · NAMESPACES（注册表）· MIGRATION · APPEARANCE
tests                unit / integration / e2e / ci（守卫契约）/ fixtures/baseline
```

包级依赖边、环、被 import 最多的文件与超预算清单只存在于
[GRAPH.md](./docs/architecture/GRAPH.md) 与 [TREE.md](./docs/architecture/TREE.md)。两者
均为生成物；手画它们就是红构建。

## 依赖铁律

`.importlinter` 拥有规则；CI 的 `guards` job 保证每条契约 KEPT：

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

加新的依赖边之前，先读 GRAPH.md 的「冻结的间接入口」一节：五条
`capabilities → execution` 边与 `providers.sandbox` 一对是已登记的例外，
多出一条即失败。

## 路由表

| 想改什么 | 去哪里 |
| --- | --- |
| 系统提示词与技能清单 | `src/questorharness/capabilities/context/prompts/context.py` |
| 压缩与微压缩 | `src/questorharness/capabilities/context/compact` |
| 工具注册表与能力索引 | `src/questorharness/capabilities/tools/registry.py` |
| 工具能力声明本体 | `src/questorharness/capabilities/tools/contract.py` |
| 权限判定与策略 | `src/questorharness/capabilities/policy` |
| 回合循环 | `src/questorharness/engine/query.py` |
| 工具执行与结果处理 | `src/questorharness/engine/tool_execution.py` |
| 工具携带式元数据 | `src/questorharness/engine/tool_metadata.py` |
| 斜杠命令注册 | `src/questorharness/commands/registry.py` |
| 事件与消息协议 | `src/questorharness/contracts/domain/events.py` |
| 配置模型与环境变量 | `src/questorharness/config/settings_models.py` |
| 会话存储与快照 | `src/questorharness/platform/session_storage.py` |
| 命令行入口 | `src/questorharness/bootstrap/cli/main.py` |
| 运行时装配根 | `src/questorharness/bootstrap/runtime.py` |
| serve 宿主与线协议（规划中） | `docs/adr/0006-serve-host-and-wire-protocol.md` |
| 前端基座与契约 codegen（规划中） | `docs/adr/0007-frontend-base-and-contract-codegen.md` |
| 形态与界面能力位（规划中） | `docs/adr/0008-profile-driven-modes.md` |
| 终端（全屏 TUI = 产品本体） | `src/questorharness/bootstrap/hosts/tui/`（Textual：对话区 / 带框输入 / 候选 / 状态栏 / 审批模态） |
| 终端（行式 REPL，`--plain` 与管道回退） | `src/questorharness/bootstrap/hosts/terminal_client.py` + `src/questorharness/bootstrap/hosts/terminal/` |
| 形态 bundle 与能力位 | `src/questor/profiles`（数据）+ `src/questorharness/profiles`（解析） |
| 渠道适配（飞书 / QQ） | `src/questorharness/surfaces/channels` |
| 产品网关与群策略 | `src/questor/gateway/runtime.py` |
| 名字是否重名 | `docs/architecture/NAMESPACES.md` |
| 门禁都跑什么 | `scripts/check.py` |
| 测试基建扩容触发器与「暂不引入」清单 | `docs/operations/ci.md` |

## 新功能落位

新增任何功能，先读目标包 AGENTS.md 的「职责 / 不负责」两行再动手：

- 归属明确 → 进该包，遵守其「允许依赖」与叶子语法（ADR-0003）。
- 两个包都像、或都不像 → 先查 [NAMESPACES.md](./docs/architecture/NAMESPACES.md) 里最近的注册名与上面的路由表再裁决；裁决不出来按下一条处理。
- 找不到位置、或职责与现有包都不重合 → **新开包**：目录 + 带 `__all__` 的 `__init__.py` + 包 AGENTS.md + CODEOWNERS 规则 + 路由表加行 + 结构基线 `--refresh-baseline --reason`；进分层阶梯的包还要在 `.importlinter` 一并声明（ADR-0002 修订版：不设数量封顶，无内容的目录才是违规）。

## 全局禁令与命令

- 行为守则、注释规范、Git 纪律、完成定义：只在 [docs/CONVENTIONS.md](./docs/CONVENTIONS.md) 维护。
- 结构红线（1500 行、30 文件扇出、禁用名、门面零逻辑、命名空间唯一、文档不撒谎）由
  `scripts/guards` 机械执行，不靠自觉；每条都能构造违规判红。
- 本地一条命令跑完全部阻断门禁：`uv run python scripts/check.py`（pre-commit 走 `--fast`，CI 走全量）。

## 行为守则速览

正文只在 [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)（§0–§6）；最常被违反的几条先钉在这里：

- **不偷工减料**：读全、做全，不为了显得有进度而少做（§0）。
- **先算长远收益**：动手前判断这件事长期是否有价值、收益是否配得上改动面；配不上的不做，不盲目动手（§1）。
- **想清楚再写**：假设摆明，多种解读呈现出来，不许默默选一种（§1）。
- **最简实现**：只写被要求的功能；单次使用的代码不做抽象（§2）。
- **外科手术式修改**：只动必须动的，不顺手"改进"无关代码；每一行改动都能追溯到请求（§3）。
- **目标驱动**：任务先转成可验证目标（红用例 → 变绿）再动手（§4）。
- **代码注释用中文**（§5.6）。
- **文档实时维护**：行为变更与文档更新同一刀；失活的文档比没有更糟（§5.5）。
- **commit 与 push 都需要用户当轮明确授权**；提交信息用英文 Conventional Commits（§6）。

## 第一个 PR

1. 用上面的路由表定位文件，改前先 `uv run python scripts/check.py --fast` 看清基线。
2. 只改请求触及的东西；行为变更必须先有一个红用例，模型可见面变更看
   `scripts/ci/prompt_surface.py --check` 与 `tests/fixtures/baseline/tool_metadata_golden.json`。
3. 提交前跑 `uv run python scripts/check.py` 与 `uv run pytest -q`；commit 与 push 都需要
   用户当轮明确授权，提交信息用英文 Conventional Commits，subject 小写开头。

---
**完整行为守则（§0–§6 原文）在 [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)。**
