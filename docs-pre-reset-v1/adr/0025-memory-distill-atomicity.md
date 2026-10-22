# ADR-0025: Deep Dream 离线蒸馏的单写者边界与原子性纪律

- 状态：✅（2026-10-16，决策定；实现见 [`../plan-archive/04-memory-soul.md`](../plan-archive/04-memory-soul.md) T13、T14）
- 背景：[`../design/06-memory.md`](../design/06-memory.md) §1 规定 dreams 蒸馏产物"**原子写、输入哈希去重、只删不编、空哨兵跳过；dreams 不进索引**"，§3 定义压缩丢弃→L2' distill 发 `MemoryWrite`。但 Deep Dream（夜间蒸馏）与 run-完成→daily flush 本质是**离线/后台批处理入口**（CLI `--dream`），**不在活 run 的 Command 队列里、没有 active `Run`/`Domain_State`**。R01-G8 评审已把"不可变/单写者"红线**只强加于 `Domain_State`**。风险点：若把离线蒸馏误读成"第二个改可信状态的写者/旁路 reduce"，就与 HARD C2/C16"唯一写入口 Command→reduce"表述冲突，实现期易纠结或被审计判违规。实扒：CowAgent `agent/memory/summarizer.py:511-648`（`deep_dream(lookback_days)` 原子写+`daily_content_hash` 去重+transient 重试）、`:288-344`（claim-then-commit 失败释放可重试）、hermes `agent/memory_manager.py:747`（`commit_session_boundary_async` 会话边界异步 flush）。
- 决策：
  - **纪律分层**：HARD C2 单写者**只强加 `Domain_State`**；记忆 store（ADR-0023）是独立持久子系统，其写入原子性由 store 自身保证——**文件（md）为真源、SQLite 索引为派生投影**；蒸馏/flush 走 `write_text_atomic`（临时文件 + `os.replace` 原子替换）+ 输入 `daily_content_hash` 去重（同输入二次为 no-op）+ claim-then-commit（in-flight/flushed 两套标记、失败释放回可重试）。它**不触碰 `Domain_State`**，故不构成"第二个改可信状态的写者"。
  - **两条写路径分工、共用同一收口**：
    - **热路径**（活 run）：显式 `WriteMemory` Command → `reduce`（产 `memory_written` 事件）→ 经注入的 `MemoryStorePort` 落库（HARD C4/C16，plan T11）。
    - **离线路径**（Deep Dream、run-完成→daily flush）：由维护入口/后台异步经**同一 `MemoryStorePort` 抽象**写、**不排活 run Command 队列、不进热 loop**（[`../design/05-policy.md`](../design/05-policy.md) §5"只读分支快照重放"，plan T13）。
    - 两者都经 `MemoryStorePort` 接口收口，**无向量库/SQLite 裸句柄旁路**（HARD C4）。
  - **蒸馏硬纪律**：只删不编（严禁造材料外信息）、空哨兵 `无/None` 跳过不写、`dreams` 不进检索索引（防近重复噪声）、transient 错误有界重试；错误不吞（fail 明确、可重试，呼应审计 D 类）。
  - **DoD① 的 daily 生产者**定为"显式 `WriteMemory` + run-完成边界 flush"，**不依赖**被后置 P10 的压缩丢弃（plan/04 §9 裁定 4），使蒸馏有真实可测输入、不必强启压缩。
- 后果：正面——离线蒸馏与活 run 解耦、不阻塞主回复、失败可重试；单写者边界口径清晰、可被守卫与 `test_p4_memory_single_writer` + AST 判红钉死。代价——热/离线两套写路径需在 ADR 与模块注释里讲清归属，防实现期误接；`memory.db` 上"离线写 vs 热路径写"并发需 `BEGIN IMMEDIATE`/锁纪律（承 P3）；真跨进程 exactly-once 后置 P9。
- 备选（被否）：
  1. Deep Dream 同步塞进活 run loop：阻塞热路径、有撕裂状态风险、破可插拔（DoD④）→ 否。
  2. 强制离线蒸馏也走 `Command→reduce`（需 active Run）：离线无 run、语义造假、违 resume/回放口径 → 否。
  3. 不做原子写/hash 去重：重复蒸馏污染 core、崩溃留半写文件 → 否（R06 实证 Cow 已用该纪律）。
- 关联：[`../design/06-memory.md`](../design/06-memory.md) §0/§1/§3/§5；[`../design/04-turn-loop.md`](../design/04-turn-loop.md) §7；[`../design/05-policy.md`](../design/05-policy.md) §5；HARD-CONSTRAINTS C2/C4/C5/C16；ADR-0004/0013/0023/0024；R06 §2.1/§2.2/§4.3。
