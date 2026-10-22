# Questor 目标结构（v2）

- 状态：目标结构（Target），不是当前实现
- 日期：2026-10-22
- 适用范围：`src/questorharness`（引擎）、`src/questor`（产品）、`apps/*`（宿主）
- 相关决策：[ADR-0002](../adr/0002-target-structure.md)、[ADR-0003](../adr/0003-file-layout.md)
- 当前布局：[Architecture](../ARCHITECTURE.md)
- 冲突裁决：运行时语义以七环设计为准；目录、依赖与文件布局以本文和两份 ADR 为准。

本文回答三个问题：

1. 包和目录怎么分，才能在 1000+ 文件时仍然可读；
2. 个人 agent 与编码 agent 两种模式，怎么做到不复制、不分叉；
3. 核心字段会持续变化时，怎么把改动限制在局部。

---

## 0. 一页结论

```text
                 ┌── profiles（纯数据，只依赖 contracts）
                 │
contracts ──┬── kernel ── runtime ── capabilities ── surfaces ── bootstrap
            │
            └── providers（适配器，只依赖 contracts）

箭头方向：右边依赖左边；bootstrap 是唯一装配点。
apps/desktop + apps/web + apps/terminal  ← 宿主，只装配，不含领域逻辑
src/questor                                ← 产品组合根 + 产品策略
```

七条结构约束：

1. **引擎与产品物理分离**：`questorharness` 永不 import `questor`；产品只 import 引擎的公开面。
2. **当前真相载体是会话快照，不是事件流**：恢复粒度 = 上一个快照。durable spine（事件流 / 回放 / upcast / 单写者租约）**未立项**，不写进结构约束，也不预先建层（见 §11）。
3. **模式是装配，不是目录**：personal / coding 是 `profiles/` 里的两份声明，不是两棵代码树。
4. **字段变更靠三层分离**：domain / storage / wire 分离；快照与 wire 要能跨版本读；不预设事件版本与 upcaster。
5. **文件可预测靠叶子语法**：每个子域的形状一致；目录有封顶；入口只有 `__init__.py`。
6. **新增能力半径 ≤1**：新能力 = 新目录 + 注册表一行 + profile 引用；不改内核。
7. **目录从内容长出来**：**没有内容就不建目录**；接口必须封顶，接缝必须可验，真源必须唯一。

---

## 1. 目标树

```text
questor/
├─ apps/                              # 非 Python 宿主：只装配 UI 与进程
│  ├─ desktop/                        # Electron: main/ preload/ resources/
│  ├─ web/                            # React renderer（desktop 与浏览器共用）
│  └─ terminal/                       # Node Ink TUI（由 frontend/terminal 迁入）
│
├─ src/
│  ├─ questorharness/                 # 引擎：headless、可独立装配
│  │  ├─ api.py                       # 唯一公开门面（只 re-export）
│  │  ├─ contracts/                   # 词表 + Port（无实现、无 IO）
│  │  │  ├─ ids.py                    # SessionId / RunId / TurnId / ProfileId
│  │  │  ├─ errors.py
│  │  │  ├─ commands/                 # session.py run.py turn.py profile.py
│  │  │  ├─ events/                   # session.py run.py memory.py tool.py
│  │  │  ├─ domain/                   # session.py run.py message.py tool_call.py
│  │  │  ├─ ports/                    # store.py model.py memory.py tool.py lease.py
│  │  │  ├─ schemas/                  # wire JSON Schema（v1）
│  │  │  └─ upcast/                   # events.py snapshots.py
│  │  ├─ kernel/                      # A环：durable spine（机制，不含策略）
│  │  │  ├─ log.py                    # append-only 事实流
│  │  │  ├─ transition.py             # 纯 reduce/apply，唯一状态改写口
│  │  │  ├─ snapshot.py               # checkpoint / 崩溃重建
│  │  │  ├─ inbox.py                  # 命令入口 + 幂等键
│  │  │  ├─ sequence.py               # per-run seq + per-session change_version
│  │  │  ├─ lease.py                  # 本地写者租约；跨进程不支持（见 §11）
│  │  │  └─ errors.py
│  │  ├─ runtime/                     # B环：run/turn 控制与循环策略
│  │  │  ├─ run/                      # controller.py state.py recovery.py
│  │  │  ├─ turn/                     # loop.py tool_cycle.py stop.py stream.py
│  │  │  ├─ session/                  # fork.py rewind.py index.py
│  │  │  ├─ tasks/                    # task_manager.py local_agent.py local_shell.py
│  │  │  ├─ budget/                   # tokens.py cost.py
│  │  │  ├─ extension/                # points.py chain.py
│  │  │  ├─ delegation/               # subagent.py dag.py（留缝）
│  │  │  └─ autopilot/                # policy.py loop.py triggers.py state.py
│  │  ├─ capabilities/                # 能力域（每个子域一个叶子语法）
│  │  │  ├─ context/                  # assemble.py compact/ budget.py
│  │  │  ├─ memory/                   # recall/ write/ consolidate/ backends/
│  │  │  ├─ tools/                    # fs/ shell/ web/ task/ agent/ mcp/ media/ cron/
│  │  │  ├─ policy/                   # permission.py sandbox.py approval.py
│  │  │  ├─ delivery/                 # D环（留缝）
│  │  │  ├─ schedule/                 # E环
│  │  │  └─ evolution/                # F环（留缝）
│  │  ├─ providers/                   # 适配器：只实现 contracts.ports
│  │  │  ├─ llm/                      # litellm.py openai.py codex.py ...
│  │  │  ├─ auth/                     # oauth.py copilot.py ...
│  │  │  ├─ store/                    # sqlite.py ...
│  │  │  ├─ sandbox/                  # process.py docker.py ...
│  │  │  ├─ search/                   # web search adapters
│  │  │  ├─ lsp/                      # language server adapters
│  │  │  └─ mcp/                      # MCP transport
│  │  ├─ surfaces/                    # 传输：只认 contracts + 注入的 facade
│  │  │  ├─ http/                     # HTTP API
│  │  │  ├─ sse/                      # 事件流
│  │  │  ├─ ipc/                      # Electron preload ↔ sidecar
│  │  │  ├─ gateway/                  # 协议/路由（无产品策略）
│  │  │  ├─ channels/                 # channel adapters
│  │  │  └─ terminal/                 # Python 终端 surface（如保留）
│  │  ├─ profiles/                    # 模式装配（纯数据，只依赖 contracts）
│  │  │  ├─ schema.py                 # Profile 槽位定义
│  │  │  ├─ registry.py               # ID → 实现，fail-closed
│  │  │  ├─ personal/profile.yaml
│  │  │  └─ coding/profile.yaml
│  │  └─ bootstrap/                   # 装配：唯一 env 入点
│  │     ├─ config/                   # schema.py load.py defaults.py
│  │     ├─ compose.py                # compose(overrides)
│  │     └─ lifecycle.py              # 启动/关闭/健康检查
│  └─ questor/                        # 产品 app：组合根 + 产品策略
│     ├─ composition.py               # 调用 harness.bootstrap.compose(overrides)
│     ├─ cli.py
│     ├─ sidecar.py
│     ├─ gateway/                     # 产品级 gateway 策略（群规则/通知）
│     ├─ channel_policy/              # 飞书群等产品策略
│     ├─ onboarding.py
│     └─ workspace.py
│
├─ plugins/                           # 数据包：skills/ prompt-packs/ themes/
├─ evals/                             # G环：任务集/判分器/trace 重放
├─ tests/                             # unit/ integration/ e2e/ contract/ golden/ property/
├─ scripts/                           # 守卫与生成器
├─ docs/                              # architecture/ adr/ guides/ reference/ operations/
├─ pyproject.toml
├─ uv.lock
├─ .importlinter
└─ README.md
```

说明：

- **不为了名字好看做全仓改名**。保留 ADR-0001 的两个分发名：`questorharness`（引擎）与 `questor`（产品）。重组发生在包内部。
- 上面的树是**目标形态**，不是当前目录。标了“未立项”的层（`kernel/`、`contracts/`、`profiles/`）**现在不建**；Phase 1 实际只会长出 5 个有内容的域。
- `apps/` 只放非 Python 宿主。Python 的 sidecar 入口在产品包 `src/questor` 内，不在 `apps/`；具体文件名等 Phase 3 定了再写。
- `plugins/` 是数据，不是代码。技能、提示词包、主题都放这里，由注册表加载。
- `evals/` 是 G 环，不属于引擎运行时，不进入 wheel。
- 每个关键包有一个 `AGENTS.md`（见 §10），树里不展开。

三个不要合并：

- `capabilities/policy`（决策）与 `providers/sandbox`（执行）；
- `runtime/tasks`（后台任务运行时）与 `capabilities/tools/task`（模型可见的 task 工具）；
- `surfaces/gateway`（协议/路由）与 `src/questor/gateway`（群规则/通知等产品策略）。

---

## 2. 依赖秩

### 2.1 允许的依赖

| from \ may import | contracts | kernel | runtime | capabilities | providers | surfaces | profiles | bootstrap |
|---|---|---|---|---|---|---|---|---|
| `kernel` | ✅ | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `runtime` | ✅ | ✅ | — | ❌ | ❌ | ❌ | ❌ | ❌ |
| `capabilities` | ✅ | ❌ | ❌ | — | ❌ | ❌ | ❌ | ❌ |
| `providers` | ✅ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ❌ |
| `surfaces` | ✅ | ❌ | ❌（facade 注入） | ❌ | ❌ | — | ❌ | ❌ |
| `profiles` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ |
| `bootstrap` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `questor`（产品） | api only | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

关键点：

- `runtime` **不 import 任何能力实现**。它只认 `contracts/ports` 与 `kernel` 的公开入口，由 `bootstrap` 注入。
- `capabilities` **不 import providers**。它只依赖 Port；适配器由 `bootstrap` 注入。
- `surfaces` **不 import runtime/capabilities**。它只认 `contracts` 和注入的 facade。
- `profiles` 是纯数据：只引用注册表 ID，不含 import。
- `kernel` 不 import `runtime`；`runtime` 不 import `kernel` 的内部模块，只用 `kernel` 的公开入口。

### 2.2 强制方式

`.importlinter` 使用 `layers` + 多条 `forbidden`，不要只画一条箭头：

```ini
[importlinter]
root_packages =
    questorharness
    questor

[importlinter:contract:engine-layers]
name = Engine layers
type = layers
layers =
    questorharness.bootstrap
    questorharness.surfaces
    questorharness.capabilities
    questorharness.runtime
    questorharness.kernel
    questorharness.contracts

[importlinter:contract:no-providers-in-capabilities]
name = Capabilities must not import provider implementations
type = forbidden
source_modules = questorharness.capabilities
forbidden_modules = questorharness.providers
```

`layers` 只表达“上层可以依赖下层”，不能表达“同级/反向禁止”。矩阵里每一个 ❌ 都要单独加 `forbidden`，至少这四组：

```ini
[importlinter:contract:capabilities-are-leaf]
name = Capabilities may import contracts only
type = forbidden
source_modules = questorharness.capabilities
forbidden_modules =
    questorharness.kernel
    questorharness.runtime
    questorharness.providers

[importlinter:contract:providers-are-adapters]
name = Providers may import contracts only
type = forbidden
source_modules = questorharness.providers
forbidden_modules =
    questorharness.kernel
    questorharness.runtime
    questorharness.capabilities

[importlinter:contract:surfaces-are-thin]
name = Surfaces may import contracts only
type = forbidden
source_modules = questorharness.surfaces
forbidden_modules =
    questorharness.kernel
    questorharness.runtime
    questorharness.capabilities
    questorharness.providers

[importlinter:contract:product-uses-public-face]
name = Product imports the public face only
type = forbidden
source_modules = questor
forbidden_modules =
    questorharness.contracts
    questorharness.kernel
    questorharness.runtime
    questorharness.capabilities
    questorharness.providers
    questorharness.surfaces
    questorharness.profiles
```

矩阵里每一行的 ❌ 都要有对应的 `forbidden`；上面四组是必须项，不是全部。`kernel`/`runtime` 对 `profiles` 的禁止也属于这一类。

**import-linter 只能挡包级 import，挡不住调用图。** 但 AST 守卫必须跟着概念走：当前树里没有 `reduce()` 咽喉，也没有事件存储，所以现在**不写**这两类守卫。当下可落地的只有两条：

- 禁止引擎 import 产品（已有契约，继续保留）；
- 禁止新代码继续依赖 `questorharness.ui`、`questorharness.utils`、`questorharness.services` 这三个漏桶（新债不加，旧债用 baseline 记录）。

将来若立项 durable，再补：“`reduce(` 只出现在状态转移入口”、“事实流 append 只由内核内部调用”两条 AST 守卫。

---

## 3. 七环映射

| 环 | 职责 | 物理位置 | 状态 |
|---|---|---|---|
| A 运行闭环 | 提交 → 循环 → 快照 → 恢复 | 当前：`engine` + 快照；durable 版本未立项 | 部分存在 |
| B 会话闭环 | 会话作用域、上下文装配、压缩 | 当前：`engine` + `services/compact` → 目标 `runtime` + `capabilities/context` | 存在，待归位 |
| C 记忆闭环 | 召回、写回、巩固、退修 | 当前 `memory/` + `services/` → 目标 `capabilities/memory` | 存在，待归位 |
| D 交付闭环 | 内容寻址义务账、投递五态 | 目标 `capabilities/delivery` | 未立项 |
| E 触发闭环 | 调度器、同一条提交入口 | 当前 `services/cron*` → 目标 `capabilities/schedule` | 存在，待归位 |
| F 自进化环 | skill/SOP/索引改写 | 目标 `capabilities/evolution` | 未立项 |
| G 评测环 | 任务集、判分器、trace 重放 | 目标 evals 目录 | 未立项 |

未立项的环**不落目录**，只在本表登记接缝与触发条件（见 §10 与 MIGRATION §8）。“声明式接缝”的准入标准见 §10；不满足就不建。

---

## 4. 模式装配

### 4.1 两条正交轴

```text
profile      = personal | coding | research
interaction  = interactive | autonomous | scheduled | webhook
run 身份     = (session_id, profile_id, interaction_mode)
```

- **profile** 决定“装什么”：上下文、记忆、循环、工具、权限、提示词、工作区。
- **interaction** 决定“怎么进来”：审批、澄清、触发方式、是否可中断。
- 两者都不是目录。它们都是 `run_started` 上的字段。

### 4.2 槽位

| 槽位 | personal | coding |
|---|---|---|
| `loop` | react + 主动收敛 | plan-execute-verify |
| `context` | 记忆优先 + 日程/收件箱 | 仓库地图 + diff + LSP |
| `memory` | 个人长期记忆（core/daily/session） | 项目记忆 + 代码索引 |
| `tools` | 消息/日程/搜索/文件 | fs/shell/git/lsp/worktree |
| `permission` | 默认询问 | 计划模式 + 写前审批 + 沙箱 |
| `workspace` | 个人目录（home scope） | repo root + worktree |
| `prompt` / `ui` | 个人助理人格 / chat+memory | 编码规范 / files+diff+terminal |

### 4.3 profile 只引用 ID

`profiles/coding/profile.yaml`：

```yaml
id: coding
loop: loop:plan-execute
context: context:repo-aware
memory: memory:project
tools:
  - tool:fs-read
  - tool:fs-write
  - tool:shell
  - tool:lsp
  - tool:git-worktree
permission: policy:coding
prompt: prompt:coding-v3
workspace: workspace:repo
ui:
  - panel:diff
  - panel:terminal
  - panel:plan
  - panel:files
```

三条纪律：

1. **profile 不含代码**。解析不到 ID 就 fail-closed，启动即报错。
2. **模式不得拥有自己的 memory/context/loop 副本**。差异必须落成对应能力的 strategy，由 profile 选。
3. **每次 run 记录 `profile_fingerprint`**：resolved ID + 参数 + prompt hash + tool schema hash + model。用于回答“同一个模式，为什么今天和昨天行为不同”。

### 4.4 切换语义

- profile 是 **session 级**属性；
- 切换发一条 `profile_changed` durable event；
- 下一个 turn 重新装配；
- 禁止在一个 turn 中间热换（工具面与事件流会不一致）。

---

## 5. 字段演进

### 5.1 三层模型

| 层 | 位置 | 谁读 | 变更规则 |
|---|---|---|---|
| domain | `contracts/domain/*.py`（待建） | runtime / capabilities | 纯数据、frozen、带 `schema_version`；加字段必须给默认值 |
| storage | 会话快照文件与 store 适配层 | store adapter | 只增不改；快照能跨版本加载；旧快照不兼容时写迁移函数 |
| wire | 对外事件/命令 schema（待建） | TS / 外部 | 只增不删；未知字段忽略；定稿后才上 codegen `--check` |

> 现状：三层里只有 domain 层是部分存在（`engine/messages.py`、`state/app_state.py`）；wire 层没有 schema 文件。所以 **storage 层现在只要求“旧快照能加载”，不要求事件重放**。

### 5.2 四条纪律

1. **加字段** = optional + 默认值 + 有生产者 + 有读取方（禁止无消费者字段）。
2. **改字段** = 新增同义字段 → 双读 → 旧快照/旧数据迁移 → 删旧；至少两个版本窗口，禁止 big-bang 改名。
3. **快照与对外事件都要可跳版本读**：加载入口先做版本判定，再进字段映射。若将来立项 durable，同一机制升级到事件 upcaster。
4. **ID** = `NewType` + 前缀 + 校验函数；禁止裸 `str` 跨层传递。

### 5.3 示例：新增 `workspace_id`

```text
域模型 session 类型                        +1 字段（默认 None）
快照读写                                +1 键，旧快照无该键时读默认
对外 wire schema（若已定稿）              +1 可选字段
旧 session fixture                        仍能加载
runtime / capabilities / surfaces          0 改动
```

字段变更的验收标准：**爆炸半径 ≤3 个文件 + 1 条旧快照 fixture**。超过，说明 domain/storage/wire 没有分开。

---

## 6. 文件级布局

完整规则见 [ADR-0003](../adr/0003-file-layout.md)。这里只列执行摘要：

| 指标 | 健康值 | 警戒 | 失败 |
|---|---|---|---|
| 目录源文件数（不含 `__init__.py`） | 3–16 | 17–30 | >30 |
| 文件行数 | 80–800 | 801–1200 | >1200 |
| 目录深度 | 2–5 | 6 | >6 |
| `__init__.py` | ≤40 行、≤10 导出（`contracts/` ≤15）、零逻辑 | 41–80 行 | >80 行或含 `def/class` |

完整例外（catalog、迁移、生成代码）见 [ADR-0003](../adr/0003-file-layout.md)。`tools/` 44 个平铺仍会失败，因为它不是 catalog 例外。

叶子语法：

```text
<subdomain>/
├─ AGENTS.md      # 10–15 行地图
├─ __init__.py    # 只导出 ≤10 个公开名
├─ model.py       # 本域数据
├─ ports.py       # 本域需要的 Protocol
├─ policy.py      # 阈值/规则/决策
├─ store.py       # 本域持久化
├─ registry.py    # ID → 实现
├─ errors.py
└─ <use-case>.py  # recall.py / write.py / select.py ...
```

禁用文件名：`utils.py`、`helpers.py`、`common.py`、`base.py`、`manager.py`、`service.py`、`handler.py`、`processor.py`、`misc.py`、`core.py`、`types.py`、`constants.py`。

折叠/展开规则：

- 文件 >800 行、>3 个独立概念、>2 个变化原因 → 拆成子目录；
- 目录只有 1 个源文件、且不是公共边界 → 塌回文件；2 个源文件若是 model+store/sql 对，可保留；
- 子域升一级域的条件：有自己的 Port、独立变化节奏、独立数据所有权。

---

## 7. Electron 与前端

```text
apps/desktop/
├─ src/main/          # 窗口/托盘/深链/自动更新/sidecar 监管/系统钥匙串
├─ src/preload/       # contextBridge 白名单，只暴露 invoke/send/on
└─ resources/

apps/web/
├─ src/app/           # 路由与壳
├─ src/features/      # 垂直切片：chat/ workspace/ memory/ schedule/ settings/
├─ src/shared/        # ui-kit、Transport port、theme
└─ src/generated/     # 契约 codegen（只读）
```

六条边界：

1. **sidecar 是唯一后端**；Electron 不内嵌 Python，不直接调领域函数。
2. **IPC 只是 Transport 的第二个实现**：`HttpTransport` / `IpcTransport` 共用同一套 Command/Event envelope。
3. **main 不写业务**：只做进程与 OS 能力（文件对话框、通知、托盘、深链、keychain、崩溃重启）。
4. **feature 之间零引用**：跨 feature 走 `generated` 契约和 `shared`，不直接 import 对方组件。
5. **profile.ui 驱动界面能力位**：沿用 `ready / declared / absent` 三态。
6. **崩溃恢复**：sidecar 崩 → main 重启 → UI 用 `after_seq` 重订阅。

`apps/web` 必须能单独在浏览器跑；Electron 只是它的一个 host。这样开发、调试、E2E 都不依赖桌面壳。

---

## 8. 现有结构 → 目标结构

| 现状 | 处置 | 去向 |
|---|---|---|
| `api/`、`auth/`、`sandbox/` | 降为适配器 | `providers/{llm,auth,sandbox}/` |
| `engine/`、`commands/`、`coordinator/`、`swarm/`、`tasks/`、`autopilot/`、`hooks/` | 下沉到运行时 | `runtime/{turn,commands,delegation,tasks,autopilot,extension}/` |
| `state/` | 拆分 | 事实状态 → `kernel/`；UI 可观察状态 → `surfaces/terminal/state.py` 或前端 store |
| `services/*` | 解散 | `capabilities/{context,memory,schedule}/`、`providers/lsp/`、`runtime/budget/` |
| `memory/`、`permissions/`、`channels/`、`mcp/` | 升级为能力/传输 | `capabilities/{memory,policy,tools/mcp}/`、`surfaces/channels/`、`providers/mcp/` |
| `ui/`、`keybindings/`、`themes/`、`vim/`、`output_styles/`、`voice/` | 上移出引擎 | `apps/terminal/`、`surfaces/terminal/`、`providers/voice/` |
| `utils/`、`config/`、`bridge/` | 解散/归位 | `kernel/`（锁）、`bootstrap/config/`、`surfaces/`（bridge） |
| `questor/gateway` | 拆产品策略与传输 | surfaces/gateway（协议路由）+ 产品包内的渠道策略目录 |

`services/` 的 5 个子包都没有独立模块文件，逻辑全在 `__init__.py`：`compact`、`lsp`、`memory_extract`、`session_memory` 先迁到各自能力域，`oauth` 为空可直接删。

---

## 9. 迁移阶段

| 阶段 | 内容 | 是否改行为 | 出口 |
|---|---|---|---|
| **Phase 0** | 文档 + 守卫 + AGENTS 地图 | 否 | 文档合并；3 个可落地守卫能跑 |
| **Phase 1** | Move-only：按耦合度排序搬文件、同 PR 改测试 patch 目标 | 否 | 基线五项不变（测试/CLI/冷导入/import-linter/旧快照加载） |
| **Phase 2** | Code-shape：拆 god file、把循环从 UI 抽出、建 Port | 否 | 金标输出不变；无 >1200 行/ >30 文件 |
| **Phase 3** | Capabilities：profiles、memory provider、Electron、第二模式 | 是 | 新能力半径 ≤1；新模式不改引擎核心 |

详细移动表、阶段边界、回滚策略见 [MIGRATION](MIGRATION.md)。Phase 1 每包一个 PR；Phase 2 每个 god file 一个 PR；Phase 3 每个能力一个开关。

---

## 10. 守卫与地图

### 10.1 现在就上的守卫（3 个）

| 守卫 | 作用 | 级别 |
|---|---|---|
| `.importlinter`（已有 1 条，扩到 4–5 条） | 引擎⊥产品；层级；禁止新代码依赖 `questorharness.ui`/`utils`/`services` | blocking |
| check_layout.py（待建） | 目录扇出、文件行数、禁用名（带 baseline）、`__init__` 门面、AGENTS 地图 | blocking |
| gen_tree.py（待建） | 生成目录树文档，--check 防漂移 | blocking |

已有的三个继续保留：`check_doc_cross_refs.py`、`check_secret_projection.py`、`check_thread_leak.py`。

**规则：守卫跟着概念走。概念不存在，守卫就不建。**

### 10.2 等概念落地才建的守卫（现在不写）

| 守卫 | 前置概念 | 触发条件 |
|---|---|---|
| check_contract_fields | 统一 domain 词表 + canonical 集 | 第一次给核心状态加字段 |
| check_event_versions | 版本化事件类型 | durable 立项 |
| check_wire_codegen | wire schema + 前端 generated | 前端开始按事件类型分支 |
| conformance / golden 目录 | 换后端契约、快照加载基线 | 有真实 fixture 那天 |

当前 `tests/` 只有 unit / integration / e2e；conformance、golden 目录等有了真 fixture 再建，不先挖空目录。

**地图**：

- 每个关键包一个 `AGENTS.md`（10–15 行）：职责、公开入口、拥有的数据、允许依赖、不变式、禁止、测试命令、关键文件。
- 必需（目录存在时）：8 个引擎域 + `src/questor`；`apps/desktop` / `apps/web` 在 Phase 3 创建后必需。热点子域（memory/tools/turn/gateway）可选。
- 一个包只放一份（`AGENTS.md` 或 `README.md`），不要两份同义文档。
- 目录树文档由 gen_tree.py 生成，不手写。
- 新文件必须能在一句话内说明“它为什么存在”；否则不要建。

**接缝的两类准入**（缺一条就不建目录）：

- **已激活接缝**（现在就要用）：Port + 真实调用方 + fake + 会跑的 conformance。
- **声明式接缝**（未来环，允许暂无生产消费者）：Port + fake + 会跑的 conformance + manifest 的 `declared` 状态；一旦出现真实调用方，升级为已激活。

`_reserved/` 不在此列：它是平行的未来树，激活时要搬一次，等于保证第二次迁移。接缝放在拥有它的域里，不集中放。

---

## 11. 非目标与硬边界

明确不做：

- **durable spine（事件流、回放、upcast、单写者租约、命令窗口）**：**未立项**。当前是快照模型；要引入必须先单独立项（ADR + 预算 + 排期），**不得混在结构迁移里默默发生**。
- **空目录占位**。没有内容的域不建；“先挖坑后填”就是 v1 式膨胀的开始。
- **跨进程/多端 exactly-once**。只保证 at-least-once + 幂等；改一致性模型必须单独 ADR。
- **`_reserved/` 预留树**。没有消费者的目录不建。
- **`modes/personal` / `modes/coding` 平行树**。模式是 profile，不是目录。
- **`ids/`、`reduce/` 这类微包**。它们在 `contracts/ids.py`、`kernel/transition.py` 里是文件，不是包。
- **`manager.py` / `service.py` / `utils.py` 这类名字**。它们会变成 god file 或垃圾桶。
- **复制 Pi 的产品 core 平铺或 DeerFlow 的 57 文件 middlewares 平铺**。抄它们的语法，不抄它们的数量。
- **一次性重写**。按 Phase 0–3 搬，每阶段行为边界明确。

硬边界：

- `questorharness` 永不 import `questor`。
- `kernel` 永不 import `runtime` / `capabilities` / `providers`。
- `capabilities` 永不 import `providers`。
- `surfaces` 永不 import `capabilities` / `runtime`（facade 注入除外）。
- `profiles` 只依赖 `contracts`。
- 任何文件 >1200 行、任何逻辑目录 >30 个源文件，CI 判红（catalog/迁移/生成代码按 ADR-0003 豁免）。

---

## 12. 验收标准

结构是否成立，不看目录好不好看，看这五条：

1. **10 秒规则**：给出一个行为描述，新人能在 3 次点击内找到实现文件。
2. **新能力半径**：新增一个工具/记忆算法/压缩策略，共享文件改动 ≤1（registry 或 profile）。
3. **新模式零内核改动**：新增第三个 profile，只加 YAML + 策略实现，不改 `kernel`/`runtime` 共享文件。
4. **字段变更局部化**：新增一个 `*_id`，爆炸半径 ≤3 文件 + 1 fixture。
5. **快照兼容**：旧 session 快照仍能加载；CLI 基线输出不变。
6. **不建空域**：目标树里每一个已存在的目录都有至少一个被导入的文件。

上述任何一条不成立，说明结构还只是“目录”，没有成为“机制”。
