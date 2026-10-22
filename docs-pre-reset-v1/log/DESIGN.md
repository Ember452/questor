# Questor 日志系统设计（长远最优版）

> 状态：设计定稿待评审（未实现）。本文按"三年后不需要回头改"为唯一判据撰写，**不受当前 `STRUCTURE.md` / `.importlinter` / ADR 口径约束**；与现状冲突处已在 §17 逐条列出需要修订的文档。
> 实现前必须经一次对抗式评审，攻击点已在 §16 标出。

---

## 0. 一句话架构

**两个入口、一个中间表示、一条治理管线、多个 exporter。**

```
带内  业务 logging.getLogger("questor.kernel.loop").info(...)
        └→ stdlib LogRecord ──[BridgeHandler]──┐
                                               ├→ LogEntry → [脱敏] → [节流] → [级别] → Exporter[]
带外  Envelope ──[事件投影适配器]───────────────┘                                    ├ console(stderr)
        （唯一允许 import questor.* 的文件）                                          ├ questor-<date>.jsonl
                                                                                     ├ errors-<date>.jsonl
                                                                                     └ llm-<date>.jsonl（可选，默认关）
```

治理逻辑（脱敏、节流、级别、渲染、轮转）**全流水线只实现一次**，覆盖两条通道。这是采 B2（自有中间表示为主干）而非 B1（stdlib 为主干）的唯一但充分的理由。

---

## 1. 定位与非目标

**定位**：本系统是 `event_log` 的**人类可读旁路镜像**，加上**账本天生装不下的那一类信息**（第三方库噪声、provider 原始错误、耗时、内存/句柄压力）。它是排障面，不是事实源。

**非目标（明确不做）**：

| 不做 | 理由 |
|---|---|
| 成为"每一步记录"的权威存储 | `event_log` 已由 ADR-0020 定为耐久事件唯一真相。日志做第二份 = 双写漂移 |
| metrics / tracing / OTel 上报 | 属 P10 追踪面板。本设计只保证 `trace_id` 能作为普通键进入 `fields`，不实现任何导出器 |
| 远程收集 / 网络 exporter | **永久红线**：日志可能含 prompt 片段，网络出口是凭据外泄的新表面积 |
| 把业务诊断信息事件化 | 违 I3（delta 不持久）与账本膨胀；带外只投影已有 Envelope，不新造事件类型 |
| 替代测试断言 | 日志可被断言（JSONL），但不是契约载体 |

---

## 2. 已定决策一览（含被否备选）

| # | 决策 | 选定 | 被否的备选 & 否掉它的理由 |
|---|---|---|---|
| D1 | 物理归属 | 留在 `src/questor/observability`，内部三层；内核文件**零 `questor.*` 依赖** | 现在抽 workspace 独立包 → 短期不发布，却要付双 pyproject/双版本/CI 改造；且参照 10 家仅 cordis 拆包 |
| D2 | 调用契约 | **双通道**：带内 stdlib + 带外事件投影 | 只门面 API → 每层 import、签名泄漏 questor 类型即毁 D1；只带外 → provider 原始 4xx 与第三方噪声永远进不来 |
| D3 | 汇流点 | **B2**：自有 `LogEntry` 为主干，写一次 stdlib 桥 | B1（全走 stdlib record）→ 治理只有一套，但"可发布内核"退化成配置脚本，且人读视图需反向解析自己格式化的文本 |
| D4 | payload 边界 | **默认零原文**：只落 `sha256` + token + 耗时 + finish_reason + 错误分类；`--log-payload` 显式开启才落截断 preview，且必过脱敏 | 默认落 2000 字 preview（DeepCode 型）→ 日志文件永久含用户代码，而它比 DB 更容易被顺手贴进 issue |
| D5 | 关联 id 注入 | **α′**：kernel 在 `drive_controller` 两处 bind，**每轮从权威 `turn` 重盖章** | β（带外投影喂 contextvar）→ 边界处静默错号，测不出来；γ（surfaces 只绑 run_id）→ P9 新入口必忘，且字段不可扩 |
| D6 | 并发原语 | **`contextvars`**，作用域 = 一个 asyncio task | `threading.local`（hermes 型）→ `http_sse` 一进程并发 N 个 run，表现为日志串号 |
| D7 | 轮转 | **按记录自身日期推文件名**，无状态、跨进程天然安全；超阈值只告警不 rename | `RotatingFileHandler` → Windows 下第二进程持 append 句柄时 `os.rename` 必 `WinError 32`，文件钉死在阈值、每次 emit 刷 stderr |
| D8 | 新依赖 | **不引入**（stdlib only）；`concurrent-log-handler` 因 D7 不再需要 | 引 loguru/structlog → 需维护 stdlib↔自有双栈桥接，且第二套 sink 语义与 D1 的"可抽包"争夺同一份治理逻辑 |
| D9 | 落盘格式 | **JSONL**（机器可断言），人读视图由渲染器从同一 `LogEntry` 产出 | 纯文本 → 无法写"载荷脱敏"这类验收断言，只能人读 |
| D10 | 级别策略 | **双档**：console `INFO` / file `DEBUG`，但 **`DEBUG` 只对一方记录开**——非 `questor.*` 的记录有效下界恒为 `INFO`（来源门，见 §11）。root logger 也**不被降到 DEBUG**，只给 `questor` 子树定低级别 | 单档 → 要么终端刷屏，要么落盘丢掉排障最需要的细节；把 root 降到 DEBUG → 所有第三方库的参数级日志（含 aiosqlite 把 SQL+参数元组整个打出来）灌进主干文件，D4 的零原文当场被旁路 |
| D11 | `fields` 值域 | **白名单标量**，非白名单对象当场 `TypeError` | 收 `object` → "不许把 `Run`/`Envelope` 塞进日志"只能靠 ADR 自律与 review 人眼 |
| D12 | 脱敏点 | `LogEntry` 构造完成后、进 exporter 前的**唯一一处 filter** | 构造时脱敏 → 两个构造点两次会忘，且覆盖不到 `msg`/`fields`/`traceback` 三个面 |
| D13 | exporter 异常 | **绝不上冒**：计数 + 一次性自我禁用 + stderr 一行 | 冒泡 → 一个磁盘满/文件锁把 agent loop 带崩，观测面拖垮被观测物 |

---

## 3. 三层形状与目录

```
src/questor/observability/
  entry.py          # LogEntry + 白名单校验 + 级别枚举            ← 内核，零 questor.*
  scope.py          # bind()/reset() contextvar，**标量            ← 内核，零 questor.*
  redact.py         # 唯一脱敏 filter（pattern 簇 + fail-closed）   ← 内核，零 questor.*
  exporter.py       # Exporter 协议 + 注册/注销（返回 callable）    ← 内核，零 questor.*
  sink_console.py   # stderr 渲染（UTF-8 errors=replace）          ← 内核，零 questor.*
  sink_file.py      # 按日 JSONL + errors 分流 + 超阈值告警         ← 内核，零 questor.*
  bridge.py         # stdlib Handler → LogEntry（含 depth 爬栈）   ← 内核，零 questor.*
  pipeline.py       # 脱敏→节流→级别→exporter fan-out              ← 内核，零 questor.*
  configure.py      # configure_logging(...) 参数化装配            ← 内核，零 questor.*
  projection.py     # Envelope → LogEntry                          ← ★ 适配层：唯一允许 import questor.contracts
```

**三层对应关系**：协议层 = `entry.py` + `exporter.py`（只定义形状与注册，不决定去处）；实现层 = `scope/redact/bridge/pipeline/sink_*/configure`（治理与落地）；适配层 = `projection.py`（唯一知道 `Envelope` 的文件，抽包时**留在 questor**）。

**为什么全平铺、不建子包**：按"只在写得出可执行 import-linter 契约时才建子包"的判据，这里唯一写得出的契约是"内核 ⟂ `questor.*`"，它靠**显式模块清单**就能表达（G-L1），不需要目录边界；给 `sinks/` 建子包写不出独立于该契约的第二条规则，故 `console`/`file` 用文件名前缀分组而非目录。

**抽包彩排（必须能跑，但不产包）**：`scripts/check_log_kernel_isolation.py` 扫描上述"内核"文件，断言 import 图只含 stdlib + 白名单第三方；任一 `questor.*` 出现即判红，且带 `--self-test`（故意插一行越界 import 能判红，防假绿）。这条守卫通过 = 将来抽包是**纯机械搬目录**。

---

## 4. `LogEntry` 契约

刻意不叫 `Envelope`/`Event`/`Record`：前两者已被 `contracts/events.py` 占用且语义高度重叠，而日志记录**恰恰不是事件**（C13 规定 `event_log` 才是真相）；`Record` 与 stdlib `LogRecord` 在读者脑中同形。

```python
@dataclass(frozen=True)
class LogEntry:
    ts: datetime              # tz-aware 强制；naive 当场 ValueError
    level: LogLevel           # DEBUG|INFO|WARNING|ERROR|CRITICAL（自有枚举）
    logger: str               # 点分名："questor.kernel.loop" / "httpx" / "questor.events"
    msg: str                  # 已格式化文本（bridge 用 record.getMessage() 取，绝不含未展开 %s）
    fields: dict[str, str|int|float|bool|None]   # ★ 白名单值域
    traceback: str | None     # 保留完整栈；落盘时压掉空行（JSONL 单行约束，见 §6）
    source: Literal["inline", "event"]           # 通道来源
    context: dict[str, str|int|float|bool|None]  # bind() 注入的关联键，同白名单
```

**白名单是这套设计里唯一的"结构性防腐化"机制**：它把"日志不得携带 questor 领域对象"从文档纪律变成运行时 `TypeError`。第一个试图 `fields={"run": run}` 的人在本地测试当场炸，而不是半年后抽包时才发现拆不动。

不变式（`__post_init__` 内强制，全 fail-closed）：

- `ts` naive → `ValueError`；必须 tz-aware。
- `fields`/`context` 值出现非白名单类型 → `TypeError`（**不是静默 `str()` 转换**）。
- `msg` 长度超 `max_msg_chars`（默认 8 KiB）→ 截断 + 附 `msg_truncated: True`，禁止无限长行污染 JSONL。
- `source` 只允许二值；带外投影必须 `"event"`。
- `context` 与 `fields` 出现同名键 → `ValueError`（fail-loud；禁止静默覆盖或靠合并顺序定义语义）。

---

## 5. 关联上下文：`bind()`

```python
@contextmanager
def bind(**kv: str | int | float | bool | None) -> Iterator[None]:
    """加键语义：新增强调字段 = 加一个 kv，不改签名。"""
```

设计要点：

1. **不是 `bind(run_id, turn)` 两个固定槽**。P8 子 agent 要 `parent_run_id`/`agent_id`/`task_path`，P10 tracing 要 `trace_id`/`span_id`。固定槽意味着将来改**已发布签名**（破坏性变更）。加键语义下，这些都是新增一个键。
2. **`contextvar` + task 作用域**（D6）。一个进程并发多个 run 时，每个 run 的 bind 只影响自己的 task 树——这是 `asyncio.create_task` 的既有语义，无需自建锁。
3. **落点只有两处，都在 `DefaultTurnLoop._drive_controller`**：
   - `_settle_open_calls` 之后（覆盖新鲜 run 与 resume 两条路）→ `bind(run_id=run.run_id)`
     （2026-10-16 注：该函数原名 `_resume_settle_open_calls`，ADR-0028 改为中性名，因为它是
     resume 入口与“回发前配对关卡”共用的派发函数；本设计的 bind 位置语义不变）
   - `while True` 内 `turn += 1` 之后 → `bind(turn=turn)`，**每轮从 loop 自己的权威局部变量重盖章**
   选这里而不选 surfaces 的原因：`_drive_controller` 是**六条现存路径的唯一出口**（CLI 首发/CLI resume/HTTP 建 run/HTTP resume/legacy/`resume_and_drive` 两分支），且 P8 编排、P9 OpenAI 兼容 API 也必须经过它。放 loop = 新入口默认正确；放 surfaces = 每个新入口都要记得 bind。
   与 ADR-0028 关卡的关系：关卡（`_stream_turn` 内的 `_ensure_paired_history`）可能在**当前 turn 窗口内**
   串行补执行多个工具，而它跑在 `turn += 1` 之后——所以带内 `turn` 盖章仍覆盖得到，无需新增 bind 点。
4. `turn` 每轮重盖章 ⇒ 号不可能漂移。这比"手工在 N 个地方 bind 一次"强，因为后者随代码演进必然漏点。
5. `seq` **不在带内**（带内代码不知道 seq），只在带外投影里由 `Envelope.seq` 带上。
6. **关联不过线程/进程边界（纪律，Issue #130）**：`contextvars` 只随 asyncio task 复制，不进入
   `threading.Thread`，更不出进程。因此：
   - 在工作者线程里打的日志（典型：aiosqlite 的 SQL 日志）**拿不到 `run_id`**——这是语言事实，
     不靠包管理或额外锁去“补上”；它们本身也已因来源门不进主干，不是关联面的责任。
     实测：未加来源门前一次真 run 的 85 行里 80 行来工作者线程且 `context={}`。
   - **我们自己的代码跳线程/子进程时，关联键必须显式传**（`extra={"log_fields": {"run_id": ...}}`），
     不得依赖 ambient `bind()`。
   - P5 的 MCP server 是**子进程**，边界更严：`run_id` 注入方式（日志文件名还是首行前缀）必须在
     `plan/05` 的 §0 扫描表里先定案，不得默认它能继承上下文。

合规性说明：`S7` 原文"observability **可被各层调用**，但只依赖 contracts"，且 AST 检查器把 `observability` 列入 `CROSS_CUTTING`（"any layer may import these"）。**kernel → observability 的 import 是明文允许的**，本设计不与之冲突。真正的红线只在反向（见 §11）。

---

## 6. 带内桥：`bridge.py`

一个 `logging.Handler`，装上 root，把 `LogRecord` 转成 `LogEntry`。

**必须修正调用点深度**。不爬栈则所有带内日志的 `%(filename)s:%(lineno)d` 都显示成桥文件，等于废掉定位能力。配方（DeepCode 已验证跨 CPython 3.12–3.14 稳定）：

```python
frame, depth = sys._getframe(), 0
while frame is not None and (depth == 0 or frame.f_code.co_filename == logging.__file__):
    frame = frame.f_back
    depth += 1
```

从 `sys._getframe()` 起爬，**不用 `logging.currentframe()`**——后者在 logging 包内的偏移属 CPython 实现细节。

桥的产物：`msg = record.getMessage()`，`traceback` 由 `record.exc_info` 格式化并**压掉空行**（JSONL 一行一条记录，空行会撕裂按行解析），`fields` 取 `record.__dict__` 中经白名单允许的键（`extra={"log_fields": {...}}` 是唯一入口，**禁止把任意 record 属性透传**——第三方库会往 record 上塞大对象）。

**不替换全局 `LogRecordFactory`**：hermes 用它是因为它把 `session_tag` 塞进 formatter 模板；本设计的关联字段在 `LogEntry` 构造处从 contextvar 读，不需要给全进程每条 record 加属性，因此少一个全局猴子补丁。

**降噪白名单**（钉在 WARNING，否则 litellm/httpx 会把有用信息埋掉）：`openai`, `openai._base_client`, `httpx`, `httpcore`, `asyncio`, `hpack`, `grpc`, `urllib3`, `websockets`, `charset_normalizer`, `markdown_it`, `litellm`（litellm 单独定 WARNING：它的请求日志体量大且与我们的 `llm-<date>.jsonl` 重复）。

---

## 7. 带外投影：`projection.py`

唯一允许 `import questor.contracts.events` 的文件，也是抽包时**留在 questor 侧**的文件。

- 事件→级别映射：错误类（`run_failed`/`warning`/`resync_required`）→ `ERROR`/`WARNING`，**绝不静默**（C6）；里程碑类（`run_started`/`run_completed`/`run_cancelled`）→ `INFO`；其余 → `DEBUG`。
- **live-only 事件不进日志**：`text_delta`、`reasoning_delta`、`tool_progress`、`heartbeat`、`usage_delta`、`node_updated`。理由与 I3 同源——它们要么体量无界，要么是热路径风暴源。
- **带内/带外同 `source` 标记**，这是 §9 纪律"日志不得是唯一载体"的执行点：排障时能一眼看出这行是账本的镜像还是账本外的独有信息。
- 载荷渲染：只取白名单键（`error.code`/`error.message`/`status`/`exit_reason`/`name`/`tool_use_id`/`seq`/`gseq`），**不做全量 `json.dumps(env.data)`**（那是把 prompt 与工具结果整包抄进日志文件的捷径）。
- `Envelope` 在 `project` 转发点旁挂一个只读订阅者产出投影，**不改动 bus 的持久化路径**；bus 自身故障（订阅者队列溢出、persist 失败）用 `questor.bus` logger 出声——该 logger 今天被定义却是死代码，正说明这类故障当前无人报。

---

## 8. 脱敏（`redact.py`）

全系统**唯一一处**，位于 `LogEntry` 构造完成之后、fan-out 之前，作用于 `msg` + `fields` 值 + `traceback` 三个面。

- **fail-closed**：无法判定是否敏感时按敏感处理，宁可丢信息不可漏凭据。脱敏自身抛异常 → 整条 entry 替换为 `<unredactable>`，**不得让原文穿过**。
- 覆盖形状（pattern 簇，非穷举）：`Authorization`/`x-api-key`/`Bearer`、URL 内嵌 `user:pass@`、`api_key=`/`LITELLM_API_KEY` 形式的键值、PEM 私钥块、常见云厂商 AK 前缀、`sk-` 前缀密钥。
- **绝不执行凭据**：日志/脱敏路径上不得调用任何可调用对象取 token（hermes 对 Azure Entra bearer 就是只标 `<entra-id-bearer>`，绝不在日志路径 refresh）。
- **prompt 回显剥离**：provider 4xx 常把请求体整段回显，错误文本里包含用户 prompt。除 pattern 脱敏外，对带外错误载荷额外做"与本轮 prompt 共享长片段 → 替换为 `<prompt>`"的处理。
- 每条被脱敏的 entry 加 `fields["redacted"]=True`，使"这次排障是不是被脱敏挡住了"可查询。

---

## 9. 与 `event_log` 的分工纪律

**唯一权威规则**：*日志不得是任何信息的唯一载体，除非该信息本来就不在账本里。*

- 允许冗余：`run_started`/`tool_completed` 的索引行（type + `run_id` + `seq` + 一行摘要）在日志里重复账本内容，为了 `tail -f` 无需开 sqlite 客户端。
- 禁止唯一：任何新的业务事实**必须先成为事件进 `event_log`**，再考虑投影。想加"只写日志不写账本"的字段是设计违例，评审必须拦。
- 允许账本外独有：第三方库日志、provider 原始错误文本（脱敏后）、耗时、内存/句柄压力、装配期诊断、exporter 自身健康。

---

## 10. Sink 与文件策略

```
QUESTOR_LOG_DIR     默认 <cwd>/.questor/logs/
questor-<YYYYMMDD>.jsonl   主干（file_level 默认 DEBUG）
errors-<YYYYMMDD>.jsonl    WARNING+ 分流（体量小、优先看）
llm-<YYYYMMDD>.jsonl       可选独立通道，默认不写
```

- **按日切，无 rename**（D7）。同一进程跨日自动换文件；文件名从记录自身 `ts` 推得 → 无状态、跨进程安全、**且天然可 GC**（删过期文件即可，无需读内容）。
- **软阈值**：单文件超 `max_size_mb`（默认 50）→ 追加一条 `WARNING` 自告警 entry，**不做轮转/改名**。
  硬上限由"按日切 + 保留 N 天"提供。**提级只对“当日”生效，不是进程终身制**（Issue #135）：字节预算按
  记录日期分桶、三个 lane 都计入，换日自动回到调用方要求的 `file_level`——否则“第一天很噪”会把此后
  所有分片永久降到 INFO，而除了 `logging_status()` 无处发现。
- **保留期**：`QUESTOR_LOG_KEEP_DAYS` 默认 14；由 `configure_logging` 启动时懒清理一次，不在写路径删文件。
- **`llm-<date>.jsonl` 独立成文件的理由是隐私而非整洁**：它是唯一可能含 prompt 截断 preview 的通道，独立文件才能单独授权、单独清理、单独在打包/分享诊断包时排除。
- **best-effort 落盘**：日志目录不可创建/不可写（桌面装到 `Program Files` 下非管理员运行、或 CWD 只读）→ 降级为 console-only + **一次性** WARNING，**绝不在 import 期或启动期崩进程**。降级状态必须可查询（`logging_status()`），否则"日志没写"本身会变成一个待排的故障。
- **只写 stderr，永不写 stdout**：`--list` 等机器可读输出走 stdout，带内 sink 走 stdout 会污染它。
  **不只管我们自己怎么写**：第三方库会给自己挂 handler 并直写 stdout——litellm 用的
  `LevelRoutingStreamHandler`（**是 stdlib Handler，不是 loguru**）按级别分流，INFO/DEBUG 落 stdout、
  WARNING+ 落 stderr——所以"把 logger 钉到 WARNING"只能挡住一部分，消不掉绑在 stdout 上的那条流。
  口径定为"谁引入副作用谁治"：在 `providers/litellm_adapter.py`（全仓唯一 import litellm 处）摘掉它
  写 stdout 的 handler（Issue #127；可见性不丢——那些 logger `propagate=True`，记录仍进 root 上的桥）。
  验收判据必须是白名单式“stdout 每行 ∈ 机器可读集”，带关键字的正则对第三方行天然免疫，不算判据。
- **编码**：所有流包装 `errors="replace"`；stderr 非 UTF-8（Windows 中文 locale）时不得抛 `UnicodeEncodeError`。
- **v1 同步写，不引 QueueListener**：buffered append 单行 µs 级，当前规模（每 run 数百行）不需要线程；`QueueHandler/QueueListener` 是 hermes 为多 handler 大体量引入的，在骨架期是**纯风险**（teardown 时 `join()` 是测试挂死的经典源，本项目已知进程/线程竞态教训）。**升级触发条件**（写进文档而非记忆）：`dropped_records>0` 或 p95 写延迟超标或出现真实现场证明写阻塞 loop。teardown 期 `ValueError("closed file")`/`OSError(EBADF)` 一律吞掉。
- **跨进程行原子性的取舍**：Windows 上无跨进程锁的并发 append 可能交错；约束“单行一次 flush + `max_msg_chars`≤8KiB”把风险压到极小但非零。**接受 rare 交错**：JSONL 读取器跳过损坏行并计入 `malformed_lines`，不引跨进程锁（DeepCode 的按日无状态 sink 同样取此舍）。

---

## 11. 装配

`configure_logging(...)` 由**组合根唯一调用**。四条现存入口（REPL / `--resume` / `--list` / `--dream`）
都经 `__main__._amain` 起手的装配；env 解析与 payload 门住在 `surfaces/_assembly.assemble_logging()`，
第二个生产入口（`python -m questor.surfaces.cli`）**调同一个函数**——Issue #138 的教训：它以前裸调
`configure_logging()`，既不建文件面也无视 `QUESTOR_LOG_*` 与 payload 门，"唯一装配口径"事实上碎成两半。

- **root 不被降到 DEBUG**（D10/Issue #126）：那等于替全仓每个第三方库打开参数级日志，而参数里装着
  prompt 与账本内容。root 仅在 NOTSET 时定在 INFO，另对 `questor` 子树显式 `setLevel(console/file 较低门)`
  ——`Logger.callHandlers` 不遍历祖先级别，所以一方 DEBUG 照样能进桥。同时在管线侧加**来源门**做纵深
  防御：非 `questor.*` 的记录有效下界恒为 INFO（逐个库打降噪名单永远追不上，默认拒绝才可扩展）。
- **一方记录要自述**：装配完落一条 `questor.assembly` INFO（目录/门/是否降级），组合根再落一条
  `questor.composition`（store/记忆库就绪）。DoD A① 的"起手即有日志"必须由一方记录兑现——
  此前它能"绿"全靠第三方噪声凑数，而修完来源门后那些噪声就不来了。
- 幂等 + `force=True` 重配；重复调用不叠加 handler（否则每条日志打 N 遍）。拆装配时**先 flush 窗尾、
  再注销 sink**（顺序反了补行就无处可写），并在装配时注册 `atexit` flush（Issue #136：否则"窗尾补
  repeated N times"只存在于测试里）。
- **参数由调用方传入，日志器绝不自己读 config**：`observability ⟂ config` 是既有 independence 契约，且"配置由外部注入"正是可发布内核的必备形状（cordis 的 `_resolveConfig` 同构）。`QUESTOR_LOG_*` 这类环境变量的读取放在组合根，不放内核。
- sidecar（`http_sse`）由宿主进程入口调用同一 `assemble_logging`，不自配一套。

---

## 12. LLM 观测面

`providers/litellm_adapter.py` 在每次调用结束（成功或失败）产一条 `llm` 通道 entry，字段：

```
provider, model, duration_ms, status(ok|error|cancelled), finish_reason,
prompt_tokens, completion_tokens, request_sha256, response_sha256, error_class
```

默认**零原文**（D4）。`--log-payload=off|truncate:N`（默认 `off`）才追加 `arguments_preview`/`response_preview`，截断 + 必过脱敏 + 只写 `llm-<date>.jsonl`。

`sha256` 的作用不是压缩，是**同一请求的可辨识性**：排"重试/重复/缓存"类问题时能确认"是不是同一次请求"，而不需要原文。

**工具侧观测**不在此系统内造新通道：工具结果已进 `tool_completed` 事件（账本），日志只投影其摘要行；工具的 stdout/stderr 属 artifact，不抄进日志。

---

## 13. 自我观测

- `exporter` 异常 → 计数 + 一次性 stderr 一行 + 该 exporter 自我禁用；`logging_status()` 返回 `{degraded: bool, disabled_exporters: [...], dropped_records: int, files: [...]}`。
- 队列满丢弃计数必须可见（否则"日志少了"不可归因）。
- **节流**在 pipeline 一处实现：`(logger, level, 消息形状指纹) → 窗口内合并计数`，窗口默认 1s，窗口结束补一条 `… repeated N times`。带外热路径（`usage_delta`/`node_updated`）由 §7 直接丢弃，不进节流——丢弃比合并更省，因为它们无信息量。依据：R08 E-P3 记录过"每次模型调用都打点 + Windows 跨进程锁 = 风暴锁、钉住一核、卡死事件循环"。

---

## 14. 消费面（后置，不进骨架）

`python -m questor logs [--run ID] [--level WARNING] [--since 1h] [--component tools] [-f] [--timeline]`

- 主干查询走 **`event_log`**（权威），日志文件作为"账本外信息"的旁路补充，两者按 `run_id + seq` 合并成时间线。
- `--timeline` 输出 markdown + JSON 双份，供贴进 issue / 交付报告。
- `llm-<date>.jsonl` 默认排除在分享型产物之外。

---

## 15. 守卫与 DoD（每条必须能判红）

| 守卫 | 判据 | 判红方式（self-test） |
|---|---|---|
| G-L1 内核零依赖 | `entry/scope/redact/exporter/sink_*`/`bridge/pipeline/configure` 的 import 图只含 stdlib + 白名单 | 往 `entry.py` 插 `import questor.contracts` → 必须红 |
| G-L2 类型不泄漏 | 内核模块签名与 `fields` 值域中不出现 questor 类型名 | 加一个 `def f(x: Envelope)` 到内核 → 必须红 |
| G-L3 脱敏覆盖 | 喂含 `sk-...`/`Authorization:` 的 msg、fields、traceback 三面 → 落盘 JSONL 三处均无该串 | 摘掉一个面 → 必须红 |
| G-L4 白名单拒绝 | `fields={"run": <obj>}` 抛 `TypeError`；非 tz-aware `ts` 抛 `ValueError` | 放宽为 `str()` → 必须红 |
| G-L5 inline 必带关联 | 跑一遍真 loop，断言每条 `source=inline` 且 logger 以 `questor.` 开头的 entry 带 `run_id` 且 `turn` 单调 | 注释掉 `bind(turn=...)` → 必须红 |
| G-L6 桥调用点保真 | 断言 entry 的 `filename`/`lineno` 指向真实调用处而非 `bridge.py` | 删爬栈循环 → 必须红 |
| G-L7 跨进程按日写 `[非阻塞·夜间]` | 两个真实 OS 进程并发写当日文件，行数守恒、无 rename 失败、无异常 | 换回 `RotatingFileHandler` 触发 rename 竞争 → 应红（Windows） |
| G-L8 幂等装配 | `configure_logging()` 两次不产生重复行（每 msg 恰 1 次） | 去掉 initialized 检查 → 必须红 |
| G-L9 不可写降级 | 只读目录下 `configure_logging` 不抛异常、`degraded=True`、仍产 console 行 | 改成硬失败/静默成功 → 必须红 |
| G-L10 stdout 洁净 | `--list` 的 stdout 不含任何日志行 | 把 console sink 指 stdout → 必须红 |
| G-L11 唯一真相纪律（AST） | AST 扫 `projection.py`：其引用的每个载荷键都必须出现在静态投影白名单常量里 | 往 projection 加白名单外的新键 → 必须红；**诚实边界**：此守卫只守住投影这一条路，“在业务里新造只写日志的事实”仍靠 PR 评审清单，不得假称机器已守 |
| G-L12 traceback 无空行 | 含异常链的 entry 落盘为**单行**，栈完整 | 用默认 `format_exc()` 不压空行 → 必须红 |

冷导入守卫（`import questor.observability` 及每个子模块）、`lint-imports` 既有四契约保持全绿；本设计**新增第五契约**（G-L1 对应的 `observability 内核 ⟂ questor.*` forbidden 契约）。

**守卫自身的维护成本声明**：G-L7 属进程树竞态高发区（本项目已有进程树超时/冷启动竞态教训），**不进 PR 阻塞门**，夜间或手动跑、Windows 门控；任何守卫连续两个 Phase 误报即降级为非阻塞——守卫是代码，也会腐烂，防它自己变成维护负担。

覆盖率：内核（纯函数 + 桥 + pipeline）目标 ≥90%；sinks/文件路径用 tmp 目录真 IO，不用 mock 冒充。

---

## 16. 提交对抗评审的三个攻击点

我自己判过，但不能自证。评审需专门攻：

1. **白名单只防住 `fields`，防不住 `msg`**。`logging.getLogger(...).info("run=%s", run)` 会把 `Run` 的 `repr` 抄进 `msg`，绕过 D11 的一切拦截。可选解：带内对 `questor.*` logger 的 `record.args` 做"非白名单标量则 `repr` 后脱敏 + 长度封顶"，或禁 `args` 直接只收 `str`。**这条不解决，D11 是纸面守卫。** 我方倾向解（待对抗评审确认）：`questor.*` logger 的带内 `args` 只收白名单标量；非标量 → `repr()` 截断 800 字符 + 强制过脱敏 + `fields` 记 `args_coerced=True`。代价是 `info("run=%s", run)` 这类写法不再原样输出，换取 D11 从纸面变事实。
2. **α′ 的正确性依赖 `drive_controller` 一直是唯一汇流点**。P8 编排引擎若自己 `create_task` 起子 run（而非经 controller），或 P9 的 OpenAI 兼容层复用 controller 但绕过 loop，bind 就漏。需要一条"入口守恒"守卫（断言任何驱动 `reduce`/发事件的协程树必须经过 `drive_controller`），否则这是"将来会静默成立也可能静默失效"的假设。
3. **按日切放弃硬大小上限**，等于接受“单次 run 打出超大文件”的可能性（例如错误风暴下每轮一条 ERROR）。需要软阈值后的**主动降级**策略（超阈值自动把 `file_level` 提到 INFO），否则“省掉轮转”的收益被磁盘占满抵消。
4. **`contextvar` 不跨进程**。P5 的 MCP server 是子进程，其日志无法继承 `bind()` 的关联字段——这是“骨架先于 P5”承诺对子进程世界的例外。P5 plan 必须前置决策：MCP server 的 stderr 重定向到独立文件（hermes `mcp-stderr.log` 形状）+ 由 spawn 侧把 `run_id` 写进文件名或首行标记，**而不是假装 contextvar 能解决**。

---

## 17. 与现状的冲突清单（本文优先，需回改文档）

| 文档 | 需要修订 | 因为 |
|---|---|---|
| `STRUCTURE.md` S7 | 补"可被各层调用"的**方向声明 + 内核零依赖**双条 | 现只写"只依赖 contracts"，与可发布内核（连 contracts 都不许依赖）冲突 |
| `.importlinter` | 新增第五契约（内核 ⟂ `questor.*`） | G-L1 |
| ADR 索引 | 新增 ADR-0027（双通道 + 中间表示 + 载荷政策） | D2/D3/D4 |
| `docs/ROADMAP.md` §1.5 P10 备注 & 373 文件配额 | observability 需分文件数与规模 | 现规划里 observability **一个文件配额都没分**，这是它能欠到现在没做的结构性原因 |
| `plan/01` T12 | 标"部分兑现"，把 `ErrorEntry`/脱敏/节流三缺口挂到本设计 | 该任务今天只有 46 行实现 |
| 环境变量 / CLI flag 族 | 新增 env `QUESTOR_LOG_DIR` / `QUESTOR_LOG_KEEP_DAYS` / `QUESTOR_LOG_LEVEL` / `QUESTOR_LOG_PAYLOAD`（CLI flag `--log-level` / `--log-payload` 为同名入口） | 与 `QUESTOR_STORE_PATH`/`QUESTOR_MEMORY_DB` 同族命名 |

---

## 18. 实施时序（三刀）

| 刀 | 内容 | 时机 | 判据 |
|---|---|---|---|
| **刀 1** | 装配上移覆盖四入口、启用 `questor.bus` 报总线故障、console sink 强制 stderr | **P4 PR 合并后立刻**，独立小 PR | 纯缺陷，不改契约不动分层，不该排进任何 Phase |
| **刀 2** | 本文骨架全套（§3–§13）+ ADR-0027 + G-L1..L12 守卫 | **P4 合入 main 之后、P5 开工之前** | ROADMAP §1.5 明写"轻量可观测从 P1 就落"——这是补债；P5 MCP 是第一个从进程外引入错误的项目（server 连不上、SKILL.md 解析失败、远程工具描述投毒），死线就在它之前 |
| **刀 3** | §14 消费命令、OTel/metrics/追踪面板、`--log-payload` 实装 | 真需求出现时（P7 桌面调试 / P10 加固） | 不预排；`llm-*.jsonl` 的独立文件已在刀 2 留好，届时不需改骨架。**P10/ADR-0049 已落地（2026-10-19）**：`questor logs` 只读消费命令（DESIGN §14）+ `--log-payload=truncate:N` preview（§12，走独立 `questor.llm.preview` 通道、主干零原文、必过脱敏）均实装；`trace_id` 作普通键保留；**OTel/metrics 移出本 Phase**（守 D8 stdlib-only、不在 P10 DoD，真需求+独立 ADR 再开）。 |

判据一句话，供后续复用：**任何会新增"入口"或新增"错误来源"的 Phase，必须排在日志骨架之后。**

---

## 19. 参照证据锚点

| 采什么 | 出自 | 出处 |
|---|---|---|
| 协议留内、sink 实现可独立发布；配置由容器注入 | **cordis** | `packages/core/src/logger.ts`（`Message`/`Exporter`/`_resolveConfig`/`bufferSize`）、`packages/logger-console/package.json`（`@cordisjs/plugin-logger-console`，description "Console logger exporter"） |
| Windows 多进程轮转死结、`errors.log` 分流、降噪白名单、幂等 `setup_logging`、Unicode 安全 stderr、QueueListener | **hermes** | `hermes_logging.py` L75-101 / L216-227 / L326-404 / L147-163 |
| stdlib↔自有栈桥的 depth 爬栈配方、traceback 不留空行、按记录时间戳推文件名的跨进程安全轮转、LLM 独立 JSONL 通道 + preview 截断 + sha256 + 绝不上网 | **DeepCode** | `core/observability/bus.py` L58-92 / L123-221 / L464-470、`core/observability/records.py`、`tests/test_log_tracebacks.py` |
| 控制台/文件双级别 | **MetaGPT** | `metagpt/logs.py:40-52` |
| 结构化事件即日志行（`__str__` 出 JSON、自动带 agent 身份） | **autogen-core** | `autogen_core/logging.py` `LLMCallEvent`/`EVENT_LOGGER_NAME` |
| 路径不可写则降级 console-only、绝不在 import 期崩 | **CowAgent** | `common/log.py:37-57` |
| 日志做成诊断产品（sources/scan/timeline、可分享时间线） | **EvoFlow** | `evoflow/cli/commands/logs.py` |
| InferenceJournal 禁含 prompt/凭据/body；观测上报为只读旁路（sink 为 nil 即 no-op）；热路径节流窗 | **wuu**（R07/R08 转述） | `internal/providers/types.go` `InferenceJournal`、`failure_sink.go:48-51`、`credential_pool.py:152-160` |
| 反面：只有颜色开关、无 sink 治理无关联 id | CrewAI / OpenManus | `crewai/utilities/logger.py`、`app/utils/logger.py` |

---

## 20. 一句话收尾

这个系统最贵的不是代码量（骨架约 600–900 行），而是**三条一旦破就不可逆的形状**：中间表示的加键语义（决定 P8/P10 要不要改已发布签名）、`fields` 白名单（决定"可抽包"是事实还是愿望）、以及"日志不得是唯一载体"这条纪律（决定它会不会在两年后变成第二个 event log）。刀 2 之前把它们全部锁死，之后每加一个 Phase 都只是加内容。
