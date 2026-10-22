# P10 独立对抗式验收审计（independent）— 可恢复压缩 / observability 刀 3 / 评测回归网 / 卫生回收

> 审计者：独立第三方评审（与被审实现者无关）。职责是**证伪**，不是背书。
> 全程 READ-ONLY：仅只读 + 实跑 + 临时证伪并当场还原；未修改被审 src/tests，未 commit/push/merge。
> 结论一律附证据（`file:line` 或亲自执行的命令原始输出）；跑不出来标 UNVERIFIED；绝不臆造。

## §0 头部 — 现场基线（实取）

| 项 | 值 | 取法 |
|---|---|---|
| 被审 worktree | `d:\DEVELOP\Project-main\questor-p10-hardening` | `pwd` |
| 分支 | `feat/p10-hardening`（= `origin/feat/p10-hardening`） | `git rev-parse --abbrev-ref HEAD` |
| HEAD（审计终态） | `03f780e9660e34de56a0f45df05e3f7c530cfa11` | `git rev-parse HEAD` |
| merge-base main HEAD | `cfc3004663c658e7319fa57de07f6748830e7d14` | `git merge-base main HEAD` |
| 提交数 | **8** | `git rev-list --count main..HEAD`（`Measure-Object -Line` 曾报 7，改 rev-list 复核） |
| 起手 porcelain | 空 | `git status --porcelain` |
| 环境 | uv 0.11.19 / Python 3.13.7 / 宿主代码页 **936（GBK）** | `uv --version`、`chcp` |

**⚠ 审计期间基线漂移（如实记录，承"证据锚定 HEAD"纪律）**：起手实测 HEAD = `d0f7dc9`（7 提交、CHANGELOG/ROADMAP 尚无 P10 交付条）。审计进行中，分支**前进一个提交**至 `03f780e`（`docs(p10): close out living docs`），并同步 `origin`。经核：`03f780e` **仅改 docs + CI**（`.github/workflows/ci-python.yml` +22、`CHANGELOG.md` +10、`docs/ROADMAP.md` +1、`docs/design/06-memory.md` +1、`docs/log/DESIGN.md`、`docs/plan/10-p10-hardening.md` +19），**未触碰任何 `src/` 或 `tests/`**——故本报告全部源码级结论对 `d0f7dc9`→`03f780e` 逐字成立。文档类判据（CHANGELOG/plan §9/CI evals lane）按**新终态 `03f780e`** 审。终态 porcelain 干净。

红线现场数：逐条读 `docs/design/HARD-CONSTRAINTS.md`，现场数 **C1–C20（20 条）**（另有一节"天花板"未编号）。据此自检。

判据源（均现场读，非记忆）：`docs/plan/10-p10-hardening.md`（§1 DoD / §2 不做 / §3 ADR 门 / §8.1 收尾 / §9 偏差回填）、`CHANGELOG.md [Unreleased]` P10 条、`docs/adr/0048~0051`、`docs/pitfalls.md #1–#5`、`AGENTS.md §5/§5.5`、`docs/ROADMAP.md §1/§1.5`。**实现者自审 `docs/audit/P10-*.md` 不存在**（glob 返回 0），本报告为首份 P10 独立审计。

---

## §1 一句话结论

**CONDITIONAL GO。** 四条 lane 的**机制层**真实落地且诚实标注：全量套件 **838 passed / 5 skipped 零回归**（与 `03f780e` 文档宣称逐字相符）、12 守卫 `--self-test` 全判红 + repo scan 全判绿、协议 additive（`v=1` 未 bump、25 types lockstep、字段级漂移门实测判红）、observability 刀 3 三闸真实且已接线、eval 网脚本化无 key 确定性。**未发现 Blocker**（无红套件 / 无第二真相 / 无载荷泄主干 / 无 cp936 崩溃 / eval 不偷依赖真 LLM）。

**但两条承重接缝无生产消费者/无兑现**（见 §4 Major-1/Major-2）→ 须关闭方可转 GO：
1. **可恢复压缩在生产态恒关**：唯一生产构造点 `surfaces/cli.py` 从不注入 `compaction`，`src/` 无任何 `CompactionConfig(...)` 构造——shipped 产品永不压缩，DoD-A 仅经测试注入配置端到端验证。
2. **`covered_hash` fail-closed 回读未实现**：`RecoveryPointer.matches()` 在 `src/` **零调用方**、无按 `recovery_pointers` 从 `event_log` 回读原文的消费者；锚是"写-only"元数据。DoD-A①/ADR-0048 把"篡改→读回拒绝"列为交付不变式，代码未兑现（CHANGELOG 措辞已收敛为"生产者"，honest）。

---

## §2 DoD 逐条判定（ROADMAP P10 行 + plan §1）

ROADMAP §1 P10 行判据：**"任务级回归网跑通；压缩不丢事实召回；追踪面板基于事件流"**。

| DoD | 判据（plan §1 摘录） | 判定 | 证据（实测/`file:line`） |
|---|---|---|---|
| **DoD-A①** 恢复锚 | 被压区 `recovery_pointers` 携 `covered_hash` 且能 `matches()` 校验、原文从 `event_log` 回读、篡改→**读回 fail-closed 拒绝** | **部分** | 生产者真实：`compaction.py:61-64`（`covered_hash`）、`:103`（写 `RecoveryPointer(seq_from,to,hash)`）、`reduce.py:371`（append）、`snapshot.py:382`（序列化）、`__post_init__` 拒空 hash（`memory.py:135`）。哈希敏感性单测真：`test_compaction_plan.py` 两例（易变字段不变 / 语义改则变）。**但回读消费者不存在**：`grep src 中 .matches(` → 0 命中，无按 seq 从 `event_log` 重建原文的路径 → "篡改→读回拒绝" 无执行点。**§4 Major-2** |
| **DoD-A②** 配对 | 压缩后每个 `tool_use` 有配对 `tool_result`（只在 `closed_prefix` 截、尾窗保留，C19） | **达成** | `reduce.py:361-362` 三道 fail-closed 含 `evict ≤ closed_prefix`；判红单测 `test_compaction_reduce.py:96`（越界拒 + WARNING、状态不变）。守卫绿 |
| **DoD-A③** 头尾锚 | 最新可见 assistant 回复 + 每个 user 轮仍在活区 | **达成（经保头/保尾）** | `compaction.py:97-98` `keep_head/keep_tail`；eval `test_p10_eval.py:103` 断言 `DELTA-9 in live_text`（保头留活区）。plan §9.5 诚实记"DELTA-9 在受保护头、不经 distill 回读" |
| **DoD-A④** 回放确定性 | `check_replay_determinism.py` 含压缩 fixture：(full-reduce)==(snapshot+尾重放)，`--self-test` 能判红 | **达成（有盲区）** | 实跑 `check_replay_determinism.py` → "6 fixtures OK"、exit 0；`_canonical` 纳入 `summary/compaction_floor/recovery_pointers`（`:228-230`）；`_fixture_compaction:149-171` split 在压缩命令**之前**（压缩前快照+尾事件==连续 reduce，正合判据文字）。**盲区**：见 §4 Minor-1 |
| **DoD-A⑤** additive 事件 | `compact_started/applied` additive、`v` 不 bump、四处 lockstep、schema 有 `$defs` | **达成** | `EVENT_SCHEMA_VERSION=1`（`events.py:28`），与 `main` 逐字相同（`git show main:...`）→ 未 bump；`check_protocol_schema --check` → "25 types lockstep"；F1 实测：改 `compact_applied` 字段名→`--check` **exit 2 判红** |
| **DoD-B①** logs 只读消费 | `python -m questor logs` 读主干 JSONL + `event_log` 权威按 `run_id+seq` 合并、只读、坏行计 `malformed_lines` | **达成且已接线** | `logs.py:23-46/80-116`（只 `replay/replay_global` + `read_text`，不写不 GC）；生产入口 `__main__.py:244→251` 真调 `run_logs_command` |
| **DoD-B②** 带外投影收口 | bus 级一处只读订阅、每 seq 恰一行（承 pitfalls #5） | **达成**（承 P7/P9，P10 未回退） | `cli.py:216` `bus.add_observer(log_envelope)`，逐消费者 `log_envelope` 已删；`check_cross_run_no_bypass`/投影守卫绿；`test_p7_out_of_band_projection` 在套件内通过 |
| **DoD-B③** preview 三闸 | `--log-payload=truncate:N` 仅独立 `llm` 通道、必过脱敏、有界、主干零原文、非法值拒启动 | **达成且已接线** | 三闸：`_assembly.py:47-68`（显式授权 + 非法 `SystemExit`）+ `:81-87`（`llm_file=preview is not None`）；生产者 `litellm_adapter.py:250-259`（`: self.payload_preview` 有界、只投 `questor.llm.preview`）；**主干白名单无载荷键** `projection.py:55-65`；canary `test_log_preview.py:61-77`（主干无 canary、llm 有、`sk-` 脱敏）；生产接线 `cli.py:89`；`check_projection_whitelist --self-test` 加 `arguments` 即红 |
| **DoD-B④** usage 聚合 | 读 durable `run_completed.usage`、跨 run gseq、不落第二真相、**不用 `usage_delta`** | **达成** | `logs.py:58-77/86-95` 仅认 `RUN_COMPLETED`；`grep src usage_delta 发射点` → 零发射（仅 `LIVE_ONLY` 集 + 丢弃 + 注释），plan §9.1 诚实登记死类型；无新表、每次现算 |
| **DoD-C①** 无 key/无网络确定性 | `ScriptedProvider` 驱动 eval、无 `LITELLM_API_KEY`/无外网跑出 pass-rate/token/cost | **达成** | 实跑 `LITELLM_API_KEY='' uv run pytest -m eval` → **3 passed**（`test_p10_eval.py`，全用 `ScriptedProvider`）；CI `evals` job `ci-python.yml:228-244` `continue-on-error:true`、`needs:boundaries`、跑 `-m eval` |
| **DoD-C②** 反假绿 | 注入"压缩丢事实/投影双投"→eval 判红；`--self-test`/突变 | **部分** | eval 含确定性两次同输入比对（`test_p10_eval.py:109-122`）；守卫突变反假绿由 `--self-test`（12/12 判红）承担。但 eval 本身的事实召回腿走"保头"（§9.5），"去写锚→eval 红"未见专测；判红主要靠 reduce 单测 + 守卫，非 eval 端到端突变 |
| **DoD-C③** 真 LLM=UNVERIFIED | 真 key 摘要质量不写进已验证 | **达成（诚实）** | `test_p10_eval.py:8` + plan §9 + ROADMAP:44 均列 UNVERIFIED；无真 LLM 用例混入 `eval` marker |
| **DoD-D①** claim/lease 回收 | 只回收过期/已释放 lease + 超 TTL 未 ack claim；**绝不裁 acked delivery**；未知版本 fail-closed | **达成（无生产触发）** | `store_sqlite.py:346-358`（仅 `expires_at<now`）、`:360-375`（仅 `state='claimed' 且过期`、注释明令不碰 acked）；`_enforce_schema_version:110-126` fail-closed；`test_p10_hygiene.py` 判红覆盖。见 §4 Minor-2（无调用方） |
| **DoD-D②** artifact 孤儿 GC | 只删不被任何事件/检查点引用的孤儿；不虚称 session cleanup | **达成（无生产触发）** | `artifact_store.py:107-125` 按 `referenced_ids` 可达性删、`referenced_artifact_ids:128+` 递归取 `artifact://`；MAJ-7 session cleanup 未做且诚实后置（ADR-0050、§9.2） |
| **DoD-D③** event_log 裁剪显式不做 | 与 `recovery_pointers`/单真相冲突 → 后置登记 | **达成** | ADR-0050 决策 1 + plan §2.5 点名后置；代码无 trunk 裁剪路径 |
| **贯穿质量门** | 全量 pytest 零回归、ruff clean、lint-imports kept、冷导入、协议零 diff、Windows leg、UTF-8 锁定 | **达成** | 838/5（实测）、ruff "All checks passed!"、`lint-imports` 5 kept/0 broken、25 types lockstep、cp936 `-W error` 18 passed 无崩溃（§4 证伪见下） |

---

## §3 红线 C1–C20 逐条自检（现场读 HARD-CONSTRAINTS + 实测）

| C | 约束要点 | 判定 | 证据 |
|---|---|---|---|
| C1 | 分层依赖方向、禁跨层直调 | ✅ | `lint-imports` 5 kept（含"kernel 不 import policy/surfaces""logging kernel 不 import 任何 questor 层"）；`check_layering_ast` 116 files/0 违规 |
| C2 | 单写者 + 不可变视图 | ✅ | 压缩经 `CompactContext`→`reduce`（`reduce.py:352-388`，返回新 State、不改旧）；无 out-of-band 直改 `context.items`；`check_cross_run_no_bypass` 绿 |
| C3 | 视图 vs 快照 | ✅ | `pre_compact` 走既有 `save_checkpoint`（`loop.py:469`），未滥用全量快照 |
| C4 | Store 读写过接口 | ✅ | `logs.py` 只持 `StorePort` 抽象；distill 经 `WriteMemory`→reduce→`MemoryStorePort`（`loop.py:496-501`） |
| C5 | Command/Event 分离、Event 不回灌 | ✅ | `compact_*` 为输出事件，未被作为改状态输入 |
| C6 | 事件内外分层 + 版本、只增、折叠/合并同罪 | ✅ | `compact_*` additive、`v=1` 未 bump；错误类未静默（`_LEVEL_MAP`）；投影守卫绿 |
| C7 | 终止权在 Harness | ✅ | 压缩不引入第二终止路径（`reduce` CompactContext 非终态） |
| C8 | 工具边界有界 | ✅ | `compact_applied.data` 仅 `{baseline_seq,covered_from,to,summary_bytes}`（`reduce.py:385`），无正文；`covered_hash` 有界 |
| C9 | 权限三态 | ✅ | 压缩不改权限；distill 写走既有收口 |
| C10 | 插件生命周期隔离 | ✅（本 Phase 未触） | — |
| C11 | 状态谨慎演进、字段 additive | ✅ | `CompactionConfig` 新字段 additive；`snapshot` v3 不 bump、v1/v2 无锚迁 `()`（`snapshot.py:417-423`） |
| C12 | 非分布式 | ✅ | 无跨机代码；后置 UNVERIFIED |
| C13 | 只存内部事件 / 终态唯一 | ✅ | `logs`/usage 全读 `event_log` 派生、不落第二表；每 run 恰一终态（eval 断言） |
| C14 | 结构边界机器守 | ✅ | import-linter + ruff banned-api + AST 守卫；logs 属 surfaces 只读、零业务下沉 |
| C15 | 外部契约单一真源 + 守卫可信 | ✅ | `protocol/event.schema.json` 单真源、`--check`/`--self-test` 全绿且 F1 实测判红；12 守卫全 `--self-test` 判红 + scan 判绿 |
| C16 | Command Inbox 唯一写入口 | ✅ | 压缩为**内核内部** Command（loop 内 `reduce`，非 surface 直调）；surfaces 无 `reduce()` 直调；`check_cross_run_no_bypass` 拦 foreign `.run=` |
| C17 | 权限/floor 优先 | ✅ | 压缩不改权限、distill 照走既有审批 |
| C18 | 载荷有界 + artifact 指针 | ✅ | `covered_hash`/preview 有界；artifact 走 `artifact://` 指针非全文 |
| C19 | 回发前配对 + provider 不崩 + **非并行通行证** | ✅ | 只在 `closed_prefix` 内截（`reduce.py:361`）；`_stream_turn` 关卡未动（`:516`）；**不读 `parallel_safe`/`barrier`**（`grep src` 0 读点），ADR-0051 收口为独立 Phase，C19 `:108` 措辞同步（`03f780e` HARD +1/-1） |
| C20 | 观测面非第二载体（含不越界款） | ✅ | preview 采 C20 明许"显式授权+独立通道+有界截断"三闸；主干 `_DATA_KEYS` 无载荷键（`projection.py:55-65`）；`check_projection_whitelist` 加载荷键即红；真文件 canary 主干零原文；OTel/metrics 未引入（§2.7/MAJ-6），九内核 `check_log_kernel_isolation` 9 files 零依赖 |

> 顺带：C21（registry first-writer-wins）非本 Phase 红线，`_freeze_surface` 未破。

---

## §4 发现清单

### Blocker
- **无。**（套件全绿、守卫全判红、协议 additive、无第二真相/载荷泄主干、eval 脚本化无网络、cp936 无崩溃。）

### Major-1 — 可恢复压缩在生产态恒关（承重接缝无消费者 / 失败族③）
- **证据（实测）**：唯一生产构造 `DefaultTurnLoop(...)` 在 `surfaces/cli.py:170-186`（`http_sse`/`subagent` 经 `surface._loop` 复用同一函数），**参数表不含 `compaction=`**；`Select-String src/questor/surfaces/cli.py -Pattern "compaction"` → **0 命中**；`Select-String src/**/*.py -Pattern "CompactionConfig\("` → **0 构造**。`loop.py:464-465` `if self.compaction is None: return run` 故生产每次安全点 `maybe_compact` 即时空转。
- **机制本身真实**：`loop.py:391` 确在安全点调用、`:469` 真发 `pre_compact`（补上 ADR-0048 指出的"pre_compact 从未发射"缺口）、`:470-501` 经 Command→reduce→durable + L2' 蒸馏桥；eval/集成用**显式注入** `compaction=CompactionConfig(...)`（`test_compaction_loop.py:51`、`test_p10_eval.py:69/90`）验证端到端可跑。
- **后果**：DoD-A"压缩不丢事实召回"仅在测试注入配置下成立；shipped CLI/serve/桌面**永不触发压缩**，"压缩转正"作为阶段成果在运行态未兑现。文档（CHANGELOG/ROADMAP）未谎称默认开启，属**交付完整性缺口**而非虚报。
- **可复现**：`git grep -n "compaction" src/questor/surfaces/cli.py`（应见注入却为零）；`git grep -n "CompactionConfig(" src`（应见生产构造点却为零）。

### Major-2 — `covered_hash` fail-closed 回读消费者缺失（DoD-A①/ADR-0048 未兑现 / 失败族③）
- **证据（实测）**：`Select-String src/questor -Pattern "\.matches\("` → **仅 `memory.py:137` 定义、0 调用方**；无任何按 `recovery_pointers.seq_from/to` 从 `event_log` 回读原文 + 重算 `covered_hash` + `matches()` + 拒返旧内容的执行路径。`replay/replay_global` 存在但无消费者把它接到锚校验。
- **已兑现部分**：锚**生产者**完整（`compaction.py:61-64/103`、`reduce.py:371`、`snapshot.py:382`）；哈希语义敏感性有单测（`test_compaction_plan.py`）；快照迁移诚实（v1/v2 无锚→`()`,绝不伪造，`test_snapshot_v2.py:122-128`，缺失 hash 由 `__post_init__` 拒）。
- **缺口**："历史被改写/分叉即 fail-closed"（`memory.py:125`）是文档化不变式但无强制点——当前 `recovery_pointers` 为写-only 元数据，读回时无任何校验会拒绝被篡改的覆盖区。
- **文档诚实度**：CHANGELOG 措辞为"covered_hash fail-closed **生产者**"、plan §9.5 把召回腿收敛为"保头 + distill 检索"，**未**bold 声称回读消费者；但 plan §1 DoD-A① / ADR-0048 决策 5 文本仍把"读回 fail-closed 拒绝"列为已验证交付不变式，与代码不符 → 记 Major，须么补消费者 + 端到端判红测、要么把 DoD-A① 该子句改标"后置/未实现"。
- **可复现**：`git grep -n "\.matches(" src`（生产调用应为 ≥1，实为 0）。

### Minor-1 — `check_replay_determinism` 压缩 fixture 存在盲区（实测证伪）
- **证伪实验（当场还原）**：临时把 `state/snapshot.py:380-382` 的 `summary`/`recovery_pointers` 序列化**改为丢弃**（`None`/`[]`，模拟有损快照）→ `uv run python scripts/check_replay_determinism.py` **仍 exit 0（"6 fixtures OK"）**。原因：`_fixture_compaction:171` 的 split=3 落在 `CompactContext` **之前**，两条路径各自在 tail 应用同一命令，故压缩态快照 round-trip 丢失对本 fixture 不可见。→ 同一次篡改下 `pytest tests/unit/test_snapshot_v2.py::test_snapshot_roundtrips_full_authority` **FAILED**（pytest 层抓得住），故真实回归仍会被全量套件拦下。`git checkout` 已还原、porcelain 干净。
- **判定**：守卫非空转（approve 截断样例能判红），但其"压缩确定性"覆盖面窄于 BLK-1 所忧"压缩后状态经快照 round-trip"。可接受（有 pytest 兜底），建议 split 移到 compact 之后补一条 round-trip 断言。

### Minor-2 — Lane D 回收/GC 无生产触发点（账本无界增长动机未解 / 失败族③）
- **证据**：`reclaim_expired_leases`/`reclaim_stale_claims`（`store_sqlite.py:346/360`）、`gc_orphans`（`artifact_store.py:107`）在 `src/` 仅有定义 + `ports.py` 声明，**无生产调用方**（`grep` 命中的 `gc` 只有 `configure.py:92` 的日志按日 gc 与 logs.py 的"不触发 GC"注释）；调用只在 `test_p10_hygiene.py`。
- **后果**：ADR-0050 立项动机"三账本无界增长"在运行态未被任何 sweep/命令/启动钩子化解——回收方法正确但从不运行。
- **文档诚实度**：DoD-D/ROADMAP 只称"回收保守子集已机器验证（行为正确）"、未称已接生产触发 → 属交付完整性观察，非虚报。

### Minor-3 — 文档 eval 计数漂移（"evals 4 passed" vs `-m eval` = 3）
- **实测**：CI `evals` job 跑 `pytest -m eval` → **3 passed**（仅 `test_p10_eval.py`，`pytestmark=pytest.mark.eval`）；`tests/evals/` 目录收集 **4**（另含未标 `eval` 的 `test_p4_memory_eval.py`，它随常规套件跑、不在 `-m eval` lane）。CHANGELOG/plan §235 称"evals 4 passed"取自"跑整个 evals 目录"，与 CI 标记选择数不一致 → 记 Minor 计数漂移。全量"838 passed / 5 skipped""基线 800+38""25 types lockstep"**逐字命中实测**，无漂移。

### 可接受占位（据实点名，非缺陷）
- **OTel/metrics**：移出 P10（§2.7/MAJ-6），无新依赖、九内核零依赖守卫绿——**正确的 YAGNI**，非半成品。
- **真 LLM 摘要质量 / 真多模态/远程面 / `check:protocol` TS codegen freshness（本环境无 `node_modules`、`event.ts` 手改待 CI 校验，§9.3）/ 工具 reader-writer gate 真并发（ADR-0051 后置独立 Phase）/ event_log 主干裁剪 / acked-delivery 与 session-artifact 回收（绑裁剪）/ embedding-trigram-CJK**：均在 plan §2 / ADR / ROADMAP:44 显式后置并标 UNVERIFIED，**未见冒充已验证**。

---

## §5 "宣称 ≠ 现实"专表（逐条对 CHANGELOG[Unreleased] / plan §9 / ROADMAP:44）

| # | 宣称（文档原文） | 实测 | 结论 |
|---|---|---|---|
| 1 | "全量 838 passed / 5 skipped 零回归（基线 800+38）" | 实跑 `838 passed, 5 skipped`（2:46）；5 skip 全为 P2 bash/powershell 沙箱缺后端、"不 fake 冒充真跑" | **符** |
| 2 | "协议 25 types lockstep、`v` 不 bump" | `EVENT_SCHEMA_VERSION=1`（`main`==HEAD）；`--check` "25 event types in lockstep"；F1 字段改名实测判红 exit 2 | **符** |
| 3 | "全树 ruff clean、`lint-imports` 5 kept" | `ruff check src scripts tests` "All checks passed!"；`lint-imports` "5 kept, 0 broken" | **符** |
| 4 | "10 边界守卫全绿 + `--self-test`" | 现场 12 守卫（§9.4 诚实记 12≠11），12/12 `--self-test` 判红 + 12/12 scan 判绿 | **符（且优于宣称）** |
| 5 | "`compact_started/applied` additive、四处 lockstep、无正文（C18/C20）" | `reduce.py:385` data 无 `summary_text`；`test_compaction_reduce.py:93` 断言 `summary_text not in applied`；projection 白名单不含载荷键 | **符** |
| 6 | "压缩经 Command→reduce→durable、reduce 纯应用不算摘要（MAJ-8）" | `reduce.py:352-388` 纯校验+应用；`compaction.py` loop 侧算好随命令携带；`test_compaction_reduce.py:132` 同命令两 reduce 逐字等 | **符** |
| 7 | "只在 `closed_prefix` 内截、不孤儿化 open tool_use（C19）" | `reduce.py:361` + `compaction.py:96-100`；判红 `test_compaction_reduce.py:96` | **符** |
| 8 | "`covered_hash` fail-closed **生产者**、剔 per-run seq/tool_call_id" | 生产者真（`compaction.py:61-64/103`）、易变字段剔除有单测；但 `matches()` **0 生产调用**、无回读消费者 | **部分符**（生产者为真；回读"拒绝"未兑现，见 Major-2） |
| 9 | "压缩不丢事实召回"（ROADMAP P10 行/DoD-A） | 经**保头**（eval `DELTA-9 in live_text`）+ **distill 检索**（`test_compaction_loop.py:74-76`）两腿成立；但**生产无压缩触发**、且 covered 区无回读 | **部分符**（机制经注入验证，运行态未开，见 Major-1） |
| 10 | "observability 刀 3：logs 只读、preview 三闸主干零原文、usage 读 `run_completed`" | logs 只读已接线（`__main__.py:244`）；三闸+生产接线（`cli.py:89`）+canary 主干零原文+脱敏；usage 只 `RUN_COMPLETED`、`usage_delta` 零发射 | **符** |
| 11 | "带外投影 bus 级一处只读订阅、每 seq 恰一行（pitfalls #5）" | `cli.py:216` 单 observer、逐消费者 `log_envelope` 已删；守卫绿；P7/P9 投影 canary 在套件内通过 | **符** |
| 12 | "确定性 eval 网、`-m eval` 非阻塞 CI lane" | `pytest -m eval` 3 passed（无 key）；CI `evals` `continue-on-error:true`、`needs:boundaries` | **符**（计数"4"取目录，见 Minor-3） |
| 13 | "卫生回收保守子集（lease/超 TTL claim + artifact 孤儿 GC）、绝不裁 acked/event_log" | `store_sqlite.py:346/360`、`artifact_store.py:107` 逻辑正确、判红测在；但**无生产触发** | **部分符**（行为兑现；运行态不回收，见 Minor-2） |
| 14 | "两路对抗评审 Blocker/Major 全关" | 无法在本地复验外部评审事件 | **UNVERIFIED** |
| 15 | "usage_delta 死类型、artifact docstring 与实现不符、守卫数 12" | 全部现场复核为真、且文档就地登记（§9.1/§9.2/§9.4） | **符（诚实）** |

---

## §6 must-fix（转 GO 判据：Major 全关）

1. **压缩生产触发路径（Major-1）**：二选一——
   - 在生产组合根接入 `CompactionConfig`（例如 `CliSurface` 读 env/`LoopPolicy.compaction`，`cli._loop` 透传 `compaction=` 到 `DefaultTurnLoop`），并加一条"默认口径下真 run 达阈值确会压缩"的端到端判红测；**或**
   - 若有意 opt-in 暂不暴露，则在 ROADMAP/CHANGELOG/DoD-A 显式改标"内核就绪、生产 surfacing 后置"，不得以"压缩转正/已机器验证"含混覆盖运行态恒关的现实。
2. **`covered_hash` 回读 fail-closed 消费者（Major-2）**：实现按 `recovery_pointers` 从 `event_log` 回读原文 → 重算 `covered_hash` → `matches()` 不符即 fail-closed 拒返，并加"篡改覆盖区→读回拒绝"端到端判红测；**或**把 ADR-0048 决策 5 / DoD-A① 的"读回拒绝"子句改标后置，与"生产者已交付"的诚实措辞对齐。
3. （建议，非阻断 GO）Minor-1：`check_replay_determinism` 增"压缩**后**快照 + 尾重放"fixture；Minor-2：给 Lane D 一个显式触发（启动懒回收或 `questor` 维护子命令）或在文档点明"回收方法就绪、调度后置"；Minor-3：文档 eval 计数与 `-m eval` 选择口径对齐。

> Blocker：无。关闭 Major-1 + Major-2 → **GO**。

---

## §7 UNVERIFIED 诚实边界（附"缺什么才能验"）

| 项 | 为何未验 | 缺什么 |
|---|---|---|
| 真 LLM 压缩摘要质量、真多模态/远程面 | 本机无 key/离线 | 真 LLM 凭据 + 远程部署 |
| `check:protocol` TS codegen freshness（`event.ts`） | 本环境无 `node_modules`，`npm run generate:protocol` 未跑，手改 | 装依赖后跑 `check:protocol`/codegen 校验 `event.ts` 与 schema 逐字一致（Python 侧 `--check` 已 25 types 绿） |
| GUI/Tauri 追踪面板渲染 | 无窗口/桌面 lane | 真开桌面、按 `run_id+seq` 渲染同一事件协议（瘦客户端零下沉） |
| "两路对抗评审 Blocker/Major 全关" | 外部流程事件，本地不可复跑 | 评审记录/Issue 时间线 |
| 跨机 exactly-once、`event_log` 裁剪、acked/session-artifact 回收、embedding/trigram、工具真并发 | 显式后置（ADR-0050/0051 等） | 对应后置 Phase |
| Windows 真机 leg / CI 远端绿 | 本机 cp936 已代跑关键用例，CI 实跑属远端 | GitHub Actions run 记录 |

---

## §8 正面确认（无需返工项）

- **地基诚实**：全量 838/5、ruff、lint-imports 5 kept、25 types lockstep、12 守卫 self-test 判红 + scan 判绿——逐字命中宣称，**未以部分绿替红套件买单**（本就没有红套件）。
- **协议 additive 严守**：`v` 未 bump（与 `main` 比对=1）、四处 lockstep，且**字段级漂移门实测能判红**（F1：改 `compact_applied` 字段名 `--check` exit 2）——P7 审计曾判"字段级漂移无门"，此缺口在 P10 已闭。
- **C20/零原文纪律真落地**：preview 三闸（显式授权+独立通道+有界+脱敏）、`_DATA_KEYS` 无载荷键、真文件 canary 主干零原文、`usage_delta` 不入库不用、OTel 未引→九内核零依赖守卫绿。**观测面未成第二真相/第二载体。**
- **跨平台编码钉（失败族②）**：宿主 cp936 下 `-W error::PytestUnhandledThreadExceptionWarning` 跑子进程/真文件重集（含两真 OS 子进程的 `test_run_lease_multiprocess`、`test_p3_kill_resume`、`test_log_zero_plaintext`）→ **18 passed、无读线程崩溃**；CLI 用户可见输出 ASCII-only 纪律守住。
- **eval 网（失败族⑥）**：全用 `ScriptedProvider`、无 key/无网络、确定性、CI lane 非阻塞且 `needs:boundaries`——**未偷偷依赖真 LLM/网络**。
- **reduce 纯函数/确定性（BLK-1/MAJ-8）**：摘要/锚 loop 侧算好随命令携带、reduce 纯应用、`pre_compact` 补点、只截 `closed_prefix`、迭代只追锚——设计不变式与代码一致。
- **文档诚实纪律（AGENTS §5.5）**：`03f780e` 已回填 CHANGELOG/ROADMAP/plan §9/design/06/log/DESIGN，§9 主动登记 usage_delta 死类型、artifact docstring-vs-impl、守卫数 12、DELTA-9 召回腿修正——**"code merged, docs stale" 未发生**，"未做/真机才能验"未被冒充"已验证"。
- **证伪纪律**：两次临时篡改（schema 字段名、snapshot 丢锚）均当场 `git checkout` 还原，porcelain 除本审计文件外干净。

---

*审计工具链*：`uv run pytest -q`；`uv run pytest -m eval`；12×`scripts/check_*.py --self-test` + scan；`uv run ruff check src scripts tests`；`uv run lint-imports`；`check_protocol_schema --check`（含 F1 字段篡改证伪）；`check_replay_determinism`（含 F2 snapshot 丢锚证伪）；cp936 `-W error` 子进程集；全量 `git grep`/`Select-String` 核生产调用点。所有源码级结论锚定 `src/`（`03f780e` 未改 src，对 `d0f7dc9` 亦成立）。
