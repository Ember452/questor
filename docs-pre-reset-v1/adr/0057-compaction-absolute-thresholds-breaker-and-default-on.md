# ADR-0057: 压缩口径改绝对阈值（带预警与熔断）并把生产默认翻到 on

- 状态：✅（2026-10-21，B10/c1–c3）
- supersedes：`ADR-0048` 的"默认关、只按条数触发"生产口径（机制本身不变，**默认值与触发信号**变）；
  并推翻 v2 §4.9 的 `COMPACT_TRIGGER_FRACTION` 分数口径（T4 已裁决，本 ADR 是落地记录）
- 背景：P10 把可恢复压缩实现完了但生产默认关（`QUESTOR_COMPACTION` 未设 = 不压），长会话的真实
  形态是"上下文一路涨到 provider 4xx"。而"什么时候压"如果用一个分数（如 0.8 × 窗口）算，就把
  **摘要自己的输出预留**和**一次 turn 的正常增长**都省掉了——上游正是为此吃过事故（连续失败
  1,279 个会话、最高 3,272 次）。同时 questor 自己欠一条账：`closed_prefix` 是**单向**定义，
  从头部下刀会造出"没有 `tool_use` 的头部 `tool_result`"（§7.2 缺陷 ⑤，此前只有静态推导、无测试）。
- 决策：
  1. **阈值一律绝对算**（`contracts/policy.py`）：`EW = context_window − min(max_output, 20_000)`；
     自动 `EW − max(摘要预留, 13_000)`、手动 `EW − 3_000`、预警 `EW − 26_000`。20_000/13_000/3_000
     取上游实测常量；`warning_buffer=26_000` 是 questor 自定值（= 自动余量 + 一个 turn 的典型增长）。
     未配 `context_window` 时**逐字退回**旧的 `trigger_tokens`/`max_items` 判据（既有 6 个压缩测试零改动）。
  2. **窗口尺寸不猜**（`providers/model_windows.py`）：查不到家族就返回 `UNKNOWN_WINDOW`，绝对阈值
     整条不启用；`QUESTOR_CONTEXT_WINDOW` / `QUESTOR_MAX_OUTPUT` 显式覆盖优先。窗口小到算不出正
     阈值 → `CompactionConfig.__post_init__` 直接拒（fail-closed：拿假窗口截真上下文比不压更糟）。
  3. **压缩有代际**：`compact_started/compact_applied` 带 `window_id/previous_window_id/window_number/
     trigger/source`（全 optional，B10 之前落库的帧仍合法）；身份从**既有** `command_window` 行 + 事实流
     里 durable `compact_applied` 的个数派生（取较大值），**不建第二张窗口表**。信号源优先
     `server_observed`（模型报回的 usage），没报就老实标 `estimated`。
  4. **不静默**：新增 durable `compact_warning`（`EventType` 31→32，配 `WarnCompaction` 命令，
     Command 21→22——durable 事件只能由 reduce 产，所以必须占 seq）。`reason` 是闭集
     `pressure | breaker_tripped`，只带阈值/用量/计数，零正文（C18/C20）。
  5. **熔断 = 3**（`MAX_CONSECUTIVE_COMPACT_FAILURES`）：连续三次折叠失败（reduce 拒或摘要器交白卷）
     就跳闸——落一条 `breaker_tripped`，之后本轮**连摘要器都不再问**（省的就是上游那 25 万次/天）。
     一次成功即清零：熔断只数连续失败。
  6. **白名单 + 可见占位符**（`COMPACTABLE_TOOLS`）：只读检索类与受控 shell 的输出可折叠；
     `write/edit/apply_patch/delegate` 的结果不压（不可重建）；查不到工具名按不可压处理。
     被逐出的工具结果在摘要末尾留 `[Old tool result content cleared]`。
  7. **头部孤儿收口**（闸门⑤）：`state/checkpoint.py` 增 `tool_result_pairing`/`orphan_tool_result_ids`
     （只扩展、不改 `closed_prefix` 语义），`kernel/compaction.legal_evict_end` 把右界退到不产生孤儿
     的位置，退无可退就返回 `None`（不压）。`tests/unit/test_compaction_orphan.py` 用 6 种头尾组合
     把这条静态推导**测成了事实**：§17 第 11 条 ③ 就此关账。
  8. **摘要器移出 L2**：新增 `SummarizerPort`（`contracts/ports.py`）+ `providers/fake.py::FakeSummarizer`
     （确定性、与 L2 启发式逐字同形，由测试钉住占位符一致性）。**生产组合根暂不注入 LLM 摘要器**：
     side-query 走便宜档需要 modelroles 接线，本轮刻意不做——内核继续用确定性启发式，
     于是翻默认不引入网络、不改回放确定性（真 LLM 摘要质量仍 UNVERIFIED）。
  9. **翻默认只在 `composition.build_app()`**：新函数 `production_compaction_from_env(model)` 读
     "未设 = 开"，**显式 `off` 仍然关**（用户否决权优先），`items:N` 仍尊重用户条数；
     `compaction_from_env()`（"未设=关"）原样保留给 `CliSurface` 直接构造路径与既有测试。
- 实测（§17-8 要求，`tests/evals/test_compaction_summary_p99.py`，100 个确定性构造段）：
  `summarize()` 输出长度 **p50=723 / p95=1248 / p99=1248 / mean=679 / max=1248 字符**，
  上界恒 ≤ `SUMMARY_MAX_CHARS=4000`。按 `chars/4` 粗估（**无官方 tokenizer，估算值**）p99 ≈ 312 token，
  远低于沿用的 20_000 token 摘要预留 → **20_000/13_000/3_000 对我们自己的分布是保守的，可以沿用**，
  不改；`warning_buffer=26_000` 与摘要分布无关（它是"一次窗口的余量"口径），仍属待生产校准。
  该分布被钉成断言（改构造段就会红），不得只打印不留痕。
- 后果：
  - 正面：长会话不再一路涨到 4xx；预警/熔断/代际都可回放，"莫名其妙失败"有了证据；
    头部孤儿从"未测的推导"变成"有 property 的判据"；阈值不再是拍脑袋的分数。
  - 代价：生产默认改变属行为变更（本刀标 `[behavior]`）；每条撤回/预警各占一个 durable seq；
    窗口表需要随模型目录维护（表值 UNVERIFIED，env 覆盖是逃生门）；`warning_buffer` 是自定数。
  - 需持续守：**任何人新增压缩触发口径都必须走 `CompactionConfig.threshold()`**（不在 loop 里重算窗口
    数学，与 §7.1"单一真源"一致）；`compact_warning` 的 `reason` 不得扩成自由文本；
    白名单只能收紧不能放宽（写类结果不可重建）。
- 备选（被否）：
  1. **沿用分数阈值（`COMPACT_TRIGGER_FRACTION`）**：否——不减摘要输出预留与单 turn 增长，溢出照旧。
  2. **建一张 `compaction_windows` 表存窗口身份**：否——§20 零新表；身份可从命令窗口/事实流派生。
  3. **把 `compact_warning` 发成 live-only 观测**：否——预警与跳闸必须能事后复盘（不静默）。
  4. **生产直接接 LLM 摘要器**：否（本轮）——引入网络与回放不确定性，而收益（摘要质量）无法在 CI 判。
  5. **未配窗口时按 128k 兜底**：否——用一个猜来的窗口去截真实上下文，误截比不压更难查。
- 关联：v3 §7.1/§7.2/§7.3/§7.4、§13 B10、§17 第 8/11/13 条；`ADR-0048`（机制）、`ADR-0024`（锚与
  `covered_hash`）、`ADR-0050`（卫生回收边界）、`ADR-0054`（cache 三条款，同属请求体预算）。
  代码：`contracts/policy.py`、`contracts/ports.py`、`contracts/events.py`、`kernel/compaction.py`、
  `kernel/loop.py`、`state/checkpoint.py`、`state/reduce.py`、`providers/model_windows.py`、
  `providers/fake.py`、`providers/store_sqlite.py`、`surfaces/_assembly.py`、`surfaces/cli.py`、`composition.py`。
  测试：`tests/unit/test_compaction_{orphan,absolute,overflow}.py`、`tests/evals/test_compaction_summary_p99.py`。
