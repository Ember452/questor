# ADR 0008: 形态与能力位（profile 驱动的一种产品两种形态）

- Status: Accepted
- Date: 2026-10-24
- Deciders: Questor maintainers

## Context

ADR-0005 §3 已经写了"personal / coding 两种模式共用同一套 run/session"，`STRUCTURE.md` §7
边界 5 也已写"`profile.ui` 驱动界面能力位，沿用 ready / declared / absent 三态"。**但这两条
目前只有文档，没有实现**——实测 `src/` 下没有 profiles 包（只有 `providers/auth/profile_naming.py`，
那是 provider 别名），Python 侧对 `profile.ui` / 能力位 **0 命中**。

计划 02 的阶段 4 以 DeepCode 骨架落地**单一编码形态**（thread / workbench / inspector /
files / tests / browser）。如果不在骨架落地时留下形态扩展点，第二个形态（个人 agent：人设 /
记忆 / 日程 / 渠道 / 会话）只能靠组件里的 `if (mode === 'personal')`——那正是 ADR-0005 否掉
"两套 renderer"的同一个坑，只是换了个入口。

注入面已经具备，形态化**不需要改引擎**：

- `build_runtime(active_profile, system_prompt, session_backend, memory_backend,
  include_project_memory, extra_skill_dirs, extra_plugin_roots, permission_mode,
  ask_user_prompt, edit_approval_prompt)`（`bootstrap/runtime.py:275-300`）；
- 工具过滤已有机制：`capabilities/policy/checker.py:102`（显式拒绝）与 `:105`
  （`allowed_tools`），`capabilities/tools/registry.py` 的 `read_only_tools`。

参照（实测）：hermes 的 profile 是**目录 bundle + 角色描述**（`hermes_cli/profiles.py:1048
list_profiles`、`:1377 create_profile`；`ProfileInfo` 含 `model / provider / skill_count /
description`），前端用 `/api/profiles` + `$activeGatewayProfile` 驱动设置/技能/工具作用域；
CowAgent 的个人形态控件是 `AgentSelector / AgentScopeSelect / ChannelTeamSelect /
ContextUsageDonut`；业界 Roo Code 的 custom modes 把"模式"定义为 roleDefinition + tool groups。

## Decision

1. **形态 = profile bundle（数据）**。`profile.yaml` 含 `name / description / system_prompt /
   model / provider / skill_dirs / plugin_roots / allowed_tools / ui.capabilities`。形态差异
   只在数据，不在代码。
2. **`/rt/r1/profile` 是契约帧**：返回
   `{id, name, description, ui: {capabilities: {page_id: ready|declared|absent}}}`；
   三态沿用 `STRUCTURE.md` §7 边界 5 的词表，不另造一套。
3. **前端页面从注册表生成**：`pages/registry.ts` 每页声明 `{id, capability, title, component}`；
   导航、命令面板、快捷键、搜索**全部派生自注册表**；禁止硬编码路由。
4. **卡片按 capability 门控**：`cardSlots` 每个槽位带 `capability?`；当前形态为 `absent`
   时**显式不展示**（并登记进形态映射表），不是运行时兜底。未登记 kind 仍由 `tsc` 穷尽与
   kind 覆盖守卫拦截。
5. **映射表按 产品 × 形态 分表**：**docs/plan/mapping/questor-coding.md** 与
   **docs/plan/mapping/questor-personal.md**；kind 覆盖守卫按当前 profile 选表校验。
6. **禁止形态分支**：`apps/web` 内不得出现 `mode ===` / `isPersonal` 类判断（`rg` 探针守卫）；
   Python 引擎内不得写形态分支。
7. `allowed_tools` 经 `build_runtime` 注入 policy；个人形态的技能/插件目录走
   `extra_skill_dirs / extra_plugin_roots`——**引擎零改动**。
8. **页面 id 是契约，页面集可增量增长**：首批为 `chat` / `persona` / `memory` / `schedule` /
   `channels`（**首批注册集，不是上限**）。`registry` 的 id 一旦提交即**只增不改名、不删除**；
   下线/替换改用 `absent` 并在映射表登记，别名期至少一个 minor 版本。新增页面不改本 ADR——
   注册表 + `ui.capabilities` +（必要时的）schema kind + 形态映射表四步即可。一级导航固定
   ≤7 项，超出归入“更多 / 设置”，不得为单页新开一级入口。

## Alternatives considered

- **两套前端**（personal 与 coding 各一个 app）：状态投影、输入、主题、E2E 全部 ×2，
  ADR-0005 已明确否决。拒绝。
- **运行时 if 分支**（一个 app 内按 mode 分支渲染）：前期最省，但每加一个形态要给所有页面加
  分支，且无法用守卫拦截；三个月后退化为两套不可测 UI。拒绝。
- **只做 coding，personal 另立项**：与"一个产品两种形态"的方向冲突，且会把 profile 契约
  推到无法回填的时点。拒绝。
- **用 feature flag / 环境变量区分形态**：能力位与文档、守卫脱钩（配置能开、界面无登记）。
  拒绝。

## Consequences

- 变得容易：新增页面 = 一条注册项 + 一个 capability；新增形态 = 一份 `profile.yaml`；
  新增功能仍被 schema codegen + kind 覆盖守卫逼全；personal 复用同一 run / session /
  transport / 对话卡。
- 变得难 / 必须接受：每加一个页面都必须给出 capability 归属，否则门控无从生效；映射表从 1 张
  变 2 张（维护成本 ×2，由守卫兜底）；`profile.ui` 与 `STRUCTURE.md` §7 边界 5 必须同刀维护。
- 不变：ADR-0005 的 Electron 壳与唯一 renderer；ADR-0006 的 SSE / 36 kind / 五件套；
  ADR-0007 的基座与双侧 codegen。

## Verification

- **tests/ci/test_kind_coverage.py** 按 profile 选表：某 kind 在当前形态为 absent 时，映射表
  必须有"不展示"行，否则红。
- `rg "mode ===|isPersonal" apps/web/src` = 0。
- 把某页 capability 置为 absent → 导航 / 命令面板 / 卡片同步消失（4a 判绿）。
- 两个 profile 的 `allowed_tools` 可枚举且互不相同；personal 形态下 coding 专属工具不可见。
- `/profile` 返回的 capabilities 必须与页面注册表、形态映射表三处一致。
- `registry` 的 page id 集合必须 ⊆ 当前 profile 的 capabilities；已有 id 消失或改名 → 红。
