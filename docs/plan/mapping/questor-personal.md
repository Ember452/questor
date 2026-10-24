# questor · personal 形态：功能可见性映射表

- Status: Draft（阶段 1 建空壳，首批页面待用户裁决）
- Owner: 用户裁决
- 配套：`docs/plan/mapping/questor-coding.md`（coding 形态）

## 规则（与 coding 表同源）

每一个用户可感知的功能必须有一行——要么有界面载体，要么显式登记"暂不暴露"。
personal 形态当前**整体处于 `declared`**：页面 id 已登记、页面未实现，入口在界面上不出现
（`declared` ≠ 灰置，而是不渲染入口）。本表在 personal 开工时逐行补齐，**不预设功能**。

## 首批 page id（均 `declared`）

| page id | 含义 | 能力位 | 备注 |
|---|---|---|---|
| `chat` | 对话主屏 | declared | 与 coding 共用对话卡框架 |
| `persona` | 人设 / 档案 | declared | 参照 CowAgent `AgentSelector` |
| `memory` | 记忆浏览 / 召回 | declared | 产品侧 personal memory |
| `schedule` | 日程 / 定时任务 | declared | 复用 cron 四工具语义 |
| `channels` | 渠道会话（飞书 / QQ） | declared | 只读 session_key 起步 |

## 功能映射（待裁决）

| questor 功能 | 界面载体 | 复用来源 |
|---|---|---|
| （待裁决） | — | 首批功能清单由用户在 personal 开工前裁决；未裁决前不得实现 |

## 工具面

`personal` 形态与 `coding` 的工具面**不同**，由 bundle 表达：

- `allowed_tools: [ask_user_question]` —— 无副作用的交互直接放行；
- `denied_tools: [bash, edit_file, write_file, notebook_edit, enter_worktree, exit_worktree]`
  —— 不进代码编辑 / 执行面，fail-closed。

判红：`tests/unit/test_permissions/test_profile_tool_surface.py`（personal 下 `bash` 必须被拒）。
