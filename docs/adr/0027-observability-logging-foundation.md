# ADR-0027: 日志骨架（双通道 + LogEntry 中间表示 + 零原文载荷 + 按日切 + 主动降级）

- 状态：✅（2026-10-16，决策定；规格真源 [`../log/DESIGN.md`](../log/DESIGN.md)，实现 [`../log/PLAN.md`](../log/PLAN.md) 刀 2 T2.2–T2.16）
- 背景：`event_log`（ADR-0020）是耐久事件唯一真相；日志是其**人类可读旁路镜像** + 装进账本不合适的那一类信息（第三方库噪声、provider 原始错误、耗时、句柄压力）。刀 1（PR-A）已补最严重缺陷——`configure_logging` 上移组合根覆盖四入口、`questor.bus` 报总线故障、console 绑 stderr；但**脱敏/节流/关联 id/白名单/文件面/双通道汇流**仍缺，且 ROADMAP §1.5 明写"轻量可观测从 P1 就落"——这是补债。死线在 P5（MCP 是第一个从进程外引入错误来源的 Phase）之前。实现前经一次对抗式评审攻 DESIGN §16 四攻击点（结论入本 ADR）。
- 决策：
  - **物理归属（D1）**：留在 `src/questor/observability`，内部三层（协议 `entry`+`exporter` / 实现 `scope`/`redact`/`bridge`/`pipeline`/`sink_*`/`configure` / 适配 `projection`）；九内核文件**零 `questor.*` 依赖**（连 `contracts` 都不许），使"将来抽包 = 纯机械搬目录"。短期不拆 workspace 包（不发布却要付双 pyproject/CI）。
  - **双通道（D2）**：带内 `logging.getLogger("questor.*")` 经 `BridgeHandler` 转 `LogEntry`；带外 `Envelope` 经 `projection.py`（唯一允许 import `contracts`）转 `LogEntry`。两条都在同一个 `LogEntry` 汇流，治理逻辑只实现一次。
  - **中间表示 B2（D3）**：自有 `LogEntry` frozen dataclass 为主干（不叫 Record/Event/Envelope：前两者语义已占、且"日志记录恰恰不是事件"C13）。
  - **载荷政策零原文（D4）**：LLM 通道默认只落 `provider/model/duration_ms/status/finish_reason/prompt_tokens/completion_tokens/request_sha256/response_sha256/error_class`，**无任何 prompt/响应片段**；`sha256` 用于同一请求可辨识性（非压缩）。`--log-payload` preview 截断实装后置刀 3。
  - **关联 id α′（D5/D6）**：kernel 在 `_drive_controller`（`loop.py:254`）两处 `bind`——`_settle_open_calls` 返回后（`:262`，原名 `_resume_settle_open_calls`，ADR-0028 改名）`bind(run_id=…)` 覆盖新鲜+resume、`turn += 1`（`:282`）后 `bind(turn=…)` 每轮从 loop 权威局部变量重盖章；用 `contextvars`（**task 作用域**，非 `threading.local`），因 `http_sse` 一进程并发 N run 需隔离。`seq/gseq` 不在带内（带内不知 seq），仅带外投影由 `Envelope.seq` 带上（ADR-0011）。
  - **轮转按日切（D7）**：文件名从记录自身 `ts` 推得 `questor-<YYYYMMDD>.jsonl`，无 rename、跨进程天然安全、天然可 GC（删过期文件）；保留期 `QUESTOR_LOG_KEEP_DAYS`(14) 启动懒清一次，不在写路径删。
  - **带内 `args` 政策（DESIGN §16.1，对抗评审确认设计倾向）**：`questor.*` logger 的 `record.args` 出现非白名单标量 → `repr()` 截断 800 字符 + 强制过脱敏 + `fields["args_coerced"]=True`（在 `bridge.py` 内、`record.getMessage()` 前预强转）。目的：把 D11 白名单从"只防 `fields`"扩到"也防 `msg`"，令"不许把 `Run` 抄进日志"从纸面纪律变运行时事实；纯拒收会丢有用摘要，故不采。
  - **软阈值主动降级（DESIGN §16.3，对抗评审定案）**：主干文件超 `max_size_mb`(50) → 追加一条明确自告警 entry + **自动把主干 `file_level` 提到 INFO**。三点消除"静默降精度"：① WARNING+ 的 `errors-<YYYYMMDD>.jsonl` 分流 lane **不受提级影响**（错误/警告永不丢）；② 提级动作本身落一条宣告；③ `logging_status()` 暴露当前 `file_level` 与 `degraded`。DESIGN §10 原只写自告警不写降级，是其自标的已知缺口——"省掉轮转"的收益必须靠此封顶磁盘，否则错误风暴会抵消收益。
  - **"日志不得是唯一载体"纪律（DESIGN §9）**：任何新业务事实必须先成事件进 `event_log` 再投影；`projection.py` 载荷只取静态白名单键（`error.code`/`error.message`/`status`/`exit_reason`/`name`/`tool_use_id`/`seq`/`gseq`），**不做全量 `json.dumps(env.data)`**。由 G-L11 AST 守卫守 projection 这条路的载荷键 ⊆ 白名单（诚实边界：业务里新造"只写日志"的事实仍靠 PR 评审清单）。
  - **脱敏单点 fail-closed（D12）**：全系统唯一一处 filter（`LogEntry` 构造后、fan-out 前）作用于 `msg`+`fields` 值+`traceback` 三面；pattern 簇覆盖 `Authorization`/`Bearer`/`x-api-key`/URL `user:pass@`/`api_key=`/PEM 块/云 AK 前缀/`sk-`；脱敏自身抛异常→整条替换 `<unredactable>`；命中加 `fields["redacted"]=True`；**绝不在日志路径执行凭据**（只标不 refresh）。
  - **exporter 异常不上冒（D13）**：计数 + 一次性自我禁用 + stderr 一行；磁盘满/文件锁绝不把 agent loop 带崩。
  - **装配参数注入、内核 env-free**：`configure_logging(...)` 参数全由调用方传入、**绝不读 config/env**（守 `config ⟂ observability` independence 契约；cordis `_resolveConfig` 同构）；`QUESTOR_LOG_*` 的读取放在组合根。幂等 + `force=True` 重配不叠 handler。
  - **落盘 JSONL（D9）+ 双级别（D10）**：机器可断言；console INFO / file DEBUG。v1 同步写、**不引 `QueueListener`**（升级触发条件写 DESIGN §10：`dropped_records>0` / p95 写延迟超标 / 现场证明写阻塞 loop）；跨进程 JSONL 行交错 rare 接受（读取器跳损坏行计 `malformed_lines`）。
  - **分层强制（机械）**：`.importlinter` 增第五契约（内核九文件 ⟂ `questor.*`）作**意图声明**；真正机械强制靠 `scripts/check_log_kernel_isolation.py`（G-L1/G-L2，含 `--self-test` 判红 + fail-on-empty）+ ruff/AST——与既有选型一致（import-linter 抓不到动态 import，R09）。
- 后果：
  - 正面——治理（脱敏/节流/级别/渲染/轮转）只实现一次覆盖两通道；关联 id 随新入口默认正确（放 loop 而非 surfaces）；白名单令 `fields={"run": obj}` 当场 `TypeError`，把"可抽包"从愿望变事实；隐私面（零原文默认 + llm 通道独立文件 + 无网络 exporter）守住。
  - 代价/需持续守——① `msg` 面靠 args 强转 + 脱敏兜底**非绝对**（人可把敏感串拼进字面 msg，仍靠脱敏 pattern + PR 评审）；② 主动降级在错误风暴降主干精度（errors lane 保底）；③ **入口守恒 §16.2**：对抗评审核当前 `drive`/`drive_controller`/`resume_and_drive`/`http_sse` 全经 `_drive_controller`、`bus.emit`/`reduce` 仅 loop 内 → α′ bind 对 P1–P4 成立；但 **P8 子 agent 若自 `create_task` 起子 run 绕过 controller 就会漏 bind**，故更强的"入口守恒守卫"列为 **P8 前置**（本刀先以集成测试断言 `drive_controller` 唯一驱动 + G-L5 关联判据兜当前）；④ **跨进程 §16.4**：`contextvar` 不覆盖 P5 的 MCP 子进程 → "MCP server stderr 重定向独立文件 + spawn 侧注入 `run_id`（文件名或首行）"列为 **P5 前置决策**（见 ROADMAP P5 行 + DESIGN §16.4），不假装 contextvar 能解决；⑤ `strip_prompt_echo` 仅落纯函数+单测，**接线后置** P5/刀 3。
- 备选（被否）：
  1. 全走 stdlib `LogRecord`（B1）：治理只一套但"可发布内核"退化成配置脚本，且人读视图需反向解析自己格式化的文本 → 否（D3）。
  2. 默认落 2000 字 preview（DeepCode 型）：日志文件永久含用户代码，而它比 DB 更易被顺手贴进 issue → 否（D4）。
  3. `RotatingFileHandler`：Windows 下第二进程持 append 句柄时 `os.rename` 必 `WinError 32`（hermes 反面实证）→ 否（D7）。
  4. `threading.local`（hermes 型）：`http_sse` 并发 N run 表现为日志串号 → 否（D6）。
  5. 带内 `args` 纯拒收非标量：丢有用摘要、且 msg 面本身仍会漏 → 否（采 repr 强转，评审定）。
  6. 软阈值只告警不降级：磁盘占满抵消"省轮转"收益（DESIGN 自标缺口）→ 否（采主动降级 + errors lane 保底）。
  7. 引 loguru/structlog/concurrent-log-handler：需维护 stdlib↔自有双栈桥 + 第二套 sink 语义与"可抽包"争同一份治理逻辑 → 否（D8，stdlib only）。
  8. 网络 exporter / 远程收集：日志可能含 prompt 片段，网络出口是凭据外泄新表面积 → 否（永久红线，DESIGN §1 / HARD C12）。
- provenance / 许可（改造思路 + 文件内标注，AGENTS §5.6；六仓均 MIT 兼容，autogen 代码走 `LICENSE-CODE`=MIT）：桥 depth 爬栈配方 + 按记录时间戳无状态日切 + LLM 独立 JSONL 通道/sha256/preview ← **DeepCode** `core/observability/bus.py:58-92`/`464-470`/`123-221`+`records.py`（MIT）；降噪白名单钉 WARNING + Unicode 安全 stderr + 幂等 `setup_logging` ← **hermes** `hermes_logging.py:216-227`/`147-163`/`326-404`（MIT，Windows 轮转死结 `:75-101` 为反面、不采纳其 CLH 解）；控制台/文件双级别 ← **MetaGPT** `metagpt/logs.py:40-52`（MIT）；路径不可写降级 console-only、import 期不崩 ← **CowAgent** `common/log.py:37-57`（MIT）；协议留内/sink 可独立发布/配置容器注入的**形状**参照 ← **cordis** `packages/core/src/logger.ts`（MIT，本仓不拆包）；结构化事件即日志行的自我描述风格参照 ← **autogen-core** `autogen_core/logging.py`（MIT code license）。
- 关联：[`../log/DESIGN.md`](../log/DESIGN.md) §2/§9/§10/§16/§17；HARD-CONSTRAINTS C5（事件不反哺/协议 schema 零 diff）/C6（错误绝不静默）/C12（进程内、无网络 exporter）/C13（日志非第二真相）/C14（结构边界机器守）/C15（守卫可信）/C18（有界）；STRUCTURE S7；`.importlinter` 第五契约；ADR-0020（event_log 唯一真相、日志旁路镜像）/ADR-0011（seq 语义）/ADR-0028（`_settle_open_calls` 改名 → bind 落点）。
