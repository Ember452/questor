# 日志面 BUGLOG（疑难复发档案）

只收**架构相关、理解成本高、容易再次踩**的三条。普通缺陷一律走 GitHub Issue（label `bug`），
不进本文件；发 Release 时把这三条的修复摘要摘进 `CHANGELOG.md`。

每条格式：现象 / 触发条件 / 为什么容易复发 / 纪律 / 关联。

---

## 1. 外来日志把账本内容与 prompt 灌进主干文件（准入边界）

- **现象**：一次真 run 之后，`.questor/logs/questor-<date>.jsonl` 里出现用户 prompt 原文与
  `checkpoints.state_digest` 全文——不是我们的代码写的，是 `aiosqlite` 的 DEBUG 记录
  （`executing <SQL> <参数元组>`）经带内桥落进去的。
- **触发条件**：装配把 root logger 降到 DEBUG（为了让一方 DEBUG 能进桥）+ 主干 `file_level=DEBUG`。
  任何会在日志里打印参数的第三方库都会命中。
- **为什么容易复发**：三个抽象各看都对——"root 开低才能收到记录"、"文件收 DEBUG"、"脱敏只在
  pipeline 一处"（pattern 簇只认凭据形状，认不出散文）。单看每一层都不会发现 D4「零原文默认」被
  整条旁路。逐个库加降噪名单也追不上：新依赖、P5 的 MCP SDK、任何驱动都会带来新的参数日志。
- **纪律**：① 装配**永不降 root**，只给 `questor` 子树定低级别（`callHandlers` 不遍历祖先级别）；
  ② pipeline 有**来源门**：非 `questor.*` 的记录有效下界恒为 INFO；③ 验收必须跑真进程 grep
  canary，不能只测 `LogEntry` 构造（`tests/integration/test_log_zero_plaintext.py`）。
- **关联**：Issue #126 / #129 / #130；DESIGN D10、§11；`scripts/check_projection_whitelist.py` 的
  敏感键禁词是同一政策的带外侧防线。

## 2. 节流签名与事件形状错配：错误被"合并"掉（静默丢日志）

- **现象**：两个 run 在同一 1 秒窗内各失败一次，日志里只有第一个 run 的 `run_failed`，
  第二个 run **一行都没有**（合并出的窗尾 summary 仍归属第一个 run 的 `context`）。
- **触发条件**：节流签名是 `(logger, level, msg)`，而带外投影的 msg 恒为 `event <type>`——
  区分信息全在 `context`/`fields`，签名看不见。同 run 内 1 秒多条 `tool_completed`/`warning`
  同样被折成第一条。
- **为什么容易复发**：节流与投影是两个独立正确的模块，缺陷只在它们对"什么算同一条"的理解上错位；
  而且反向也错——用完整 msg 当指纹时，"同一行代码、值不同"的日志风暴零抑制（实测 50 条全放行）。
  任何新增的"msg 里不带区分信息"的记录类型都会再踩一次。
- **纪律**：① ERROR/CRITICAL **完全绕过节流**（HARD C6，错误绝不静默）；② 签名 =
  `(logger, level, msg 形状, run_id)`，形状归一（数字/十六进制/引号串 → `<*>`）；③ 投影类记录若
  要靠 fields 区分，fields 必须进签名或 msg。
- **关联**：Issue #128 / #131；DESIGN §13；`tests/unit/observability/test_pipeline.py` 的双向判据。

## 3. 关联上下文不过线程/进程边界（`run_id` 静默缺失）

- **现象**：真 run 的日志文件里，绝大多数行（实测 80/85）`context` 为空，一条都不带
  `run_id`/`turn`——它们全产生于 aiosqlite 的专用工作者线程。
- **触发条件**：`bind()` 用 `contextvars`，它只随 `asyncio.create_task` 复制，**不进入
  `threading.Thread`，更不出进程**。凡在线程池/工作者线程/子进程里打日志都拿不到关联。
- **为什么容易复发**：P5 会把工具与 MCP server 搬进线程与子进程，届时"日志里查不到这是哪个 run"
  会以新面貌再出现；而这看起来像 bind 的 bug，容易被拿去加锁、加透传，越修越复杂。
- **纪律**：① 跨线程/子进程**禁止依赖 ambient `bind()`**，关联键必须显式随记录传
  （`extra={"log_fields": {"run_id": ...}}`）；② 子进程侧的 `run_id` 注入方式（文件名 / 首行前缀）
  必须在 `plan/05` 的 §0 扫描表里先定案；③ 不给 `contextvars` 加自建传播层——语言事实，认它。
- **关联**：Issue #130；DESIGN §5.6；与 G-L7（跨进程按日写）同属"进程/线程边界"未收口面。
