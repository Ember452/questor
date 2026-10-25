# questor · 终端（coding 形态）功能可见性映射表

- Status: Active（plan03 波 A1 建立；与 `questor-coding.md` 并列，**不替代**它）
- Owner: 用户裁决（本表是终端侧的产品契约）
- 配套：`docs/plan/03-terminal-repl.md` §0.5（能力对账四表）

## 规则

1. `id` 是跨文档契约：本表 `status=absent` 的行集合 **必须等于**
   `src/questorharness/bootstrap/hosts/terminal/unsupported.py` 的 key 集合，
   由 `tests/ci/test_unsupported_badges.py` 双向断言（左多 = 渲染了没登记的能力；
   右多 = 真功能黑洞）。
2. `status` 三态：`ready`（终端有载体且可用）、`declared`（已声明、部分可用或缺数据）、
   `absent`（后端缺契约，终端只渲染 `⊘ 未实现 · <id> <名词>` 徽标）。
3. 新增一行 = 新增一处用户可感知的能力；**id 一入表即只增不改名、不删除**，下线改 `absent`。
4. 来源列只写参照的 `file` 或本仓文件，不写"自设计"——视觉与交互参数必须可追溯
   （plan03 §0-9 三序）。

## 表

| id | 功能 | status | 终端载体 | 来源 |
|---|---|---|---|---|
| A1 | 审批第三档 / 记住本次选择 | absent | 两档审批卡 + 徽标 | Reasonix `tui/approve` + `ApprovalCard` |
| A2 | Ask 单选 / 多选 / 自填 | absent | 自由文本问答卡 + 徽标 | Reasonix `tui/ask.go` |
| A3 | 回合中插话（steer） | absent | 排队 pending 行 + 徽标 | Reasonix `tui/queue_slash.go` |
| A4 | 任意检查点回滚 | declared | `/rewind` 一步 + help 注明"部分可用" | Reasonix `tui/rewind.go` |
| A5 | 图片 / 附件提交 | absent | 粘贴图片时徽标 | Reasonix `tui/clippaste.go` |
| A6 | 语音采集（录音→转写） | absent | `/voice` 开关保留 + 徽标 | Claude Code `voice` |
| T1 | 回合中继续输入并排队 | ready | pending 行 + 状态栏“队列 1”；Ctrl-D 前收完已受理回合 | Reasonix `queue_slash.go` |
| T2 | 斜杠命令补全（前缀 + 子序列 + 描述） | ready | prompt_toolkit 补全菜单，数据取 `GET /commands` | Reasonix `complete.go` |
| T3 | `@` 与路径补全 | ready | FileCompleter | Reasonix `complete.go` |
| T4 | 多行粘贴保护与图片粘贴识别 | ready | `paste.normalize/needs_confirmation/is_image_paste`；图片走 A5 | Reasonix `pastekeep.go` |
| T5 | 审批/提问截止提示与本地超时 | ready | 卡的倒数说明行 + 超时按 deny/未回答 | Reasonix `ask_countdown` |
| T6 | 单帧渲染降级 | ready | `降级 <类型> · <原因>` 一行，事件消费不中断 | DeepCode `test_tui_resilience.py` 口径 |
| T7 | 模型面板 | ready | `:model` → `GET /catalog/models` → `/model <id>` | Reasonix `modelpick.go` |
| T8 | 会话面板 | ready | `:session` → `/catalog/sessions` → `/resume` | Reasonix `sessions.go` |
| T9 | 技能面板 | ready | `:skill` → `/catalog/skills` → `/<skill>` | Reasonix `skillpick.go` |
| T10 | MCP 面板 | ready | `:mcp` → `/catalog/mcp` → `/mcp` | Reasonix `mcppanel.go` |
| T11 | 任务与 cron 面板 | ready | `:task` / `:job` 分别读 `catalog/tasks` 与 `catalog/jobs`，确认后 `/tasks` | Reasonix `todos.go` |
| T12 | git 面板 | ready | `:git` → `/catalog/git` → `/branch` | Claude Code `branch` |
| T13 | 插件面板 | declared | catalog 暂无 `plugins` kind（无公开枚举 API），故不开放 `:plugin` | — |
| T14 | 费用 / 上下文占比 | declared | 窗口已知则显比例；`costUsd`/`cachedTokens` 引擎无数据 → 显 `—` | Reasonix `footer.go` |
| T15 | transcript 浏览与搜索 | ready | `:transcript`（等价 `:t` / `:history`）读 `/history`，面板内 `/` 过滤 + j/k 游标；只读不发命令 | Claude Code transcript mode |

> `id` 一入表即不重新编号、不删除；下线只改 `status`。`absent` 行集合必须与
> `terminal/unsupported.py` 的 key 集合相等（`tests/ci/test_unsupported_badges.py`）；
> `todos` 面板与 `plugins` kind 落地时把对应行改 `ready`。
