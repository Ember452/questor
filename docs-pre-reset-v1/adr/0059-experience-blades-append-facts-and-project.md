# ADR-0059: 体验三刀（可退 / 可改 / 可问可看）都只做"追加事实 + 投影"，不开第二通道

- 状态：✅（2026-10-21，B13–B15/c1–c4）
- 背景：§13 把 B13–B15 排成"体验留位的交付刀"。这三刀最容易做错的地方不是功能，而是**每条新能力都想
  再开一条自己的通道**：回退直接改事件流、会话元数据只写表不留事实、提问另建一套"用户回答"协议、
  成本按一个凭空的汇率折算成钱。每一条都会把 C13（事实流唯一权威）或 §17-9（不许把假设写成结论）破掉。
- 决策：
  1. **rewind / fork 只追加事实（§8 可退）**：`RewindRun` → durable `run_rewounded` + 新 run 的
     `Run.history_base={run_id, to_seq}`；`ForkSession` → 新会话流 `sess:<new>` 上的 `session_forked`。
     **旧流一行不改**（判据是"回退后旧 run 的 replay 逐行相同"，不是"看起来没删")。旧前缀经 B4 已有的
     seed 接缝带入：`prefix_seed_refs` 只做一件事——把 per-run `to_seq` 换算成 seed 认的全局 `gseq`。
  2. **回退必须在创建点落，不能"先 start 再投 inbox"**：Echo 一轮就终态，届时 `RewindRun` 会被 reduce
     拒成一条 warning——所以 `start_run` 加 `prelude`，与创建同一个 task 内经咽喉取号。
  3. **会话元数据 = 先事实后投影（§8 可看可改）**：`UpdateSession` 只对**本次真变了**的 facet 发
     `session_renamed/archived/pinned`，之后再写 `sessions` 行的既有列（title/archived/pinned）。
     **不新建表、不新建列**；会话列表因此原则上可由事件重建。同值 PATCH 必须与行的现值比对后**零事件、
     零 seq**——因为会话流没有活 controller，每次 `apply_on_stream` 都从头取号，只靠幂等键挡不住重试。
  4. **记忆改/删同构（§8 可见可改）**：`UpdateMemory`/`DeleteMemory` 先落事实，再动派生索引；真源 md
     **永不就地改**（编辑走 `supersede`：先退役再写替代，顺序不可反）；一次编辑**只记一条**
     `memory_updated`，**不多记 `memory_written`**——否则 B12 的写入噪声率会被编辑次数虚增，
     指标恰在用户开始维护记忆时开始说谎。citation 在前端只做格式化（丢弃坏条目、区间反了不算归因、
     无引用返回空串），不发命令。
  5. **ask_user 复用审批生命周期（§8 可问）**：`approval_mode="prompt"` 由
     `permission_policy._apply_approval_mode` 把 ALLOW 抬成 ASK，于是"问一句"就是既有的
     `RequestApproval` → resolve / expire；三态都是可回放事实，**不新增事件类型、不新建人机通道**。
  6. **自由文本答案当前没有通道，工具就明说**：`ResolveApproval` 只带 allow/deny。给
     `result` 塞一句"assent only"而不是假装拿到了回答；扩 `ResolveApproval` 是 additive 契约变更，
     留给后续刀（本 ADR 记为已知边界，不当已实现）。
  7. **/context 与 /cost 是只读投影**：分段与 §6.1 的 cache 段对齐（system / 记忆索引子段 / 工具面 /
     历史 / 摘要 / 锚），token 一律标 `estimate`（仓内无 tokenizer，`chars/4` 向上取整）；
     **被折叠掉的字符数宁可不列**（存留快照里没有这个事实，猜一个就是假数）；无窗口时报
     `window: unknown`；成本复用 `session_totals` + B12 的 `per_task_cost`，无价目表就是
     `cost_usd=UNVERIFIED`，无成功任务就是 `n/a` 而不是 0。两个命令**只进 `_KNOWN_COMMANDS`、
     不进 `_USAGE`**（`--help` 有逐字节快照测试，同 B5 的 `--inspect-extensions` 纪律）。
  8. **默认翻转仍只在组合根**：`ask_user` 由 `CliSurface(extra_tools=...)` 追加、`build_app()` 传入；
     默认 profile 的 11 工具名册与直接构造面的行为逐字不变（`test_default_profile_keeps_the_exact_eleven_tool_order`）。
- 后果：
  - 正面：三刀共 6 个新事件 + 4 个新命令全部 additive（`EventType` 32→38、`Command` 22→26），旧帧仍合法；
    回退/分叉/编辑/撤回/提问都能从事件流回答"为什么"；`DomainState.session_id` 从此带显式 UNWIRED 说明。
  - 代价：会话与记忆的写路径各多一次"先与现值比对"的读；`memory_updated` 不带正文，UI 要显示新内容必须
    回读记忆库（这是 C18/C20 的代价，不是遗漏）；ask_user 只能问"准不准"，不能问"你的答案是什么"。
  - 需持续守：**任何人加体验面都不许开第二通道**（人机交互走审批、会话作用域事实走 `sess:<id>`、
    成本走 durable `run_completed.usage`）；不得为 PATCH 加"顺手改点什么"的字段白名单之外的键；
    不得把 `estimate` 字样从 token 数字上摘掉。
- 备选（被否）：
  1. **rewind 直接截断/重写旧事件流**：否——事实流是权威（C13/C5），历史只能被追加。
  2. **只写 `sessions` 表不发事件**：否——会话列表退化成"只能读表"，审计与重放两条腿断一条。
  3. **给 ask_user 新建一条 elicitation 通道 / 启用 `Elicitation` 点位**：否（本刀）——审批已经是既成通道，
     两套并行会让"用户拒绝"有两个真值源；`Elicitation` 仍是 §5.1 的预留点位。
  4. **`--cost` 内置一张价目表把 token 换算成钱**：否——本仓无汇率依据（§17-9），编一张就是把假设写成结论。
  5. **把 `--context`/`--cost` 写进 `_USAGE`**：否——`--help` 有逐字节快照断言，改它属改既有断言（R3）。
- 关联：v3 §5.1/§6.1/§6.3/§6.4/§8/§13 B13–B15/§17 第 14 条；`ADR-0024`（seed 与锚）、`ADR-0045/0047`
  （审批与投递账本）、`ADR-0055`（citation 解析即剥）、`ADR-0056`（软删与不建历史表、supersede 顺序）、
  `ADR-0057`（窗口身份）、`ADR-0058`（六指标口径）。
  代码：`contracts/events.py`、`contracts/ports.py`、`state/reduce.py`、`state/domain_state.py`、
  `state/snapshot.py`、`kernel/session_ops.py`、`providers/store_sqlite.py`、
  `providers/store_memory_sqlite.py`、`surfaces/http_sse.py`、`surfaces/cli.py`、`composition.py`、
  `capabilities/tools/ask_user.py`、`surfaces/context_report.py`、`desktop/web/src/api/citations.ts`。
  测试：`tests/unit/test_session_ops.py`、`tests/integration/test_session_routes.py`、
  `tests/integration/test_memory_admin.py`、`tests/unit/test_ask_user_and_reports.py`、
  `desktop/web/src/api/citations.test.ts`。
