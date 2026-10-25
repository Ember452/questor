# questor · coding 形态：功能可见性映射表

- Status: Active（阶段 1 从 `docs/plan/02-studio-serve-host.md` 迁出）
- Owner: 用户裁决（本表是**产品契约**，不是通用契约）
- 配套：`docs/plan/mapping/questor-personal.md`（personal 形态）

## 规则

每一个用户可感知的功能必须有一行——要么有界面载体，要么显式登记"暂不暴露"（由用户裁决，
执行 agent 不得默默省略）。**"引擎有、界面无"的功能黑洞是验收红线**。本表随阶段回填
（阶段 1 初版核对，4a 逐端点核对，4b 逐屏验收），与启动扇出表并列维护。

kind 覆盖守卫（`tests/ci/test_kind_coverage.py`）以本表与 `tests/ci/test_serve_wire_fixtures.py`
为数据源：schema 的帧集合必须等于"引擎映射 ∪ 宿主直出 ∪ 登记为不展示"。

初版基于 2026-10-24 引擎探索事实（39 工具 / 16 命令族 / 各能力域） ：

## 4a 页面首批（coding 形态）

| page id | capability | 载体 | 后端依据 |
|---|---|---|---|
| `chat` | ready | 对话流 + 五卡 + Composer | `/submit` `/events` `/cancel` `/approve` `/ask` |
| `thread` | ready | 当前会话快照视图（只读） | `/history` |
| `inspector` | declared | 入口不出现（待端点） | 无 `/inspect` 端点 |
| `settings` | declared | 入口不出现（待端点） | 无 settings 端点 |
| `workbench` | declared | 入口不出现（待端点） | 无文件/diff 端点 |

`files` / `tests` / `browser` **不注册**（无端点，登记为未实现）；新增页面走
`apps/web/docs/ADDING_A_PAGE.md` 四步。三态语义见 ADR-0008。

## 映射

| questor 功能 | 界面载体 | 复用来源（§0 三序） |
|---|---|---|
| 对话流 / 流式回复 / 思考 | Transcript 卡片流（SayCard） | Reasonix 原样 |
| 取消当前回合（Stop） | Composer 停止按钮 → `turn_done{cancelled}` | 阶段 1 `/cancel` 端点；按钮取自 DeepCode `Composer` |
| 提交队列 / 插话（followup / steer） | 无独立界面 | **初版登记：暂不暴露**（引擎单回合无队列；要开先走计划 §3） |
| 工具执行可视化（fs/shell/web/media…） | ToolCard 原位展开 + diff/输出面板 | Reasonix 原样 |
| 权限审批（三态+敏感路径拦截） | ApprovalCard 三档按钮 | Reasonix 原样 |
| 工具提问 AskUserQuestion | AskCard（单选/多选/自填） | Reasonix 原样 |
| 压缩进度（auto/manual/reactive × 9 相位） | CompactionCard + MeterRail 上下文环 | Reasonix 卡片 + Context 仪表 |
| 项目记忆 / 个人记忆（写入、召回、auto-dream） | RememberCard + Settings 记忆页 | Reasonix RememberCard；个人记忆语义微调 |
| 技能（SKILL.md 发现/调用/清单） | Composer ChipMirror 芯片 + /skill + Settings 技能页 | Reasonix 原样 |
| 插件（六类工件、启停、安装） | Settings 扩展页 | Reasonix PluginsPage 形态 |
| MCP 服务器（连接/认证/工具桥接） | Settings MCP 页 + Metrics 的 Mcp 面板 | Reasonix 原样 |
| 模型 / Provider / profiles 档位切换 | 模型 Picker + Settings 连接页 | Reasonix Picker/ConnectionSettings；profiles 档位微调 |
| 推理强度（effort/passes） | 推理强度四格条 Picker | Reasonix 原样 |
| 权限模式（默认/PLAN/FULL_AUTO） | Policy 三档菜单（Ask/Auto/YOLO） | Reasonix 原样（语义映射） |
| Plan 工具 / TodoWrite | PlanGate + Metrics 的 Plan 面板 | Reasonix 原样 |
| 上下文用量 / 缓存命中 / 费用 | MeterRail（上下文环/费用/隐藏金额） + Metrics Cost/Cache | Reasonix 原样 |
| 会话快照（保存/恢复/列出/按 id 加载/导出 md） | Sidebar 会话树 + /resume | Reasonix 会话树；导出入口微调 |
| 斜杠命令（16 族）+ 技能回退 | CompletionMenu 补全 + /help | Reasonix 补全菜单；命令集为 questor 内容 |
| Cron 四工具（创建/列表/启停/删除） | Metrics 的 Jobs 面板 | Reasonix Jobs；cron 语义微调 |
| autopilot 自动巡检 | Jobs 面板（后台任务） | Reasonix Jobs 微调；**初版登记：暂不暴露**（用户裁决） |
| 后台异步 agent（AgentTool/task_manager） | DeckChips + Agents 面板 | Reasonix 原样 |
| swarm / team（队友、worktree、权限上抛） | Agents 面板 + DeckChips | Reasonix 子代理卡微调；team 生命周期需**新增 kind** |
| coordinator 协调模式 | 阶段标记（只读展示） | **初版登记：暂不暴露**（用户裁决） |
| 渠道会话（飞书/QQ gateway） | Sidebar 机器区段（只读展示 session_key） | questor 特有，**新增**（首版只读） |
| 沙箱（Docker 配置与状态） | Settings 沙盒页 + Policy | Reasonix 沙盒页微调 |
| 视觉输入（图像块/多模态降级） | Composer 附件 chips + 图片卡 | Reasonix 原样 |
| 诊断 / doctor / 配置展示 | Settings 版本与日志页 | Reasonix 原样 |
| git 工作区（分支/worktree 切换） | WorktreeChip / BranchChip + Workbench 改动页 | Reasonix 原样 |

## 表的读法

"Reasonix 原样" 指**交互与视觉形态**的来源；实际落地载体优先用 **DeepCode 骨架内的同名区域**
（Settings / Inspector / Composer / navigation），只有五张对话卡直接搬 Reasonix 组件。
新造任何一项前，先按计划 §0-9 的三序登记。

## 已登记"暂不暴露"（coding 形态）

autopilot、coordinator、提交队列/插话（followup/steer，首版）。
**需新增 kind**：swarm/team 生命周期、渠道会话标识。此三处是计划 §3 中断-上报-授权的预定触发点。
