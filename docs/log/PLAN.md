# Questor 日志系统实施计划（刀 1 + 刀 2）· 基于 docs/log/DESIGN.md

> 起手必读：[`docs/log/DESIGN.md`](./DESIGN.md)（本计划的**规格真源**，D1–D13 决策与 §3–§15 全部条目按它执行）· [`AGENTS.md §4.5`](../../AGENTS.md) · [`docs/ROADMAP.md §1.5`](../ROADMAP.md) · [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md) · [`docs/plan/_TEMPLATE.md`](../plan/_TEMPLATE.md)（分节遵循）。
> **性质**：非 Phase 计划——横切补债 + P5 前置。**不占 `docs/plan/NN` 编号**（`plan/05` 已由 ROADMAP P5 行预留）；本文与 DESIGN.md 同住 `docs/log/`，通过 §9 与现有计划挂钩。
> **READ-ONLY 规划**：本文只落文档不改代码；实现需用户逐轮明确许可（AGENTS §6）。设计规格实现前必须过一次对抗评审（DESIGN §16 + §0 表行号重验）。
> 分支策略见 §10：PR-A（刀 1）→ 合并 → PR-B（刀 2）从新 main 切。

## 0. Peer-Repo 扫描（AGENTS §4.5 硬门禁；证据在设计阶段实 Grep/Read 核过）

**重列 `project-main/` 目录**：12 个业务/参考目录（hermes-agent-main / wuu-main / DeepCode-main / CowAgent-master / MetaGPT-main / crewAI-main / OpenManus-main / GenericAgent-main / autogen-main / Agent-S-main / EvoFlow-main / cordis-main）。**本表在 PR-B 开工当天（T2.0）逐行重验 `file:line` 仍有效**（防 P3 审计 F 类 stale 引用），并核对各仓 LICENSE。

| 能力 | 扫描仓（`repo:path:line`） | 结论（复用/改造/自写） | 说明 · 许可/署名注意 |
|---|---|---|---|
| stdlib↔自有栈桥的 depth 爬栈 | DeepCode `core/observability/bus.py:58-92` | 改造 | 配方已抄入 DESIGN §6；跨 CPython 3.12–3.14 实测。改造点：从 `sys._getframe()` 起爬（弃 `logging.currentframe()`） |
| 按记录时间戳推文件名的无状态轮转 | DeepCode `core/observability/bus.py:464-470` | 改造 | D7 采纳；Questor 加 errors/llm 分流与保留期懒清理 |
| LLM 独立 JSONL 通道 + preview 截断 + sha256 | DeepCode `core/observability/records.py`、`bus.py:123-221` | 改造 | preview 机制属刀 3；刀 2 只建通道结构 + 零原文 entry |
| Windows 轮转死结（反面教材）| hermes `hermes_logging.py:75-101`（CLH `os.rename` WinError 32） | 参考（不采纳其解） | D7 否掉 RotatingFileHandler 路线的实证；改按日切 |
| 降噪白名单 | hermes `hermes_logging.py:216-227` | 改造 | DESIGN §6 白名单（openai/httpx/litellm…钉 WARNING）由此改造 |
| 幂等 `setup_logging` / Unicode 安全 stderr | hermes `hermes_logging.py:326-404` / `147-163` | 改造 | G-L8 / `errors="replace"` 的参照；**QueueListener 不采纳**（DESIGN §10 v1 同步写） |
| 控制台/文件双级别 | MetaGPT `metagpt/logs.py:40-52` | 改造 | D10 console INFO / file DEBUG |
| 协议留内、sink 可独立发布、配置由容器注入 | cordis `packages/core/src/logger.ts`（`Message`/`Exporter`/`_resolveConfig`）、`packages/logger-console/package.json` | 参考（形状） | D1 三层归属与 §11 参数注入的同构证据；Questor 不拆包（短期不发） |
| 结构化事件即日志行 | autogen-core `autogen_core/logging.py`（`LLMCallEvent`） | 参考 | 带外投影行的自我描述风格 |
| 路径不可写降级 console-only、import 期不崩 | CowAgent `common/log.py:37-57` | 改造 | G-L9；`logging_status()` 使降级可查询（超出 Cow 的部分自写） |
| 诊断产品化日志命令（sources/scan/timeline） | EvoFlow `evoflow/cli/commands/logs.py` | 参考（刀 3） | §14 消费命令的形状；刀 2 不做 |
| InferenceJournal 禁 prompt/凭据/body | wuu `internal/providers/types.go`（R07/R08 转述，二手） | 参考 | D4 零原文政策的旁证；**标注：未一手核码** |
| 脱敏 pattern 簇、绝不执行凭据 | hermes `hermes_logging.py`（RedactingFormatter、`<entra-id-bearer>` 只标不 refresh） | 改造 | §8；prompt 回显剥离为 Questor 自写（纯函数 + 后置接线，见 §4 诚实边界） |
| 反面：只有颜色开关、无治理无关联 id | crewAI `crewai/utilities/logger.py`、OpenManus `app/utils/logger.py` | 否 | 自写理由的对照 |
| 桥/管线/白名单契约本体 | — | 自写 | 10 家无一同时满足"零业务依赖内核 + fields 白名单 + 加键 bind"；B2 中间表示为本设计独有（DESIGN §2 D3） |

> 许可边界：EvoFlow `evopanel`（PolyForm Noncommercial）**禁止搬码**（本计划不触碰其代码，仅参考命令交互形状）；hermes/DeepCode/cordis/MetaGPT/CowAgent/autogen 复用一律**改造思路 + 文件内标 provenance**，随 PR-B 各 commit 核对 LICENSE 并在 CHANGELOG 注明（AGENTS §5.6）。wuu 为转述证据，不作为搬码来源。

## 1. 目标与可验证判据（DoD）

**进入条件（已满足）**：P4 经 PR #103（merge commit `f2bd810`）合入 `main`；`questor` 主 worktree 本地 main = origin/main = f2bd810。DESIGN §18 刀 1 的前置"P4 合并后立刻"已成立。

**DoD-PR-A（刀 1，可复现行为）**：
- **A① 四入口全覆盖**：kill 进程后 `python -m questor --resume <id>` 从起手即有 stderr 日志行；`--list` / `--dream` / REPL 同。集成测试断言 `--resume` 路径 stderr 非"零日志"（当前实测为零）。
- **A② 总线故障出声**：注入订阅者队列溢出/持久化失败 → stderr 出现 `questor.bus` WARNING（当前 `_log` 定义于 `kernel/events.py:28` 且零调用=死 logger）。
- **A③ stdout 洁净**：`--list` 的 stdout 只含 run id 行；console sink 显式绑 stderr。
- **A④ 不叠 handler**：`configure_logging` 重复调用每条 msg 恰 1 次。

**DoD-PR-B（刀 2，可复现行为）**：
- **B① 双通道汇流 + 关联正确**：真 loop（fake provider）跑完一个 run → 当日 `questor-<YYYYMMDD>.jsonl` 中每条 `source="inline"` 且 logger 以 `questor.` 开头的行带 `run_id`、`turn` 单调不减；带外行 `source="event"` 同 run_id。两 run 并发（asyncio task）日志不串号（DESIGN §16 攻击点 2 的守卫 G-L5 承载）。
- **B② 白名单与脱敏三面**：`fields={"run": <obj>}` 抛 `TypeError`、naive `ts` 抛 `ValueError`（G-L4）；含 `sk-`/`Authorization:` 的 msg、fields、traceback 落盘 JSONL 三处均无原串且带 `redacted=True`（G-L3）。
- **B③ 调用点保真**：bridge 产物的 `filename/lineno` 指向业务调用处而非 `bridge.py`（G-L6）。
- **B④ 内核零依赖可抽包**：`scripts/check_log_kernel_isolation.py --self-test` 能判红；`lint-imports` **5 契约**全绿（新增第五契约：内核文件清单 ⟂ `questor.*`）；冷导入全绿。
- **B⑤ LLM 零原文**：`providers/litellm_adapter.py` 每次 `stream()` 结束（成功/失败）产一条 `questor.llm` 行：`provider/model/duration_ms/status/finish_reason/prompt_tokens/completion_tokens/request_sha256/response_sha256/error_class`，**无任何 prompt/响应片段**；`llm-<date>.jsonl` 通道结构就位但默认不写（preview 随刀 3）。
- **B⑥ 降级/幂等/stdout/单行**：只读日志目录 → `degraded=True`、console 仍出、进程不崩、`logging_status()` 可查（G-L9）；`configure_logging` ×2 每行恰 1 次（G-L8）；`--list` stdout 零日志行（G-L10）；含异常链 entry 落盘单行且栈完整（G-L12）。
- **B⑦ 带外投影纪律**：`usage_delta/node_updated` 等热路径事件不进日志；error 类事件级别映射绝不静默（C6）；投影载荷键 ⊆ 静态白名单（G-L11 AST 守卫）。
- **B⑧ 质量门**：全量 pytest 零回归（基线 416 passed / 5 skipped）、ruff clean、`lint-imports` kept、既有守卫 + 新守卫 `--self-test` 全部能判红且 fail-on-empty、protocol schema 零 diff、Windows 真机 leg。

**刀 3（不进本计划 DoD）**：§14 `questor logs` 消费命令、`--log-payload` preview 实装、OTel/metrics——挂钩点见 §9，真需求出现时另立计划。

## 2. 子任务清单

### PR-A · 刀 1（独立小 PR，`feat/log-assembly-coverage`；纯缺陷，不改契约不动分层）

- [ ] **T1.1 组合根装配上移**：`__main__.py:61` `_amain` 起始处调 `configure_logging(level=_log_level_from_env())`（env 读取 `QUESTOR_LOG_LEVEL` 放组合根，默认 INFO）；删除 `surfaces/cli.py:263` `interactive()` 内的 `configure_logging()` 调用（组合根唯一调用，DESIGN §11；直接调 `interactive()` 的测试自行显式 configure）。涉及层：L6/组合根。依赖：无。验证：DoD A①（`--resume`/`--list`/`--dream` 三入口起手有 stderr 行 + 集成测试）。commit：`fix(observability): assemble logging at composition root covering all four entries`。
- [ ] **T1.2 启用 questor.bus**：`kernel/events.py` 的订阅者入队溢出与 persist 失败两路径接 `_log.warning(...)`（该 logger 现为零调用的死代码）。涉及层：L2。依赖：T1.1（否则警告无处显示）。验证：DoD A②（测试注入溢出断言 stderr/caplog 命中）。commit：`fix(kernel): wire questor.bus logger for subscriber-overflow and persist failures`。
- [ ] **T1.3 stdout 洁净**：`configure_logging` 显式 `StreamHandler(sys.stderr)`（不依赖 basicConfig 默认），落 G-L10 雏形测试（`--list` stdout 断言）。涉及层：observability。依赖：T1.1。验证：DoD A③/A④。commit：`fix(observability): bind console sink to stderr explicitly, keep stdout machine-clean`。
- [ ] **T1.4 文档入库与收尾**：`docs/log/{DESIGN,PLAN}.md` 随本 PR 提交（commit/push 须用户当轮许可；若用户选择自行处理 git 则本项改为验证 untracked 无阻删除即可）；`CHANGELOG.md` `[Unreleased]` Fixed 补装配缺口两条；`docs/plan/01-p1-minimal-loop.md` T12 标注"部分兑现：装配缺口由 PR-A 补齐，脱敏/节流/白名单/文件面随 PR-B"。commit：`docs(log): land logging design+plan, mark plan/01 T12 partially delivered`。

### PR-B · 刀 2（骨架全套，`feat/log-foundation`，从 PR-A 合并后的 main 切）

> **开工前置门（缺一不可）**：① 对抗评审通过——专门攻 DESIGN §16 四攻击点，其中三事项在评审中拍板、结论写进 ADR-0027：§16.1 带内 args 政策（倾向：`questor.*` logger 的 `record.args` 只收白名单标量；非标量 → `repr()` 截 800 字 + 强制过脱敏 + `fields["args_coerced"]=True`）；§16.3 软阈值后的**主动降级策略**（超阈值是否自动把 `file_level` 提到 INFO，DESIGN §10 目前只写了自告警未写降级，评审必须定案）；G-L7 非阻塞夜间；② T2.0 扫描重验完成。

- [ ] **T2.0 开工扫描重验**（无 commit，结论入 PR 描述）：§0 表逐行重验 `file:line`；核对 hermes/DeepCode/cordis/MetaGPT/CowAgent/autogen 六仓 LICENSE；产出"直接抄/改造/仅参照"三档清单，改造处文件内标 provenance。
- [ ] **T2.1 ADR-0027 + 文档回改**：`docs/adr/0027-observability-logging-foundation.md`——双通道（D2）+ LogEntry 中间表示（D3）+ 载荷政策（D4，零原文默认）+ args 政策（评审结论）+ 按日切（D7）+ "日志不得是唯一载体"纪律（§9）。同 commit 回改：`STRUCTURE.md` S7 补"可被各层调用方向 + 内核零依赖"双条；`.importlinter` 增第五契约（`source_modules` = 内核九文件清单，`forbidden_modules` = `questor.contracts`..`questor.surfaces` 全部；**文件保持纯 ASCII**）；`ROADMAP.md` §1.5 P5 行备注"前置：日志骨架已合入；MCP 子进程日志决策见 DESIGN §16.4"、P10 备注补 observability 文件配额。commit：`docs(adr): 0027 logging foundation + S7/importlinter/roadmap alignment`。
- [ ] **T2.2 内核契约 `observability/entry.py`**（L0'，零 questor.*）：`LogLevel` 枚举 + `LogEntry` frozen dataclass（DESIGN §4 全字段）+ `__post_init__` 五不变式全 fail-closed：naive `ts`→`ValueError`；非白名单值→`TypeError`；`msg>max_msg_chars`(8KiB)→截断+`msg_truncated`；`source`∈{inline,event}；`context`∩`fields` 同键→`ValueError`。测试：G-L4 全判例 + `fields={"run": Run(…)}` 真对象判红。commit：`feat(observability): LogEntry contract with whitelist value domain (kernel, zero questor deps)`。
- [ ] **T2.3 关联作用域 `observability/scope.py`**：`@contextmanager def bind(**kv: str|int|float|bool|None)` + `current_context() -> dict`，contextvars 实现、task 作用域（D6）、加键语义（嵌套 bind 合并、退出还原）。测试：嵌套叠加/还原；两 asyncio task 各自 bind 互不串号。commit：`feat(observability): contextvar bind with additive-key semantics`。
- [ ] **T2.4 脱敏 `observability/redact.py`**：唯一 filter（DESIGN §8）——pattern 簇（`Authorization`/`Bearer`/`x-api-key`/URL `user:pass@`/`api_key=`/PEM 块/云 AK 前缀/`sk-`）作用于 `msg`+`fields` 值+`traceback` 三面；fail-closed（脱敏自身抛异常→整条替换 `<unredactable>`）；命中加 `fields["redacted"]=True`；`strip_prompt_echo(text, prompts, min_len)` 纯函数（长公共片段→`<prompt>`）**接线后置**（见 §4 诚实边界）。测试：G-L3 三面 + pattern 簇逐条 + fail-closed 判红。commit：`feat(observability): single redaction filter, fail-closed across msg/fields/traceback`。
- [ ] **T2.5 exporter 协议 `observability/exporter.py`**：`Exporter` Protocol（`emit(entry: LogEntry) -> None`）+ `register()/unregister()`（unregister 返回 callable 且幂等）。测试：注册/fan-out 顺序/注销后不再收。commit：`feat(observability): exporter protocol with idempotent registration`。
- [ ] **T2.6 治理管线 `observability/pipeline.py`**：`emit(entry)` = 脱敏 → 节流（`(logger, level, 指纹)` 1s 窗口合并计数，窗尾补 `repeated N times`）→ 级别过滤 → exporter fan-out；exporter 异常**绝不上冒**：计数 + 一次性自我禁用 + stderr 一行（D13）。测试：节流窗合并/窗尾补行；fan-out 中一个 exporter 抛错不影响其余且计数可见。commit：`feat(observability): redact->throttle->level->fan-out pipeline with exporter self-disable`。
- [ ] **T2.7 console sink `observability/sink_console.py`**：stderr 渲染（人读格式）、`errors="replace"` 包装、永不 stdout。测试：非 UTF-8 字符不炸；G-L10 判红样例（指 stdout 即红）。commit：`feat(observability): stderr console sink with unicode-safe rendering`。
- [ ] **T2.8 file sink `observability/sink_file.py`**：按记录 `ts` 推文件名 `questor-<YYYYMMDD>.jsonl`（无 rename，D7）；WARNING+ 分流 `errors-<YYYYMMDD>.jsonl`；`llm-<YYYYMMDD>.jsonl` 通道位（默认关）；软阈值 50MB 追加自告警 entry 不改名；`QUESTOR_LOG_KEEP_DAYS`(14) 启动懒清理；best-effort：目录不可建/不可写→console-only 降级 + 一次性 WARNING + `logging_status()`（`{degraded, disabled_exporters, dropped_records, files}`）；teardown 期 `ValueError/OSError` 吞掉。测试：tmp 真 IO（roundtrip/跨日换文件/保留期清理/只读目录降级）；G-L9；G-L7 两进程并发守卫**标 `[非阻塞·夜间]`，Windows 门控，不进 PR 阻塞门**（DESIGN §15 维护成本声明）。commit：`feat(observability): date-sharded JSONL file sink with errors lane, lazy GC, degraded mode`。
- [ ] **T2.9 带内桥 `observability/bridge.py`**：`logging.Handler` 装根 → `LogEntry`；depth 爬栈（DESIGN §6 配方，从 `sys._getframe()` 起爬过 logging 帧）；`msg=record.getMessage()`；`traceback` 由 `exc_info` 格式化并压空行；`fields` **仅**取 `extra={"log_fields": {...}}` 白名单入口（禁透传 record 属性）；不替换全局 LogRecordFactory。测试：G-L6（filename/lineno 指业务文件）+ G-L12（单行+栈完整）+ 降噪白名单生效。commit：`feat(observability): stdlib bridge with depth-corrected call site and noisy-logger whitelist`。
- [ ] **T2.10 装配 `observability/configure.py`**：`configure_logging(*, console_level=INFO, file_level=DEBUG, log_dir=None, keep_days=14, llm_file=False, force=True)` 幂等 + force 重配不叠 handler；**参数全部由调用方传入，绝不读 config/env**（config ⟂ observability 既有契约；cordis `_resolveConfig` 同构）；`logging_status()` 导出。测试：G-L8 幂等判红；参数注入生效。commit：`feat(observability): parameterized idempotent assembly, env-free kernel`。
- [ ] **T2.11 带外投影 `observability/projection.py`**（唯一允许 import `questor.contracts` 的文件）：Envelope→LogEntry；级别映射（`run_failed`→ERROR、`warning/resync_required`→WARNING 绝不静默 C6、里程碑→INFO、余→DEBUG）；live-only 丢弃集补齐 `usage_delta/node_updated`（现 `logging.py:34` 缺）；载荷只取白名单键（`error.code/error.message/status/exit_reason/name/tool_use_id/seq/gseq`），**替换现 `logging.py:37` 把 `error` dict 整个抄进日志的写法**；`source="event"`；旁路只读订阅，不改 bus 持久化路径；**迁移**：删 `observability/logging.py` 的 `log_event`/`error_from_failed_event`（调用点 `surfaces/cli.py` 改走投影），`configure_logging` 兼容签名保留至 PR-B 收尾删除。测试：G-L11 AST（投影载荷键 ⊆ 静态白名单常量，加键即红，含诚实边界注释）；级别映射判例。commit：`feat(observability): envelope projection with whitelisted payload keys, replace legacy log_event`。
- [ ] **T2.12 内核 bind 两点接入 `kernel/loop.py`**：`_drive_controller` 内 `_settle_open_calls` 返回后（`loop.py:262` 后；该函数原名 `_resume_settle_open_calls`，ADR-0028 改为中性名）`bind(run_id=run.run_id)`；`turn += 1`（`loop.py:282`）后 `bind(turn=turn)` 每轮重盖章（α′，D5）。行号会随代码演进飘移，**以符号名为准定位**。涉及层：L2（kernel→observability 为 S7/AST 明文允许方向）。验证：G-L5——真 loop 跑一遍断言每条 inline 行带 run_id 且 turn 单调；**判红样例：注释掉 `bind(turn=...)` 该测试必须红**。commit：`feat(kernel): bind run_id/turn at drive_controller dual points (per-turn restamp)`。
- [ ] **T2.13 LLM 观测 `providers/litellm_adapter.py`**：`stream()` 累积 usage/finish_reason，`finally` 产一条 `logging.getLogger("questor.llm").info(...)` 携 `log_fields={provider, model, duration_ms, status(ok|error|cancelled), finish_reason, prompt_tokens, completion_tokens, request_sha256, response_sha256, error_class}`（sha256=规范化请求 JSON 与累积响应块的哈希）；**零原文**（D4）；llm 行不进 console、主干文件按 DEBUG 收录元数据行、`llm-<date>.jsonl` 仅在 `llm_file=True` 时承载该 logger 行（preview 字段随刀 3）。测试：fake provider 回放断言字段齐全且无 prompt 片段；失败路径（provider 抛错）仍产行。commit：`feat(providers): llm call observation with sha256 identifiability, zero payload by default`。
- [ ] **T2.14 组合根接线 `__main__.py`**：读 `QUESTOR_LOG_DIR`（默认 `<cwd>/.questor/logs/`）/`QUESTOR_LOG_KEEP_DAYS`/`QUESTOR_LOG_LEVEL`/`QUESTOR_LOG_PAYLOAD`（刀 3 实装、本期仅解析拒绝未实现值）传入 `configure_logging`；sidecar（`http_sse` 宿主入口）调同一装配不自配。验证：DoD B⑥ 全套 + 四入口冒烟。commit：`feat(surfaces): wire log env family at composition root, shared assembly for sidecar`。
- [ ] **T2.15 守卫族 + CI wiring `scripts/check_log_kernel_isolation.py`**：G-L1（内核九文件 import 图 ⊆ stdlib+白名单第三方，含 `--self-test` 植入越界 import 判红 + fail-on-empty）+ G-L2（签名/fields 值域无 questor 类型名，AST）；接入 CI `boundaries` blocking job（扩现有守卫引擎模式，参考 P4 扩 `check_layering_ast.py` 的先例，不建重复 walker）；G-L5/G-L11 测试归入本任务清单核对齐全；G-L7 夜间 job 不阻塞。测试：self-test 全判红。commit：`test(ci): log kernel isolation guard + G-L guard self-tests`。
- [ ] **T2.16 全量回归与收尾**：全量 pytest（基线 416 passed / 5 skipped 零回归 + 新增）、ruff、`lint-imports` 5 契约、既有七守卫 + 新守卫 self-test、冷导入逐模块、protocol schema 零 diff、Windows 真机 leg；`CHANGELOG.md` `[Unreleased]` Added — 日志骨架（含 provenance/许可注）；DESIGN.md §17 回改清单逐项核对闭环（plan/01 T12 二次标注"骨架已兑现，消费命令随刀 3"）。commit：`test(log): full regression + dod assertions` + `docs(log): close design §17 backfill checklist`。

## 3. 契约与红线自检

- **触分层/契约？□是 → 先 ADR（T2.1 在任何代码前）**：新增 ADR-0027（双通道/中间表示/载荷政策/args 政策/按日切）；STRUCTURE S7 与 `.importlinter` 同步回改。
- **逐条对照 HARD-CONSTRAINTS**：C13 日志非第二真相——"日志不得是任何信息的唯一载体"纪律（DESIGN §9）+ G-L11 AST 守卫，新业务事实必须先成事件；C6 错误绝不静默——投影级别映射 error→ERROR/WARNING（T2.11）+ `questor.bus` 故障出声（T1.2）；C5 事件不反哺——投影为只读旁路订阅、不改 bus 持久化路径、零新增 Command/事件 type（**protocol schema 零 diff**）；C18 有界——`max_msg_chars` 8KiB + 载荷白名单键 + preview 截断（刀 3）；C15 守卫可信——G-L 全族 `--self-test` 能判红 + fail-on-empty；C14 结构边界机器守——第五契约 + `check_log_kernel_isolation` 进 blocking job；C12 进程内——无网络 exporter（**永久红线**，DESIGN §1）；S7 方向——kernel→observability 为 AST 明文允许方向，真红线仅反向（G-L1/G-L2 锁内核零依赖）。
- **事件协议**：只读订阅，零新增/修改事件 type 与字段；`check_protocol_schema --check` 通过。
- **D8 零新依赖**：stdlib only（`logging`/`contextvars`/`dataclasses`/`json`/`hashlib`）；不引 loguru/structlog/concurrent-log-handler（DESIGN D8 否决理由）；依赖守卫（pyproject 锁定）零变化。
- **工具侧不造新通道**（DESIGN §12）：工具结果已进 `tool_completed` 事件（账本），日志只经 T2.11 投影其摘要行；工具 stdout/stderr 属 artifact，不抄进日志。T2.11 的投影白名单不含任何工具原始输出键。
- **config ⟂ observability**：`configure.py` 参数注入、env 读取在组合根（T2.14），既有 independence 契约不动。

## 4. 测试与回归

- **单元**（`tests/unit/observability/`）：entry 不变式全判例（T2.2）、bind 嵌套/task 隔离（T2.3）、redact pattern 簇逐条+三面+fail-closed（T2.4）、pipeline 节流/自禁（T2.6）、console unicode（T2.7）、file sink tmp 真 IO：roundtrip/跨日/软阈值/懒清理/只读降级（T2.8，**不用 mock 冒充 IO**）、bridge 爬栈/压空行/白名单 extra（T2.9）、configure 幂等（T2.10）、projection 级别映射+白名单键（T2.11）。
- **集成**（`tests/integration/`）：`test_log_correlation_via_real_loop.py`（B①：真 loop + fake provider，inline 行带 run_id、turn 单调、**判红样例注释 bind 即红**）、`test_log_concurrent_runs_no_interleave.py`（两 task 不串号）、`test_log_degraded_dir.py`（B⑥）、`test_llm_observation_no_payload.py`（B⑤：fake provider 回放）、`test_resume_has_logging.py`（A①：kill→`--resume` stderr 非空）。
- **守卫**：G-L1..L12 每条判红方式按 DESIGN §15 表执行；G-L7 双进程并发守卫标 `[非阻塞·夜间]`、Windows 门控；G-L11 诚实边界写死在测试 docstring——"只守住 projection 这条路，业务里新造只写日志的事实仍靠 PR 评审清单"。
- **冷导入 + 静态**：`import questor.observability` 及各子模块逐个冷导入；`lint-imports` 5 契约 kept；`check_layering_ast`/`check_protocol_schema`/既有守卫零回归。
- **诚实边界（UNVERIFIED / 后置，不用 fake 冒充）**：① `strip_prompt_echo` 仅落纯函数+单测，**接线**（prompt 原文来源：带内桥无 prompt、错误回显的比对基准需账本查询）后置 P5/刀 3；② G-L7 Windows 真机双进程在夜间 job 实测，PR 门不含；③ 跨进程 JSONL 行交错 rare 接受（读取器跳损坏行计数 `malformed_lines`）；④ preview/`--log-payload` 实装随刀 3；⑤ 真实多 provider 4xx 回显脱敏效果 UNVERIFIED（无 key）。

## 5. 落地风险 & 备选

| 风险 | 触发条件 | 缓解 | 备选 |
|---|---|---|---|
| 对抗评审否决 args 倾向解 | 评审认为 repr 强转改变写法习惯代价过高 | 回退更严版：`questor.*` logger 带内 args 直接拒收非标量（`logging.Filter` 抛/降级为 `<non-scalar-arg>` 占位），结论入 ADR-0027 后才动 T2.9 | 不处理 → 否（DESIGN §16.1：D11 沦为纸面守卫） |
| 同步写阻塞 loop | 现场证明 p95 写延迟超标或 `dropped_records>0` | 触发条件已写入 DESIGN §10（文档非记忆）；届时升级 QueueListener 为独立小 PR | 默认启用 QueueListener → 否（teardown join 挂死是本项目已知竞态雷区） |
| G-L7 双进程测试 flaky | CI 间歇红 | 已标非阻塞夜间；连续两个 Phase 误报即降级（DESIGN §15 声明） | 进阻塞门 → 否 |
| §0 行号 stale（P3 审计 F 类教训） | DeepCode/hermes 上游文件变动 | T2.0 开工当天重验；stale 即改判"仅参照思路" | 信任旧行号直接抄 → 否 |
| 旧 `logging.py` 迁移遗漏调用点 | `log_event` 在 cli.py 外还有调用方 | T2.11 执行前全仓 grep `log_event|error_from_failed_event` 清点 | 并存双实现 → 否（双通道汇流点必须唯一） |
| worktree 多窗口提交落错分支（项目已知教训） | 并发窗口 | 按 §10 独立 worktree 承载两个 PR 分支；commit/push 逐轮许可 | 主工作区切分支 → 否 |
| 许可/署名 | 搬运 DeepCode/hermes 片段 | T2.0 核 LICENSE + 文件内 provenance + CHANGELOG 注明；EvoFlow evopanel 码零接触 | 无署名照搬 → 否（AGENTS §5.6） |

## 6. 收尾（活文档，AGENTS §5.5）

- [ ] DESIGN §17 回改清单逐项闭环核对（STRUCTURE S7 / `.importlinter` / ADR-0027 / ROADMAP §1.5+配额 / plan/01 T12 / env 变量族）——随 T2.1/T2.16
- [ ] `CHANGELOG.md` `[Unreleased]`：PR-A Fixed 两条；PR-B Added 日志骨架（provenance 注）
- [ ] `ROADMAP.md` §1.5：P5 行加"前置：日志骨架已合入"；P10 备注补 observability 配额
- [ ] 偏差回填 ADR-0027 与本文 §7（实现偏差节）
- [ ] §0 表行号终检（交付前防 stale）

## 7. 实现偏差回填（执行期追加）

**完成状态（2026-10-17，PR-B 刀 2 收尾）**：T1.1–T1.4 已合入（刀 1）；T2.0–T2.16 已落地。全量回归 **527 passed / 5 skipped 零回归**；ruff clean；lint-imports **5 kept**；protocol schema **20 types 零 diff**；六既有守卫 + 新 `check_log_kernel_isolation` self-test 全判红。闭环实证：`test_log_correlation_via_real_loop.py` 走真 loop + 真 IO，断言 inline 行落 `questor-<date>.jsonl` 并携 `run_id`/`turn`。

**reality-wins 偏差**（不改设计结论，只记实现落点）：
1. **LLM 观测级别 DEBUG（非 T2.13 文案的 `.info`）**：DESIGN §12/DoD B⑤ 要「llm 行不进 console、主干按 DEBUG 收录」——`.info` 会被 console（INFO 门）收下、与"不进 console"矛盾。故 `providers/litellm_adapter.py` 以 `questor.llm` logger 打 **DEBUG** 行；行为判据（§12）优先于文案措辞。sha256=对规范化请求 JSON / 累积响应块的哈希（零原文）。
2. **带内 `turn` 盖章用 `ExitStack` 内联于 `_drive_controller`**：`bind` 是 `@contextmanager`，DESIGN §5.3 的「两处 `bind(...)`」以 `with ExitStack()` 承载——`run_id` 整轮 enter 一次、`turn` 每轮 enter（同名覆盖、号不漂移）、退出统一 reset 不泄漏进调用方 task。落点仍在 `_drive_controller` 两处，语义与 α′ 一致。
3. **组合根由兼容层切到新 `configure.configure_logging`**：`__main__`/`cli.main` 均改调 `observability.configure.configure_logging`（装桥 + console + 文件 sink），不再用 `observability.logging` 兼容层（刀 2 收尾已删该兼容层 + 其 `test_configure_logging_idempotent.py`，G-L8 幂等由 `test_configure.py` 承接）。`QUESTOR_LOG_PAYLOAD` 非 off 值按 T2.14 拒绝启动（preview 归刀 3）。
4. **带外投影仍挂在 surfaces 消费者（非 bus 只读订阅）**：沿用 T2.11 已提交的 `log_envelope`（在 `cli._stream` 消费点调用），未改为 bus 级订阅——避免与既有消费者双重投影。后果：HTTP sidecar 路径的带外投影暂未覆盖（inline 关联因 loop bind 仍生效）。收口点记为刀 3/backlog，CHANGELOG 诚实标注。
5. **测试隔离修复**：新增 `test_log_correlation_via_real_loop.py`、`test_llm_observation_no_payload.py` 用快照/还原 fixture 回滚进程级装配；`test_composition_root_model.py`（在进程内跑 `_amain`）补装 `QUESTOR_LOG_DIR=tmp` + 回滚 root/exporter/pipeline/`_state`，否则装配单例泄进后续用例。另修 pytest basename 冲突：`observability/test_projection.py` → `test_log_projection.py`（区别于事件投影 `tests/unit/test_projection.py`，此为 T2.11 引入、因 T2.16 从未跑而漏检的潜在回归）。
6. **§0 扫描重验（T2.0）**：本轮以既有 DESIGN §19/PLAN §0 锚点为准，未再逐行 `file:line` 复验外部参考仓（本任务不搬新码，仅接线）；随 PR-B 合入前按 AGENTS §4.5 复核。

**未进本 PR 门（诚实边界，§4）**：G-L7 跨进程按日写标 `[非阻塞·夜间]`、Windows 门控；真 key 下多 provider 4xx 回显脱敏效果 UNVERIFIED；`strip_prompt_echo` 仅纯函数 + 单测、接线后置。

## 8. 依赖图与时序

```
[现在] PR-A 刀1（feat/log-assembly-coverage，独立小 PR，1-2 天量级）
  T1.1 组合根装配 ─ T1.2 questor.bus ─ T1.3 stderr/stdout ─ T1.4 文档入库
[PR-A 合并后]
  对抗评审门（DESIGN §16 四攻击点 + args/G-L7 拍板 → ADR-0027） + T2.0 扫描重验
[评审通过后] PR-B 刀2（feat/log-foundation，从新 main 切）
  T2.1 ADR-0027+回改 ─┬─ T2.2 entry ─ T2.3 scope ─┬─ T2.6 pipeline ─ T2.7/T2.8 sinks ─┐
                       ├─ T2.4 redact ─────────────┤                                    ├─ T2.9 bridge ─ T2.10 configure ─ T2.14 组合根
                       └─ T2.5 exporter ───────────┘                                    ├─ T2.11 projection（替换旧 logging.py）
                                                                                         └─ T2.12 loop bind（依赖 T2.3）
  T2.13 llm entry（依赖 T2.2/T2.10） ─ T2.15 守卫+CI ─ T2.16 回归收尾
[PR-B 合并后] → P5 plan 可开工（其 §0 扫描表必须含 MCP stderr 重定向 + spawn 侧 run_id 注入决策，DESIGN §16.4）
刀3：logs 命令 / --log-payload preview / OTel —— 不预排，挂钩 P7 桌面调试或 P10 加固（§9）
```

关键路径：`T2.1 → T2.2 → T2.3 → T2.6 → T2.8 → T2.9 → T2.10 → T2.11 → T2.14 → T2.15 → T2.16`；T2.4/T2.5/T2.7/T2.13 并行支线。

## 9. 与现有计划的挂钩（本文"结合现有计划"的执行表）

| 现有计划/文档 | 挂钩动作 | 执行点 |
|---|---|---|
| `plan/01-p1-minimal-loop.md` T12（轻量可观测/错误栈） | 标注"部分兑现"：装配缺口→PR-A 补齐；脱敏/节流/白名单/文件面→PR-B；消费命令→刀 3 | T1.4 首标、T2.16 二标 |
| `ROADMAP.md` §1.5 P10 备注（"轻量可观测从 P1 就落"） | 补 observability 文件配额（现 373 文件规划零配额=欠债的结构性原因） | T2.1 |
| `ROADMAP.md` §1 P5 行（`plan/05`） | 备注进入条件追加"日志骨架已合入"+ MCP 子进程日志决策指针（DESIGN §16.4） | T2.1 |
| **P5 plan（将来撰写）** | 其 §0 扫描表必须含"MCP server stderr 重定向独立文件 + spawn 侧注入 run_id（文件名或首行）"决策；进入条件核对 B①–B⑧ 已合入 | PR-B 合并后 |
| `plan/02` R7（并行工具完整版→P5） | 无直接耦合；P5 并行化新增错误来源恰好落在骨架保护窗内 | — |
| P7（桌面调试）/ P10（加固） | 刀 3 挂钩点：`questor logs` 消费命令、`--log-payload` preview 实装、OTel/metrics——真需求出现时另立计划，骨架已留接缝（llm 文件通道/渲染器/`trace_id` 键位） | ROADMAP 备注即可 |
| `CHANGELOG.md` / `STRUCTURE.md` S7 / `.importlinter` | 回改（§6） | T1.4 / T2.1 |

## 10. 执行约定

- **隔离 worktree（项目硬纪律）**：PR-A 用独立 worktree 承载 `feat/log-assembly-coverage`；合并后 PR-B 用新 worktree 从**最新 main** 切 `feat/log-foundation`。禁止主工作区切分支（"多窗口切分支提交落错分支"教训）。
- **TDD**：每任务先写判红测试再实现；守卫类任务先写 self-test 再写守卫本体。
- **细粒度提交**：每任务一 commit，英文 Conventional Commits（`fix/feat/test/docs(observability|kernel|surfaces|providers|ci|log|adr)`）；**每次 commit/push 须经用户当轮明确许可**（AGENTS §6）；PR-only 合并，分支保护不动。
- **安全评审**：PR-B push/开 PR 前走 L3 深度评审——日志面涉及凭据外泄与隐私（脱敏 fail-closed、llm 通道隔离、零原文默认、无网络 exporter 红线）为审查重点。
- **验收**：以 §1 DoD 可复现行为为准；UNVERIFIED 逐项标注（§4 诚实边界），不用 fake 冒充真机结果。
