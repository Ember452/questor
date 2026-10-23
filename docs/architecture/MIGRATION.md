# Questor 结构迁移计划（Move-first）

- 状态：Active plan
- 日期：2026-10-22
- 相关：[STRUCTURE](STRUCTURE.md)、[ADR-0002](../adr/0002-target-structure.md)、[ADR-0003](../adr/0003-file-layout.md)、[ADR-0004](../adr/0004-memory-provider-contract.md)

## 0. 原则

1. **先搬，再改，再加。** Phase 1 只做路径移动与 import 更新；Phase 2 才拆文件、抽端口；Phase 3 才加新能力。
2. **Behavior-preserving。** Phase 1/2 前后，测试断言不变、CLI 输出不变、旧快照加载不变。
3. **一个包一个 PR。** 禁止“搬 10 个包 + 顺手重构”混在一个 PR。
4. **先搬测试。** 测试路径跟着源码走；先让测试在新路径跑通，再删旧路径。
5. **搬迁顺序按耦合度排，不按行数排。** 先数测试里的字符串 patch 目标（`monkeypatch.setattr("模块路径.名字")`），低的先动。
6. **禁止用 re-export shim 兼容测试 patch。** shim 只保 `import`；patch 旧路径会静默失去作用对象，把红测试变成假绿。patch 目标数 > 0 的模块不许留 shim。
7. **不建空目录。** 目录只在第一个真实文件落地时创建；未立项的层（`kernel`、`contracts`、`profiles`）现在不建。
8. **纯移动要能机器证明。** 移动 PR 的 diff 必须只含 import 行与改名；出现其他行的改动即视为越界，拆成两个 PR。

---

## 1. 三阶段总览

| 阶段 | 内容 | 是否改行为 | 出口 |
|---|---|---|---|
| **Phase 0** | 文档 + 3 个可落地守卫 + AGENTS 地图 | 否 | 守卫能跑；文档合并 |
| **Phase 1** | Move-only：**只含 W1/W2/W2b**；W1b/W3/W3b 移入 Phase 2 | 否 | 基线五项不变 |
| **Phase 2** | Code-shape + 语义归位：拆 god file、config 注入、state 拆分、plugins/skills 拆开、UI 移除 | 否 | 基线不变 + 尺寸阈值达标 |
| **Phase 3** | Capabilities：profiles、memory provider、Electron、第二模式 | 是 | 新能力半径 ≤1；新模式不改引擎核心 |

Phase 1 有**时间盒**：≤10 个 PR 或 ≤2 周。超时不加班，先砍范围（见 §3.7）。

---

## 2. Phase 0：文档与守卫

- 本文 + `STRUCTURE.md` + ADR-0002/0003/0004。
- 现在就上的守卫只有 3 个：
  1. 扩 `.importlinter`：保留“引擎不 import 产品”，加层级与“新代码不得依赖 `questorharness.ui` / `utils` / `services`”；
  2. check_layout（待建，规格见 ADR-0003 §8，含 `--self-test` 与 fail-on-empty、baseline 只挡新增）；
  3. gen_tree（待建，生成目录树文档，`--check` 防漂移）。
- 已有的 `check_doc_cross_refs.py`、`check_secret_projection.py`、`check_thread_leak.py` 继续保留。
- **不建**的守卫：字段 canonical、事件版本、wire codegen、conformance 目录 —— 前置概念还不存在。
- 在**已存在的域**建 `AGENTS.md`（`src/questor` + 每个已落地的引擎域；`contracts` / `kernel` / `profiles` 随对应包落地时补，不建空目录）；`apps/desktop` / `apps/web` 在 Phase 3 创建后补。
- 根 `AGENTS.md` 降级为指针：只指向 `docs/architecture/STRUCTURE.md` 与包级 `AGENTS.md`，不再新增规则。

---

## 3. Phase 1：Move-only

### 3.1 先冻结基线（每个 PR 都要重跑）

基线必须写成“命令 + 期望输出”，不能写“测试全绿”。已固化为脚本：

```bash
uv run python scripts/baseline_check.py --record          # 重新冻结（新增测试 / 契约时）
uv run python scripts/baseline_check.py --check           # 全量：pytest + node-id + lint + 冷导入 + help/dry-run/snapshot/doctor
uv run python scripts/baseline_check.py --check --fast    # 跳过 pytest / node-id（约 18s），pre-push 用
```

当前冻结值（2026-10-23）：`1144 passed, 29 skipped, 10 deselected`；`lint 6 kept, 0 broken`；`node-id 1173 = main 1166 + 7 allowed`；snapshot 4 条。fixture 在 `tests/fixtures/baseline/`。

pre-push 钩子需要 `uv run pre-commit install --hook-type pre-push` 才会生效。

第 1 项必须用 `uv run`：直接跑 `.venv\Scripts\python.exe -m pytest` 会因为 PATH 缺少 `.venv/Scripts` 导致 `test_import_boundaries` 失败。

### 3.2 建目录规则

- 只建“这个 PR 就有文件进去”的目录。
- 目标树里的 `contracts/`、`kernel/`、`profiles/` **不在 Phase 1 创建**。
- 新目录的 `__init__.py` 是门面（≤40 行、≤10 导出、零逻辑），配 `AGENTS.md`。

### 3.3 耦合度排序（搬之前先看清楚）

patch 目标数 = 该模块在测试里被 `monkeypatch.setattr("...")` 或 `mock.patch("...")` 引用的次数。

2026-10-22 实测：`tests/` 下这两类调用共 **477 处，分布 52 个测试文件**（本文早先的 310 是更窄口径）。排序结论不变，但每波的实际改写量按 477 计；**单 PR 预算 ≤50 处改写 + ≤1 个包**，超了就拆。

| 波次 | 内容 | patch 目标 | 说明 |
|---|---|---|---|
| **W1** | `tools/` 44 个平铺 → `capabilities/tools/` 下 fs / shell / web / task / agent / mcp / media / cron 八个子域 | 9 | 唯一 >30 文件的目录；工具彼此独立，失败响亮 |
| **W2** | `memory/`(13) → `capabilities/memory/`；`permissions/` → `capabilities/policy/`；`mcp/` → `providers/mcp/`（transport）+ `capabilities/tools/mcp/`（4 个工具适配器） | 0 | 领域清晰；三包均无字符串 patch 目标（2026-10-22 实测）；`prompts/` 因文本与 loader 要拆，移出 Phase 1 |
| **W2b** | `api/` → `providers/llm/`；`auth/` → `providers/auth/`；`sandbox/` → `providers/sandbox/`；`channels/` → `surfaces/channels/` | 49 | api 20、auth 19、sandbox 10、channels 0（2026-10-22 实测）；`api` 路径引用多但 patch 少 |
| **W3** | `hooks/` → `runtime/extension/`；`commands/` → `runtime/commands/`；`tasks/` → `runtime/tasks/`；`coordinator/` + `swarm/` → `runtime/delegation/` + `capabilities/policy/`；`state/` → `surfaces/terminal/state/` | ≈30 | 核心编排相关；路径引用要改，但 patch 目标不高 |
| **W3b** | `services/` 解散（compact / lsp / memory_extract / session_memory / cron / token_estimation / tool_outputs / session_*）；`utils/` 归位；`config/` → `bootstrap/config/` | ≈47 | `services.compact` 11、`utils` 18、`config` 少量；空壳 `oauth` 直接删 |
| **W4（推到 Phase 2）** | `engine/` → `runtime/turn/`；`ui/` → `surfaces/terminal/`；`autopilot/` → `runtime/autopilot/`；`bridge/` → `surfaces/bridge/` | ≈158 | engine 64、ui 62、autopilot 41、bridge 少量；这几处一动必然大片红，单独排期 |
| **W5（Phase 1 完全不动）** | 产品包 `questor/gateway/`（拆到 surfaces/ 与产品策略） | 76 + 102 | 单点最贵；且属于产品包，不影响引擎结构收敛 |

**Phase 1 范围 = W1 + W2 + W2b。** `prompts/` 与 UI 目录（`themes/`、`keybindings/`、`vim/`、`output_styles/`）均属 Phase 2：前者是 prompt 文本与 loader 代码要拆的语义改动，后者按 ADR-0005 冻结后移除。

一句话：**W1 用 9 处 patch 成本解决你最痛的 44 平铺；W5 用 178 处成本解决一个可有可无的归位——先做前者。** W1 + W2 + W2b 实测合计 **58 处** patch 改写（旧估算 ≈99 偏高）。

### 3.4 每个包的固定动作

1. `git mv` 保历史；
2. 更新生产代码与测试的 import；
3. **同 PR 改写该包所有字符串 patch 目标**（数量在 PR 描述里写明：“patch 目标改写 N 处”）；
4. 旧包位置只保留一个 `__init__.py` re-export（**仅当 patch 目标数 = 0**），保留一个版本窗口；
5. 跑该包子集测试 + 全量基线五项；
6. `uv sync` 后跑一次真实入口/entry point 加载（entry point 断在运行时，不在 import 时）；
7. move-only 证明：`git show --stat` + 内容 diff 只含 import 行/改名行。

### 3.5 移动映射表

| 现状 | Phase 1 目标 | Phase 2 再拆 |
|---|---|---|
| `api/*.py` | `providers/llm/` | 按 vendor 拆 |
| `auth/*.py` | `providers/auth/` | 按 OAuth / 凭据拆 |
| `sandbox/*.py` | `providers/sandbox/` | 按 backend 拆 |
| `tools/`（44 平铺） | `capabilities/tools/{fs,shell,web,task,agent,mcp,media,cron}/` | 一工具一文件，不拆 |
| `memory/`（13 平铺） | `capabilities/memory/` | 按 recall / write / consolidate / backends 拆 |
| `permissions/` | `capabilities/policy/` | 按 permission / sandbox / approval 拆 |
| `channels/` | `surfaces/channels/` | 按 channel 拆；`feishu.py` 1115 行拆子目录 |
| `mcp/` | `providers/mcp/`（client / config / types）+ `capabilities/tools/mcp/`（4 个工具适配器） | 策略与 transport 分离 |
| `prompts/` | `capabilities/context/prompts/`（已完成）；`coordinator_mode` 的纯模式/提示词部分下沉 `capabilities/context/coordinator.py` | prompt 文本仍内嵌，后续可按 profile 外置 |
| `skills/`、`plugins/` | `skills/` → `capabilities/skills/`（已完成）；`AgentDefinition` → `contracts/agent.py`（已完成） | `plugins/` 仍依赖 coordinator 的私有解析函数（`_parse_agent_frontmatter` 等），暂留顶层作为扩展层 |
| `state/`（UI store） | **Phase 1 不动**；Phase 2 再拆 | 事实状态层不建（durable 未立项） |
| `engine/` | **保留在顶层**（编排层） | 循环组合 capabilities/providers/runtime；内核立项后再拆 `runtime/run` + `runtime/turn` |
| `commands/` | **保留在顶层**（应用层分派器） | `registry.py` 2586 行按命令族拆（未做） |
| `coordinator/`、`swarm/` | `runtime/coordinator/` + `runtime/swarm/`（已完成） | 按 team / permission / backend 拆 |
| `tasks/` | `runtime/tasks/`（已完成） | 拆 task_manager / local_agent / local_shell |
| `autopilot/` | `runtime/autopilot/`（已完成，文件未拆） | 拆 `{policy,loop,triggers,state}`（service.py 2089） |
| `hooks/` | `runtime/hooks/`（已完成） | 按 hook 类型拆 |
| `ui/` | 已完成：`bootstrap/runtime.py` + `surfaces/ipc/` | 不删除（ADR-0005 已更新）；`keybindings/`、`themes/`、`vim/`、`output_styles/` 保留 |
| `keybindings/`、`themes/`、`vim/`、`output_styles/` | **Phase 1 冻结**；Phase 2 随 UI 一起移除（ADR-0005） | 不迁 `surfaces/terminal/` |
| `voice/` | `providers/voice/`（Phase 2） | 有策略时升 capabilities |
| `utils/` | Phase 2 才归位；落 `providers/`（fs / shell / network_guard） | 解散，不留 utils |
| `config/` | 已收敛为叶子：模型与加载同包，只依赖 `contracts` | `Settings.resolve_auth()` 的 provider 惰性边待销账 |
| `bridge/` | `runtime/bridge/`（已完成） | 有策略时再拆 |
| `questor/gateway/` | **Phase 1 不动**（W5） | 协议路由进 `surfaces/gateway/`，产品策略留在产品包 |
| `frontend/terminal/` | **Phase 1 冻结**；Phase 2 移除（ADR-0005） | 不迁 `apps/terminal/`；wheel force-include 同步删除 |

> `mcp` 不能整体挂在 eager 的 `capabilities/tools/__init__.py` 之下：`config.settings` 需要 `McpServerConfig`，导入 `capabilities.tools.mcp.types` 会执行整个工具门面，形成 `config → tools → agent_tool → swarm → tasks → config` 循环。Phase 1 实测后改为 transport 落 `providers/mcp/`，工具适配器留 `capabilities/tools/mcp/`；Phase 2 再做瘦身与策略拆分。

`services/` 的 5 个子包都没有独立模块文件，逻辑全在 `__init__.py`：`compact`、`lsp`、`memory_extract`、`session_memory` 整体搬到各自能力域（Phase 2 再拆文件），`oauth` 为空可直接删。

### 3.6 Phase 1 不做的事

- 不拆任何 >800 行的文件（`commands/registry.py`、`cli.py`、`autopilot/service.py`、`services/compact/__init__.py` 全部保持整文件搬迁）；
- 不改函数签名、不改协议、不改事件/快照类型；
- 不引入新依赖；
- 不建 `contracts/`、`kernel/`、`profiles/`；
- 不动 `frontend/terminal/`、不建 `apps/desktop` / `apps/web`；
- 不写 memory provider；ADR-0004 只记录契约，代码到 Phase 3。
- **不做任何语义归位**（这些都不是 move-only，归 Phase 2）：config 注入、`state/` 拆分、`plugins/skills` 拆代码与数据、`prompts/` 重定位、`ui/` 移除、`utils/` 解散。

Phase 1 允许的临时例外（写进 layout 豁免清单，Phase 2 销账）：

```text
capabilities/context/compact 的 __init__.py（约 1.5k 行，Phase 2 拆）
capabilities/tools/__init__.py（108 行，含 `def create_default_tool_registry` 与全量工具 import；Phase 2 拆出门面）
runtime/commands/registry.py（约 2.6k 行，Phase 2 拆）
runtime/autopilot/service.py（约 2.1k 行，Phase 2 拆）
surfaces/gateway/runtime.py（约 1.1k 行，Phase 2 拆）
surfaces/channels/feishu.py（约 1.1k 行，Phase 2 拆）
manager.py / service.py / utils 的存量命名（baseline 只挡新增）
```

### 3.7 Phase 1 出口与时间盒

- 基线五项逐字不变；
- 所有测试在新路径通过；旧路径 shim 只存在于 patch 目标为 0 的模块；
- `lint-imports` 绿；
- `check_layout.py` 只报豁免清单里的已知项，**不新增违规**；
- 每个已建目录有 `AGENTS.md`；
- **时间盒**：Phase 1 收在一个分支上，一包一 commit；单 commit 预算 = 1 个包 + 该包全部 patch 目标（本阶段最大 20，`api/`）。超盒时先砍 W2b 的 `channels/`，再砍 `auth/`；W1b/W3/W3b/W4/W5 本来就不在本阶段。

> Phase 1 保持 `tests/` 文件路径不变：`tests/conftest.py` 的 Windows skip 表按 node-id 精确匹配（含 `tests/unit/test_tools/test_core_tools.py`），搬测试目录会改变 skipped 计数。只改 import 与 patch 字符串。

---

## 4. Phase 2：Code-shape

### 4.1 拆 god file（按“patch 目标少 → 多”排）

| 现状 | 行数 | patch 目标 | 拆成 |
|---|---:|---:|---|
| `runtime/commands/registry.py` | 2586 | ≈0 | `commands/{session,run,turn,memory,tool,profile}.py` + `registry.py` |
| `questor/cli.py` | 2245 | 3 | `cli/{main,repl,render,input,commands}.py` |
| `capabilities/context/compact/__init__.py` | 1527 | 11 | `compact/{policy,summarize,placeholders}.py` |
| `providers/{auth,sandbox,llm}` 内部 | 544 / 497 / 1855 | 15–19 | 按 vendor / backend 拆 |
| `capabilities/memory/*` | 1270 总量 | 31 | `recall/`、`write/`、`consolidate/`、`backends/` |
| `runtime/turn/query.py`（W4 才搬进来） | 932 | 64 | `turn/{loop,tool_cycle,stop}.py` + `context/assemble.py` |
| `runtime/autopilot/service.py` | 2089 | 41 | `autopilot/{policy,loop,triggers,state}.py` |
| `surfaces/terminal/*`（原 `ui/`） | 723 / 879 | 37 | 表现层留 surface，编排进 `runtime/` |
| `surfaces/gateway/runtime.py` | 1144 | 76 | `gateway/{session,events,commands}.py` |

### 4.2 把循环从 UI 抽出

- `ui/runtime.py`、`ui/backend_host.py` 的编排职责 → `runtime/run/controller.py`、`runtime/turn/loop.py`、`runtime/run/recovery.py`；
- UI 只保留订阅与渲染；
- 验收：CLI 基线输出逐字不变、旧快照仍可加载、恢复路径（resume）行为不变。

### 4.3 建 Port（只建有真实调用方的）

- `ModelPort`（providers/llm）；
- `ToolInvokerPort`（runtime → capabilities/tools）；
- `ContextAssemblerPort`、`TurnSettlerPort`（runtime 只认这两个，不认 memory）；
- `SessionStorePort`（快照读写，当前形态）；
- **不建** `EventStorePort`：durable 未立项；将来立项时单独 ADR。
- `MemoryPort` 与 conformance 属于 Phase 3。

### 4.4 尺寸与命名销账

- 无文件 >1200 行；801–1200 行的文件必须在豁免清单里有理由；
- 无逻辑目录 >30 个源文件；
- `manager.py` / `service.py` / `utils/` 存量归零或降级为限定名；
- `services/`、`utils/`、`config/`、`state/` 四个一级类型桶从包结构里消失。

---

## 5. Phase 3：Capabilities

按顺序，不并行：

1. **Profiles**：personal / coding 两份 YAML；当前行为固化为 `default` profile；`profile_fingerprint` 记录解析后的实现 ID + 参数 + prompt hash + 工具 schema hash。
2. **Memory**：按 [ADR-0004](../adr/0004-memory-provider-contract.md)：NullMemory → FileMemory → SQLiteMemory → 外部 adapter；每步 conformance → shadow → canary。
3. **Electron**：`apps/desktop` + `apps/web`；IPC 作为 Transport 的第二个实现；sidecar 崩溃恢复；此时 `apps/*/AGENTS.md` 才纳入守卫。
4. **第二模式**：用第二个 profile 验证“新模式不改引擎共享文件”。
5. **wire schema**：只有当前端要按事件类型分支时才定稿并上 codegen `--check`。

---

## 6. 触发条件（防止规划变成第二个项目）

| 事项 | 触发条件（不满足就不做） |
|---|---|
| durable spine（事件流 / 回放 / upcast / 租约） | 需要 rewind-as-facts、审计重放、跨端同会话续跑中的任一项被真实需求顶穿；**必须先立项 ADR + 预算** |
| `contracts/` 层 | 出现第一个需要跨层共享的不可变类型（在此之前类型留在各自包里） |
| `profiles/` | 第一个真实模式差异需要表达 |
| `MemoryPort` + provider | 第二次要换/接 memory 实现，或 personal 与 coding 记忆策略第一次冲突 |
| 字段 canonical 守卫 | 统一 domain 词表建好之后 |
| 事件版本 / wire codegen 守卫 | 事件版本化 / schema 定稿之后 |
| `apps/desktop` / `apps/web` | 前端事件契约定稿那天 |
| conformance / golden 目录 | 有第一份真实 fixture 那天 |

---

## 7. 关键包的 AGENTS.md

### 7.1 放哪些

必需（目录存在时 9 个；Phase 3 后 11 个）：

```text
src/questorharness/contracts/AGENTS.md        （已建）
src/questorharness/runtime/AGENTS.md          （已建）
src/questorharness/engine/AGENTS.md           （待补：编排层）
src/questorharness/capabilities/AGENTS.md     （已建）
src/questorharness/providers/AGENTS.md        （已建）
src/questorharness/surfaces/AGENTS.md         （已建）
src/questorharness/profiles/AGENTS.md         （profiles 建立后）
src/questorharness/bootstrap/AGENTS.md        （bootstrap 建立后）
src/questor/AGENTS.md                         （待补：产品组合根）
apps/desktop/AGENTS.md                        （Phase 3）
apps/web/AGENTS.md                            （Phase 3）
```

可选热点：`capabilities/memory/`、`capabilities/tools/`、`runtime/turn/`、`surfaces/gateway/`。

### 7.2 模板（10–15 行）

```markdown
# <package> — Agent Contract

职责：一句话。
公开入口：__init__.py 导出的 3–5 个名字。
拥有的数据：类型 / 表 / 文件。
允许依赖：contracts / 同级 / 注入的 Port。
不变式：2–3 条必须始终成立的约束。
禁止：最容易犯的 2–3 个错误。
测试：一条可直接复制运行的命令。
关键文件：3 个文件路径（守卫会校验它们存在）。
```

### 7.3 规则

- 一个包只放一份：`AGENTS.md` 或 `README.md`，不要两份同义文档；
- 设计长篇留在 `docs/architecture/`，包级文件只写本地契约；
- 根 `AGENTS.md` 只做指针，不再累积规则；
- 不要每个文件一个 README。

---

## 8. 回滚

- Phase 1 每包一个分支；回滚按包回滚，不按整波。
- 旧路径 re-export 保留一个版本窗口（仅 patch 目标为 0 的模块适用）；窗口结束前不改调用方。
- Phase 2 每个 god file 一个 PR；拆坏了只回滚该文件。
- Phase 3 每个能力一个开关；memory / Electron / 第二模式都可配置关闭。

---

## 9. 附录：本次决策依据的实测数字（2026-10-22）

| 项 | 数值 |
|---|---|
| 工作区 Python 源文件 | 241（含 44 个 `__init__.py`，源文件 197） |
| 测试里的字符串 patch 目标总数 | 310（旧口径）；**477（2026-10-22 实测，含 `monkeypatch.setattr` / `mock.patch` 全部调用，52 个文件）** |
| 快照 schema 版本字段 | **无**（实测 snapshot keys 只有 session_id/cwd/model/system_prompt/messages/usage/tool_metadata/created_at/summary/message_count） |
| patch 热点 | gateway.runtime 76、autopilot.service 41、ui.app 23、auth.external 12、utils.shell 12、services.compact 11、api.copilot_auth 11、ui.backend_host 10 |
| 测试内路径引用 | tools 172、questor.gateway 102、api 82、engine 64、ui 62、services 50、memory 31 |
| >1200 行文件 | 4（2586 / 2245 / 2089 / 1527） |
| 801–1200 行文件 | 5（1144 / 1115 / 940 / 932 / 913） |
| 唯一 >30 文件的目录 | `tools/`（44，平均 69 行） |
| 事件溯源相关符号 | 工作树 0 命中（无 Envelope / EventType / reduce / SNAPSHOT_VERSION / upcast） |
| 持久化现状 | 会话快照 JSON（`services/session_backend.py` + 产品侧 session_storage），恢复粒度 = 上一个快照 |

这些数字决定了两件事：**Phase 1 的排序**（按 patch 目标数）与**durable 必须显式立项**（当前树里没有任何 durable 实现可继承）。
