# ADR 0003: File-Level Layout and Readability Budget

- Status: Accepted (target; implementation in waves)
- Date: 2026-10-22
- Deciders: Questor maintainers

## Context

包级结构（ADR-0002）只解决“东西放哪一层”，不解决“一个目录里 40 个文件怎么读”。当前仓库的文件级形态是双峰的：

- `src/` 下 241 个 `.py`，其中 44 个 `__init__.py`，197 个源文件；
- 197 个源文件中，67 个 ≤40 行、35 个 41–80 行（合计 52%），52 个 81–200 行，21 个 201–400 行，9 个 401–600 行，5 个 601–900 行，8 个 >900 行；
- `tools/` 是唯一一个 >30 文件的目录（44 个平铺，平均 69 行）；
- 最大文件：`commands/registry.py` 2586 行、`cli.py` 2245 行、`autopilot/service.py` 2089 行、`services/compact/__init__.py` 1527 行、`gateway/runtime.py` 1144 行、`channels/impl/feishu.py` 1115 行、`config/settings.py` 940 行、`engine/query.py` 932 行。

> 行数均按非空行统计。

参考项目也没治好这个病，只是用别的东西扛住了：

- Pi：`coding-agent/src/core` 98 个文件平铺，`interactive-mode.ts` 6459 行、`agent-session.ts` 4051 行；它靠极具体的文件名、文档站和测试扛住。内核（`agent/src` 6 个文件、`durable/src/harness` 22 个概念文件）是好的文件级范本。
- DeerFlow：`persistence/` 是全场最佳——22 个聚合子目录，每个 3–5 个文件（`model.py` + `sql.py` + `__init__.py`）；但 `agents/middlewares` 57 个文件平铺、`channels/manager.py` 3344 行、`runtime/runs/worker.py` 3155 行。它靠 40 个域级 `AGENTS.md` 扛住。

结论：**“很多 .py 文件散落”不是文件数量问题，是缺四样东西**：

1. 目录扇出封顶；
2. 可预测的文件名语法；
3. 唯一的公开入口（`__init__.py` 门面）；
4. 每个域一张本地地图。

本 ADR 只定文件级布局；包级结构见 [ADR-0002](0002-target-structure.md)。

## Decision

### 1. 叶子语法

每个能力子域使用同一套文件角色。不是每个文件都必须存在，但出现时必须遵守角色：

```text
<subdomain>/
├─ AGENTS.md      # 10–15 行地图：职责/入口/数据/依赖/不变式/关键文件
├─ __init__.py    # 只导出 ≤10 个公开名，零逻辑
├─ model.py       # 本域数据类/枚举
├─ ports.py       # 本域需要的 Protocol
├─ policy.py      # 阈值、规则、决策
├─ store.py       # 本域持久化适配
├─ registry.py    # ID → 实现的映射
├─ errors.py      # 本域异常
└─ <use-case>.py  # recall.py / write.py / select.py / fork.py ...
```

命名语法：

- 概念用名词：`inbox.py`、`snapshot.py`、`compaction.py`；
- 用例用动宾：`fork_session.py`、`rewind_session.py`、`select.py`；
- 适配器用供应商名：`sqlite.py`、`litellm.py`、`feishu.py`；
- 角色后缀：`_port.py`、`_policy.py`、`_store.py`、`_registry.py`、`_schema.py`。

### 2. 阈值

| 指标 | 健康值 | 警戒 | 失败 | 例外 |
|---|---|---|---|---|
| 目录源文件数（不含 `__init__.py`） | 3–16 | 17–30 | >30 | migrations、schemas、providers 下的 vendor 目录这类 catalog；需在 layout 豁免清单列明 |
| 文件行数 | 80–800 | 801–1200 | >1200 | 生成代码、迁移、conformance fixture |
| 目录深度 | 2–5 | 6 | >6 | 适配器/后端实现可到 7，需豁免 |
| `__init__.py` | ≤40 行、≤10 导出（`contracts/` ≤15）、零逻辑 | 41–80 行 | >80 行或含 `def/class` | 无 |
| 子包公共面 | ≤10 个名字 | 11–15 | >15 | `contracts/` 词表包 |

阈值不是审美：16 是“人还能一眼扫完”的上限；30 是硬上限；40 是 G8 给机器看的，不是给人看的。catalog 目录（migrations / schemas / vendors）必须显式列在豁免清单（tests/layout_exemptions.txt）里，不能默默超限。

2 个源文件的目录在“model + store/sql 对”或公共边界时视为健康；只有 1 个源文件且不是公共边界时才塌回文件。

### 3. 禁用文件名

任何层级都不允许：

```text
utils.py  helpers.py  common.py  base.py  manager.py  service.py
handler.py  processor.py  misc.py  core.py  types.py  constants.py
```

理由：这些名字没有唯一职责，必然变成垃圾桶或 god file。`manager.py` 在 DeerFlow 里对应 1053/2452/3344 行；`services/` 在 questor 里已经变成 9 件事 + 5 个只有 `__init__.py` 的子包。

例外：`runtime/tasks/task_manager.py` 这种“限定词 + 生命周期所有者”的名字可以保留，但必须是该目录的唯一入口，且 ≤600 行；裸 `manager.py` 仍然禁止。

**baseline 规则**：旧账不一刀切回改。现有违规（`bridge/manager.py`、`channels/impl/manager.py`、`memory/manager.py`、`tasks/manager.py`、`autopilot/service.py`、`gateway/service.py`、`services/autodream/service.py`、整个 `utils/` 包）写进 layout baseline，**只挡新增**；Phase 2 逐销账。

### 4. 折叠 / 展开

文件变目录，当且仅当：

- >600 行；
- 有 >3 个独立概念（需要“和”来描述）；
- 有 >2 个变化原因；
- 测试需要 >1 组不相关 fixture；
- 文件头 “Owns” 列表 >3 项。

目录塌回文件，当且仅当：

- 只有 1 个源文件，且不是公共边界；
- 2 个源文件只有在“model + store/sql 对”或公共边界时才保留；
- 所有文件 <80 行，且只有一个消费者；
- 子目录只是按类型拆的（`utils/`、`helpers/`）。

子域升一级域，当且仅当：

- 有自己的 Port；
- 有独立变化节奏；
- 有独立数据所有权。

### 5. 模块头

每个源文件前 3 行必须回答三个问题：

```python
"""记忆召回：三通道 + 终选。

Owns: 查询构建、通道合并、top-k 选择。
Does not own: 存储（ports）、写回（write/）、巩固（consolidate/）。
"""
```

这不是装饰：它让读者在 10 秒内判断“这个文件该不该改”。

### 6. 门面规则

- `__init__.py` 只做 re-export + `__all__` + 一句 docstring；
- 禁止在 `__init__.py` 里写 `def` / `class` / 业务逻辑；
- 禁止跨子域 import 内部模块：`from ..memory._internal import` 一律禁止，只能走 `memory/__init__.py` 的公开名；
- 公开名控制在 7 个以内；超过就是命名空间，不是模块。

当前的 `services/compact/__init__.py`（1527 行）是反面样本：门面变成了实现，import 即加载全部逻辑。

### 7. 地图与测试

- 每个关键包一个 `AGENTS.md`（10–15 行）：职责、公开入口、拥有的数据、允许依赖、不变式、禁止、测试命令、关键文件。
- 必需（目录存在时）：8 个引擎域 + `src/questor`；`apps/desktop` / `apps/web` 在 Phase 3 创建后必需。热点子域（memory/tools/turn/gateway）可选。
- 一个包只放一份（`AGENTS.md` 或 `README.md`），不要两份同义文档。
- 目录树文档（docs/architecture/tree.md）由 gen_tree.py 生成，CI `--check` 防漂移；不手写目录树。
- 测试镜像源码：`capabilities/memory/recall/select.py` 对应 tests/unit 下的同路径镜像文件 tests/unit/capabilities/memory/recall/test_select.py（两个目录都尚未创建，此处路径只表达约定，不是当前仓引用）；没有同名测试的文件必须在豁免清单里说明理由（纯数据、纯 re-export、生成代码）。

### 8. 守卫规格

**原则：守卫跟着概念走。概念不存在，守卫不建。** 本 ADR 只定义 check_layout 一个守卫；字段 canonical、事件版本、wire codegen 等守卫等对应概念落地后再写规格。

check_layout.py（复用 scripts/guards 下的 `_guard_kit.py`，blocking ≤90s）：

```text
1. 遍历 src/ 下所有逻辑目录（排除 migrations/schemas/generated）：
   - 源文件数 >30 → fail；17–30 → warn
2. 遍历所有 .py：
   - 行数 >1200 → fail；801–1200 → warn
   - 文件名在禁用清单 → fail
   - __init__.py 行数 >40 或含 def/class → fail
3. 每个存在的关键包：
   - 缺 AGENTS.md → fail
   - AGENTS.md 的“关键文件”少于 2 个或路径不存在 → fail
   - 同一包同时有 README.md 和 AGENTS.md → fail
   - __init__.py 无 __all__ 或导出 >10 → fail
4. 每个源文件：
   - 缺同名测试且不在 exemptions → fail
5. 全局：禁用名与尺寸违规先比对 baseline，只报新增
6. --self-test：构造临时违规目录，逐条断言能判红
7. fail-on-empty：扫描不到文件 → exit 2
```

gen_tree.py（待建）：

```text
输出 docs/architecture/tree.md：每个目录的文件数、最大文件行数、总行数。
--check：与磁盘不一致 → exit 1。
```

## Alternatives considered

- **少文件、大文件**（Pi 的产品 core 风格）。拒绝：4051/6459 行的文件无法安全修改；测试定位和 review 成本随行数超线性增长。
- **一类一文件**（Java 风格）。拒绝：会产生大量 <40 行的微文件，目录噪声大，跳转成本高；本仓库已有 67 个 ≤40 行的非 `__init__` 文件。
- **沿用 G8 的 40 文件上限**。拒绝：40 是“机器还能扫”的上限，不是“人还能读”的上限；实测 44 个平铺的 `tools/` 已经不可读。改为 16 警戒、30 失败。
- **测试与源码同目录（colocate）**。拒绝：Python 包内混入 `test_*.py` 会污染发布包与 import 面；保持 `tests/` 镜像更清晰。
- **每个文件一个 README**。拒绝：文档噪声；包级 AGENTS.md + 模块头足够。
- **所有目录都强制 `model/ports/policy/store` 四件套**。拒绝：只为“整齐”制造空文件；角色文件按需出现，但出现即遵守角色。

## Consequences

变得更容易：

- 读者先看目录名，再看文件名，就能猜出 80% 的落点；不需要 grep 全仓。
- 新增能力有固定形状：`model/ports/use-case/README`，review 时一眼能看出缺什么。
- `__init__.py` 是稳定门面，重构内部文件不破坏外部 import。
- 守卫可机器执行，不依赖“大家自觉”。

变得更难：

- 文件数会增加；这是有意的。1000 文件 × 300 行比 300 文件 × 900 行更可维护。
- 拆文件会产生短期 churn；必须 move-only、测试先搬、每刀行为不变。
- 需要维护 exemptions 清单；但它是显式的，比“没人知道该放哪”好。
- 16/30 的阈值对 catalog 目录不适用，需要在守卫里维护例外名单。

必须保留的不变式：

- 禁止逻辑进 `__init__.py`；
- 禁止 `manager.py` / `service.py` / `utils.py`；
- 禁止目录 >30 个源文件（catalog 例外需在 exemptions 里列明）；
- 禁止文件 >1200 行；
- 每个关键包必须有 AGENTS.md；
- 每个源文件必须有同名测试或豁免理由。

## Verification

`check_layout.py` 的验收用例：

| 构造 | 期望 |
|---|---|
| 一个目录 31 个源文件 | fail，报目录名与数量 |
| 一个目录 20 个源文件 | warn，不阻塞 |
| 一个 1201 行文件 | fail |
| 一个 900 行文件 | warn |
| `manager.py` | fail |
| `__init__.py` 含 `def` | fail |
| 关键包缺 AGENTS.md | fail |
| `__init__.py` 导出 11 个名字 | fail |
| 源文件无同名测试且不在 exemptions | fail |
| 扫描结果为空 | exit 2 |
| `--self-test` | 上述每条都能判红 |

gen_tree.py --check：

- 磁盘与生成的目录树文档不一致 → exit 1；
- 生成文件只读，不允许手改。

导航验收（人工，每季度一次）：

- 给出 5 个行为描述（记忆召回终选、工具审批、压缩阈值、会话 fork、事件 upcast），新人 3 次点击内找到文件；
- 给出 3 个新增任务（加一个工具、加一个记忆策略、加一个 profile），每个任务共享文件改动 ≤1。
