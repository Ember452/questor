# ADR 0002: Target Package Structure and Dependency Rank

- Status: Accepted (target; implementation in waves)
- Date: 2026-10-22
- Deciders: Questor maintainers

## Context

当前引擎在 `src/questorharness/` 下是一层 30 个平级子包：`api`、`auth`、`autopilot`、`bridge`、`channels`、`commands`、`config`、`coordinator`、`engine`、`hooks`、`keybindings`、`mcp`、`memory`、`output_styles`、`permissions`、`personalization`、`plugins`、`prompts`、`sandbox`、`services`、`skills`、`state`、`swarm`、`tasks`、`themes`、`tools`、`ui`、`utils`、`vim`、`voice`。类型词（`services`、`utils`、`config`、`state`、`ui`）与领域词（`memory`、`tools`、`channels`）混在同一层，没有统一的变化轴。

2026-10-22 实测：

- `src/` 下 241 个 `.py`，其中 44 个 `__init__.py`，197 个源文件；
- 197 个源文件中，102 个 ≤80 行（52%），13 个 >600 行，8 个 >900 行；
- `tools/` 是唯一一个 >20 文件的目录（44 个平铺）；
- 最大文件：`commands/registry.py` 2586 行、`cli.py` 2245 行、`autopilot/service.py` 2089 行、`services/compact/__init__.py` 1527 行；
- `services/` 里有 5 个子包没有独立模块文件，逻辑全在 `__init__.py`（`compact` 1527 行、`lsp` 190 行、`memory_extract` 223 行、`session_memory` 109 行；`oauth` 为空）。

> 行数均按非空行统计（`Get-Content | Measure-Object -Line` 口径）。

同时有三条未来约束：

1. 产品要走两种模式（个人 agent、编码 agent），两者在上下文、记忆、循环策略上不同；
2. 核心字段会持续变化（例如新增 `workspace_id` 等 `*_id`）；
3. Electron 桌面端会带来第二个宿主，但后端仍应是同一个 sidecar。

参考项目 Pi 与 DeerFlow 给出的不是可直接照抄的目录，而是两组可验证的做法：

- Pi：包 = 能力边界，依赖单向；内核一概念一文件；一工具一文件；conformance 套件；多界面共用同一套 agent + session；
- DeerFlow：`app` / `harness` / `community` 物理三层；持久化按聚合拆子目录（`model.py` + `sql.py`）；40 个域级 `AGENTS.md`；配置即数据；
- 两者的反面：Pi 的 `coding-agent/src/core` 98 个文件平铺、`interactive-mode.ts` 6459 行；DeerFlow 的 `agents/middlewares` 57 个文件平铺、`channels/manager.py` 3344 行。**目录好不等于文件级可读。**

本 ADR 决定包级结构；文件级布局由 [ADR-0003](0003-file-layout.md) 决定。

## Decision

1. **保留两个分发**：`questorharness`（引擎）与 `questor`（产品），沿用 ADR-0001。不为了名字好看做全仓改名；重组发生在包内部。
2. **引擎固定 8 个域**：`contracts`、`kernel`、`runtime`、`capabilities`、`providers`、`surfaces`、`profiles`、`bootstrap`。一级目录封顶 10 个。
   > **2026-10-24 修订**：上面这份 8 域清单与「封顶 10」是立项时的目标态，与现实已偏离——`kernel`/`profiles` 未建（见第 3、8 条），实际长出的是 12 个核心域（`bootstrap`/`capabilities`/`commands`/`config`/`contracts`/`engine`/`execution`/`platform`/`plugins`/`providers`/`runtime`/`surfaces`）加 5 个表现层叶子（`state`/`keybindings`/`themes`/`vim`/`output_styles`）。**修订决定：不设一级目录数量封顶**——数量不是风险，无内容的目录才是；起约束作用的是 STRUCTURE.md §0 第 7 条（目录从内容长出来、没有内容不建目录）、禁用名与空目录规则、以及分层契约对新包依赖边的判定。一级目录的**现状真源**是 [TREE.md](../architecture/TREE.md)，不由本文维护。
3. **`kernel` 这个名字为 durable 保留，但现在不建**：当前持久化是会话快照（`services/session_backend.py` + 产品包内的 session_storage），**没有事件流、没有 `reduce()` 咽喉、没有 upcast**。durable spine 属于**未立项**事项：要引入必须先单独 ADR + 预算 + 排期，不混在结构迁移里；在那之前 `kernel/` 目录不创建。
4. **`runtime` 是循环与控制**：run/turn、tool cycle、session ops、budget、extension points、tasks、delegation、autopilot。它只认 `contracts/ports` 与 `kernel` 的公开入口，不 import 能力实现。
5. **`capabilities` 是能力域**：context、memory、tools、policy、delivery、schedule、evolution。每个子域是一个叶子，拥有自己的 `model/ports/policy/store/README`。
6. **`providers` 是适配器**：llm、auth、store、sandbox、search、lsp、mcp。只实现 `contracts/ports`，不 import runtime/capabilities；由 `bootstrap` 注入。
7. **`surfaces` 是传输**：http、sse、ipc、gateway、channels。只认 `contracts` 和注入的 facade，不写业务、不写状态；不建 `surfaces/terminal`（ADR-0005）。
8. **`profiles` 是模式装配，纯数据**：personal / coding 是两份 YAML，只引用注册表 ID；每次 run 记录 `profile_fingerprint`。模式不是目录，不复制 memory/context/loop。profiles 只放 YAML 与文本；prompt 的加载代码归 `capabilities/context`，不下沉进 profiles。
9. **产品只 import 引擎公开面**：`questorharness.api` + `bootstrap`。`questor` 负责组合根与产品策略（gateway 群规则、通知、onboarding、workspace）。
   - 现状校正（2026-10-22）：公开门面 `questorharness/api.py` **尚不存在**；`questorharness/api/` 是 LLM 客户端包，Phase 1 已整包移入 `providers/llm/`。本文的 `questorharness.api` 是目标态门面，待 Phase 2/3 建立。
10. **Electron 是宿主，不是第二后端**：`apps/desktop`（main/preload）+ `apps/web`（共享 renderer）；IPC 只是 Transport 的第二个实现，和 HTTP/SSE 共用同一套 Command/Event envelope。
11. **字段三层（不预设事件溯源）**：domain（`contracts/domain`）/ storage（会话快照与 store 适配）/ wire（对外 schema）分离；现在只要求“旧快照能加载”与“wire 只增不删”；事件 `event_version` + upcaster 推到 durable 立项之后。新增字段必须 optional + 默认值 + 有生产者 + 有读取方。
12. **文件级规则走 ADR-0003**：叶子语法、3–16 文件/目录、80–800 行/文件、禁用类型词、`__init__` 只做门面；关键包一个 `AGENTS.md`。
13. **不建 `_reserved/`**：接缝放在拥有它的域里。已激活接缝必须满足“Port + 真实消费者 + fake + 会跑的 conformance”；未来环允许“声明式接缝”（Port + fake + conformance + manifest 的 `declared`），一旦有真实调用方就升级。
14. **迁移分三阶段**：Phase 1 move-only、Phase 2 code-shape、Phase 3 capabilities；先搬测试、每阶段行为边界明确；见 `docs/architecture/MIGRATION.md`。
15. **Phase 1 按耦合度排序，不按行数**：搬之前先数测试里的 `monkeypatch.setattr("模块路径.名字")` 目标数；低的先搬，高的（gateway 76、autopilot 41、ui 37）推到 Phase 2。每个包的 patch 目标在同 PR 里改完。
16. **禁止用 re-export shim 兼容测试 patch**：shim 只保 `import`，会静默改变 patch 命中目标，把红测试变成假绿。patch 目标数 > 0 的模块不许留 shim。
17. **不建空目录**：`contracts/`、`kernel/`、`profiles/` 在第一个真实文件落地前不创建；目录从内容长出来。
18. **`bootstrap` 只装配，不承载被 import 的配置类型**：配置类型放 `contracts/settings.py`（frozen dataclass，只依赖标准库），由 `bootstrap` 解析后注入。理由：`bootstrap` 是依赖秩最高层，而 `config` 当前被 78 处 import；把 `config/` 直接平移到 `bootstrap/` 会让下层反向依赖装配层。
19. **模式差异走 `LoopStrategy` Port，不进循环骨架**：`contracts/ports/loop.py` 定义策略，`runtime/turn/loop.py` 只跑“装配→调用→判定→结算”骨架，`runtime/turn/strategies/*` 提供 react / plan-execute-verify；profile 只选 ID。循环内不得出现 `if profile == ...`。
20. **UI 宿主以 ADR-0005 为准**：`apps/web`（React）是唯一 renderer，`apps/desktop` 只是宿主；不建 `surfaces/terminal/`，Python textual 与 Node Ink 不再演进。

## Alternatives considered

- **先照搬 durable 内核（事件流 + 回放 + upcast + 单写者租约）**。拒绝：那是一个独立的大立项，混进结构调优就会重演“目标宏大、一个人扛不动”的旧坑。当前先跑快照模型，真需要 rewind/审计/跳端续跑时再立项。
- **先挖好 8 个域的空目录再搬**。拒绝：空目录既不改行为也不产生价值，只制造“欠账感”和后续返工；先建壳再填内容等于把旧结构冻住。
- **保留现有 30 个平级子包**。拒绝：没有变化轴；类型词与领域词混层；新增能力无处安放，只能继续加平级目录。
- **照抄 Pi 的“少文件大文件”**。拒绝：Pi 的内核只有 6–22 个概念文件，但产品 `core` 是 98 个文件平铺 + 4051 行 `agent-session.ts`；你的目标是 1000+ 文件的多产品工作台，照抄会得到文件内迷宫。
- **照抄 DeerFlow 的 `app` / `harness` / `community` 三层**。部分采纳：引擎/产品分离、provider 子包、配置即数据采纳；但不采纳 `middlewares` 57 文件平铺和 `community` 单层平铺，改为 `capabilities/<domain>/` 与 `providers/<kind>/` 两级。
- **`modes/personal/` + `modes/coding/` 两棵平行树**。拒绝：memory/context/loop 会双份维护；模式差异应落成能力域的 strategy，由 profile 选。
- **uv workspace 拆 8 个 Python 分发**。暂缓：单人维护，版本与循环依赖成本大于收益；先用包内边界 + import-linter 拿到 95% 的收益。等 `kernel` 边界稳定后再评估拆出 `questor-contracts` 或 `questor-kernel`。
- **用 `runtime/` 命名 spine**。拒绝：runtime 是变化最快的循环层，spine 是变化最慢的机制层；同名会互相拖累。spine 叫 `kernel`。
- **建 `_reserved/` 放 subagents/dag/scheduler/codemode**。拒绝：这是平行的未来树，激活时要搬一次，等于保证第二次迁移；接缝应归属 `runtime/delegation`、`capabilities/schedule`、`capabilities/tools`。
- **把 `composition.py` 放在产品包里作为唯一装配根**。拒绝：引擎将无法独立装配与测试。引擎提供 `bootstrap.compose(overrides)`；产品调用它并注入产品 bindings。
- **把 `config/` 平移到 `bootstrap/config/`**。拒绝：`bootstrap` 是依赖秩最高层，而 `config` 被 78 处 import；直接平移会让下层反向依赖装配层。改为“类型进 contracts/settings、解析与注入留在 bootstrap”。
- **保留 Python textual TUI 作为第二 UI**。拒绝：见 ADR-0005；三套 UI 会让 `surfaces/terminal` 与 `apps/web` 争抢同一份状态投影，且测试与依赖成本翻倍。
- **把模式差异写进 `runtime/turn/loop.py`**。拒绝：一旦循环里出现 `if profile == ...`，第三个模式就会变成改内核；模式差异必须落成 `LoopStrategy` 与 capability strategy。

## Consequences

变得更容易：

- 新增能力有唯一落点：`capabilities/<domain>/` + registry 一行 + profile 引用；共享文件改动 ≤1。
- 新增模式不改内核：personal/coding 只换 profile 与 strategy，不复制 memory/context/loop。
- 字段变更局部化：domain/storage/wire 分离后，新增 `*_id` 的爆炸半径 ≤3 文件 + 1 fixture。
- Electron 不产生第二后端：IPC/HTTP/SSE 共用同一 envelope；renderer 可在浏览器独立跑。
- 文件导航可预测：每个叶子形状一致，目录有封顶，入口只有 `__init__.py`。

变得更难：

- 需要更多 Protocol：runtime 不 import 能力实现，依赖注入会增加一层间接。
- W1–W5 有持续的重组成本；每波必须保持行为不变，测试先搬。
- 短期内两套路径并存（旧 `questorharness/*` 与新域），必须靠 import-linter 和目录守卫防止回流。
- 团队要接受“更多、更小、更有名字的文件”；这与“少文件”直觉相反，但这是避免 god file 的唯一路径。

必须保留的不变式：

- `questorharness` 永不 import `questor`；
- 引擎新代码不新增对 `questorharness.ui` / `utils` / `services` 的依赖；
- `capabilities` 永不 import `providers`；
- `surfaces` 永不 import `runtime` / `capabilities`（facade 注入除外）；
- `profiles` 只依赖 `contracts`；
- 下层模块不得 import `bootstrap`（配置类型在 `contracts/settings.py`，由 bootstrap 注入）；
- 循环骨架不得出现 profile 分支（差异走 `LoopStrategy`）；
- 没有内容的目录不建；没有消费者的 Port 不建；
- 任何文件 >1200 行、任何逻辑目录 >30 个源文件，CI 判红。

## Verification

- `.importlinter`：`layers` + 多条 `forbidden`（见 `docs/architecture/STRUCTURE.md` §2.2）。
- `docs/architecture/MIGRATION.md`：Phase 边界、**按耦合度排序的搬运表**；`docs/architecture/MEMORY.md` + ADR-0004：memory provider 契约。
- 现在就上的守卫（3）：import-linter 扩展、check_layout（待建，含 `--self-test` 与 fail-on-empty）、gen_tree（待建）。
- 基线五项（Phase 1/2 逐 PR 对比）：测试通过集、CLI `--help` 输出、一次固定会话 stdout、冷导入、旧 session 快照能加载。
- 结构实验：
  - **新能力实验**：新增一个工具/记忆算法，共享文件改动 ≤1；
  - **新模式实验**：新增第三个 profile，只加 YAML + strategy，不改引擎共享文件；
  - **字段实验**：新增一个 `*_id`，爆炸半径 ≤3 文件 + 1 条旧快照 fixture。
- 其余守卫（字段 canonical、事件版本、wire codegen、conformance）等对应概念存在后再加。
