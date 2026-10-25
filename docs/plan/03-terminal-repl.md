# 计划 03：终端版（REPL + 覆盖层）

- Status: Draft Rev2（2026-10-25 立项；同日经评审 10 条修订后重写，见附录 A）
- 基线：分支 `feat/terminal-repl`，HEAD `57fb980`
- 修订要点（Rev2）：契约扩张由 8 个同构端点合并为 1 个 `/catalog/{kind}`（§4 波 D）；新增 §2.4 并发契约（唯一写终端通道 / alt-screen 归属 / 审批时序）并把并发列为最高风险；`wire_view` 与 `FooterVM` 前置到波 A；映射表加 `id`/`status` 两列使占位守卫可机器执行；修正 §10 与新增 kind 的矛盾。
- 决策依据：[ADR-0005](../adr/0005-single-ui-host.md)（终端=瘦客户端；prompt-toolkit 以输入层回归）、
  [ADR-0006](../adr/0006-serve-host-and-wire-protocol.md)（一份契约两种传输）、
  [ADR-0008](../adr/0008-profile-driven-modes.md)（形态是数据）
- 用户裁决（2026-10-25，本轮）：
  1. **渲染模型 = 混合**：日常对话写进终端原生 scrollback，只有 transcript 浏览/搜索这类"看"的动作临时进 alt-screen；
  2. **功能面 = 全表覆盖**（`docs/plan/mapping/questor-coding.md` 逐行要有终端载体）；
  3. **缺失项显式占位，不注释掉代码**（`注释=`静默缺失=功能黑洞，见 §2/§6-11；`占位`=登记为 absent，见 §5）；
  4. **复用优先**：代码结构、配色、布局一律取参照项目，不自设计。
- 参照系（四参照，均本机实测，见 §3 与文末参考地图）：
  - **交互语法 = Claude Code**（`编码/Claude-Code-main`）——**专有许可，只读语法，不搬代码**；
  - **Python 骨架与测试范式 = DeepCode `cli/tui`**（MIT，同语言同栈同渲染模型）——**例外：输入并发维度不可平移**，DeepCode 是行式模型（`app.py:1075-1096` 建 task → SIGINT 路由 → `await` 到底），见 §2.4；
  - **卡片语汇 / 视觉真源 / CJK 宽度 = Reasonix**（MIT；tokens 已是本仓 `terminal_theme.py` 的真源）；
  - **面板细节 = codex**（Apache-2.0，按需取形，不取码）。
- 前序计划：[计划 02](02-studio-serve-host.md)（serve 契约、五张对话卡、Electron 壳）。本计划只做**终端这一个消费者**：
  不改 `apps/web` 的页面与交互；**唯一例外**是新增 wire kind 时必须同步 `cardSlots.ts` 一条槽位与生成物
  （`tests/ci/test_kind_coverage.py` 的全等断言强制，见 §2.3）。不改引擎对标功能路线。
- 纪律：**复用检索义务**（§0-8）、**零视觉自设计**（§0-9 三序）、**许可与 CONVENTIONS §4.5**（§0-10）、
  **每刀红绿 + 三张对账表**（§0.5-6）、**中断-上报-授权**（§3）。

---

## 0. 怎么用

1. 每波开工前重跑 §1 基线采集比对；任一读数不符先停。
2. 按 A→B→C→D→E 推进；**前一波绿验收不过不进下一波**。
3. **波 A/B/C 不碰帧契约**（只用现有 8 端点 13 kind + 本地能力）；**波 D 才开始契约扩张**（1 个 catalog 路由 + 2 处字段扩展），且需 §9 的裁决。
4. 每波结束回填 §8 总验收表，注明 commit 与三张对账表（条目 / 影响面 / 判红）。
5. 触发 §7 任一停工症状，先停手诊断，禁止加豁免绕过。
6. §9 的开放问题只能由用户裁决，执行 agent 不得代答。
7. 分支制：A–C 在 `feat/terminal-repl`；D–E 因动契约，从 `main` 切 `feat/terminal-contract`，
   **合入顺序锁**：`feat/terminal-contract` 在 A–C 绿之前不合入。
8. **视觉真源不变**：颜色/间距/图标一律取 Reasonix tokens 的终端投影（`serve/terminal_theme.py`），
   本计划不新增任何自造色值。终端的**信息架构**（首屏/空态/分区/键位分组）由本仓裁决，但每个图元必须
   在 §3 登记来源（Claude Code / Reasonix / DeepCode / codex 四者之一），**无来源即新造，须单独过用户**。
9. **中文是一等公民**：终端界面文案用中文（命令名、工具名、模型名等标识符保持原样）。
   参照项目全是英文，但中文排版对宽度计算更敏感，§3 的 CJK 层是必需项而非可选装饰。
10. **许可口径**（CONVENTIONS §4.5，[CONVENTIONS.md:64-69](../CONVENTIONS.md#L64-L69)）：外部实现只作灵感，
    入仓代码**不带外部来源/许可/归属标记**。DeepCode/Reasonix/GenericAgent 为 MIT、codex 为 Apache-2.0，
    Claude Code 根目录**无 LICENSE（专有）** → 只能是"读懂后按本仓契约重写"，不是带版权头复制。
    带许可头的整树复制在 `src/` 内禁止（`apps/` 的 vendored 例外不适用于引擎侧代码）。
11. **编号体系**（本文档有四套编号，执行时勿混）：`表 A–D` = 能力对账；`波 A–E` = 实施波次；
    `F1/F2` = 本轮发现的本仓缺陷；`W-D1…` = 波 D 的条目。**禁止再用 `D1/D2` 指代缺陷或波次条目。**
12. **计数口径**（避免 §0-1 误触停工）：文件行数一律用
    `python -c "from pathlib import Path; print(len(Path(F).read_text(encoding='utf-8').splitlines()))"`；
    **禁止用 `Get-Content | Measure-Object -Line`**（它忽略空行，本仓已踩过）；行号引用一律用 `Select-String` 或 grep 核验。

---

## 0.5 全量对账（2026-10-25 实测，本计划的立项依据）

计数口径来自实跑与逐文件读取，不是估计：**引擎事件 7 类 → wire 13 kind**（`protocol/app-wire.schema.json`）、
**工具 39**（`capabilities/tools/registry.py:35-75`）、**斜杠命令 62 内置 + 48 技能 = 110**（实例化注册表 dump）、
**HTTP 端点 8**（`hosts/serve/routes.py:127-142`）、**会话存储 API 5**（`platform/session_storage.py:70,131,139,202,218`）。

### 表 A：后端真没有（参照有、本仓无法实现）——6 项

| # | 能力 | 参照 | 本仓缺在哪（证据） | 处置 |
|---|---|---|---|---|
| A1 | 审批三档 / 记住本次选择 | Reasonix `ApprovalCard` + `tool-approval-mode`（`footer.go` 标签：Ask/Auto/yolo/Read only/Don't ask） | `PermissionPrompt = Callable[[str, str], Awaitable[bool]]`（[runtime.py:55](../../src/questorharness/bootstrap/runtime.py)）**只有 bool**；`/approve` 只收 `approve\|deny`（`routes.py:191`） | 做两档；第三档渲染 `⊘ 未实现 · A1`（§5） |
| A2 | Ask 单选 / 多选 / 自填 | Reasonix `AskCard` | 工具入参只有 `question: str`（`capabilities/tools/agent/ask_user_question_tool.py:15-20`）；回调 `Callable[[str], Awaitable[str]]`（`:12`）；帧只有 `{id,question}`（`wire.py:86-88`） | 做自由文本；选项类渲染 `⊘ 未实现 · A2` |
| A3 | 回合中插话 steer（不打断地增补指令） | Reasonix `Steer`/`Pending`（`transcript.go` `ItemUser.Steer`、`queue_slash.go`） | 无 `/steer` 端点；`authority.py` 只有 **1 个排队槽**（`queue_depth=1`，`authority.py:67,104-117`） | 排队做满；steer 渲染 `⊘ 未实现 · A3` |
| A4 | 任意检查点回滚 | Reasonix `checkpoints` + `restore.go`(44) + `rewind.go`(284) | 只有 `/rewind` 删最后一轮；无检查点列表 | 标「部分可用」并在 help 注明 |
| A5 | 提交附件 / 图片输入 | Reasonix `clippaste.go`(96)；Claude Code `attach` | `/submit` 只收 `{line, clientRequestId}`（`routes.py:150-158`）；`turn_started` 无 attachments | 粘贴图片渲染 `⊘ 未实现 · A5` |
| A6 | 语音采集（录音→转写） | Claude Code `voice` | `/voice` 只是设置开关（`commands/families/appearance.py:190`），无采集模块 | 开关保留；采集 `⊘ 未实现 · A6` |

**表 A 的 id 就是契约**：A1–A6 同时是 `terminal/unsupported.py` 的 key、映射表新增 `id` 列的取值。
三处用同一个 id 对齐，不许各自编号（§5 三条守卫靠它机器执行）。

### 表 B：后端有、契约拿不到（投影缺口）——11 项，加 catalog kind / 字段即可

| # | 能力 | 参照 | 后端已有 | 缺的是 |
|---|---|---|---|---|
| B1 | 上下文用量 / 费用 / 缓存命中 | Reasonix `footer.go`（`contextUsed/contextWindow`、`≈$%.4f`） | `/cost` `/usage` `/stats` | schema `Usage` 只有 input/output tokens（`app-wire.schema.json` `Usage` 定义） |
| B2 | 模型 / Provider 列表 | Reasonix `modelpick.go`(145) | `/model` `/provider` | 无 catalog kind `models` |
| B3 | 技能清单 | Reasonix `skillpick.go`(260) | `/skills` + `SkillTool` | 无 catalog kind `skills` |
| B4 | MCP 服务器状态/认证 | Reasonix `mcppanel.go`(338) `mcpmanage.go`(341) | `/mcp` + `McpAuthTool` | 无 catalog kind `mcp` |
| B5 | 插件清单 | Claude Code `ManagePlugins` | `/plugin` `/reload-plugins` | 无 catalog kind `plugins` |
| B6 | cron / Jobs | Reasonix `queue_cmd.go`(191) | 4 个 Cron 工具（`CronCreate/List/Delete/Toggle`） | 无 catalog kind `jobs` |
| B7 | 任务 / 子代理清单 | Reasonix DeckChips + `todos.go`(99) | 6 个 Task 工具 + `/tasks` `/agents` `/subagents` | 无 catalog kind `tasks` |
| B8 | todo / plan 面板 | Reasonix `todos.go`(99) | `TodoWriteTool` + `EnterPlanModeTool` | 无 wire kind |
| B9 | 会话列表（多会话） | Reasonix `sessions.go`(248) | `list_session_snapshots` / `load_session_by_id`（`session_storage.py:139,202`）+ `/resume` `/tag` | `/history` 只给当前会话；无 catalog kind `sessions` |
| B10 | 分支 / worktree 状态 | Claude Code `branch` | `Enter/ExitWorktreeTool` + `/diff` `/branch` | 无 catalog kind `git` |
| B11 | 编辑审批的结构化 diff | Reasonix `diffview.go`(410) `diffformatter.go`(334) | `detail` 字符串：`+{added}/-{removed}` + 补丁正文 ≤4000 字符（`authority.py:194-195`、`wire.py:76-83`） | 无 `patch`/`added`/`removed` 结构字段 |

**表 B 落地状态（W-D1…W-D4）**：B1（usage 扩展）、B11（结构化 diff）、B2–B7、B9、B10（catalog kind）、B8（`todos` kind + 终端/web 清单卡）**均已落地**；仅 B12（缓存命中）仍为 nullable（引擎无统计）。

### 表 C：后端够用、纯终端没做——19 项（本计划主战场）

| 组 | 项 | 参照实现 |
|---|---|---|
| 渲染 | markdown 流式、语法高亮、diff 卡、CJK/emoji 宽度与截断、多行工具卡折叠、spinner/耗时、盒线与间距 | Reasonix `termrender/md.go`(512) `cells.go`(120) `box.go`(52) `toolcard.go`(155) `glyph_fit.go`(280)；DeepCode `markdown_stream.py`(162) `animation.py`(74) |
| 输入 | **回合中排队**、`@` 文件补全、多行粘贴保护、斜杠补全（fuzzy + 描述）、历史文件 | Reasonix `queue_slash.go`(188) `complete.go`(249) `pastekeep.go`(77)；DeepCode `input.py`(308) `picker.py`(240) |
| 覆盖层 | transcript 浏览 + 搜索、会话切换、模型/effort/权限 picker | Claude Code transcript mode（`REPL.tsx:4530-4543`）；Reasonix `transcript.go`(610) `sessions.go`(248) `modelpick.go`(145) `posture.go`(54) |
| 状态 | 状态栏（模型·上下文·费用·权限模式·分支）、`/help` 分组、doctor 渲染 | Reasonix `footer.go`(339) `chrome.go`(186) `help.go`(79) `status_cmd.go`(101) |
| 主题 | `/theme` 真正作用于终端 | 引擎 `themes` 包已有（[APPEARANCE.md](../architecture/APPEARANCE.md)）；终端当前写死 ANSI |

### 表 D：登记不做（已判死或无后端）

| 项 | 理由 |
|---|---|
| vim 模式（Reasonix `vimode.go` 273 行） | **范围裁剪，不是判死**：本轮优先级低于表 C 与波 E，故不做。注意原判死理由已失效——ADR-0005 末段已放行"将来的 vim 键位属于编辑器/前端实现"，且波 B 引入 prompt_toolkit 后行编辑器就已存在（原生 `EditingMode.VI`）。仍保留的硬红线：**不得在引擎 settings 层复活 `vim_mode`**（那才是 ADR-0005 §4 当年判死的东西） |
| 常驻 alt-screen 全屏 TUI（Reasonix `screen.go:401 v.AltScreen=true`） | 等于第二套 UI 宿主与状态投影；用户已裁"混合"而非常驻 |
| textual 系（crewAI / deer-flow / akashic / OpenHarness / autogen） | ADR-0005 已删 textual；回头等于推翻裁决 |
| codex 的 dashboard 面板族 | 依赖其 app-server 协议，本仓无对应后端 |

### 本轮顺带发现的两个缺陷（本计划同刀修）

| # | 缺陷 | 证据 | 修在哪 |
|---|---|---|---|
| F1 | `status_bar()` **零调用点**（声明了行为却不产生行为，同 ADR-0005 §4 的 vim 判例） | 定义于 `serve/terminal_theme.py:122-129`；全 `src/` 无调用 | 波 A 接进 `FooterVM`，并加守卫 `tests/ci/test_terminal_theme_usage.py` |
| F2 | 映射表与计划漂移："提交队列暂不暴露（引擎无队列）" | `docs/plan/mapping/questor-coding.md:37,72` vs 计划 02 §8「容量 1 排队已落地」 | 波 B 同刀订正该行 |

**F1 已修**（波 A）：`status_bar()` 现在由 `terminal/footer.py` 调用，并由
`tests/ci/test_terminal_theme_usage.py` 守住“任何公开图元零调用即红”；该守卫当场又发现并删除了
同样零调用的 `terminal_theme.empty_state()`（空态文案已迁到 `terminal/strings.py`，单真源）。

---

## 1. 基线（`57fb980`，2026-10-25 实测）

| # | 事实 | 值 | 采集方式 |
|---|---|---|---|
| B1 | 分支/工作区 | `feat/terminal-repl`，无 upstream，干净，领先 `origin/main`(857c297) 1 提交 | `git status` / `rev-list` |
| B2 | wire kind 数 | **13**：`turn_started` `text` `message` `tool_dispatch` `tool_result` `notice` `approval_request` `ask_request` `compaction_started/progress/done` `turn_done` `stream_reset` | 读 `protocol/app-wire.schema.json` |
| B3 | 端点集 | **8**：`POST /submit /cancel /approve /ask`；`GET /events /history /profile /commands` | `routes.py:127-142` |
| B4 | 终端客户端 | `hosts/terminal_client.py` **393 行**（计数命令见 §0-12）；渲染分支在 `_render`（:161-204）；审批/提问是裸 `input()`（:206-231） | 读文件 + `Select-String` 核验行号 |
| B5 | 主题层 | `hosts/serve/terminal_theme.py` **137 行 / 8 个 `def`**（turn_header、turn_footer、tool_line、approval_header、notice_bar、compaction_line、status_bar、empty_state）+ `BANNER` 常量 | 读文件 + 计数 |
| B6 | 回合中的输入 | **阻塞**：`await renderer.done.wait()`（`terminal_client.py:279-282`），排队槽没被用上 | 读文件 |
| B7 | 排队槽 | `authority.py`（240 行）`queue_depth=1`（:67），`begin()` 入队（:104-117），`pop_queued()`（:140-148） | 读文件 |
| B8 | 审批超时 | `prompt_timeout=300.0` 秒，超时 fail-closed（`authority.py:69,167-175`）；终端不显示倒计时 | 读文件 |
| B9 | 渲染依赖 | `rich` 已在；`prompt_toolkit` 由 `check_layout.py:93-96` 白名单**只放行 `terminal_client.py`** | 读守卫 |
| B10 | 文件行数预算 | 全局 R2：>1500 fail，1001–1500 ratchet（`check_layout.py:89-90`）；可按 `FILE_BUDGETS`/`DIR_BUDGETS` 收紧（:91-92） | 读守卫 |
| B11 | 导入者（门面不可破） | `hosts/app.py:10`、`hosts/serve/studio.py:18`、`api.py:13`、`tests/e2e/test_serve_host_engine.py:21,127`、两个单测文件 | `grep terminal_client` |
| B12 | 终端测试基线 | `tests/unit/bootstrap/hosts/test_terminal_client.py`(66) + `..._multi_turn.py`(53) + `serve/test_terminal_theme.py`(33) | 逐文件行数 |
| B13 | 引擎面 | 工具 39（`registry.py:35-75`）+ 条件 MCP 3；斜杠命令 62 内置 + 48 技能 | dump 注册表 |
| B14 | 形态门控 | `/profile` 返回 `ui.capabilities`（`routes.py:281-295`）；`coding` / `personal` 两 bundle | 读 routes + profiles |

---

## 2. 终态与模块边界

### 2.1 终态拓扑（只增一层，不加新宿主）

```text
引擎（QueryEngine / handle_line / 7 类 StreamEvent）
        │ 复用注入点（B11/B12/B13 of 计划 02）
serve 宿主（bootstrap/hosts/serve/：routes + authority + broadcaster + wire）
        │ 13 kind（只加不改）+ 8 端点 → 9（波 D 新增 `GET /catalog/{kind}`）
        ├── terminal_client.py（门面：公开符号不变）
        │        └── hosts/terminal/（本计划新建：渲染 / 输入 / 覆盖层）
        ├── apps/web（wave 4 已交付）
        └── apps/desktop（Electron 壳）
```

**关键不变量**：`hosts/terminal/` 是**同一 renderer 的另一种呈现**，不持有会话事实——
它只消费 wire 帧与 `/history` 快照，退出即忘；alt-screen 只做"看"，不成为第二个状态源。

### 2.2 包结构（**扁平单包**，不建子包）

```text
src/questorharness/bootstrap/hosts/terminal/
  __init__.py          # __all__ = [...]（AGENTS.md:83 强制）
  AGENTS.md            # 职责 / 不负责 两行（强制）
  unsupported.py       # 未实现徽标登记表（key = 表A 的 A1–A6，§5）
  wire_view.py         # 帧 → 视图模型（纯函数；13 kind 穷尽）——**波 A 第一天就要有**
  strings.py           # 全部中文文案（中文一等公民的落地形态，§0-9）
  width.py             # rich.cells 的薄封装：按宽截断/折行（不另立宽度表）
  markdown.py          # 流式 markdown（未闭合围栏/表格缓冲）
  cards.py             # 七种对话图元（只消费 terminal_theme，不自建色值）
  diff.py              # detail 文本 → gutter diff 卡
  footer.py            # FooterVM（字段全 optional，缺省渲染 —）+ status_bar()
  input_session.py     # prompt_toolkit 会话 + 裸 input 回退
  completer.py         # 斜杠（fuzzy+描述）/ @文件 / 路径
  paste.py             # 多行粘贴保护；图片粘贴 → A5 徽标
  keymap.py            # 键位（读 keybindings 包）
  overlay.py           # alt-screen：transcript 浏览 + 搜索 + picker 宿主（唯一 owner）
  app.py               # 会话循环、turn 状态机、队列调度、唯一写终端通道（§2.4）
```

**为什么扁平**：每多一层子包就多一套 `AGENTS.md` + `CODEOWNERS` 规则 + `.importlinter` 条目（`AGENTS.md:83`），
而职责边界用文件边界足够表达；行数上限由 R2 与 `FILE_BUDGETS` 守住（单文件目标 ≤400 行）。

**顺序约束（Rev2 修正）**：`wire_view.py` **先于** `cards.py`。任何卡片只能接受视图模型，不得接受 raw frame；
否则波 B 引入 wire_view 时会把波 A 的卡片签名全部推翻。

### 2.3 必须同刀登记的受控改动

| 改动 | 位置 | 说明 |
|---|---|---|
| 新开包四件套 | `terminal/` | 目录 + 带 `__all__` 的 `__init__.py` + 包 `AGENTS.md` + `CODEOWNERS` 规则 + `AGENTS.md` 路由表加行（:48-72，现行 `:69` 那行改为指向本包）+ `--refresh-baseline --reason "plan03 波A: terminal 包"` |
| prompt_toolkit 白名单扩展 | `scripts/guards/check_layout.py:93-96` | 从单文件放行改为 `terminal/` 前缀 + `terminal_client.py` 两者；**同刀保判红**：未登记文件 import prompt_toolkit 仍必须红 |
| 门面保留 | `hosts/terminal_client.py` | `run_terminal_repl` / `run_terminal_client` / `build_serve_host` / `merge_tool_overrides` / `default_profile_root` / `completion_catalog` / `_frame_from_sse` 全部保名（B11 的导入者在用）；实现迁入 `terminal/` 后此处只 re-export |
| 映射表（终端） | `docs/plan/mapping/terminal-coding.md` | **F2 的根治**（A1 已落）：新建终端专用映射表，列 = `id` / `功能` / `status(ready\|declared\|absent)` / `终端载体` / `来源`；`unsupported.py` 的 key 集合必须等于 `status=absent` 的行集合，双向断言见 `tests/ci/test_unsupported_badges.py`。**偏离登记**：原计划写“给 `questor-coding.md` 加两列”，实际改为新建终端表——web 的功能行与终端的载体行不是同一张表，混在一起会让两边都漂 |
| 新增 catalog 路由 | `serve/routes.py` + `serve/catalog/` | 波 D：`GET /catalog/{kind}` → 一个 provider 注册表（每 kind 一个纯函数）；**响应 schema 不得进 `ServerFrame` 联合**（否则触发 `cardSlots` 全等守卫，§2.3 末行） |
| `apps/web` 同步（唯一例外） | `apps/web/src/app/cardSlots.ts` + `generated/` | 仅当新增 wire kind 时：补一条槽位 + 重生生成物；**不得改页面/交互**。`test_card_slots_cover_every_schema_kind` 会强制 |
| 形态门控 | 全终端代码 | 面板/命令可见性一律由 `GET /profile` 的 `ui.capabilities` 决定；**禁止硬编码 `profile_id="coding"`**（现 `terminal_client.py:319` 就是硬编码，波 A 同刀改为参数默认取 bundle 的 `is_default`）；`rg "coding" terminal/` 必须归零 |
| 基线重录 | `TREE.md` / `GRAPH.md` / `NAMESPACES.md` / `structure.json` | 每波末同刀 `--refresh-baseline --reason`，禁手改 |

### 2.4 输入/输出并发契约（Rev2 新增：**本计划最高技术风险**）

四个参照在这一维度**都不可平移**：DeepCode 是行式模型（`cli/tui/app.py:1075-1096`：`_run_line` 建 task → `_route_sigint_to` → `await task` 到底，读行要等回合结束），
它的 `patch_stdout(raw=True)` 只包住 `prompt_async` 那一小段（`cli/tui/input.py:300-302`）；Reasonix/Claude Code/codex 分别是 bubbletea / Ink / ratatui，重绘与输入抢占语义不同。
所以波 B **不能靠“照 DeepCode 写”**，必须先定死三件事：

1. **唯一写终端通道**：除 `input_session` 与 `overlay` 外，**任何渲染不得直接 `console.print`**，必须经 `app` 的单一出口
guard（`patch_stdout` 或 `get_app().run_in_terminal`）。判红：出现绕过出口的 `print`/`Console.print` 调用点。
2. **alt-screen 归属**：`overlay.py` 是 **唯一 owner**，用 prompt_toolkit `Application(full_screen=True)`（原生 alt-screen）；
**禁止** rich `Live` + 手写 escape 序列。进/出覆盖层必须走同一对 `enter/exit` 函数，且退出后 scrollback 完好（波 C 判红）。
3. **审批/提问时序**：现在是裸 `input()`（`terminal_client.py:215,226`），改卡片式后与会话抢 TTY。固定为
**暂停会话（suspend）→ 内联表单（允许后台帧继续缓冲，但不写屏）→ 恢复会话并回灌缓冲**。
判红：审批期间后台帧直接铺到屏上（撕屏）。

**前置 spike（波 B 开工前必做，不绿不进波 B）**：≤20 行脚本，串一个 prompt_toolkit 会话，验五件事：
①prompt 活跃时推一条流式文本；②prompt 活跃时弹审批；③回合中 Ctrl-C；④多行粘贴；⑤窗口 resize。
五件事任一不通过 → 回 §9 上报并选备选方案（`Application(full_screen=False)` 自绘底栏 vs `run_in_terminal`）。

---

## 3. 复用矩阵（波级检索结论；每刀开工前仍须按 §0-8 复检）

| 层 | 目标图元/机制 | 参照（file:line 已实测） | 复用方式 | 许可 |
|---|---|---|---|---|
| 宽度 | CJK/emoji 宽度、截断、折行 | **rich 15.0.0 已内置**：`rich.cells.cell_len/set_cell_size`（实测 中文=7、emoji=2、组合=1）；Reasonix `glyph_fit.go`(280) 只取“折行策略”不取宽度表 | **薄封装**：`width.py` 只做截断/折行/控制字符过滤，**禁止第二张宽度表**；判红：同一字符串上 `width.py.cell_len` 必须等于 `rich.cells.cell_len` | 本仓依赖 + MIT（只取策略） |
| Markdown | 流式块切分、未闭合围栏缓冲、表格/列表、代码块高亮 | Reasonix `termrender/md.go`(512)；DeepCode `cli/tui/markdown_stream.py`(162) + `test_tui_markdown_stream.py`(189)（验收口径） | 翻译块状态机；渲染落到 `rich.Markdown`/`rich.Syntax` | MIT |
| Diff | gutter 行、hunk、上下文折叠、截断提示 | Reasonix `termrender/diffformatter.go`(334)、`diffview.go`(410)、`difffence.go`(452) | 翻译行模型；样式取 terminal_theme | MIT |
| 卡片 | 七种图元的标题行/状态图标/缩进/间距 | 本仓 `serve/terminal_theme.py`（已是 Reasonix 投影）+ Reasonix `termrender/toolcard.go`(155)、`tui/render.go`(423) | 复用现有函数，补多行与折叠 | 本仓 + MIT |
| 状态栏 | 模型·上下文%·费用·权限模式·分支·耗时 | Reasonix `tui/footer.go`(339)、`chrome.go`(186) | 翻译字段集；**FooterVM 字段全 optional**（缺数据渲染 `—`），波 D 只填字段不重录快照 | MIT |
| 回合/事件循环 | turn 生命周期、状态机、命令分发边界 | DeepCode `cli/tui/app.py`(1233)、`domain_events.py`(65)、`thread_client.py`(514) | **结构对照**（六职责拆分），逻辑按本仓 13 kind 重写 | MIT |
| 输入层 | prompt_toolkit 会话、补全、粘贴、`Ctrl-C` 语义 | DeepCode `cli/tui/input.py`(308)、`picker.py`(240)；Reasonix `tui/input.go`(433)、`complete.go`(249)、`pastekeep.go`(77)、`clippaste.go`(96) | 翻译；**输入并发不参照任何一家（§2.4）** | MIT |
| 队列 | pending 行、队列可视化、`turn_done` 后推进 | Reasonix `tui/queue_slash.go`(188)、`queue_cmd.go`(191)；本仓 `authority.py:104-117,140-148` | 语义翻译 + 复用本仓 authority | MIT |
| 覆盖层 | transcript 浏览/搜索、键盘语义、退出后 scrollback 完好 | Claude Code `src/screens/REPL.tsx:4538-4543`（仅 `transcriptScrollRef` 时进 alt-screen）、`src/utils/staticRender.tsx:8`；Reasonix `tui/transcript.go`(610) | **只读语法**（键位与交互语义），实现自写 | Claude Code **专有** |
| 面板 | 模型/技能/MCP/会话 picker 的布局与键位 | Reasonix `modelpick.go`(145)、`skillpick.go`(260)、`mcppanel.go`(338)、`mcpmanage.go`(341)、`sessions.go`(248)、`posture.go`(54)、`help.go`(79) | 布局翻译（波 E） | MIT |
| 测试范式 | 顺序/响应性/韧性/输入安全四类用例 | `../DeepCode-main/tests/test_tui_transcript_order.py`(154)、`test_tui_responsiveness.py`(112)、`test_tui_resilience.py`(382)、`test_tui_input_safety.py`(186) | 用例分类照搬，断言自写 | MIT |
| alt-screen 开关 | 用户可配进/不进全屏 | codex `codex-rs/tui/src/tui/alternate_screen.rs` + `AltScreenMode::Always/Never/Auto` | 只取形（配置位思路） | Apache-2.0 |

**未在四参照找到、需要新造的图元**：0 项（本表覆盖 §0.5 表 C 全部 19 行）。若实现时发现新造项，
按 §0-9 登记"为何四者皆无"并**先让用户过目**。

---

## 4. 波次

> 每波开工前：§1 复核 → §3 复检（本波每个图元逐个检索）→ 本刀条目清单 → 红测试 → 实现 → 三张对账表。

### 波 A：渲染内核（无契约变更）

**新建（按此顺序）**：`wire_view.py`（**第一刀**：帧→VM，先只覆盖 6 个 kind 也可，但必须存在）→ `strings.py` →
`width.py`（rich.cells 薄封装）→ `markdown.py` → `cards.py` → `diff.py` → `footer.py`（FooterVM）→ `unsupported.py`（A1/A2/A3/A5/A6 五行）。
**动作**：`app.py` 接线，`terminal_client._render` 改为调 `wire_view` + `cards`；`status_bar()` 接进 `FooterVM`（修 **F1**）；
主题色改从 `themes` 包读（`/theme` 生效，无新端点）；`profile_id` 不再硬编码（§2.3 形态门控）。

**验收绿**：①宽度用例（中文/全角标点/emoji ZWJ/组合字符/Tab/控制字符/宽于终端）+ **与 `rich.cells.cell_len` 的一致性用例**；
②流式 markdown 快照（含未闭合 ``` 与半行表格）；③diff 用例（新增/删除/hunk/超 4000 截断提示）；
④七种对话图元 + 横幅/空态/状态栏快照（**快照 Console 参数钉死**：`width=`, `color_system=None`, `legacy_windows=False`,
`safe_box=True`, `emoji=False`；**结构断言（span 与 cell 宽）优先，全字面快照只用于纯 ASCII 图元**）；
⑤`status_bar` 有调用点且 FooterVM 缺字段渲染 `—`；⑥`/theme` 切换后图元色变化；⑦`strings.py` 之外的硬编码中文为 0。
**验收红**：①`width.py` 换成 `len()` → CJK 用例红；②`width.py` 另立宽度表 → 一致性用例红；③未闭合围栏不缓冲 → 快照红；
④`terminal_theme` 任一公开函数零调用 → `test_terminal_theme_usage.py` 红；⑤自造色值（非 terminal_theme 常量）→ 样式守卫红；
⑥卡片直接接受 raw frame（未经 `wire_view`）→ 红；⑦单卡渲染抛异常杀死 SSE 消费循环 → 红（必须降级卡 + notice，循环继续）。

### 波 B：交互骨架（无契约变更）

**前置**：§2.4 的 **spike 五件事必须全绿**；否则停，走 §9 裁决备选方案。
**新建**：`app.py`（状态机 + 唯一写终端出口）、`input_session.py`、`completer.py`、`paste.py`、`keymap.py`。
**动作**：回合中可输入 → `/submit` 返回 `queued` 时渲染 pending 行，`turn_done` 后自动推进（复用 `authority.py` 槽）；
审批/提问改卡片式（两档 + 300 秒倒计时，超时 fail-closed 要显式告知）；未知 kind 走 `unsupported` 表而不是崩溃；
订正 **F2**（映射表加 `id`/`status` 列 + 队列行改“有载体”）；落地 **Ctrl-C 四语义表**（下表）。

| 位置 | Ctrl-C 语义 | 判红 |
|---|---|---|
| 输入框 | 清当前行，不退出 | 变成退出 → 红 |
| 回合中 | `POST /cancel` → `turn_done{cancelled}` | 变成退出整个 REPL → 红 |
| 覆盖层内 | 关覆盖层，回 scrollback | 杀进程 → 红 |
| 审批中 | 视为 deny（fail-closed） | 静默挂起到超时 → 红 |

**验收绿**：①**队列判绿**：回合中连发两条 → 第二条 `{state:"queued",position:1}`，第一条 `turn_done` 后第二条自动 `turn_started`，
事件顺序断言；②未知 kind 判绿（出现在 `unsupported` 徽标里，不进异常路径）；③补全用例（斜杠描述、`@` 文件、路径、模糊前缀）；
④多行粘贴不重复执行；⑤无 TTY → 裸 `input()` 回退仍可用；⑥审批超时显示倒计时并在 300s 后 deny；⑦Ctrl-C 四语义各一条用例。
**验收红**：①回合中丢弃输入 → 红；②未知 kind 静默吞掉 → 红；③回退路径被删 → 红；④审批默认改成 approve → 红（fail-closed 反转）；
⑤出现绕过单一出口的 `print` → 红；⑥审批期间后台帧直接铺屏（撕屏）→ 红。

### 波 C：覆盖层（无契约变更）

**新建**：`overlay.py`（transcript 浏览 + 搜索 + `/help` 分组面板）。
**动作**：只有"看"的动作进 alt-screen（对齐 Claude Code `REPL.tsx:4538-4543` 的条件式进入）；退出后 scrollback 内容完好；
搜索用 `/history` + 已收帧构建的本地视图，不新写存储。

**验收绿**：①进/出覆盖层后，scrollback 行数与内容不变（`Console(file=StringIO)` + 注入终端尺寸断言）；
②搜索用例（命中/无命中/`n`/`N` 跳转）；③`/help` 按 16 命令族分组且与 `/commands` 数据一致（禁止硬编码清单）；
④窗口宽度 60/100/160 三档布局不溢出。
**验收红**：①退出覆盖层清空 scrollback → 红；②`/help` 硬编码命令清单（与 `/commands` 漂移）→ 红；③覆盖层持有会话事实（出现第二份 messages 真源）→ 红。

### 波 D：契约扩张（**需 §9 裁决后开工**）

**设计修正（Rev2）**：原计划的 8 个同构 GET 端点已**合并为 1 个 catalog 路由**——它们是同一形状
（`GET → 读一个内部注册表 → JSON`），逐个建端点会让未来每加一个面板都重付一次五步仪式。

```text
GET /catalog/{kind}   kind ∈ sessions | models | skills | mcp | plugins | jobs | tasks | git
        ↓
serve/catalog/providers.py   # 每 kind 一个纯函数（读现有注册表，不新写存储）
```

**四条硬约束**：①响应 schema 放 `$defs` 的独立 `CatalogResponse` oneOf，**绝不进 `ServerFrame` 联合**（否则触发 `cardSlots`
全等守卫）；②未知 kind → 404 + refusal code，**不得返回空数组装成功**；③新增 kind = 加一个 provider 纯函数 + schema 加一分支（additive）；
④既有 `/commands` `/profile` `/history` **不动不迁**（迁移是 breaking change）。

**每刀固定五步**：schema 加字段/分支（只加不改）→ `gen_wire_py --check` + `gen_wire_ts --check` →
`test_kind_coverage` + **新增 `test_catalog_coverage`**（schema 的 catalog kind 集合 == provider 注册表键集合，含自证）→
扇出表加**一行** → 映射表 `absent→ready`。

| 序 | 扩什么 | 对应缺口 | 判红 |
|---|---|---|---|
| W-D1 | `Usage` 扩 `cost` / `contextWindow` / `contextUsed` / `cachedTokens` | B1 | 字段扩了但生成物未重生成 → 红 |
| W-D2 | `approval_request` 扩 `patch`/`added`/`removed`（结构化 diff） | B11 | 只塞进 `detail` 字符串 → 红（结构字段缺失） |
| W-D3 | `GET /catalog/{kind}` + 8 个 provider（sessions/models/skills/mcp/plugins/jobs/tasks/git） | B2–B7、B9、B10 | 未知 kind 返回 200 空数组 → 红；catalog 响应混进 `ServerFrame` → 红 |
| W-D4 | （**待裁决**）新增 `todos` kind | B8 | 新 kind 未进 `cardSlots` + 生成物 → 红；**一旦做，必须同刀改 `apps/web` 一处**（§2.3） |

**为什么把 8 个端点收成 1 个路由**：扇出表从 8 条降为 1 条，§7-5 的停工判据从“每端点”降为“每 kind”，
测试从 8 组端点测变成 1 组路由测 + N 个纯函数单测（纯函数最好测、也最容易被真数据回放钉住）。
现在多花一天设计 catalog，省掉未来每个面板的五步仪式。

### 波 E：面板接线（波 D 之后）

**范围（Rev2 收敛，待 §9-7 裁决）**：

- **E0（本轮）**：模型 picker + 会话 picker——终端日常最常用的两个。
- **后置池**：技能 / MCP / 任务 / cron / git 面板。理由：这五个的边际价值低于
  “并发输入稳定性 / Ctrl-C 语义 / 多行粘贴 / 窄窗降级”这些已写在波 B/C 验收里的硬骨头；
  真用两周后再按需接，不砍功能、只调投资顺序。

**动作**：把 catalog 端点接到 `overlay.py` 的 picker，每面板一刀。
**验收绿**：每面板真数据驱动（端点回放 + 一次真跑），布局对齐 §3 登记的 Reasonix 对应文件，窄窗有降级位。
**验收红**：面板用假数据/stub 撑门面 → 红；面板绕过端点直读引擎内部 → 红（复用红线）。

---

## 5. 未实现徽标（占位规则，替代"注释掉代码"）

**规则**：后端没有的能力**不注释、不隐藏、不静默**，而是在对应位置渲染一枚徽标：
`⊘ 未实现 · <ID> <名词>`，`<ID>` 必须出现在 `terminal/unsupported.py` 的登记表里。

**两个真源，用 id 对齐（Rev2 修正）**：`unsupported.py` 是**渲染侧**真源（终端渲染什么徽标）；
`docs/plan/mapping/questor-*.md` 是**产品契约**真源（用户可见功能有没有载体）。两张表用同一个 id（A1–A6），
靠双向断言保持不漂。原版写“唯一真源”与守卫 #1 自相矛盾（映射表当时是散文式表格，根本解析不了）。

```python
# terminal/unsupported.py —— 渲染侧真源；key 与表A / 映射表 id 三者相等
UNSUPPORTED: dict[str, str] = {
    "A1": "审批第三档（缺三态 PermissionPrompt；runtime.py:55 为 bool）",
    "A2": "Ask 选项/多选（引擎回调只收自由文本；ask_user_question_tool.py:12）",
    "A3": "回合中插话（无 /steer 端点；authority 只有 1 槽）",
    "A5": "图片/附件提交（/submit 无 attachments 字段）",
    "A6": "语音采集（/voice 仅为设置开关）",
}
```

**前置（波 A1 已落）**：终端映射表 `docs/plan/mapping/terminal-coding.md` 自带 `id` / `status` 两列，
`unsupported.py` 与它做双向断言（见 §2.3 的偏离登记）。原版“给 `questor-coding.md` 加两列”已改为
新建终端表：web 的功能行与终端的载体行不同源，混表必漂。

**守卫** `tests/ci/test_unsupported_badges.py`（三条判红，#1 已在 A1 落地；#2/#3 随渲染代码在 A5 起补齐）：
1. **双向对齐**（已落）：`set(UNSUPPORTED)` == 映射表中 `status = absent` 的行集合
   （左边多 = 穷渲染；右边多 = 真功能黑洞）；`declared` 行不挂徽标（如 A4 部分可用）；
2. **徽标必须登记**：AST 扫描终端包，出现的 `⊘ 未实现` 字面量必须带 `UNSUPPORTED` 里的 id（随手写“未实现”字符串即红）；
3. **落地即注销**：某 id 对应能力在波 D/E 落地（映射表转 `ready`）后，`UNSUPPORTED` 里残留该 id → 红。

---

## 6. 每刀纪律（沿用计划 01/02）

- 行为变更先红用例；渲染变更用**金标快照**（固定终端宽/色深），模型可见面变更看 prompt-surface 同款思路。
- **快照参数必须钉死**（Rev2）：`Console(width=80, color_system=None, legacy_windows=False, safe_box=True, emoji=False)`；
  **结构断言（`Text` span / cell 宽）优先**，全字面快照只用于纯 ASCII 图元——本仓已踩过“rich 快照在 Windows 与 Linux 必然不同”的坑。
- **单一写终端出口**（§2.4）：除 `input_session` / `overlay` 外不得直接 `Console.print`。
- **文案集中**：所有中文进 `terminal/strings.py`，终端包其他地方出现中文字面量 → 红。
- **图元归属**：新图元先加进 `serve/terminal_theme.py`（后续可迁 `themes/`），`terminal/` 只消费；
  否则视觉真源会被终端包蚕食，`/theme` 也会失控。
- 每刀开工前在 PR 里列**条目清单**（逐条可勾选）；收刀按 §0.5-6 交**三张对账表**（条目 / 影响面 / 判红），清单条目不得合并省略。
- 每刀末同刀完成 `TREE`/`GRAPH`/`NAMESPACES`/`--refresh-baseline --reason "plan03 波X: ..."`；结构红线（行数/扇出/门面零逻辑）照常。
- 每波跑 `uv run python scripts/check.py` 全绿；**只跑单文件测试就报绿 = 违规**。
- Windows 专项：`PYTHONIOENCODING=utf-8` 固定；`cp936`/`cp1252` 宿主下中文与盒线必须不崩（参照本仓既有 UTF-8 锁定纪律）。

---

## 7. 停工症状（出现即停）

1. 想为"好看"自造色值/图标/间距 → 停，回 §3 找来源；四者皆无 → 先让用户过目。
2. 想把 `terminal/` 做成第二套状态源（缓存 messages 真源、自己维护会话事实）→ 停，回 §2.1 不变量。
3. 想绕过 `/history` 自己读会话文件、或绕过 `session_storage` 自写存储 → 停（复用红线）。
4. 想注释掉后端不支持的功能、或用 stub 糊上去 → 停，改走 §5 徽标。
5. 调用扇出表外的端点致 404 → 停，先补表再实现。
6. 想改既有 kind/字段名 → 停，回 ADR-0006 补变更记录并经用户批准。
7. `prompt_toolkit` 出现在 `terminal/` 与 `terminal_client.py` 之外 → 停（白名单守卫必须红）。
8. 覆盖层退出后 scrollback 不完整（丢行/错位） → 停，这是"混合模型"的底线。
9. 以"文件太长/工作量大"为由只读一半、只写一半或低于计划预期 → 停，按 §9 上报，不得自行降配。
10. 缺三张对账表就宣布某波完成 → 未完成。
11. 硬编码 `profile_id="coding"`、或在终端包写形态判断（`if mode == …`）→ 停，回 §2.3 形态门控。
12. 把 catalog 响应 schema 塞进 `ServerFrame` 联合，或为了让 tsc 过而删 `cardSlots` 的全等断言 → 停（§2.3）。
13. `width.py` 里另立宽度表 → 停（与 `rich.cells` 双真源，§3 宽度行）。
14. §2.4 的 spike 五件事没全绿就开写波 B → 停。

---

## 8. 总验收表（每波回填）

| 波 | 分支 | 绿验收 commit | 红验收 commit | 备注 |
|---|---|---|---|---|
| A 渲染内核 | `feat/terminal-repl` | 5b635d6 / 9f0e436 / 210b482 / c4b926e / 21b8f87 / 80d9dcc | 同一批（每条先跑失败再实现） | `wire_view` 13 kind 穷尽；width 与 `rich.cells` 一致性判红；markdown 块状态机；七图元 + diff 卡 + FooterVM；F1 接活并上探针守卫 |
| B 交互骨架 | `feat/terminal-repl` | 9eca9bb / 07ef8ba / 本刀 | 队列、未知 kind、回退、fail-closed、绕过出口各一条 | §2.4 改为“可测的守卫”而非 TTY spike：`_output_channel()` 必须带 `raw=True` 进入 `patch_stdout`，非 TTY 不包裹（无头环境跑不了真 TTY，记为偏离） |
| C 覆盖层 | `feat/terminal-repl` | bdd89e8 | 游标越界/空表/只读面板误发命令均判红 | 面板状态机 + alt-screen owner（`Application(full_screen=True)`）+ 非 TTY 编号回退；`:transcript` 走 `/history` |
| D 契约扩张 | `feat/terminal-repl`（**偏离**：未切 `feat/terminal-contract`） | be5ee5e（W-D1/2）/ 11112d8（W-D3 catalog）/ ad0b5bb（W-D4 todos） | `test_catalog_coverage` 双向 + `CatalogResponse` 不得进 `ServerFrame` | 8 个 catalog kind（含 `plugins`）与 `todos` kind 全部落地；`cachedTokens` 仍 nullable（引擎无统计，已登记 `declared`） |
| E 面板接线 | `feat/terminal-repl` | 11112d8 / bdd89e8 / 7f93ff2 | stub 数据 / 绕过端点直读引擎 → 红 | 8 个 catalog kind + transcript + 命令面板全部接真数据；`:help` 按族分组因 `SlashCommand` 无 `family` 字段登记为 `declared` |
| （结构）入包 | `feat/terminal-repl` | 3c77fbd | 入包后旧导入方仍绿（门面保留全部公开名） | `app.py` / `renderer.py` / `keymap.py` 入包，门面降为 170 行装配 |

**填写规则**：三张对账表齐备才可填；任一表缺失视为该波未完成。

---

## 9. 已决与开放问题

**已决（2026-10-25 用户裁决）**

- 渲染模型 = **混合**：scrollback 主线 + alt-screen 仅覆盖层。
- 功能面 = **全表覆盖**；缺失项**显式占位**，不注释代码。
- 参照分工：语法 = Claude Code（只读）、骨架/测试 = DeepCode、语汇/tokens/CJK = Reasonix、面板形 = codex。
- 不复用：Reasonix 的 Go 服务端实现、codex dashboard、textual 全家。
- **Rev2（评审后）已采纳的架构修正**：①8 个只读端点 → 1 个 `GET /catalog/{kind}` + provider 注册表；
  ②新增 §2.4 并发契约（最高风险，波 B 前置 spike）；③`wire_view` 与 `FooterVM` 前置到波 A；
  ④宽度改为 `rich.cells` 薄封装；⑤映射表加 `id`/`status` 列 + 双向断言；⑥vim 从“判死”改为“范围裁剪”；
  ⑦`apps/web` 条款改为“仅同步 cardSlots + 生成物”；⑧编号去重（F/W-D）；⑨`strings.py` + 渲染异常不吞 + Ctrl-C 四语义表 + 快照参数；
  ⑩计数与行号口径写进 §0-12。

**开放（执行 agent 不得代答）**

1. **A1/A2/A3 是否改引擎契约**（三态审批 / Ask options / steer）——不改则永久挂徽标，改则要动 `runtime.py:55,57` 与工具契约，属"经同意不限规模"。
2. **波 D 契约扩张授权**：1 个新路由（`GET /catalog/{kind}`，8 个 kind）+ 2 处字段扩展（usage / approval patch），是否按"只加不改 + 双侧 codegen"直接推进。
3. **三处"暂不暴露"是否翻转**：`autopilot`、`coordinator`、`steer`（`questor-coding.md:37,54,57,72`）。
4. **`/voice` 采集是否排期**（默认不做，只在 UI 标 A6）。
5. **终端 UI 语言**：中文文案 + 英文标识符（本计划默认）；若要全英文需否决。
6. **`feat/terminal-contract` 分支是否现在就切**（波 D 之前不动）。
7. **波 E 是否收敛为 E0（模型 + 会话 picker）**，其余五面板进后置池。评审建议收敛；
   但**这会改你上一轮"全表覆盖"的裁决**，所以列为待裁而不是默默改（不砍功能，只调投资顺序）。
8. **`todos` kind 本轮做不做（W-D4）**：做则必须同刀改 `apps/web/src/app/cardSlots.ts` 一处 + 重生生成物。
   建议：本轮不做，B8 挂徽标；等 E0 上线后按真实使用决定。
9. **catalog 的 kind 扩展协议**：新 kind 是“加 provider 函数 + schema 加分支”还是“必须同步登记在映射表”
   （建议两者都要，由 `test_catalog_coverage` 双向锁住）。

---

## 10. 非目标

- 不做常驻 alt-screen 全屏 TUI（用户已裁混合）。
- 不做 vim 模式（**范围裁剪**，非判死；见 §0.5 表 D 与 ADR-0005 末段）；但**不在引擎 settings 层复活 `vim_mode`**。
- 不引入 textual；不引入第二套状态投影。
- 不复制带许可标记的外部代码入 `src/`（CONVENTIONS §4.5）；Claude Code 专有，只读语法。
- 不改 `apps/web` 的页面与交互；**唯一例外**是新增 wire kind 时同步 `cardSlots.ts` 一条槽位 + 重生生成物（§2.3）。
- 不动引擎对标功能路线（P0–P5）；不动 `apps/desktop`。
- 不做 Go 单二进制分发；不做 WebSocket（ADR-0006 已弃）。
- 不为终端新增独立的会话存储或第二份 messages 真源。
- **不把 8 个只读面板拆成 8 个端点**（catalog 一弧解决，§4 波 D）。

---

## 参考地图（行号/行数均本机实测；复用前按 §0-8 复检）

### Claude Code（专有许可：**只读语法，不搬代码**）

| 先例 | 位置 | 借什么 |
|---|---|---|
| scrollback 主线 + 条件式 alt-screen | `src/screens/REPL.tsx:4538-4543`（仅 `transcriptScrollRef` 时包 `<AlternateScreen>`） | 混合模型的判据 |
| Ink 单 `<Static>` 限制的绕过 | `src/utils/staticRender.tsx:8` | scrollback 追加式渲染思路 |
| transcript 全屏模式的搜索徽标 | `REPL.tsx:4520`（`TranscriptModeFooter` + `searchBadge`） | 搜索 UX |
| 键位/命令规模 | `src/commands/*`（100+ 命令） | 只读对照，不实现同名全集 |

### DeepCode（MIT：骨架与测试范式）

| 先例 | 位置 | 借什么 |
|---|---|---|
| 六职责拆分 + 事件流只读引擎 | `cli/tui/app.py`(1233)、`renderer.py`(847)、`commands.py`(813)、`input.py`(308)、`picker.py`(240)、`theme.py`(173) | 模块边界与文件粒度 |
| 流式 markdown | `cli/tui/markdown_stream.py`(162) + `../DeepCode-main/tests/test_tui_markdown_stream.py`(189) | 缓冲策略 + 验收口径 |
| 动画/耗时 | `cli/tui/animation.py`(74) | spinner 形态 |
| TUI 测试四类 | `test_tui_transcript_order.py`(154) / `test_tui_responsiveness.py`(112) / `test_tui_resilience.py`(382) / `test_tui_input_safety.py`(186) | 判红用例分类 |
| **输入并发（反面样本，勿照抄）** | `cli/tui/app.py:1075-1096`（`_run_line`：建 task → `_route_sigint_to` → `await task` 到底）；`cli/tui/input.py:300-302`（`patch_stdout(raw=True)` 只包 `prompt_async`） | **行式模型**：回合中读不了输入；不能当并发参照（§2.4） |
| 许可 | `LICENSE`（MIT, Copyright 2025 Data Intelligence Lab@HKU） | 入仓不带标记 |

### Reasonix（MIT：语汇 / tokens / CJK / 面板形）

| 先例 | 位置 | 借什么 |
|---|---|---|
| transcript 行模型 | `internal/frontend/tui/transcript.go`(610)，`ItemKind` :12-33（User/Say/Tool/Approval/Ask/Notice/Compaction/Receipt/Worked/Usage） | 与 13 kind 的对应关系 |
| 常驻全屏（**不抄**） | `tui/screen.go:401` `v.AltScreen = true` | 反面样本 |
| 状态栏字段集 | `tui/footer.go`(339)、`chrome.go`(186) | model/contextUsed/contextWindow/cost/权限模式/goal |
| 队列 / 插话 | `tui/queue_slash.go`(188)、`queue_cmd.go`(191) | pending 行与推进时机 |
| 补全 / 粘贴 | `tui/complete.go`(249)、`pastekeep.go`(77)、`clippaste.go`(96) | 斜杠与多行/图片 |
| 宽度与格子 | `termrender/cells.go`(120)、`tui/glyph_fit.go`(280)+`glyph_fit_windows.go`(74) | CJK/emoji/Windows 字体差异 |
| 渲染原语 | `termrender/md.go`(512)、`diffformatter.go`(334)、`diffview.go`(410)、`box.go`(52)、`toolcard.go`(155)、`theme.go`(378) | markdown/diff/盒线/工具卡 |
| 面板 | `tui/modelpick.go`(145)、`skillpick.go`(260)、`mcppanel.go`(338)、`mcpmanage.go`(341)、`sessions.go`(248)、`posture.go`(54)、`help.go`(79)、`todos.go`(99) | 面板布局与键位 |
| 测试密度 | `program_test.go`(889)、`screen_test.go`(580)、`keymap_parity_test.go`(368) | 体量与守卫强度参照 |
| 许可 | `LICENSE`（MIT, Copyright 2026 Reasonix Contributors） | 入仓不带标记 |

### codex（Apache-2.0：只取形）

| 先例 | 位置 | 借什么 |
|---|---|---|
| alt-screen 可配 | `codex-rs/tui/src/tui/alternate_screen.rs`、`AltScreenMode::Always/Never/Auto` | 配置位思路 |

### 本仓既有资产（复用红线，先看这些再谈新写）

| 资产 | 位置 | 用法 |
|---|---|---|
| 13 kind 帧编码 | `bootstrap/hosts/serve/wire.py`（`WireEncoder` :126） | 终端只消费，不改语义 |
| 租约/排队/提示 Future | `serve/authority.py`（`begin` :98、`pop_queued` :140、`permission_prompt` :167、`ask_user_prompt` :177、`edit_approval_prompt` :188） | 队列与审批直接复用，不新写 |
| 会话存储 | `platform/session_storage.py`（`list_session_snapshots` :139、`load_session_by_id` :202、`export_session_markdown` :218） | 波 D 的 catalog `sessions` provider 直调 |
| 斜杠注册表 | `commands/registry.py` + `families/*`（62 内置） | 命令语义零重写，终端只做呈现与补全 |
| 主题真源 | `serve/terminal_theme.py`（**8 个 `def`** + `BANNER`） | 波 A 的唯一色源；**F1** 缺陷在本计划修 |
| 结构守卫 | `scripts/guards/check_layout.py`（R2 行数 :89-90；prompt_toolkit 白名单 :93-96） | §2.3 的受控改动按此登记 |
| kind 全等守卫 | `tests/ci/test_kind_coverage.py`（`test_card_slots_cover_every_schema_kind`） | 任何新 kind 都强制同步 `apps/web/src/app/cardSlots.ts` |

---

## 附录 A：Rev2 修订记录（评审 10 条逐条裁决）

| 序 | 评审意见 | 裁决 | 落点 |
|---|---|---|---|
| 1 | 8 个同构 GET 端点应合并为 catalog | **采纳 + 加硬约束** | §4 波 D（`/catalog/{kind}` + provider 注册表）；额外加“catalog 响应不得进 `ServerFrame`”，否则触发 cardSlots 全等守卫 |
| 2 | 并发仲裁在文中没有名字（最高风险） | **采纳** | 新增 §2.4（三件事 + spike 五件事）；表头 DeepCode 行加“输入并发不可平移”；参考地图加深色行 |
| 3 | 波 A/B 依赖倒置（wire_view / footer） | **采纳** | §2.2 顺序约束；§4 波 A 首刀 `wire_view.py`；`footer.py` 改 `FooterVM`（字段全 optional） |
| 4 | vim 判死理由已过期 | **采纳（更精确）** | 表 D 改为“范围裁剪”；保留“不得在引擎层复活 `vim_mode`”硬红线；§10 同步 |
| 5 | `unsupported.py` 与映射表双真源 | **采纳（我原文有错）** | §5 改为两真源 + id 对齐 + 三条可执行守卫；§2.3 新增“映射表加 `id`/`status` 两列”受控改动 |
| 6 | §10 与 W-D4（`todos` kind）矛盾 | **采纳（评审正确）** | 表头 + §10 改为“不改页面/交互，仅同步 cardSlots + 生成物”；W-D4 降为待裁（§9-8） |
| 7 | 宽度双真源风险 | **采纳** | §3 宽度行改为 `rich.cells` 薄封装 + 一致性判红；§4 波 A、§7-13 同步 |
| 8 | 编号三重冲突 | **采纳** | 缺陷称 F1/F2，波 D 条目称 W-D1…；§0-11 写死编号体系 |
| 9 | 其余：形态门控 / 图元归属 / 快照参数 / 文案散落 / 渲染异常 / Ctrl-C 表 | **全部采纳** | §2.3 形态门控行；§6 四条新纪律；§4 波 A ⑦ + 波 B Ctrl-C 四语义表；新增 `strings.py` |
| 10 | 行数口径未注明（并称实测 388/129/235） | **半采纳** | 采纳“写明命令”：§0-12 钉死计数命令；**但不采纳那组数字**——`Path.read_text().splitlines()` 实测为 **393 / 137 / 240**（`-split "\n"` 不会少 5），行号引用（:161/:167/:206/:215/:223/:250/:279/:282/:319）经 `Select-String` 逐条命中 |

**评审之外我另外报的一条（自查发现）**：评审说“行数差异来自计数口径而非漂移”，方向对但结论不完整——
`Get-Content | Measure-Object -Line` 会忽略空行（348 vs 393），本仓已有同类坑记录；因此 §0-12 同时禁止该命令。

---

## 附录 B：三张对账表（§0.5-6；应原样贴进 PR 描述）

### B-1 条目对账（计划条目 → 实现位置 / commit）

| 波 | 条目 | 实现位置 | commit |
|---|---|---|---|
| A1 | 扁平包 + `__all__` + 包 AGENTS + `unsupported` + `strings` + 白名单目录级放行 | `hosts/terminal/{__init__,unsupported,strings}.py`、`scripts/guards/check_layout.py` | 5b635d6 |
| A2 | 帧→VM（13 kind 穷尽、未知/坏帧降级、不持 raw frame） | `terminal/wire_view.py` | 9f0e436 |
| A3 | 宽度（rich.cells 薄封装 + 一致性） | `terminal/width.py` | 210b482 |
| A4 | 流式 markdown 块状态机 | `terminal/markdown.py` | c4b926e |
| A5/A6 | 七图元 + diff 卡 + FooterVM + F1 接活 | `terminal/{cards,diff,footer}.py`、`serve/terminal_theme.py` | 21b8f87 / 80d9dcc |
| B1–B4 | 队列、补全、粘贴、截止与本地超时、渲染降级、Ctrl-C 四语义 | `terminal_client.py`（当时代理） | 9eca9bb / 07ef8ba |
| C1/C2 | 面板状态机 + alt-screen owner + 搜索 + 只读 transcript | `terminal/overlay.py`、`terminal/pickers.py` | bdd89e8 |
| W-D1/D2 | usage 扩展 + 结构化 approval patch | `serve/wire.py`、`protocol/app-wire.schema.json` | be5ee5e |
| W-D3/D4 | `GET /catalog/{kind}`（8 kind）+ `todos` kind | `serve/catalog/*`、`serve/routes.py`、`host.py`、`web/TodoCard` | 11112d8 / ad0b5bb |
| §2.2 结构 | 循环/渲染/键位入包，门面降为装配 | `terminal/{app,renderer,keymap}.py` + 门面 170 行 | 3c77fbd |
| §5 | 徽标守卫 #2/#3 + 启动缺口行 | `terminal/cards.gaps`、`tests/ci/test_unsupported_badges.py` | 7f93ff2 |
| 波 B 补 | 审批/提问倒计时工具条 + 无控制台回退 | `terminal/approval.py`、`renderer.py`、`input_session.py` | f1a3059 |
| 波 E 补 | `plugins` catalog kind + `:help` 命令面板 | `serve/catalog/providers.py`、`terminal/pickers.py`、`terminal/app.py` | a40eb35 |

### B-2 影响面对账（被改文件 → 上下游）

| 被改文件 | 谁调用它 | 它调用谁 | 同步了谁 |
|---|---|---|---|
| `protocol/app-wire.schema.json` | 双侧 codegen、`test_wire_codegen*`、`test_kind_coverage`、fixtures 守卫 | — | `wire_types.py`、`protocol/_gen/app-wire.ts`、`apps/web/src/generated/app-wire.ts`、`tests/fixtures/serve_wire/*`、`apps/web/src/generated/wire-fixtures.json`、`cardSlots.ts` |
| `serve/wire.py` | `host.render_event`、fixtures 生成器、`test_wire*` | `contracts.domain.events`、`wire_types` | 3 个生成物同上 |
| `serve/host.py` | `terminal_client.build_serve_host`、`bootstrap/hosts/app.py` | `authority`、`broadcaster`、`routes`、`wire`、`plugins/cron/skills`（catalog 侧） | 无其他消费者（单宿主） |
| `serve/routes.py` | `MemoryTransport`、`http_server`、`test_routes` | `authority`、`catalog`、`session_storage` | R8 复杂度从 22 降到表驱动 |
| `hosts/terminal_client.py` | `bootstrap/hosts/app.py`、`api.py`、`serve/studio.py`、e2e/单测 | `terminal.app`/`renderer` | 5 个导入方零改动（公开名全保留） |
| `apps/web/src/app/{cardSlots,viewModel}.ts`、`pages/ChatPage.tsx` | web 测试、`test_card_slots_cover_every_schema_kind` | generated types | 新增 `todos` 槽位 + 穷尽 case + TodoCard |
| `docs/plan/mapping/terminal-coding.md` | `test_unsupported_badges` 双向断言 | `terminal/unsupported.py` | 新增 T1–T18 行 |

### B-3 判红对账（计划声明的红用例 == 实际存在且可复现为红）

| 红用例 | 测试文件::用例 |
|---|---|
| 宽度回退成 `len()` / 另立宽度表 | `test_width.py::test_cell_len_matches_rich_on_every_sample` |
| 未闭合围栏不缓冲 | `test_markdown.py::test_open_fence_is_held_back_until_it_closes` |
| 单卡异常杀死消费循环 | `test_terminal_degrade.py::test_render_exception_degrades_and_the_frame_after_it_still_renders` |
| 未知 kind 静默吞 | `test_terminal_degrade.py::test_unknown_kind_is_rendered_not_swallowed` |
| 审批默认改成 approve | `test_terminal_degrade.py::test_timeout_answer_is_treated_as_deny` |
| 回合中丢弃输入 | `test_queue_during_turn.py::test_second_line_is_queued_while_the_first_turn_runs` |
| 绕过单一出口写终端 | `test_package_contract.py::test_interactive_writes_go_through_one_patched_channel` |
| 未登记文件 import prompt_toolkit | `test_package_contract.py::test_prompt_toolkit_exemption_is_scoped_to_the_terminal_package` |
| 徽标登记表与映射表漂移 | `test_unsupported_badges.py::test_registry_equals_mapping_absent_rows` |
| 裸写徽标字面量 | `test_unsupported_badges.py::test_badges_are_only_built_by_the_registry` |
| 登记了但不可见 | `test_unsupported_badges.py::test_every_registered_gap_is_visible_at_startup` |
| catalog kind 与 provider 漂移 / 未知 kind 回空表 | `test_catalog_coverage.py::test_schema_kinds_equal_provider_registry`、`test_providers.py::test_unknown_kind_is_404_and_never_an_empty_success` |
| `CatalogResponse` 混进 `ServerFrame` | `test_catalog_coverage.py::test_catalog_response_is_not_a_server_frame` |
| 新 kind 不补 cardSlots | `test_kind_coverage.py::test_card_slots_cover_every_schema_kind` |
| 成功/失败/缺文件的 todos 发布时机 | `test_host_todos.py`（四条） |
| 面板游标越界/空表/只读面板误发命令 | `test_overlay.py`、`test_pickers.py::test_transcript_panel_is_read_only` |
| 图元零调用（F1 回归） | `test_terminal_theme_usage.py::test_every_public_theme_primitive_is_called` |
