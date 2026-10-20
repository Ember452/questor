# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — w2-final · B5 扩展面（w2-final，6 commit，c1–c6 各自可 revert）
- **c1 声明期词表（§5.1/§5.2）**：新增 `contracts/extension.py`：`ExtensionKind`（transform/decision/observe）、`HookOutcomeKind` 三值、13 个生效点位封闭集 + 4 个预留名（Notification/Elicitation/TaskUpdated/PlanStep，上限 17）、`ExtensionDescriptor` **6 字段**（id/kind/at/matcher/version/priority；无 `failure_semantics`，matcher 深冻结并按封闭键名校验）、`ObserveChain`（priority 降序、异常与 `FAILED_ABORT` 一律归一为 `FAILED_CONTINUE`）。判据：`tests/unit/test_extension_descriptor.py`（11 条）。
- **c2 注册表泛化（§5.2）**：`policy/registry.py` 新增 `ExtensionRegistry`（descriptor + 工厂、按 `at` 分组、priority 降序、`resolve_observe` 跳过破损/非 OBSERVE 条目、`render_chain` 稳定输出 13+4）；`PolicyRegistry` 改为兼容外壳，内部存 `ExtensionEntry`，`register/resolve/resolve_or_default/ab_select` 语义逐字不变。判据：`tests/unit/test_extension_registry.py`（5 条）+ 既有 `test_policy_registry.py` 全绿。
- **c3 settle 收口到 Stop（§5.1/§6.4b，ADR-0053）**：`DefaultTurnLoop` 只持一个 `_stop: ObserveChain`，`_settle_turn` 只有一次 `_stop.emit(boundary)`；`settle=` 保留为 R3 兼容薄糖（内部包成单条 `settle-turn` OBSERVE 条目，无第二字段/第二路径）；`CliSurface.build_extension_registry()` 把 `TurnSettler` 注册为 Stop 条目，四入口共用。判据：`tests/unit/test_stop_point.py`（4 条）+ 既有 `test_settle_turn.py` 全绿。
- **c4 工具集=数据 + 六方言（OPT-5）**：新增 `capabilities/toolset.py`（`TOOL_FACTORIES` 11 个、`PROFILES.default` 保序、`build_tools` 唯一取件口；未知 profile 回落默认并 WARN）；`surfaces/cli._default_registry` 改消费数据表，默认 11 工具顺序逐项不变；新增 `capabilities/extension_dialects.py`（policy/tool/memory/compaction/permission/provider 各一 descriptor，全落在 13 个生效点位内）。判据：`tests/unit/test_toolset.py`（6 条）+ `test_p2_file_tools`/`test_registry`/`test_assemble_spec_default` 全绿。
- **c5 provider 上移 + N3 守卫（OPT-6）**：provider env 判据搬到 `providers/provider_factory.py`（`provider_from_env(payload_preview=...)`，判据逐字不变、离线 Echo 回落保留）；`composition.build_app()` 只在 `spec.surface is None` 时调用工厂，`provider_factory` 恰好一次；`surfaces/cli.provider_from_env()` 降为兼容薄壳。`.importlinter` 在 kernel 与 state 之间补 `questor.memory` 层；新增 blocking 守卫 `scripts/check_extension_points.py`（复用 `_guard_kit`，检查 13+4 封闭 / OBSERVE 不可 abort / kernel 不 import policy-surfaces / 组合根仅 spec 收窄，`--self-test` 逐条判红）并接入 CI；`gate_scripts` 16→17、`ci_gate_steps` 18→19。
- **c6 inspect-extensions（§5.3）**：`python -m questor --inspect-extensions` 打印 13+4 点位、策略名册与 `settle-turn` Stop 条目，**先于日志/存储装配**（不建库、不装日志），退出 0；命令刻意不进 `_USAGE`，以保住 `--help` 逐字节快照（R3）。判据：`tests/integration/test_inspect_extensions.py`（2 条）+ `test_cli_help`/`test_assemble_spec_default` 不变。

### Added — w2-final · P10 卫生（w2-final，6 commit）
- **p1 sandbox_selector（OPT-7）**：`providers/sandbox.py` 新增 `backend_available()` / `select_sandbox(requested, *, system, which, path_exists)`：不请求时逐字等于 `detect_sandbox()`；名字不可识别或本主机不存在 → `NullSandbox`（fail-closed，绝不猜）；不提供任何“绕过首次尝试”开关；seatbelt/bwrap 仍诚实报 `fences_writes=False`。`AssembleSpec.sandbox_backend` 新字段由组合根消费。判据：`tests/unit/test_sandbox_selector.py`（6 条）+ `test_sandbox_gate` 三断言（deny/ran=False/COMPLETED）不变。ADR 判定：**不新增**——默认路径逐字不变、能力事实未放宽，只是多一个可选后端选择接缝（非不可逆决定）。
- **p2 壳中立参数化（OPT-10）**：`check_thin_client.py` 新增 `--generated-symbol`（默认 `QuestorExternalEventProjectionV1`）、`check_desktop_csp.py` 新增 `--tauri-conf`/`--caps-dir`（默认现值）；两者 `--self-test` 各新增“换壳符号同样拦”的判红样本，默认扫描结果 0 违规。`contracts/sidecar_status.py` docstring 改述为“宿主壳（当前=Tauri Rust）”，并明写 bootstrap/形状不变量与壳无关；UI 事件名单改由 `generate-protocol.mjs` 从 schema `type` enum 派生出 `EVENT_TYPE_NAMES`，`main.ts` 不再手抄（`npm run check:protocol` 仍是漂移门）。不变量冻结：`SidecarStatus` 形状、bootstrap `{host,port,generation,pid,token}`、thin-client 三不变量。

- **p3 协议/文档计数纠偏（以实测为准）**：`protocol/README.md` 新增计数行——**27 个 `EventType` / 20 个 `Command`**（`contracts/events.py:341-375` / `:296-317`），并明写“`check_protocol_schema --check` 才是真源、本行仅文档”；`docs/ROADMAP.md` 里旧的“20 个 `EventType`（`events.py:251-273`）”校正为 27/现行行号；`contracts/__init__.py` 的“无实现”改口为“抽象接口 + frozen 数据 + 确定性纯函数，零 IO/零外层 import/无业务分支”（PLAN §5 已核项）。零代码行为变更。

- **p4 SCAN-2 全量清单机守**：新增 `tests/unit/test_scan2_inventory.py`（9 条）把“tests/ 口径”从纸面变可执行：四个桶非空、**各桶之和 == tests/ 下 .py 总数**（新增目录必须登记，否则立即红）、support fixture 可见、`unit/{capabilities,observability}` 子树计入（旧口径只数顶层的原病）、跨桶文件名不重。刻意不断言绝对数字（数字归 `check_doc_cross_refs.EXPECTED`，形状归本测试）；PLAN §4 SCAN-2 转 ✅。

- **p5 G7 僵尸位（§21 G7）**：`ToolSpec.available` 从“无人读的死字段”改为**真接线**——`ToolRegistry` 现在同时要求 `spec.available and tool.available()`（内置工具全为 True，零行为变更；新增两个单测钉住“静态关 = 注册但不外露”与“默认真 = 不消失”）。`artifact_ref` 家族**先拆同名再判死活，不直删**（决策表）：① `ToolCall.artifact_refs` = **活**（快照往返不丢）→ 保留；② `envelope_for_text` 产物的 `artifact_ref` **dict 键** = **活消费者**（`state/reduce.py:140-155` 已读，`tool_completed`/`memory_written` 白名单已列），生产端接线归 B10；③ `MemorySearchResult.artifact_ref` = **预留无生产者**（属 L0 契约词汇，删 = 破坏性变更）→ 保留并在测试里明写。判据：`tests/unit/test_p10_hygiene.py` 新增 4 条 + `tests/unit/test_registry.py` 新增 2 条；`test_registry_collision`/`test_p2_registry_freeze_loop`/`test_p2_file_tools` 全绿。

- **p6 待核清单归一（§20.5 / W1 §8 / PLAN §6）**：把 W1 §8 的 6 项与 PLAN §6 的 4 项全部归入设计文档 §17（第 15–23 项，附实测证据）：策略装配点/surface 抽象/mode 真源/desktop 实况/openai 投影边界/`fences_network` 均✅已证；codex、OpenHarness 本地码与 OPT-11 的 allowlist保持未证/不做；B9 布局表一项标“待 Stage 5 收口”。§20.5 从“尚未并入”改为“已归一完成（§17 现有 23 项）”；PLAN §6 标“以 §17 为准、原文仅作历史”。文档不在仓内→ `optimize-scan/DOCS-MANIFEST.md` 的 SHA256/行数/HEAD pin 于收尾时更新（R12 降级口径）。

### Changed — OPT-2a / OPT-12a / OPT-3 / OPT-4：组合根接缝 + 上下文装配器 + 配置/profile 词汇（分支 `opt-seams`；12 commit，a1–a3 / b1–b3 / c1–c6 各自可 revert；**零行为变更**）
- **OPT-2a 组合根接缝（a1–a3）**：新增 `composition.AssembleSpec`（frozen 纯数据，12 字段全默认 `None` = 走现路径自建；不是服务定位器）+ `build_app(spec=None)`（未给字段仍按历史顺序自建）+ `App.surface` 放宽为最小 `contracts.ports.SurfacePort`（只声明调用方实际用到的 `run_once`/`resume`/`_loop`/`_discover_mcp`/`_freeze_surface`/`_resolve_for_run` 与 `store`）。判据：`tests/integration/test_assemble_spec_default.py`——默认 spec 与 `build_app()` **逐字段等价**、注入字段真被使用（未给的仍自建）、`--help` stdout/exit-code **逐字节快照**。
- **OPT-12a 上下文装配器（b1–b3）**：`CliSurface.__init__` 里的 `f"{system}\n\n{catalog}".strip() if catalog else system` 原样搬到 `surfaces/_assembly.py::assemble_system_prompt`，经新增 `ContextAssemblerPort` 接缝（`AssembleSpec.context_assembler` 已接线）；**逐字节等价，包括 `system=None` 时那个字面 `"None"`**（修它是 OPT-12b/B7，不在本刀）。新增 `tests/golden/prompt_system{,_none}.txt`（由**当前实现**生成一次并入库、LF-only）+ 逐字节单测；记忆注入位 `memory_block_provider` **默认关**，默认路径 `ProviderRequest.system` 一个字节不变。
- **OPT-3 配置层（c1–c2）**：新增 `questor/config/model.py`（frozen、stdlib-only、无 pydantic）：把 `composition.*_from_env`、`surfaces/_assembly.*_from_env`、`__main__` 内联的 env 读取收口成 `load_config()`——**无缓存，读取时点 = 调用时点**；env 名/默认值/判定顺序逐字平移（`generation`/`keep_days`/`port` 坏值回落，`dream_lookback` 仍在**使用点**抛）。`config ⟂ observability` 不破（`LogLevel` 解析留在 `_assembly`，`configure_logging` 仍 env-free；`lint-imports` 5 kept）。
- **OPT-4 L0 词汇（c3–c4，ADR-0052）**：新增 `contracts/profile.py`（`PERMISSION_MODES`/`PERMISSION_MODE_SET`/`PERMISSION_MODE_RANK`/`normalize`/`permission_preset_for`）。5 处 Python 侧 mode 真源全部改引用它：`kernel/permission_policy.PermissionMode`（+ 两处比较）、`kernel/subagent_permission._MODE_RANK`、`state/reduce.py` 合法集、`surfaces/http_sse.py` 合法集、`capabilities/subagent/delegate.py` 的 `params.mode.enum`（**顺序不变**，故 `ProviderRequest.tools` 字节不变）。`normalize` 刻意**不做**大小写/空格/别名映射（放宽词表 = 行为变更）；预设只携带收紧旋钮，capability floor 不放宽。**不 collapse**：`protocol/event.schema.json` 仍是 wire 真源，`desktop/web/src/api/commandClient.ts` 本轮**零改动**（协议派生留给 P10）。
- **计数（c6，mechanical）**：`src_py` 123→**125**（`config/model.py`、`contracts/profile.py`）、`test_files` 184→**188**、`test_unit` 109→**112**、`test_integration` 69→**70**；`EventType` 仍 **26**、`gate_scripts` **16**、`ci_gate_steps` **18**、`reduce_calls` **0**。
- **ADR 判定**：**新增 [`ADR-0052`](docs/adr/0052-permission-profile-preset-vocabulary.md)**（L0 新增 profile 词汇与「预设只收紧」边界）。

### Added — B1：事实流补齐（user input as durable fact；分支 `b1-fact-stream`；6 commit，c1–c6 各自可 revert）
- **新事件 `user_message`（additive，`EventType` 25→26）**：非 idle（busy / awaiting_approval）提交的用户输入现在产一条 durable 事件——正文按 `OutputBudget().model_result_bytes`（UTF-8 字节、不劈多字节）有界、截断不静默（`truncated`），并 bump seq；修掉 `reduce.py:217-229` 的“无事件、不 bump seq”不对称（旧实现下 busy 提交只在内存 context 里，崩溃/重连后事实流与 `after_seq` 重放都看不到）。**idle 首条保持既有冻结契约**（恰 `[run_started]`、seq==1；`test_reduce.py:51` / `test_transition_chokepoint.py:45` 零改动），其 durable 承载 = `run_started` + turn 边界快照——设计文档 §2-3/§4.2/§11/§13/§15.6/§21 G5 与 PLAN §0/§5/SCAN-2 已同步（含 §15.6 新勘误行）。
- **四处 lockstep（c1）**：`contracts/events.py` ⟂ `protocol/event.schema.json`（enum + `$defs.user_message`（required `text`、`maxLength=16384`、`additionalProperties:false`）+ if/then 分支）⟂ TS codegen（**真跑** `npm run generate:protocol`，`npm run check:protocol` 绿）⟂ `kernel/events.py:EXTERNAL_EVENT_FIELDS`（`{text, truncated}`，重连可渲染）。`check_protocol_schema` 增一条 `maxLength` 数值门（wire 上限 == `OutputBudget.model_result_bytes`）+ user_message 合法/超限 fixture（超限必拒）；`EVENT_SCHEMA_VERSION` **不 bump**。observability 投影不动（`text` 不在 `_DATA_KEYS`，C20 零明文；`check_projection_whitelist` 仍绿）。
- **幂等提交：内容派生键（c3）**：`SubmitMessage` 的 apply 幂等键改为 `submit:<turn>:<content_sha256>`（`kernel/loop.py:_submit_key`）——通用“类型+游标”键会让同一安全点批量消费的两条**不同**消息撞键（apply 抛 `IdempotencyConflictError`，实测）；现同内容重投 = no-op、异内容各落一条。所有路径仍只经 B0 的 `apply()`（inbox / legacy-drive / resume），无第二写者、无新增 IO。
- **落库前剥注入脚手架（c4，带内标记）**：`state/persist_form.py`（B0 的“事实流形态唯一判定点”）新增 `SCAFFOLDING_OPEN/CLOSE`（`<<questor:injected>>…<<questor:end-injected>>`）与 `strip_scaffolding`；`durable_form` 只对 `user_message.text` 剥掉注入段（未闭合 OPEN 按 fail-closed 截到文末、孤儿 CLOSE 只剥记号、无标记逐字节等价）。**before/after**：`real user words <<questor:injected>>system injected preamble<<questor:end-injected>> and a closing line` → 持久正文 `real user words  and a closing line`。**去重不靠标记扫描**（只靠 apply 幂等键，不抄 hermes `_DB_PERSISTED_MARKER` 的标记去重）；模型输入（context/快照）保留注入段——事实是“用户原话”、快照是模型输入。
- **终态处置（C13 不放宽）**：终态 run 的迟到 `SubmitMessage` 被拒（durable warning + 占 seq），经 inbox 得 `REJECTED_TERMINAL`；surface 侧合法路径是新建 run（本刀不改 surface）。
- **判据（均机器验证）**：新单测 `tests/unit/test_user_message_fact.py`（busy 追加+seq+1+wire 合法 / idle 冻结契约 / 有界+`truncated` / 多字节不劈 / 终态拒收 / 内容派生键 / 标记剥离 / 同内容重复 apply 不重复追加；9 条）+ `tests/integration/test_command_inbox_loop.py` 新增 3 条（`test_submit_message_persists_when_busy`、`test_submit_after_terminal_is_rejected_and_surface_starts_a_new_run`、`test_resume_transcript_equals_production_transcript`：3 条消息 kill 后 `rebuild_run`+`to_openai_messages` 与生产**逐条相等**；`resume_and_drive` 不改写转录、不新增事实行）。**RED 先证**：把 `reduce.py` 退回 c1，busy 测的 durable 行只有 `[run_started, turn_started, message_completed, run_completed]`（无 user_message、busy 不占 seq）→ 判红。全量 pytest **932 passed / 6 skipped**（= 920 既有全绿 + 12 新增；**既有断言零改动**）、ruff 与 `lint-imports` 绿、`check_protocol_schema --check`（**26 types** lockstep）/`check_projection_whitelist`/`check_replay_determinism --self-test`（139 字段）/`check_reduce_chokepoint --self-test`（kernel 直调=0）/`check_doc_cross_refs`（EventType=26、test_files=184、unit=109）全绿。
- **ADR 判定**：**不新增 ADR**。additive 事件 + 既有咽喉/形态的**执行点上推**：无破坏性 wire 变更（`v` 不 bump、信封/关联键不变）、无新表/新端口、C13/C5/C2 语义未放宽（终态仍 first-writer-wins 拒写）。
- **UNVERIFIED/边界**：① idle 首条的用户正文不在事件流（只在快照）——受两条既有冻结断言约束，勘误与理由见设计文档 §15.6；② 幂等 no-op 判定在“同一游标”上成立（B0 咽喉语义），跨游标重投去重属 B2 有界命令窗口；③ “事实流+快照联合重建 UI 转录”的只读投影（`user_originated_turn_view` 式）留给 B13/B14 体验刀。

### Changed — B0.5 + B0：状态迁移咽喉（`apply()` + `durable_form()` + `append` epoch 栅栏 + 守卫）
- **B0.5（test-only）**：`scripts/check_replay_determinism.py` 的 `_canonical` 从“手工白名单”改为**反射全字段**——新增 `schema` 投影，递归 `Run` 及内嵌 dataclass（`Context`/`Budget`/`TaskLedger`/`PermissionCtx`/`ApprovalRequest`/`TaskNode`/`Checkpoint`/`ErrorEntry`/`PolicyRef`…），**139 个字段路径**逐条断言必须出现在比对集；缺失即以字段路径判红（如 `Run.context.flags`）。`--self-test` 新增“删字段→红 / 恢复→绿”判据。既有手工键与 7 个 fixture 全部保持不变。
- **B0（重构 + 栅栏）**：
  - 新增 `src/questor/state/transition.py`：`apply(store, run, command, *, source, idempotency_key, now)` = **幂等判定 → reduce → 返回 `(Run, 事件元组)`**。幂等作用域是 run 血统（`run_id`+`created_at`，跨 reduce/快照稳定）：同 key 同 digest 且状态已含该次应用 → no-op；同 key 异 digest 且状态未推进 → `IdempotencyConflictError`。**不做 IO**（store 仅注入；耐久 command window 属 B6/B7）。
  - `kernel/loop.py` 16 处 + `kernel/recovery.py` 1 处 `reduce(` **全部改走 `apply`**，kernel 直调数 **17 → 0**；`check_reduce_chokepoint` 机守（AST）。
  - 新增 `src/questor/state/persist_form.py`：`LIVE_ONLY`/`TERMINAL` 与 `durable_form(env, budget)` 收敛为一处判定；`kernel/events.py` 只调用（`LIVE_ONLY`/`TERMINAL` 仍从 kernel re-export，旧调用方无感）。`EventType` 取值域**未新增/未改名**（属 P4）。
  - `providers/store_sqlite.py`：`append(run_id, events, *, holder=None, epoch=None)` 在 `BEGIN IMMEDIATE` 事务内比对 `run_leases`，不匹配抛 **`StaleWriterError`**；写者身份由同一 store 实例的 `acquire_lease`/`renew_lease` 记录（`writer_identity`），bus 落库时携带。无租约行（内存测试/只读回放）保持既有行为——**不是校验开关**，而是“没人持租约时无竞争”。
  - 新增 `scripts/check_reduce_chokepoint.py`（复用 `_guard_kit`）：① `reduce(` 只许出现在 `state/transition.py`（调用）与 `state/reduce.py`（定义），连 `import ... as _r` 的别名绕法一并判红；② `event_log.append` 的载荷只许来自 `durable_form()`；`--self-test` 用 loop 直调 / inline 拼载荷两个反例判红，fail-on-empty 防扫描面缩小。
  - **计数联动（同一 PR）**：CI `boundaries` blocking 门步 **17 → 18**；`check_doc_cross_refs` 的 EXPECTED：`gate_scripts` 15→16、`ci_gate_steps` 17→18、`reduce_calls` 17→0、`src_py` 121→123、`test_files` 182→183、`test_unit` 107→108；设计文档 §2-1/§21（及 §19 保留段）与 PLAN SCAN-1/SCAN-2 同步。
  - `.gitignore` 增 `!scripts/_guard_kit.py`：共用 kit 不再靠 `git add -f` 入库。
- **判据**：17 处调用点消失（`loop.py`/`recovery.py` 的 `reduce(` = 0）；同 idem_key 二次应用不重产事件、异 digest 被拒；陈旧 epoch → `StaleWriterError`、正确 holder+epoch 通过；`check_replay_determinism --self-test` / `check_reduce_chokepoint --self-test` / `check_layering_ast --self-test` / `check_cross_run_no_bypass` / `check_projection_whitelist` / `check_doc_cross_refs` 全绿；`ruff check .` 与 `lint-imports`（5 kept）全绿；全量 pytest **920 passed / 6 skipped**（= 既有 913 全绿 + 新增 7；既有断言零改动）。
- **ADR 判定**：纯重构 + 护栏，**不新增 ADR**。理由：没有外部行为/线协议/存表结构变化（`event_log` DDL 未动，`run_leases` 仅被读取校验），`EventType`/`Command` 未变；栅栏是 ADR-0047 已授权机制的**执行点下推**，B0 之前它只是 surfaces 层约定。
- **UNVERIFIED/边界**：进程内幂等窗口（耐久 `command_window` 属 B6/B7）；跨进程“租约被夺后旧驱动者”只在写点被拒（已被本守卫/测试覆盖），未做真双进程长跑压测；`durable_form(budget)` 的有界形态已实现但**默认不启用**（无人传 budget = 逐字节等价）；`StorePort` 协议签名未加 `holder/epoch`（B0 范围锁），栅栏目前只在 `SQLiteStore` 落地，协议同步留给后续刀。

### Added — 守卫基础设施：共用 kit + 文档一致性守卫（advisory；v3 §21 G2 / §15.6 / §20.3）
- **`scripts/_guard_kit.py`（新）**：§21 G2 要求的「共 walker 引擎」落地——`walk_py`（`Path.rglob` + 剪枝 `__pycache__/.venv/.ruff_cache/build`、排序）/ `read_text`+`count_lines`（UTF-8-sig + `splitlines()`，与 §15.6 口径声明同一口径）/ `run_self_test`（统一 `[PASS]/[FAIL]` + `self-test: PASS|FAIL`）/ `fail_on_empty`（空集合退 **2**，不是通过）/ `EXIT_OK|EXIT_RED|EXIT_CONFIG`。顶层 docstring 写死「新守卫必须复用本 kit，否则不得入 CI」。
- **`scripts/check_doc_cross_refs.py`（新，advisory）**：只读设计文档，四项检查——**A** 9 条 EXPECTED（取舍 19 / 刀 17 / 点位 12+5 / `src/**/*.py` 121 / 门脚本 15 / boundaries 门步 17 / `reduce()` 17 / 测试 182=107+69+3+2+1；基线 913/6 只注释不断言）且**标题声明数必须等于表行数**；**B** §n·附录X·B刀·C条引用必须在文内有定义（外部文档引用按限定词/显式理由豁免）；**C** §15.6/§20.3 每行必须同时有「原写」侧与「已改」侧；**D** PLAN §3 否决词出现必须同句带 `C-\d|已改|不建|不拆|仅借`。缺省 `SKIP: doc not present` 退 0（文档在仓外一层）。
- **两个已实测的坑写进代码**：`各自\s*os\.walk` 只许扫 §21 G2 行（裸搜全文会误伤 §15.5.1/§16 的「外部仓扫描方法」正确文本）；`unit\s*\*{0,2}83` 只许扫 §4 行（裸搜会误伤「83→107」勘误记录）。
- **CI**：`boundaries` job 末尾加 `doc cross-refs (advisory)`（`continue-on-error: true`），不改任何既有 step 的阻塞性、不动 `pytest` 的 `needs`；仓内无文档时该步打印 SKIP，真断言在本地/pre-commit 跑。
- **口径澄清（本轮只读文档，仅登记不修）**：§21「boundaries 实串 17 步」= **blocking 门步**（21 step = 3 个 `uses:` + `uv sync` + 17 blocking + advisory）；字面「step 数 − Setup Node」= 20，会误判。§21「15 个质量门脚本」同按 blocking 口径计（advisory 守卫单列）；加本守卫后磁盘上 `check_*/verify_*` 共 **16** 个（14+2）。
- **判据**：`check_doc_cross_refs.py` 退 0、`--self-test` 退 0（改 EXPECTED / 删定义 / 拆已改对 / 塞裸否决词 + 两个坑的反例，共 **6 种判红各演示一次**，另证 fixture 基线为绿）、全量 pytest **913 passed / 6 skipped 零变化**、`ruff check .` All checks passed。

### Added — P10 加固（可恢复压缩 / observability 刀 3 / 评测回归网）（分支 `feat/p10-hardening`；详 `docs/plan/10-p10-hardening.md`；ADR-0048~0051）
- **可恢复上下文压缩转正（Lane A，ADR-0048）**：`LoopPolicy.disable_compaction` 转正为 `CompactionConfig`；新内核内部 `CompactContext` Command 经 Command→reduce→durable（C2/C16，禁 out-of-band）；`kernel/compaction.py` 纯决策（`covered_hash` 剔 per-run seq/tool_call_id、确定性启发式摘要、只截 `closed_prefix` 内 C19 不孤儿化 open tool_use）；`reduce` 只纯校验+纯应用（摘要/锚由 loop 侧算好随命令携带，MAJ-8 保回放确定性）；`compact_started`/`compact_applied` additive 事件（22→25 type、四处 lockstep、`v` 不 bump）+ `baseline_seq` 栅栏 + `pre_compact` 补点；L2' 蒸馏桥（压缩丢弃区→`WriteMemory(distill)`→daily，可检索回读，ADR-0024/0025 生产者转正）；`check_replay_determinism._canonical` 纳入压缩态 + compaction fixture。
- **observability 刀 3（Lane B，ADR-0049）**：`python -m questor logs` 只读消费命令（`surfaces/logs.py`，`event_log` 主干 + 旁路按日 JSONL 按 `run_id+seq` 合并、坏行跳计 `malformed_lines`、全程只读不写）；`--log-payload`/`QUESTOR_LOG_PAYLOAD=truncate:N` preview 实装（C20 三闸：显式授权 + 独立 `questor.llm.preview` logger/`llm-<date>.jsonl` 通道 + 有界截断；`sink_file` 主干排除该 logger 保 D4 零原文；preview 过单一脱敏 filter；非法值仍 fail-closed 拒绝启动）；`logs --totals` session 用量聚合 = 跨 run 读 **durable `run_completed.usage`** 的 gseq 读侧投影（**不用从不发射的 `usage_delta`**，MAJ-4，非第二真相 ADR-0041/C13）。
- **评测回归网（Lane C，DoD-C）**：`tests/evals/test_p10_eval.py` 以 `ScriptedProvider` 驱全 loop、无 key/无网络出确定性判据（happy-path 恰一终态 + 压缩端到端真发 `compact_applied` 不丢事实召回 + 同输入两次事件序列一致）；新 `eval` pytest marker + 独立**非阻塞** `evals` CI job（`-m eval`，`continue-on-error`）。
- **卫生面回收（Lane D，ADR-0050）**：`StorePort` 增量 `reclaim_expired_leases`（只删过期）/`reclaim_stale_claims`（只删超 TTL 未 ack、**绝不删 acked 幂等键**——BLK-2 保 exactly-once）；`FileSystemArtifactStore.gc_orphans`（可达性孤儿扫描，内容寻址去重安全）+ `referenced_artifact_ids`；**`event_log` 主干裁剪显式后置**（与 `recovery_pointers`/回放权威/`--resume` 冲突，ACK 投递行与 session 级 artifact 回收绑定其后置）。
- **并行 gate 再后置登记（ADR-0051）**：工具 reader/writer gate + 真并发派发从 P10 悬置收口为独立并行化 Phase（post-P10、未立项），同步 HARD C19 `:108`/ADR-0039 措辞；执行仍严格串行 + 回发前配对（C19），不读 `parallel_safe`/`barrier`。
- **判据（均机器验证）**：全量 **838 passed / 5 skipped 零回归**（基线 800 + 38 新增）、全树 ruff clean、`lint-imports` 5 kept、协议 **25 types lockstep**、10 边界守卫全绿（layering/replay/cross-run/secret/log-isolation/projection-whitelist/output-budgets/openai-wire/thread-leak + protocol `--self-test`）、冷导入逐模块、`-m eval` **3 passed**（`test_p10_eval.py`；`tests/evals/` 目录共 4，含未标记的 `test_p4_memory_eval.py`）。**两路对抗评审**（首轮 2 Blocker+7 Major、二轮回归自查 2 Major）Blocker/Major 全关。
- **顺带发现登记**：`usage_delta` 为“已声明+已进外部白名单+生产路径从不发射”的死类型（驱动一度误用为聚合源，已纠正）；`FileSystemArtifactStore` docstring 称“按 run 隔离”与“内容寻址、run_id 不入路径”实现不符（以实际为准做可达性 GC）；`check_*` 守卫现场数=12（非 11）。
- **UNVERIFIED/后置（诚实边界）**：真 LLM 摘要质量、真多模态/远程面；桌前端 `check:protocol` TS codegen freshness（本轮无 node_modules 手工同步 `event.ts`，待依赖齐备时由 codegen 校验一致）；跨机 exactly-once、`event_log` 主干裁剪、acked-delivery/session-artifact 回收（绑 event_log 裁剪）、embedding/trigram-CJK 检索、工具真并发（独立 Phase）。未合 main（PR-only，push/merge 待逐次授权）。

### Added — P9 对外接口（OpenAI 兼容）+ 插件宿主（分支 `feat/p9-openai-plugin-host`；详 `docs/plan/09-p9-openai-plugin-host.md`；ADR-0043~0047）
- **OpenAI 兼容 = 投影适配器（T6/T9，ADR-0043）**：`surfaces/openai_compat.py` 新增 `POST /v1/chat/completions`——入站 `SubmitMessage` 经 Command Inbox（C16，禁直 reduce）、出站只读订总线投影为 OpenAI SSE（`text_delta`→`delta.content`、`tool_started`→`tool_calls`、终态→`finish_reason`+`[DONE]`、`run_failed`→错误编进末帧）；**无原生续传=断连经 inbox 提 `Cancel`、不假装 resume**；带外零双投（复用 `EventServer` 唯一 observer）。**鉴权外部 lane**：API-key/bearer fail-closed（无/错 key→401）+ 组合根 `--serve-openai`（默认 loopback、需 `QUESTOR_OPENAI_API_KEYS`）；对 ADR-0032 分道 scoping、sidecar loopback 红线不动。
- **wire 单一真源（T6，ADR-0043）**：OpenAI wire 独立于 questor 事件契约——新增 `contracts/openai_wire.py`（请求解析/chunk/error 构造）+ `protocol/openai_compat.schema.json` + 新守卫 `scripts/check_openai_compat_schema.py`（进 `boundaries` job）；questor `EVENT_SCHEMA_VERSION` **不 bump**、`event.schema.json` 不收 OpenAI 形状。
- **非文本归一拒绝（T7，ADR-0044）**：`image_url`/`input_audio`/`file`/语音类 content part → surface fail-fast 返 HTTP 400 OpenAI error（不起 run、不崩、不静默降级），additive `ErrorKind.UNSUPPORTED_MODALITY`（承 ADR-0036 决策 5）。
- **策略可插拔落地（T1–T4，ADR-0045）**：`policy/registry.py` `PolicyRegistry`（L4、进程内、trust project>user>system、`UnknownPolicyError`/`BrokenPolicyError` 留名、fail-open 回落默认+WARN、A/B 按 fingerprint）；`PolicyRef` + `Run.policy_ref` additive + `run_started.policy_ref`（不 bump `v`、四处 lockstep）；`surfaces/cli.py` 从硬编码 `ReActPolicy()` 改为经 registry 解析注入 loop（loop 仍只认 `PolicyPort`，C1）。
- **能力热插拔宿主（T5，ADR-0046）**：`capabilities/_host.py` `PluginHost`（统一 `init`/`teardown` + 每插件熔断隔离，C10，不吞 CancelledError）；`ToolRegistry` 加 `generation`；`tools_changed` 定为 **live-only**（`LIVE_ONLY`、不占 durable seq）由 loop 在 generation bump 处发；不移植 cordis TS 容器。
- **接回 P8：claim/delivery + 单机多进程 lease（T8，ADR-0047）**：`StorePort` 增量 `claim_delivery/delivery_state/ack_delivery` + `acquire/renew/release_lease`（epoch+ttl）；投递账本**从事件重放重建、不落第二真相**（C13/C15）；真接 `ReportChildTerminal` 投递路径（claim-then-deliver-ack）。
- **判据（均机器验证，`09 §9`）**：`test_openai_endpoint`（流式/聚合、401 fail-closed、400 非文本拒、断连→Cancel）、`test_openai_projection`、`test_openai_wire`、`test_policy_registry`、`test_policy_assembly`、`test_plugin_host`、`test_capability_generation`、`test_claim_delivery_lease`、`test_run_lease_multiprocess`（**两真 OS 子进程共享 SQLite 验单写者**）、`test_p9_policy_hotswap`、`test_tools_changed_lockstep`。全量 **800 passed / 5 skipped**、全树 ruff clean、协议 23 types lockstep、`check_openai_compat_schema` `--check`/`--self-test` 全绿。`v` 不 bump、信封/关联键/终止序零动。**独立复核（`P9-review-2026-10-18-independent.md`，CONDITIONAL GO）MA-1/MA-2 + MI-1/MI-2/MI-3/MI-4 已修**：`acquire/release_lease` 接进 resume 路径（run-lease 的真实单写者消费者，409/None 拒双驱）、cp936 子进程读线程钉 UTF-8、非 ASCII 往返测、非文本拒断言“不起 run”；PluginHost 与跨机消费者口径已按现实诚实收敛（见 `docs/audit/P9-review-2026-10-18.md §7`）。
- **UNVERIFIED/后置（诚实边界）**：真 LLM 驱动 OpenAI 面、真跨机 exactly-once（C12 天花板，单机多进程已验）、真广网部署/TLS（属算子）。未合 main（PR-only，push/merge 待逐次授权）。

### Added — P8 多 agent / 子 agent + DAG（分支 `feat/p8-multi-agent-dag`；详 `docs/plan/08-p8-multi-agent-dag.md`；ADR-0037~0042）
- **契约/事件（T1/T2，ADR-0042）**：新增外部事件 `peer_started`/`peer_ended`（20→22 type、additive、不 bump `v`），`contracts` ⟂ `protocol/event.schema.json` ⟂ TS `event.ts` 三处 lockstep（`check_protocol_schema` 守、`--self-test` 扩 fixture）；新增 `SpawnSubagent`/`ReportChildTerminal`/`UpdateTaskTree` Command 与 `Budget.max_parallel_children`/`max_tree_depth`。
- **状态机（T3/T4，ADR-0037/0038）**：`reduce` 首次处理 `task_tree`——DAG 依赖校验（无环/悬空/自环/唯一，I1）+ spawn 绑定 `assigned_run_id` + 子终态回填 `peer_ended`；非法命令拒+发错误事件、不改树、不崩。快照 schema 保持 v3（TaskNode 字段未变）；`check_replay_determinism` `_canonical` 纳入 `task_tree` + spawn/report fixture + 子顺序无关判据。
- **子 agent=独立 Run（T5/T6/T8，ADR-0038）**：`SubagentSpawnerPort`/`CommandRouterPort` 抽象 + `surfaces/subagent_orchestrator.py` 实现（同进程 asyncio 起子 run、跨 run 只经 Command、子终态 `ReportChildTerminal` 回父、父 terminal→`Cancel(owner)` 冻结子树不硬杀）；L3 `delegate` 工具复用既有工具生命周期。
- **安全边界（T7/T13，ADR-0040/0041）**：子 `PermissionCtx` 投影 fail-closed（mode 不继承、rules⊆父、denylist 只扩大、floor 同 OS）；fan-out 宽度/深度 admission gate（默认 4/1）。
- **判据（均机器验证）**：`test_p8_two_run_collaboration`（两 run 协作端到端、无旁路写）、`test_p8_reduce`/`test_p8_dag`（非法 DAG 拒+不崩）、`test_p8_permission_inherit`（子⊆父）、`test_p8_cancel_and_fanout`（取消传播+宽度/深度门，含 fire-and-forget 真路径）、`test_p8_isolation_and_projection`（子故障隔离 C10 + 扇出投影恰一次）、`test_p8_resume_roundtrip`（快照 round-trip/幂等）。**对抗审计（`docs/audit/P8-review-2026-10-18.md`）B1+Major/Minor 已全部闭环**：新增 `scripts/check_cross_run_no_bypass.py` 源码级守卫（F4）、`check_replay_determinism` 加 multi-child fixture（F6）、HARD C19 同步 ADR-0039/0041（F8）、payload-gate 消息 ASCII 化 + 测试锁 UTF-8（F1/F2/B1）。全量 **739 passed / 5 skipped**、**8 项边界守卫全绿**（含 cross-run 门）、TS codegen 无回归。
- **UNVERIFIED/后置（诚实边界）**：真 LLM/真开窗口驱动多 agent；跨进程 exactly-once（claim/delivery_state 账本归 P9，ADR-0021/0038）；工具 reader/writer gate（ADR-0039 显式再推后）。未合 main（PR-only，push/merge 待授权）。

### Fixed — `python -m questor --help` 掉进 REPL（Issue #148）

实地验证复现：`--help` / `-h` **不打印任何用法**而是直接起交互 REPL（rc=0），且拼错的选项（如 `--resum`）
同样被当成"无参数"静默起 REPL——属 **fail-open**，在自动化/CI 里表现成"挂住"而不是"明确失败"。
更隐性的一笔：参数判定之前就已 `assemble_logging()` + `SQLiteStore/SQLiteMemoryStore.connect()`，
所以**一次 `--help` 会顺手创建 `state.db` / `memory.db` / `memory_store/` / `logs/`**。

- 修：`_amain` 改为**先判参数、再装配**——`-h/--help` 打印用法进 stdout 退 0；未知选项打用法进 stderr 退 2；
  两者都在任何 store/日志装配**之前**返回。用法文本收敛为 `__main__._USAGE` 常量，与模块 docstring 的入口清单同源。
- 判红用例：`tests/integration/test_cli_help.py`（真子进程跑 `-m questor`，不 mock 组合根，与刀1 A①/A③ 同法）——
  四条分别钉住退出码、stdout 用法含四个入口、**不进 REPL**、且 `tmp_path` 下**不生成任何文件**（装配前置的硬可测代理）。
  修复前实测 4/4 判红（证据：stdout=`questor CLI — type a message …`、tmp 下生成 `logs/memory.db/memory_store/state.db`）。
- 本地全量门：689 passed / 5 skipped、ruff clean、冷导入 OK、import-linter 5 kept、AST 守卫 0 violation、协议 20 types lockstep。
- **回归（由 CI `tests-windows` 抓出、本机 cp936 抓不出）**：首版 `_USAGE` 把中文写进了用户可见输出，而 Windows runner 控制台是 **cp1252**
  → `print(_USAGE)` 直接 `UnicodeEncodeError` 带堆栈崩掉（rc=1、stdout 空）——“修 help”本身成了新崩溃。
  修：用法文本改 **ASCII-only**（AGENTS §5.6：一方输出用英文，中文只进注释/docstring）；并新增两条用
  `PYTHONIOENCODING=cp1252` 钉住代码页的回归用例（**在任何开发机上确定性复现**，不再依赖“恰好有块 Windows 机器”）；
  修复前先拿它判红、后转绿，全量 **691 passed / 5 skipped**。

### Changed — 文档漂移清扫（只加状态注记，不改阶段结论、不回改历史验收判据）

- **阶段列未同步的完成态**：`docs/ROADMAP.md §1` 的 **P5** 行无 ✅（实已经 PR #143 `114fb0f` + 加固 PR #144 `290375e` 合入）、
  **P7** 行无 ✅ 且 DoD 仍写"跑通 P1-P4"（§1.5 已上修为 P1–P5）——均按实况补齐并链到 `plan/05`/`plan/07`；
  §4 节点 C 标"阶段条件已满足、实际发布仍待消两项 UNVERIFIED（全量 `tauri build` 安装介质 + 真开窗口验收）"。
- **进度与决策计数陈旧**：`docs/VISION.md §8` 仍写"P0–P4 已交付（ADR-0001…0028）"与"P5 开工仍需先定 MCP `run_id` 注入/stderr 重定向"——
  实况为 P0–P5 + P7 已合入、ADR 至 0036，且该前置已随 P5 落地（`providers/mcp_stderr.py` 的 per-run `mcp-stderr-<run_id>.log`）。
- **死命令与不存在的 extras**：`CONTRIBUTING.md` 让人跑 `uv run questor --help`，但 `pyproject.toml` 无 `[project.scripts]`（入口只有
  `python -m questor`，已实跑验证）；同行声称的 `uv sync --extra im|voice|browser|docs` 四个 extras 从来不存在（无
  `[project.optional-dependencies]`），已改为实况说明并把 `voice`/`im` 指向 ADR-0036。
- **未修（属对外口径，需产品拍定，已登记）**：仓库根 `README.md:10` 仍写"暂无可运行版本"、快速开始仍写"P1 落地后更新为 `uv run questor`"——
  属对外口径改写（且桌面安装介质仍 UNVERIFIED），不在本次机械校平范围内。同轮撞到的 `python -m questor --help` 入口缺陷
  已开 **Issue #148** 并在本区间的 Fixed 条目里修掉（含判红用例）。

### Changed — 路线图：P6（多模态/语音）整阶段移除（[ADR-0036](docs/adr/0036-p6-dropped-from-roadmap.md)）

- **决策**：语音 + 图像识别两半**全砍**，不再占 Phase 编号；v1 后既定序列收敛为 **P7（已合入）→ P8 → P9 → P10**。
  依据：P6 在依赖图上是叶子（P8 进条件=P4、P9=P7、P10=P3 起持续，无 Phase 消费其产出）；`SCALE-ESTIMATE §3` 估其
  80–150 commit/文件 + 10+ provider，且 DoD 全压在本机无法证伪的外部云服务上。
- **编号不重排**：P7–P10 保持原号（已作为锚点散布于 ADR-0029~0035、已合并分支 `feat/p7-desktop-shell`、
  `docs/audit/*`、`docs/delivery/*` 与本文），重排等于回改历史快照。`plan/06` 从未开工，无需作废。
- **逆转路径写死**：将来确有需求 → 按 ROADMAP §5 另记 ADR，落点 = **L5 新增 vision/ASR/TTS provider + L6 接收面 +
  事件面只加 `type`（不碰信封/关联键/终止序）+ 大载荷复用 ADR-0019**；与 `SCALE-ESTIMATE §6` 既有归口一致。
- **P9 新增一条硬判据**（本次砍出的唯一工程欠债）：OpenAI 兼容面收到 `image_url` / `input_audio` 等非文本
  content part 时**必须归一化拒绝**（走 ADR-0028 故障归一终态），绝不崩、绝不静默降级成纯文本继续跑。
- **文档偏差记账**：核实发现 ROADMAP §1.5 R2、`delivery/P1-completion-report.md:110`、`plan/01:44,112` 宣称的
  "多模态事件 `type` 占位"**从未落地**——`contracts/events.py:251-273` 的 20 个 `EventType` 无一多模态类，全 `src/`
  对 `voice|audio|tts|asr|vision|attachment|modalit` 零命中。→ 移除 P6 无孤儿占位需清理；已把 §1.5 R2 改为实况口径，
  **历史交付报告不回改**（与既有纪律一致），只在 ADR-0036 记账。
- **同步修订**：`docs/ROADMAP.md` §1（P6 行）/§1.5（R2 + 新增 P9 备注）/§2；`docs/VISION.md` §8（原"待拍：多模态/语音
  哪些进第一版" → 已拍）；`docs/adr/README.md`（索引 0036）；`docs/SCALE-ESTIMATE.md` §2/§3/§4/§6（总量下调至
  ~1020–1650 commit）。
- **零代码/零契约变更**：无任何 Python/TS/Rust 文件改动，事件协议、状态模型、分层守卫均不受影响。

### Added — P7 桌面壳（Tauri）地基（分支 `feat/p7-desktop-shell`；详 `docs/plan/07-p7-desktop-shell.md`）

- **sidecar serve 生产入口（DoD①/⑤，ADR-0032/D-P7-B）**：`surfaces/serve.py` 把 `EventServer` 挂上 uvicorn，
  **只 bind `127.0.0.1:0`**（OS 临时口、绝不 `0.0.0.0`）、先写进程握手 bootstrap（`{host,port,generation,pid}`）
  再常驻；`__main__.py` 新增 `--serve`（具体 store 装配留组合根、serve 面不 import store 实现，守分层 AST 守卫）；
  `create_app` 加 `GET /health` 就绪探针。真 uvicorn 子进程 + 真 httpx 跑穿 `POST /run`→`text_delta`→终态。
- **带外投影收口为 bus 级只读订阅（DoD⑤，ADR-0033/D-P7-A，正面收 `plan/05` §0.4 缺口）**：`InProcessEventBus`
  新增 `add_observer`，`emit` 对每条投影后 Envelope **恰触发一次**（与订阅者数量无关）；`EventServer`/`CliSurface`
  各挂**一条** `log_envelope` observer；**删除 `cli._stream` 的逐消费者 `log_envelope`**（多 surface 双投隐患消除，
  违 C6/C20/pitfalls#2 的隐患收口）。九内核零依赖不破（`check_log_kernel_isolation` 绿、`lint-imports` 5 kept）。
- **协议 TS codegen + 漂移门（DoD①，C15）**：`desktop/web/scripts/generate-protocol.mjs`（`json-schema-to-typescript`）
  从 `protocol/event.schema.json` 生成 `desktop/web/src/generated/event.ts`（含 20 类 type 判别联合）；`--check`
  比对现算输出、陈旧即退出码非零；并入独立 blocking `boundaries` job。校正 `protocol/README.md` stale 的 “19”→**20**。
- **契约 additive 定形（DoD②，ADR-0034/0035；只增不改、三处 lockstep、类型数恒 20 不 bump）**：`node_updated` 从
  `None` 透传收为有界白名单 `{node_id,status,title,parent_id}`（去 draft 透传隐患）；`tool_completed` 加**有界**
  `preview` + `artifact_ref` 指针 + `truncated`（复用 ADR-0019，写失败绝不回退原文）；`message_completed` 加**有界**
  `final_text` + `item_id`（D-P7-C 选型①，重连仅靠事件流即恢复定稿文本、单一真源不另开 `/transcript`）。带外投影
  白名单恒不含 preview/final_text（C20）。修 `check_protocol_schema` 一处 doc/code 偏差：`project` 对未列表类型是**丢弃**而非透传。
- **TS 瘦客户端（DoD①/②/④，S6/C14/C16）**：`desktop/web/src/api/eventStream.ts`（`ThreadEventStream`：按 `seq` 游标
  去重不丢不重、live `text_delta` 按 `item_id` 缓冲、终态帧停流恰一终态、错误类 `run_failed/warning` 必出声、
  `resync_required` 即停重握手）+ `commandClient.ts`（**只**投既有 Command Inbox 端点、decision/mode 域锁死、非 2xx
  出声、绝不第二写入口）。事件类型仅从 `generated/` 导入。`tsc --noEmit` 净 + `vitest` 12 绿（纯逻辑，非像素）。
- **守卫扩面（DoD④，C14/C15）**：`scripts/check_thin_client.py`——静态扫 `desktop/web/src`（排除 `generated/`）拦 harness
  逻辑下沉（bus/store/权限/reduce/`questor.` 等）+ 事件信封类型只可来自 `generated/`；fail-on-empty + `--self-test` 判红；
  并入独立 blocking `boundaries` job。`scripts/verify_release_bundle.py`——结构门：sidecar 二进制**恰一个**（0/多→红）+
  内嵌解释器在位（无系统 Python 回退）+ 资源树非空；`--self-test` 判红/绿；sidecar 三段式步骤①窄锁
  `desktop/sidecar-requirements.{in,lock}`（`uv pip compile` 产出）。
- **端到端能力矩阵（DoD①/②，脚本化 provider）**：`test_p7_desktop_e2e.py`——真 uvicorn+httpx 跑流式（`text_delta` +
  `message_completed.final_text` + 终态、durable seq 不重，交叉校 `store.replay`）、取消回填（`Cancel`→`run_cancelled` +
  未闭合 `tool_use` 配对、无悬空，C7/C19）、Skills 目录注入 system prompt；断言落 reducer/store 侧。
- **Rust sidecar 监管核心（DoD③/⑤，`desktop/sidecar` crate，cargo 验证）**：零外部依赖的生命周期状态机，供
  `src-tauri` 壳复用——`Fence`（`AtomicU64` generation 栅栏，重启后旧代连接一律判陈旧丢弃，ADR-0032）、
  `two_phase_shutdown`（优雅请求→轮询到 grace→`force_kill` 兜底）、`fail_all`（按代失效当前代 pending，C10/C19 不撕裂）、
  `wait_ready`（轮询 loopback `127.0.0.1:<port>` 就绪，替代参考仓 stdin 握手）；`backend.rs` 把 `Process` 接到真
  `std::process::Child`，**真子进程**跑通强杀兜底并回收（DoD③ 崩溃/teardown 在真 OS 上验证，非 mock）。`cargo test` 8 passed。
- **Tauri v2 桌面壳（T8，本地编译验证）**：`desktop/src-tauri` 复用 `questor-sidecar`——setup 里 bump generation → spawn
  `python -m questor --serve` 为独立进程 → 读 bootstrap 拿 loopback 端口 → webview 指 `http://127.0.0.1:<port>`
  （S5/ADR-0007：仅 HTTP+SSE、不进程内直调 Python）；ExitRequested 走 `two_phase_shutdown`。`tauri.conf.json` 锁 CSP
  （`default-src 'self'`、`object-src 'none'`、`connect-src` 仅 loopback），capabilities 不授 fs/shell。本机
  `cargo check` Finished + `cargo test` 2 passed（bootstrap 契约解析 + 无 sidecar 时 shutdown no-op）。
- **Windows Job Object 杀进程树（T8，cargo 验证）**：`StdProcess` 在 Windows 下用裸 kernel32 FFI
  建 `KILL_ON_JOB_CLOSE` Job 并 assign 子进程，`force_kill` 走 `TerminateJobObject`（连 MCP 孙进程一起回收）、
  Drop 关 job 防孤儿；真机 `cargo test` 含 `job_object_terminates_assigned_child` 绿。
- **sidecar 三段式 + PyInstaller 冻结（T8，本机实产跑通）**：`desktop/scripts/build-sidecar.py` 把
  `questor --serve` 冻结为 **onedir**（非 onefile）；`verify_release_bundle.py --verify-runtime` **启动冻结 exe**
  （无系统 Python）→读 bootstrap → /health → /run → /events，实测 `run_started/turn_started/message_completed/run_completed`
  全流（带外投影行也真落盘）——“无系统 Python 回退 + 冻结产物真能服务”由 UNVERIFIED **转已验**。
- **决策**：ADR-0032（sidecar serve 接线与进程边界）、ADR-0033（bus 级只读投影）、ADR-0034（D-P7-C 重连文本=选型①
  有界 `final_text`）、ADR-0035（工具/节点事件 additive 定形）。
- **P7 对抗式审计后加固（`docs/audit/P7-review-2026-10-17.md` 判 NO-GO → 逐条修）**：sidecar 启动位解析
  `resolve_sidecar`（env→发布资源→开发态，发布态不写死 `python`）+ bundle 打包链；会话 token 强制端点鉴权（
  缺→401，堆本机旁路 HITL）；真 `/shutdown` 优雅关闭；崩溃检测/重启决策原语；MCP 接进 sidecar 路径（原仅 CLI）；
  字段级协议漂移两道 `--check` 门；`resync_required` 分因（after_ahead）+ 传输级 `stream_end` 尾帧；clippy/fmt 绿；
  新增独立 `ci-desktop` 桌面 lane 与 `check_desktop_csp` 锁定。修一处预存在测试时区缺陷（日志读器用本地日期而 sink 按 UTC 命名）。
  **仍 UNVERIFIED**：真开窗口/全量 `tauri build` 安装介质/真远程 MCP/真 LLM（环境受限）。
- **诚实边界（UNVERIFIED，不用 fake 冒充真机）**：真**开窗口/像素渲染**（需显示环境）与全量 `tauri build` 桌面 bundle
  （需 `@tauri-apps/cli` + WebView2 runtime + 上一步的 vite 产物链）、真远程 MCP server 端到端、真 LLM、
  在途半条 live-delta 文本恢复——本机无头环境不跑真窗口，未伪造（sidecar 冻结产物已实跑、Tauri 壳已 `cargo check`/`test` 编译级验）。

### Added — P5 Skills / MCP（分支 `feat/p5-skills-mcp`；详 `docs/plan/05-p5-skills-mcp.md`）

- **Skills 加载（DoD①）**：`capabilities/skills`——`SKILL.md` 严格 frontmatter 解析（依赖最小、不新增第三方）、
  name/目录名校验、**单坏文件降级+出声不拖垮发现**（C6）、METADATA→INSTRUCTIONS→RESOURCES 渐进披露、
  正文有界告警；发现的技能目录注入 agent system prompt（生效）。改造自 crewAI `skills/{parser,validation,loader}.py`（MIT）。
- **MCP 客户端（DoD②③）**：`capabilities/mcp`——`mcp.json` 载入（整体坏 fail-closed / 单条坏出声跳过）+ 配置文件名
  与 `PROTECTED_IN_ROOTS` 写保护的机器耦合测试；载入/spawn **双门**安全（裸 shell 解释器 / egress / exfil / 持久化，
  hermes `mcp_security.py` 思路）；stdio 连接生命周期（官方 `mcp` SDK v1，ADR-0030；握手限时、失败清理不留半初始化、
  aclose 回收子进程树）；远程 `inputSchema` 归一（DeepCode `core/mcp/schema.py`）、`mcp_<server>_<tool>` 命名、
  描述过共享 `bound_description` 有界、远程→`ToolSpec` 非放宽（capability=NETWORK、read_only 默认 False、
  approval unknown→deny）；`ToolRegistry` 命名冲突拒覆盖+出声；`McpManager` 编排（env/stderr 工厂注入，L3 不 import L5）。
  真 stdio 假 server roundtrip + 断连/失败恢复测试通过（非 mock 冒充真进程）。
- **子进程观测（DoD⑤ / DESIGN §16.4 D-16.4-A/B）**：`providers/mcp_stderr.py`——MCP server stderr 落**独立 per-run 文件**
  `mcp-stderr-<run_id>.log` + spawn 侧 `run_id` 显式注入（文件名主、首行辅）；跨进程关联 canary 真子进程实测通过
  （`contextvars` 不过进程边界，绝不靠 ambient `bind()`——`docs/pitfalls.md` 第 3 条）。C20：独立通道只放子进程自有输出。
- **决策**：ADR-0029（`parallel_safe`/`barrier` 移出 P5、执行严格串行）、ADR-0030（采用官方 `mcp` SDK，pin `<2` 对齐参考实现）。
- **端到端已接**：L6 组合根 bootstrap（`surfaces/mcp_bootstrap.py`）把 MCP 连接接入单次 run 的工具面（per-run 生命周期
  + teardown）；C17 env 凭据门在装配侧拒绝 server.env 携带 provider 凭据；`test_mcp_loop_integration.py` 以真子进程
  + 真 SQLiteStore 实测“远程工具→`event_log` 先入账”与“无网络围栏时 C17 floor fail-closed 拒但配对仍闭合”。
  真实外网 MCP server / 真 key 端到端、HTTP sidecar 带外投影仍标 **UNVERIFIED**（见 `docs/plan/05` §0.4）。
- **对抗式验收审计加固**（`docs/audit/P5-review-2026-10-17.md`）：MCP 发现上限 256、逐工具畸形 descriptor 守卫、`normalize_mcp_schema` 递归深度上限、`${VAR}` 占位符 fail-closed、`McpServerConfig.env` repr 隐值（C17/C18/C20，各配判红测试）。
- 许可/provenance：crewAI / DeepCode / hermes / CowAgent 改造（MIT，改造处文件内标 provenance）；`mcp` SDK MIT；EvoFlow evopanel 零接触。

### Fixed

- **`test_powershell_timeout_kills_parent_and_child` 在 UTF-8 模式下确定性报 `UnicodeDecodeError`**：
  测试辅助 `_process_alive` 用 `check_output(..., text=True)` 解码 `tasklist` 输出；无匹配项时 tasklist
  把提示写向 stdout 且用 OEM 代码页（zh-CN=cp936），开 `PYTHONUTF8`/PEP 540 时按 UTF-8 解码崩溃。
  改为按字节在原始输出里查 ASCII PID，不再依赖子进程输出解码（与代码页/locale 无关）。
  产品路径不受影响（`process_runner._read_stream` 早已 `errors="replace"`）。另见对应 GitHub Issue。

### Fixed — 日志骨架（刀 2）复审修正（分支 `fix/log-blade2-audit`；Issue #126–#139）

把刀 2 的所有可走路径全量跑了一遍（真子进程、真 IO、真并发），发现并修掉 3 个 BLOCKER + 6 个 MAJOR + 4 个 MINOR：

- **#126（BLOCKER，零原文）**：装配不再把 root logger 降到 DEBUG，pipeline 新增**来源门**——非 `questor.*` 的
  记录有效下界恒为 INFO。旧行为下 `aiosqlite` 会把 `INSERT INTO checkpoints ...` 的**完整参数元组**（含用户 prompt
  原文与 `state_digest` 全量快照）经带内桥写进主干 JSONL，D4「零原文默认」实际被旁路。
- **#127（BLOCKER，stdout 洁净）**：在 `providers/litellm_adapter.py`（全仓唯一 import litellm 处）摘掉 litellm 自己挂在
  stdout 上的 handler（`LevelRoutingStreamHandler`：按级别分流，INFO/DEBUG 写 stdout）；`--list`/`--dream` 的 stdout
  现在逐行必须是机器可读行（哨兵 / run id / `deep_dream:` 摘要）。旧判据正则要求同行 level 后再出现 `questor`，
  对第三方行天然免疫，所以 G-L10 从未真生效。（复审过程中先误归因为 loguru sink，按实测推翻后改了修法——
  可见性不丢：那些 logger `propagate=True`，记录仍进 root 上的桥。）
- **#128/#131（BLOCKER/MAJOR，错误不静默）**：ERROR/CRITICAL 完全绕过节流；节流签名改为
  `(logger, level, msg 形状, run_id)`，形状归一（数字/十六进制/引号串 → `<*>`）。旧行为下同秒两个 run 各失败一次时
  第二个 run 的 `run_failed` 在日志里一行都不剩；反向则是“同形状不同值”的风暴零抑制。
- **#129**：`NOISY_LOGGERS` 补真实 logger 名 `LiteLLM`（大小写敏感，旧条目 `litellm` 从未生效）与 `aiosqlite`。
- **#132**：`pipeline.emit/flush` 补顶层兜底（兑现 docstring 的“绝不上冒”）；`redact` 的 fail-closed 分支与节流窗尾
  补行都不再因 `fields`/`context` 撞键反过来抛 `ValueError`。
- **#133**：带内桥不再丢整行——`log_fields` 与关联键/保留键撞名时改 `f_` 前缀并标 `fields_collapsed`，非标量值走
  §16.1 的有界 repr 并标 `args_coerced`。
- **#134/#137（MAJOR，守卫可信）**：新建 `scripts/check_projection_whitelist.py`（G-L11 真正的 AST 守卫：内联读键必须
  ∈ 白名单 + 白名单不得含敏感键，带 `--self-test` 判红与 fail-on-empty）并接入 CI `boundaries`；
  `check_log_kernel_isolation.py` 补“防作用域变宽”。投影白名单同时补上 `message`/`reason`/`expected`/`current`，
  让 `warning`/`resync_required`/`run_cancelled` 的日志行不再级别对、内容空。
- **#135/#136/#138**：软阈值提级改为**按日**记账与重置（不再进程终身制把此后所有分片永久降到 INFO）；`atexit` +
  拆装配时先 flush 再注销 sink，使窗尾 `repeated N times` 在生产路径成立；`surfaces/_assembly.assemble_logging()`
  统一两个生产入口的 env 族与 payload 门（旧 `cli.main()` 裸装配，既不建文件面也不拒非法 payload 值）。
- **A① 真实成立**：组合根与装配面各补一方记录（`questor.assembly` / `questor.composition`）——旧“起手有日志”是
  靠第三方噪声凑数，修完来源门后那些噪声已不再进入。
- 回归：全量 `559 passed / 5 skipped`（基线 527，新增 32 条判据，无新增 skip）；新判据在未修复源码上经
  `git stash` 突变验证 **21 条全红**，确认不是装饰性测试。

### Changed — 建立陷阱档案与一条新红线（同一轮复审的制度产出）

- 新增 [`docs/pitfalls.md`](docs/pitfalls.md)：只收“跨子系统 + 理解成本高 + 会再踩”的架构级陷阱（按分区）。
  **普通 bug 不进来**——它们走带 `bug` 标签的 GitHub Issue，由 commit 正文的 `Fixes #N` 在合进 `main` 时自动关闭。
- 新增工程红线 **C20（观测面不得成为载荷的第二载体）**，并在 C6 例外款下补一行：“静默”不限于丢弃，
  节流折叠/合并不比丢弃轻。本区间的范围提法（AGENTS / CLAUDE / VISION / `plan/_TEMPLATE`）同步抬到 C1–C20，
  `plan/_TEMPLATE` §3 加一行“开工先查 pitfalls”的自检项。

### Changed (文档对齐 / dead-pointer 清除，附 ADR-0028 同分支)
扫描并修掉会让下一位读者走错路的文档漂移（**不改任何阶段结论、不回改历史验收判据**，只加“当时至 Cxx”型注记）：
- **死链**：`AGENTS.md`（仓库根）的 `./design/HARD-CONSTRAINTS.md`、`./VISION.md`、`./ROADMAP.md` 与 `../CONTRIBUTING.md` 均指不到目标（真源在 `docs/`）——`AGENTS.md` 本身要求“读链接后的文档、不要凭记忆工作”，链接断则规则书自相矛盾；`CLAUDE.md` 同步修两条同类死链。
- **红线范围漂移**：`AGENTS.md`/`CLAUDE.md` 仍写 C1–C13、`VISION.md` §8 仍写 C1-C12；已统一至 **C1–C19**。已完成阶段的 `plan/02`/`plan/03`/`plan/04` 与 `plan/01` DoD 保留原文并加“本阶段验收时至 Cxx”注记（历史判据不回改）；`plan/_TEMPLATE.md` 的自检范围从 C15 抬到 C19，使 P5 开工时不会漏新红线。
- **与 ADR-0020 矛盾的旧口径**：`design/01` 两处（§5 “P3 落定”、§13 Checkpoint 行）仍写“默认**写门截断**到 `closed_prefix`”——该方案在实现期已被修正为“完整快照 + 派发侧补齐”（截断会抹掉 `awaiting_approval` 续跑稳态）；已改为实况并保留修正出处。`plan/01` T9 同步就地标注。
- **陈旧进度块**：`VISION.md` §8 仍说“下一步：02→03→04 设计文档”（早已全部定稿）；改为指向 **ROADMAP §1 为进度真源** + 当前 P0–P4 已交付，并就地解释“单步接口”与 ADR-0028 多调用关卡不矛盾。`plan/02` §13 开头仍写“尚未实现”而 §13.1–13.3 已回填——加状态更正。
- **ADR 计数**：`CLAUDE.md` 仍写 ADR-0001…0012、CHANGELOG 仍写 …0019 → 均改为 0028 并注明 0027 预留。
- 审计/交付报告（`docs/audit/*`、`docs/delivery/*`）是**时间点证据**，按纪律不回改（包括其引用的旧行号/旧函数名）。

### Added
- 设计文档体系：VISION、ROADMAP、STRUCTURE、design（分层/状态/事件/工具/循环/策略/记忆/工程红线）。
- 架构决策记录 ADR-0001…0028（阶段新增见下方各段；0027 为日志骨架刀 2 预留，索引见 `docs/adr/README.md`）。
- 外部参考扫描报告 R01–R09（docs/references）。
- 仓库治理：README、LICENSE、CONTRIBUTING、SECURITY、CODE_OF_CONDUCT、.github 模板与 dependabot、工程卫生配置。
- 阶段计划：`docs/plan/02-p2-tools-permission.md`（P2 工具 + 权限 lite；按 2026-10-15 对抗审计全面修订，固化 Command Inbox、PermissionCtx 单一真源、capability floor、审批生命周期、Shell IR、ProcessRunner、有界 Artifact 与字段级投影）。

### Added — 日志骨架（刀 2 / PR-B，ADR-0027；补 ROADMAP §1.5“轻量可观测从 P1 就落”的欠债）
把日志从刀 1 的 console-only 升为完整“两入口 → 一个中间表示 → 一条治理管线 → 多个 exporter”闭环（`docs/log/DESIGN.md` 三层形状）：
- **九内核文件**（零 `questor.*` 依赖、连 contracts 都不许，可整体抽包）：`entry`（`LogEntry` frozen + 白名单值域 fail-closed，D3/D11）、`scope`（`contextvars` `bind` 加键语义，D5/D6）、`redact`（唯一脱敏 filter、msg/fields/traceback 三面 fail-closed，D12）、`exporter`（协议 + 幂等注册）、`sink_console`（stderr、Unicode 安全）、`sink_file`（按记录 `ts` 日切 JSONL + `errors`/`llm` 分流 + 软阈值主动降级 + 懒清理 + 只读降级，D7/§16.3）、`bridge`（stdlib Handler→LogEntry、降噪白名单、§16.1 args 强转）、`pipeline`（脱敏→节流→级别→fan-out、exporter 异常绝不上冒 D13）、`configure`（参数化幂等装配 + `logging_status`、env-free）；适配层 `projection`（唯一 import contracts、Envelope→LogEntry 白名单载荷、live-only 丢弃、错误类非静默 C6）。
- **组合根接线**（`__main__`）：读 env 族 `QUESTOR_LOG_DIR`/`QUESTOR_LOG_KEEP_DAYS`/`QUESTOR_LOG_LEVEL`/`QUESTOR_LOG_PAYLOAD`（preview 归刀 3、本期非 off 拒绝启动）传入 `configure_logging`——带内桥 + 按日文件面在生产运行时**首次生效**（此前 `__main__` 只调 console-only 兼容层，刀 2 管线是“写完没接线”的死代码，且半成品迁移把带外投影改走 pipeline 后无人接→`--resume` 零日志）。
- **关联 id α′**（`kernel/loop.py`）：`_drive_controller` 两处 `bind`（run_id 整轮、turn 每轮从权威局部变量重盖章）→ inline 行携 `run_id`/`turn`（G-L5；`test_log_correlation_via_real_loop.py` 真 loop + 真 IO 锁死，注释 `bind(turn=...)` 即判红）。
- **LLM 观测零原文**（`providers/litellm_adapter.py`）：每次 `stream` 结束（成功/失败/取消）产一条 `questor.llm` DEBUG 行，携 `provider/model/duration_ms/status/finish_reason/prompt_tokens/completion_tokens/request_sha256/response_sha256/error_class`，**无任何 prompt/响应片段**（D4/B⑤，`test_llm_observation_no_payload.py`）。
- **守卫 G-L1/G-L2**：`scripts/check_log_kernel_isolation.py`（内核零依赖 + 类型不泄漏，含 `--self-test` 判红 + fail-on-empty + 抓动态 import，复用 `check_layering_ast` 单一 walker）接入 CI `boundaries` blocking job；`.importlinter` 第五契约同步。
- 迁移：删 `observability/logging.py` 兼容层（`configure_logging` 迁至 `configure.py`、`log_event`/`error_from_failed_event` 由 `projection.log_envelope` 取代）及其 `test_configure_logging_idempotent.py`（G-L8 幂等由 `tests/unit/observability/test_configure.py` 承接）；`surfaces/cli.py` 走 `log_envelope` + `configure.configure_logging`。
- provenance（改造思路 + 文件内标注，六仓 MIT/兼容，详见 ADR-0027）：栈桥日切 + LLM 通道/sha256 ← DeepCode；降噪白名单/幂等/Unicode ← hermes；双级别 ← MetaGPT；不可写降级 ← CowAgent；协议留内/容器注入形状 ← cordis；结构化事件行风格 ← autogen-core。
- **刀 3 后置（未做，诚实标注）**：§14 `questor logs` 消费命令、`--log-payload` preview 实装、OTel/metrics；HTTP sidecar 路径的带外投影仍只在 CLI 消费者处挂（bus 级只读订阅为将来收口点）；`strip_prompt_echo` 仅纯函数 + 单测、接线后置。G-L7 跨进程按日写为 `[非阻塞·夜间]`、不入 PR 门。

### Added — P0 (interface skeleton)
- `src/questor` 8-layer package skeleton with L0 contracts (commands/events/state-schema/policy/tool/ports) and stub base classes.
- Mechanical layering guards: `.importlinter` + ruff `banned-api` + a self-written AST checker (dynamic imports, fail-on-empty, self-test).
- `protocol/event.schema.json` as the external-event single source + `check_protocol_schema.py --check` drift guard.
- CI `ci-python.yml` (boundaries as an independent blocking job) + `verify_p0.py` one-click check.

### Added — P1 (minimal runnable loop)
- `reduce()` single writer: tool_use/tool_result pairing, terminal uniqueness, cancel backfill of open calls.
- SQLite event-sourcing store (per-run seq, `after_seq` replay) + `closed_prefix` checkpoint write-gate.
- In-process event bus: internal→external projection, live-only deltas, first-writer-wins terminal, version gate.
- Turn loop (phase pipeline) with serial tools, budget termination, deny + illegal-intent non-crash paths.
- Three-state permission engine (non-overridable realpath denylist); `read` tool; LiteLLM + scripted providers; in-process ReAct policy.
- CLI terminal surface + HTTP/SSE service (`/run`,`/events`,`/cancel` with `id:<seq>` + `Last-Event-ID` resume) + structured logging.

### Added — P2 foundation (T1–T13, on `feat/p2-foundation-hitl`)
- Non-blocking coverage baseline: `pytest-cov` + branch coverage XML artifact in the `tests` job (no `fail-under` gate yet).
- L0/contract vocabulary: tool-call lifecycle states, `ApprovalRequest`/`ApprovalStatus`, raw-args status, `SandboxDescriptor`, `ProcessRequest/Result`, `ArtifactRef`/`OutputBudget`, shell-analysis IR, `CommandInboxPort`/`InboxReceipt`, `PermissionDecision`/`Outcome`; protocol EventType grew 17→19 (`approval_resolved`, `permission_mode_changed`).
- Versioned snapshot (v2) round-trips full authority: `permission_ctx`/approvals/rules, task_tree, error_stack, and expanded ToolCall fields; unknown versions fail-closed with v1 lossy migration.
- `RunController` serialized Command Inbox (FIFO, idempotency, backpressure, terminal rejection) wired into the turn loop; five-layer validation reordered to args→schema→shell-analysis→validate→permission→floor.
- Pure `PermissionCtx` engine + fail-closed POSIX/PowerShell shell parsers + capability floors above `mode`; honest host sandbox backend detection.
- Harness-owned `SandboxedProcessRunner` (Job Object + taskkill process-tree cleanup, env credential scrub, output limits→artifact), content-addressed `FileSystemArtifactStore`, provider `env_safety`.
- Full HITL lifecycle (request/resolve/expire/cancel idempotency, approval timeout) driven only via Commands; CLI + HTTP (`/runs/{id}/approvals/{req}/resolve`, `/permissions`, `/runs/{id}/cancel`) submit through `RunRegistry` and never `reduce`.

### Added — P2 tools, protocol, guards (T14–T21, `feat/p2-foundation-hitl`)
- `ToolRegistry` + L0 `RunToolSurface`: per-run frozen tool view (hot register/unregister never mutates a running run), description sanitize/bounds, unknown-name candidate hints surfaced to the model.
- File tools with shared workspace-containment resolver: `read` (offset/limit + line/byte caps + dir/binary reject), `write`, `edit` (unique-anchor / `replace_all`), `apply_patch` (unified-diff, per-file all-or-nothing), `ls`/`glob`/`grep` (entry/match caps, noise-dir skip, symlink-escape + invalid-regex handling).
- `bash`/`powershell` tools built only on `ctx.run_process` (no spawn in capabilities); CLI registry now exposes the full P2 tool set; loop wires a real `ProcessRunner` + `ArtifactStore` into `ToolContext`.
- Field-level protocol: `protocol/event.schema.json` gains per-type `$defs` + `if/then` (required fields, bounded strings, `additionalProperties:false`); projection enforces a per-type outbound whitelist (full args / abs path / env values / provider state never leave).
- HITL checkpoint resume: `resume_run` restores awaiting-approval state and closes due approvals via `ExpireApproval` (permission/approval state cannot silently evaporate on restart).
- New machine guards (each with `--self-test` that goes red): AST forbidden-import rules (capabilities/surfaces/contracts), output-budget invariant guard, secret/env-value projection guard; CI runs them and adds platform-split `tests-posix` / `tests-windows` jobs so PowerShell vs bash DoD is exercised on the real platform (skip-when-absent, never faked) — Windows only on PR/dispatch/main to keep its runner minutes down.
- P2 end-to-end DoD test drives a fully-wired loop (engine + capability floor + registry + Command Inbox) for the headline dangerous-op flows.

### Added — P3 persistence + resume (`feat/p3-persistence-resume`)
- **Durability is now the normal path**: the CLI loop and HTTP server persist every durable event + turn/`pre_tool`/`post_tool` checkpoints through `StorePort` (the composition root `__main__` injects `SQLiteStore`; surfaces still import no concrete store — C4/C14). A killed run leaves a durable, resumable trail.
- **Dual cursor materialized on `StorePort`** (ADR-0011/0022): per-run logical `seq` (SSE `after_seq`) + a global monotonic physical `gseq` watermark (`watermark`/`replay_global` cross-run catch-up); `meta(store_schema_version)` fails closed on a newer-than-known DDL; `list_unfinished_runs` derives resume candidates from the log (no terminal event present).
- **Cross-process resume** (ADR-0020/0021): `rebuild_run` = latest full snapshot + `seq` aligned to `sequence_head` + close due approvals; `resume_and_drive` hands the rebuilt run back to the single `DefaultTurnLoop`. Before the next provider call the loop settles still-open calls — `awaiting_approval` waits on its existing request, crashed `ready/running` calls re-dispatch once, and `pending/validated` calls re-run the **full permission gate** (resume never silently bypasses `ask`). Checkpoints keep the full authoritative state (incl. open calls & approvals); `closed_prefix` identifies the in-flight set rather than truncating it, so HITL survives restart.
- **Surfaces**: `python -m questor --resume <run_id>` / `--list` and `POST /runs/{id}/resume`, all submitting through `RunController`/`RunRegistry`, never `reduce` (C16).
- **Verified on the real platform**: cross-connection and OS-subprocess kill→`--resume` (`test_p3_kill_resume.py`, Windows); a real `uvicorn` + `httpx` SSE reconnect with `Last-Event-ID` proves `after_seq` no-loss/no-dup over an actual socket, closing the P2 audit §7 "跨真实 socket UNVERIFIED (uvicorn 未装)" item.
- **New guard** `check_replay_determinism.py` (wired into the CI `boundaries` job): asserts `snapshot + tail-replay == continuous reduce` over fixtures, with a `--self-test` that proves it can go red + fail-on-empty; plus a durability guard that no durable event bypasses `store.append` while live-only never persists.

### Added — P4 memory v1 / soul (`feat/p4-memory-soul`)
- 记忆子系统 `src/questor/memory/`（与 `state/` 分离，ADR-0023）+ L0 `contracts/memory.py`：`MemoryChunk`/`MemorySearchResult`/typed `RecoveryPointer`/typed `MemoryWrite`/`MemoryStorePort`/`VectorBackend`/`MemoryStrategyConfig`。
- 写记忆走 `Command→reduce→MemoryStorePort` 单写者路径（HARD C4/C16）：`reduce` 处理 `WriteMemory` → 内部 `memory_written` 事件（有界、**无原文**）→ kernel 在消费点 sink 落**独立 `memory.db`**；记忆正文绝不进 `Domain_State`（DoD⑤）。
- `providers/store_memory_sqlite.py`：md 文件真源 + SQLite/FTS5 派生索引、单一 `_SCHEMA` authority + `meta(memory_schema_version)` fail-closed + `BEGIN IMMEDIATE`；与 event-log 分库故障隔离（R03 D-P1）。
- 混合检索 `memory/{chunker,sync,search}.py`（ADR-0026）：markdown 感知切块 + 文件真源重建 + rank-normalize 加权融合（**非 RRF**）+ 时间衰减（daily 半衰、core 常绿）+ 无 embedding 静默降级关键词-only；`memory_search` 工具经 Harness 持有的 `MemoryStorePort`，策略/工具无裸句柄。
- Deep Dream 离线蒸馏 + run-完成→daily flush（`memory/distill.py`，ADR-0025）：原子写 + 输入哈希去重 + 只删不编 + 空哨兵跳过；CLI `--dream` 入口（无密钥走确定性 heuristic fallback；真 LLM 蒸馏质量 UNVERIFIED）。composition root 注入 `SQLiteMemoryStore`。
- 快照 schema **v2→v3**：`recovery_pointers` 定为 typed `(seq_from, seq_to, covered_hash)` + 读前 fail-closed；v1/v2 无锚旧值迁移为 `()`（不伪造锚，ADR-0024）。`covered_hash` **生产者**随 `disable_compaction=True` 后置 P10。
- 事件协议 **19→20**：新增可选外部 type `memory_written`（bounded `kind/chunk_count/source/artifact_ref`），`check_protocol_schema` enum+$defs+branches+fixtures lockstep（只增不改）。
- 策略 `policy/memory_policy.py`：记忆感知 ReAct 变体消费 `PolicyView.memory` 有界投影（L4 接缝示例、可插拔，不改 kernel）。
- 守卫：`check_layering_ast.py` 扩记忆规则（memory=state peer、只依 contracts；`policy`/`surfaces`/`capabilities` 禁 import 具体 `store_memory_sqlite`），`--self-test` 判红；已在 CI `boundaries` blocking job 运行。记忆写/读旁路=0（reduce 唯一入口 + AST 守卫）。
- 决策 ADR-0023~0026 + 阶段计划 `docs/plan/04-memory-soul.md`。质量门：405 passed / 5 skipped（DoD① 跨会话写入→检索命中、DoD② Deep Dream 产出、DoD③ 单写者、DoD④ 可插拔、DoD⑤ state/memory 分离 + evals 雏形）。UNVERIFIED：真 LLM/embedding 召回质量、trigram-CJK 未实现（后置 P10）、完整四档压缩（→P10）、跨进程记忆 exactly-once（→P9）。

### Fixed (多 tool_call 配对崩溃 — ADR-0028, 2026-10-16)
真机复现并逐段核验：模型一轮返回 ≥2 个 tool_call 时，串行循环只执行第一条就回发下一次请求，历史留下
悬空 tool_call → provider `400 …must be followed by tool messages…` → **异常穿出 `drive_controller`、整个 CLI
进程带 traceback 退出、run 不落任何终态**。
- **回发前配对关卡（新硬约束 C19）**：全仓唯一的 `ProviderPort.stream` 调用点（`kernel/loop.py::_stream_turn`）
  内先跑 `_ensure_paired_history`：一条 assistant 里**所有**未应答 tool_use 串行闭合才允许下一次请求（仍不启用
  并行，ROADMAP §2.5 口径不变）。判据取 **context 侧** `open_tool_use_ids` 而非账本 OPEN 集合——实测存在
  “context 有悬空、ledger 无条目”的分叉，账本驱动的回填盖不住。不可调和 → fail-closed 落 `run_failed(format_error)`
  且**一次都不发**（不靠投影层合成假 tool_result 骗过协议，那会把 ledger/context 分叉制度化）。
- **provider 故障归一（plan/01 T4、design/01 §8、ADR-0010 首次真接线）**：新增 `contracts/errors.py::
  classify_provider_error` 纯函数（不 import provider/litellm；状态码 → 消息 `Error code: NNN` → 有序模式表 →
  fail-closed UNKNOWN，自己绝不抛），kernel 边界捕获 `Exception` → `_fail_with_entry` 落唯一终态；BaseException
  （取消/中断）继续上抛。**400 配对违规钉为不可重试**：否则 P10 接上退避重试会把同一确定性错误打满预算。
  本轮不自动重试（退避/fallback 链/凭据池仍归 P10）。
- **stop-gate 同源路径**：策略给 `SuggestFinish` 而账本仍有 OPEN 调用时的 `continue`，实测会反复带悬空历史回发
  直到 max_turns（白烧 3 轮预算）；现由同一关卡收掉。
- **被拒收消息的 durable 泄漏**：重复 `tool_use_id` 被 `AppendAssistantMessage` 整条拒收后，loop 仍把本地消息
  当已落库定稿，经 `FinalizeRun(final=…)` **走私回 context**，留下一条永不配对的 tool_use 且因 `completed` 不进
  `--list`/resume（比崩更难查）。现改为“未产 `message_completed` 即出声”→ `run_failed`。
- **取消优先**：关卡不得为补配对而继续执行未跑调用；实测取消后 `provider.stream` 不新增、落单调用作
  `cancelled` 回填、`error_stack` 保持空（R01 F8：取消绝不进重试分类）。
- **关卡不改变“谁能跑”**：补执行仍走完整权限/floor/参数校验。实测关卡补执行一个 none 后端的 write 时
  **真的发出 `approval_request`**（理由为 write capability floor）→ 无人决策超时 fail-closed deny、目标文件不落盘；
  非法参数的落单调用也回 error 结果闭合配对。
- **复用不新写**：ADR-0021 的 `_resume_settle_open_calls` 改名 `_settle_open_calls`（resume 入口与关卡两个安全点共用，
  行为逐字不变）。`docs/log/{DESIGN,PLAN}.md`、`plan/01`、`plan/03` 同步注记。
- peer-scan（AGENTS §4.5）：位置采纳 CowAgent `agent/protocol/agent_stream.py:1604-1608`；**拒** CowAgent
  `message_utils.py:21-120` 的合成 tool_result 抹平（事件溯源下会分叉）；分类器形状改造自 hermes
  `agent/error_surface.py` + `error_classifier.py`（MIT © Nous Research，已就地注 provenance）。
- 机械守卫：新增源码级测试——全仓 `self.provider.stream(` 调用点必须唯一且在 `kernel/loop.py`、关卡必在请求
  之前（fail-on-empty；已验证“拆掉关卡即判红”）。
- 测试：`tests/integration/test_pairing_gate_and_provider_fault.py`（10）+ `tests/unit/test_provider_error_classification.py`（8），
  先红后绿（修前同文件 7 条集成测试中 6 条全红、包含“非法历史真的被发出去了”这一直接证据；仅“取消优先”当时已绿）。
  质量门：**443 passed / 5 skipped**（已含 PR #123 的 3 条；单独本分支基于旧 main 时 440）；ruff clean；lint-imports 4 kept；AST 76 files/0 违规且 self-test 判红；
  protocol 20 types lockstep；replay/output/secret/thread 守卫全绿；`verify_p0` ALL PASS。端到端在 `CliSurface.run_once`
  层面复验：一轮 `ls`+`read` + 严格网关判 400 的 provider → `completed`、两次 stream 均无悬空、异常不再穿出。
  UNVERIFIED：真 key 下 litellm 具体异常类型与 `status_code` 载体（版本相关）。

### Fixed (composition-root model wiring — `QUESTOR_MODEL` 到不了真实供应商, 2026-10-16)
实地复现：配 `QUESTOR_MODEL` 后 CLI 仍未打到 DeepSeek。
- **组合根未透传 model**：`__main__._amain` 以 `CliSurface(store=…, memory_store=…)` 生成 surface，缺省 `model="echo"`。该 "echo" 经 `loop` → `ProviderRequest.model` 在 `litellm_adapter` 的 `request.model or self.model` 里以非空真值覆盖了 `LiteLLMProvider` 自带的 `QUESTOR_MODEL`，模型名到不了真实供应商。修复：组合根新增 `_model_from_env()`（读 `QUESTOR_MODEL`、缺省回落 "echo"，与 `_store_path`/`_log_level_from_env` 同为 env 收口点，DESIGN §11），显式传入 `CliSurface(model=…)`。`test_composition_root_model.py` 跑真实组合根（替换 `interactive` 捕获 surface、真 SQLiteStore、不联网）锁死：有 env → 透传、无 env → 回落、且 `surface.model` 必落到 `ProviderRequest.model`。质量门：**425 passed / 5 skipped**。

### Fixed (log assembly coverage — PR-A / 日志刀 1, 2026-10-16)
补齐 `docs/log/DESIGN.md` §11 点名的"最严重装配缺口"（纯缺陷，不动契约/分层）：
- **四入口日志裸奔**：`configure_logging` 此前只在 `interactive()` 里调，崩溃恢复最该有日志的 `--resume`（及 `--list`/`--dream`）无 handler → INFO 全丢。修复：装配上移组合根 `__main__._amain` 起手，读 `QUESTOR_LOG_LEVEL`（默认 INFO），覆盖 REPL/`--resume`/`--list`/`--dream` 四入口（`test_log_assembly_coverage.py` 真子进程断言 `--resume` stderr 有 questor 行）。
- **`questor.bus` 死 logger**：`kernel/events.py` 定义 `_log` 却零调用，订阅者队列溢出与持久化失败无人报。修复：`emit()` 溢出→出声丢帧、持久化失败→出声后上冒（数据丢失不静默吞）（`test_bus_failures_voiced.py`）。
- **console sink 显式绑 stderr**：`configure_logging` 不再依赖 `basicConfig` 默认，显式 `StreamHandler(sys.stderr)`、幂等不叠 handler、永不污染机器可读 stdout（`test_configure_logging_idempotent.py`，DoD A③/A④）。
- 落 `docs/log/{DESIGN,PLAN}.md`（设计定稿 + 刀 1/刀 2 实施计划）；`plan/01` T12 标"部分兑现"。脱敏/节流/白名单/文件面/双通道汇流随 PR-B（刀 2，对抗评审门后）。

### Fixed (P4 adversarial audit round, 2026-10-16 — closes `docs/audit/P4-review-2026-10-16.md` CONDITIONAL GO)
对抗审计发现两处"文档宣称≠代码现实"+ 三处小问题，均已复核并修复：
- **写生产者未接线（阻断记忆可用性）**：`flush_run_to_daily` 无生产调用者、产品无 `WriteMemory` 触发器。修复：`CliSurface.run_once` 在 run 完成边界 best-effort 调 `flush_run_to_daily`（经 `MemoryStorePort` 收口、不进热 loop、`run_id` 幂等、失败仅告警），episodic→daily→Deep Dream 链在产品中真能跑；新增 `test_p4_memory_flush.py` 走真实 loop（非手动 inbox）证写→检索。
- **trigram 档位谎报**：代码只有 unicode61→LIKE 两档，`store:13` 过期注释 + ADR-0026/design-06/plan 宣"三档"。修复：全部改为"两档实现、trigram-CJK 未实现→后置 P10"、删过期注释。
- **`memory_written.source`** 误用 `kind.value` → 抽 `contracts.memory.source_for_write`（L0，store/reduce 共用），emit 真实 `MemorySource`。
- **Deep Dream 无界重试**：ADR-0025 宣"transient 重试 3 次"却无实现。修复：`_call_distill` 有界重试、耗尽上抛（不静默吞）；测试 transient×2→第3次成功 + 耗尽抛。
- **D③ 命名测试缺失**：补 `test_p4_memory_single_writer.py`（加载 AST 守卫断 capabilities/policy/surfaces 直连具体 store 判红）。`PolicyView.memory` 无生产填充者（loop 有意不填以免耦合）→ plan §11 记 P5/P7 backlog。
- 复跑质量门：**412 passed / 5 skipped**（+7 审计修复测试），全守卫 self-test 判红、protocol 20 types lockstep、lint-imports 4 kept。

### Fixed (P2 adversarial audit round, 2026-10-16 — closes `docs/audit/P2-review-2026-10-15.md` NO-GO)
All four blocking findings were reproduced by hand before fixing, and each is now pinned by a test:
- **Tool panics escaped the kernel**: `loop.py` called `tool.execute()` with no shield, so a raising tool (or an unwired `ProcessRunner`/`ArtifactStore`) crashed the run and left the call stuck open. The Harness now wraps every tool call in `asyncio.wait_for` + `except Exception` → `ToolResult(status="error")`, while `CancelledError`/`KeyboardInterrupt`/`SystemExit` still propagate (`test_p2_tool_fault_isolation.py`).
- **`FinalizeRun` left dangling `tool_use`**: a `failed` terminal didn't backfill open calls, breaking the pairing invariant I1 and guaranteeing a 4xx once P3 replays the context to a provider. Both terminal paths now backfill with distinct `note` text and continuous seq allocation (`test_reduce_finalize_pairing.py`).
- **Bundled short flags were mis-classified as read-only**: `sed -ni` reads as `-n`+`-i` (in-place write) to a shell, but the parser compared the whole token against the write-flag set, so under job/partial + `full_auto` an in-place file edit could skip the approval floor entirely. Flags are now expanded before comparison, and spacing no longer changes a security decision (`test_bundled_short_flags_are_expanded`).
- **`PermissionCtx.denylist` was a fake control plane**: the engine only consulted hard-coded constants, so adding a path had no effect despite ADR-0014 claiming otherwise. It now participates as its own evaluation step (union with built-in defaults; cannot weaken them), and ADR-0014 gained an implementation addendum describing exactly this.
Also fixed: Harness-armed deadlines for non-process tools (a `sleep(30)` tool previously ran to completion and reported success); `TIMED_OUT` now actually produced instead of being flattened into `error`; `enforce_read_only` / `protected-root` / Windows junction-escape branches covered by real tests (junction escape now **verified**, no longer UNVERIFIED); `check_output_budgets --self-test` can now prove red; AST guard no longer misses `from questor import <layer>`; `wrap_shell` seam exists and is refused by every backend; dead `ToolSpec` fields annotated `NOT enforced until P#`; process output previews now cut on valid UTF-8 boundaries.

### Fixed (found by the first P2 CI run on Linux, 2026-10-16)
- `surfaces/approval.py`: the reader thread called `loop.call_soon_threadsafe` outside its `try`, so a keystroke arriving after an approval timeout (loop already closed) raised `RuntimeError: Event loop is closed` inside a daemon thread. Now routed through `_safe_settle()`, which discards late input — that drop *is* the timeout-means-deny semantics — with two falsifiable regression tests.
- Shell-tool platform gating: the DoD tests keyed off `shutil.which("powershell")`, but the ubuntu runner ships `pwsh`, so tests that must skip did not — and they used `NullSandbox` as if it could execute. They now probe the real capability (`detect_sandbox().wrap_argv`) and skip with an explicit reason when the host cannot wrap argv, while a new always-run assertion locks the correct behaviour: no capable backend means a structured error, never an unconfined spawn.
- `tests/unit/test_loop_tool_ctx.py` hard-coded a Windows path as "absolute argv[0]", which `ProcessRequest` correctly rejects on POSIX; switched to `sys.executable`.

### Fixed (P0/P1 adversarial audit, 2026-10-15)
- C2: deep-freeze JSON leaves (`ToolCall.args`, `ContentBlock.input/payload/provider_state`, `Envelope.data`) via `immutables` so COW states no longer share mutable leaves.
- C7/ADR-0011: Cancel no longer emits two events with the same seq (was causing a store `IntegrityError`).
- Capability/risk fail-closed: exec/write/network with no capable sandbox backend are denied in the loop.
- Protocol guard now fails on an empty `EventType` set; bus prunes subscriber queues at terminal; `python -m questor` launches the CLI.

<!-- 实现里程碑 (P0/P1/…) 达成后在此按 Keep a Changelog 追记 -->
