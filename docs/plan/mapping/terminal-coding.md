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

> 波 B–E 落地时逐行追加：队列（A3 的排队部分转 `ready`）、覆盖层、面板六行、
> `todos` 面板、`cachedTokens`（`declared`）。每次追加同刀更新 `unsupported.py` 与
> plan03 §8 总验收表。
