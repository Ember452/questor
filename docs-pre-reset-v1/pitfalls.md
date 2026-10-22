# Questor 陷阱档案（Pitfalls）

**这里不收 bug 清单。** Bug 一律走 GitHub Issue（label `bug`，正文 5 行：现象 / 复现 / 根因 / 修复 / 关联 commit），
合并进 `main` 时由 `Fixes #N` 自动关闭——那是"发生过什么"的真源，本文件不复制它。

这里只收**同时满足三条**的架构级陷阱：

1. **跨子系统**——根因或后果不止落在它被发现的那一层；
2. **理解成本高**——不看现场证据就想不到，看一次也记不住；
3. **会再踩**——同类触发条件在后续 Phase 必然重现（新依赖、新 surface、新进程边界）。

每条格式固定：**现象 / 触发条件 / 为什么容易复发 / 纪律 / 关联**。
"纪律"必须是可执行的一句话（要么已被某条 `HARD-CONSTRAINTS` 红线机器守，要么写清由哪个守卫/测试守）。
提炼不出纪律的条目说明它只是 bug——那就该留在 Issue 里，不要进本文件。

> 发 Release 时，把当轮新增条目的摘要摘进 `CHANGELOG.md`；本文件**不做历史流水**，只维护"当前有效的教训"。

---

## 可观测性 / 日志面

### 1. 外来日志把账本内容与 prompt 灌进主干文件（准入边界）

- **现象**：一次真 run 之后，`.questor/logs/questor-<date>.jsonl` 里出现用户 prompt 原文与
  `checkpoints.state_digest` 全文——不是我们的代码写的，是 `aiosqlite` 的 DEBUG 记录
  （`executing <SQL> <参数元组>`）经带内桥落进去的。
- **触发条件**：装配把 root logger 降到 DEBUG（为了让一方 DEBUG 能进桥）+ 主干 `file_level=DEBUG`。
  任何会在日志里打印参数的第三方库都会命中。
- **为什么容易复发**：三个抽象各自都"看起来对"——"root 开低才收得到记录"、"文件收 DEBUG"、
  "脱敏只在 pipeline 一处"（pattern 簇只认凭据形状，认不出散文）。单看任何一层都发现不了 D4
  「零原文默认」被整条旁路。靠逐个库加降噪名单永远追不上：新依赖、P5 的 MCP SDK、任何驱动
  都会带来新的参数日志。
- **纪律**：**HARD C20**（机器守 + 人工判据）。① 装配永不降 root，只给 `questor` 子树定级
  （`Logger.callHandlers` 不遍历祖先级别）；② pipeline 有**来源门**：非 `questor.*` 的记录有效
  下界恒为 INFO；③ 验收必须跑真进程 grep canary，不能只测 `LogEntry` 构造
  （`tests/integration/test_log_zero_plaintext.py`）。
- **关联**：Issue #126 / #129 / #130；ADR-0027 复审修正；DESIGN D10、§10、§11。

### 2. 治理管线把错误"合并"掉（节流与事件形状错配）

- **现象**：两个 run 在同一 1 秒窗内各失败一次，日志里只有第一个 run 的 `run_failed`，
  第二个 run **一行都没有**（合并出的窗尾 summary 仍归属第一个 run 的 `context`）。
- **触发条件**：节流签名是 `(logger, level, msg)`，而带外投影的 msg 恒为 `event <type>`——
  区分信息全在 `context`/`fields`，签名看不见。同 run 内 1 秒多条 `tool_completed`/`warning`
  同样被折成第一条。反向也错：用完整 msg 当指纹时，"同一行代码、值不同"的风暴零抑制。
- **为什么容易复发**：节流与投影是两个各自正确的模块，缺陷只出现在它们对"什么算同一条"的理解
  错位上；而且**静默丢日志比崩溃更难发现**——没有任何报错，只是排障时那一行不在。任何"msg 不带
  区分信息、靠 fields 区分"的新记录类型都会再踩一次。
- **纪律**：① ERROR/CRITICAL **完全绕过节流**（C6 例外款：错误类不得静默，折叠与丢弃同罪）；
  ② 签名 = `(logger, level, msg 形状, run_id)`，形状归一（数字/十六进制/引号串 → `<*>`）；
  ③ 新写一类"只靠 fields 区分"的记录时，必须同时给它一条跨实体不合并的判据
  （`tests/unit/observability/test_pipeline.py`）。
- **关联**：Issue #128 / #131 / #132 / #133；DESIGN §13；HARD C6、C18。

### 3. 关联上下文不过线程/进程边界（`run_id` 静默缺失）

- **现象**：真 run 的日志文件里，绝大多数行（实测 80/85）`context` 为空，一条都不带
  `run_id`/`turn`——它们全产生于 aiosqlite 的专用工作者线程。
- **触发条件**：`bind()` 用 `contextvars`，它只随 `asyncio.create_task` 复制，**不进入
  `threading.Thread`，更不出进程**。凡在线程池 / 工作者线程 / 子进程里打日志都拿不到关联。
- **为什么容易复发**：P5 会把工具与 MCP server 搬进线程与子进程，"日志里查不到这是哪个 run"
  会以新面貌再出现；而它看起来像 `bind` 的实现 bug，容易被拿去加锁、加透传层，越修越复杂。
- **纪律**：① 跨线程/子进程**禁止依赖 ambient `bind()`**，关联键必须显式随记录传
  （`extra={"log_fields": {"run_id": ...}}`）；② 子进程侧 `run_id` 注入方式（文件名 / 首行前缀）
  必须在 `plan/05` 的 §0 扫描表里先定案；③ **不**给 `contextvars` 加自建传播层——语言事实，认它。
- **关联**：Issue #130；DESIGN §5.6；P5 前置门槛（与 G-L7 跨进程写同属"进程/线程边界"未收口面）。

### 4. 第三方库的日志出口不在 `logging` 管辖内

- **现象**：`--list` 的 stdout 混入 `HH:MM:SS - LiteLLM:DEBUG: logging_worker.py:561 - ...`，
  而 console sink 明明绑的是 stderr。
- **触发条件**：litellm 给自己的三个包级 logger 挂了 `LevelRoutingStreamHandler`（**stdlib
  Handler，不是 loguru**），按级别分流：INFO/DEBUG → `sys.stdout`，WARNING+ → `sys.stderr`。
- **为什么容易复发**：降噪白名单与级别门只能决定"要不要生成记录"，**决定不了对方向哪个流写**。
  更要命的是首轮误判：以为是 loguru，写了 `remove()/add()`，`AttributeError` 被 fail-soft 吞掉，
  判据静默 skip——"用假机制换了一个永远不跑的绿色用例"。
- **纪律**：① **谁引入副作用谁治**：在唯一 import 该库的适配器模块里摘掉它写 stdout 的 handler
  （不违反内核零依赖，因为内核根本不 import 它）；② 验收判据必须**不可 skip**、且是白名单式
  "stdout 每行 ∈ 机器可读集"——带关键字的正则对第三方行天然免疫，等于没判据（G-L10）。
- **关联**：Issue #127；HARD C14/C15（守卫必须能判红）；DESIGN §10。

### 5. 带外投影逐消费者调用 = 多 surface 双投（收口只能 bus 级一处只读订阅）

- **现象**：同一条 Envelope 在主干 JSONL 出现**两份**带外事件行；且同 run 多一个消费者就多一份。
- **触发条件**：`log_envelope` 挂在**每个** surface 消费者的循环里（P5 时只有 CLI `_stream` 调、看着没事）；
  P7 桌面使同一 `InProcessEventBus` 上**同时**有 SSE 订阅者 + CLI 打印者（+ 以后 IM/OpenAI 兼容），各消费者各投一次就翻倍。
- **为什么容易复发**：逐消费者投影在每个 surface 里都“看起来只投自己那一份”，缺陷只在“多个 surface 共享一个总线”时
  才暴露；而第 2 条“节流签名看不见区分信息”会把它伪装成“偶尔少一行”而非“翻倍”，极难定位。**任何新增 surface 都会再踩一次**。
- **纪律**：投影是**总线级单一副作用**，不是消费者职责。收口点写死为 bus 级**一条只读订阅**（`InProcessEventBus.add_observer`，
  `emit` 对每条投影后 Envelope 恰触发一次、与订阅者数量无关）；消费者（`cli._stream`）**不得**再调 `log_envelope`。
  验收必须跑**真文件 canary**：开 2 个并发 `/events` 订阅者跑同一 run，主干日志每 seq **恰一行**（`tests/integration/test_p7_out_of_band_projection.py`）。
- **关联**：ADR-0033 / plan/07 D-P7-A；HARD C6（折叠/合并同罪）/C20（第二载体）；本文件第 2 条；`surfaces/cli.py`、`surfaces/http_sse.py`。
