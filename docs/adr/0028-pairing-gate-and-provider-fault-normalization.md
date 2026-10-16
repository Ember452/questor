# ADR-0028: 回发前配对关卡（provider 请求唯一闸口）+ provider 故障归一终态

- 状态：✅（2026-10-16）
- 编号说明：**ADR-0027 已被日志刀 2 预留**（[`../log/PLAN.md`](../log/PLAN.md) §6、[`../log/DESIGN.md`](../log/DESIGN.md) §17「新增 ADR-0027（双通道+中间表示+载荷政策）」），本决策直接取 0028，不改号、不占用 0027。

## 背景

真实使用中，模型（DeepSeek V4 等会并行发工具调用的任一模型）**在一轮里返回 ≥2 个 tool_call** 时，
CLI 进程带 traceback 直接退出、run 不落任何终态。逐段核验 + 脚本化 provider 复现（按 OpenAI/DeepSeek
线上规则校验投影历史）得到三类确定性形状，非概率问题：

1. **主路径**：策略每轮只挑**一个**未闭合 tool_use 执行（`policy/react_policy.py:21-35` 命中即 `return`；
   `kernel/loop.py` 的 `ProposeToolCall` 分支执行一条就回到循环顶），随后 `AdvanceTurn → provider.stream`
   **中间没有任何配对关卡**，于是带着「assistant 挂 2 个 tool_calls、只有 1 个 tool 回应」的历史回发 →
   `400 An assistant message with 'tool_calls' must be followed by tool messages…`。实测事件流停在
   `turn_started`，其后永远没有 `run_failed`。
2. **stop-gate 二阶路径**：策略给 `SuggestFinish` 而账本仍有 OPEN 调用时 `continue`，**同样带悬空回发**；
   对不校验的宽容网关实测表现为「反复带非法历史重试，直到 max_turns 才 run_failed」（白烧 3 轮预算）。
3. **durable 泄漏路径**（同片雷区，实测比预期更糟）：`state/reduce.py:86-89` 对重复 `tool_use_id` **整条拒收**
   assistant 消息，但 loop 仍把本地 `assistant_msg` 当已落库的定稿，最终经 `FinalizeRun(final=…)`
   （`reduce.py:276-277`）把它**原样写回 context**——留下一条永远没有 `tool_result` 的悬空 tool_use，
   账本与 context 分叉，且因状态是 `completed` 而**不进 `--list`/resume**，比崩更难查。

义务来源不在 DoD 的"三条异常路径"（plan/01 §5-2 只列取消/deny/非法意图），而在写死的设计条款：
design/01 §8「各阶段 catch → 归一成本 envelope」、design/04 §8「Provider 错误→重试/fallback；耗尽则
`run_failed`；全走 Command/reduce，状态不被撕裂」、plan/01 T4「错误归一为 `ErrorEntry`」。实况是
`ErrorLayer.PROVIDER` 生产路径 0 处、`provider.stream` 唯一调用点裸奔、src 内 `FORMAT_ERROR`/retry 零生产者。
**故障域测试矩阵也印证了不对称**：tool panic（`test_p2_tool_fault_isolation`）、policy panic
（`test_loop_hardening`）、persist 失败（`test_bus_failures_voiced`）都有钉桩，**provider 抛错 0 条**；
且全部脚本化测试每 turn 只发 `index: 0` 一条 tool_call——多调用形状从未被测。
本类缺陷在 P2 审计已被点名（`docs/audit/P2-review-2026-10-15.md` §5-1），当时只修了**终态**分支
（`FinalizeRun` 回填），循环内的回发关卡始终缺席。

## 决策

1. **关卡放在唯一的 provider 调用点内部**（`kernel/loop.py::_stream_turn`）：请求前先执行
   `_ensure_paired_history`，把上一条 assistant 里**所有**未应答的 tool_use 闭合，才允许下一次请求。
   串行执行不变（不启用并行，ROADMAP §2.5 不破）；变的只是"不半截发"。
2. **判据取 context 侧 `state/checkpoint.py::open_tool_use_ids`**，不是账本的 OPEN 集合——回填/重派只能
   处理"有 OPEN 条目"的调用，而缺陷 3 证明 context 可以带一条 ledger 里根本没条目的悬空 tool_use。
   以**真正要发出去的形状**为准才拦得住。执行仍委托 ADR-0021 的派发函数。
3. **执行复用、不新写机制**：`_resume_settle_open_calls` 更名为中性的 **`_settle_open_calls`**（行为逐字不变），
   由 resume 入口与关卡两个安全点共用。`pending/validated` 重走权限、`awaiting_approval` 等现有 request，
   **绝不绕过 ask**（已由测试钉住：关卡补执行一个 none 后端的 write 时，真的发出 `approval_request`、
   无人决策则超时 fail-closed deny、目标文件不落盘）；保留 resume 入口调用，因为它在 `turn += 1` 之前，
   被 kill 的 run 不必为补一个已批准的工具多花一轮预算（ADR-0021 已测行为，本 ADR 不改）。
4. **不可调和即 fail-closed**：补执行后仍悬空 → 归一 `run_failed`（`layer=KERNEL`、`kind=format_error`、
   不可重试）并在 message 里点名 id，**一次都不发**。
5. **provider 故障在此归一终态**：`_stream_turn` 捕获 `Exception`（`CancelledError`/`KeyboardInterrupt`/
   `SystemExit` 等 BaseException 继续上抛，与 `_execute_tool` 同一纪律），交 `contracts/errors.py::
   classify_provider_error` 归一 `ErrorEntry` → `_fail_with_entry` 落 `run_failed`。分类是 **ADR-0010 归
   contracts 的纯函数**（不 import provider/litellm）；`_fail` 原把 layer 写死 KERNEL，故另开
   `_fail_with_entry` 让 envelope 的 layer/kind/hint 能各自出声。
6. **400 配对违规必须判为不可重试**（`format_error` + `retryable=False`）：它是确定性错误，重发必同样失败。
   若照 plan/01 T4「满预算重试」字面接线而不先分类，会把预算原样烧光。
7. **拒收即出声**：`AppendAssistantMessage` 未产 `message_completed`（重复 tool_use_id）时立即归一
   `run_failed`（`layer=PROVIDER`），不再把本地消息当作已落库的定稿，堵死缺陷 3 的走私路径。
8. **机械守卫**：新增源码级测试断言全仓 `self.provider.stream(` 调用点唯一且在 `kernel/loop.py`、
   `_stream_turn` 内关卡先于请求（fail-on-empty；已验证"把关卡拆掉即判红"）。理由见 §后果。
9. **红线入册**：`HARD-CONSTRAINTS` 新增 **C19**（回发前配对 + provider 故障不得崩宿主进程，靠机制不靠自觉）。

## 后果

- **正面**：多 tool_call 轮不再打崩宿主进程；非法历史在发出前被拦；provider 侧故障按 design/01 §8 的
  envelope 定位到 `provider` 层并带正确 `retryable`/`should_compress`；durable 历史不再带"账本没有、
  context 有"的悬空 tool_use；取消/deny/非法意图/provider 四条路径都不崩进程。
- **turn 粒度确实变了**（这是本 ADR 要显式批准的部分）：一条 assistant 里的 N 个调用在**同一次回发前**串行
  闭合，因此 ① 一个 turn 窗口可执行多个工具；② `tool_started` 节奏相应密集；③ 关卡补执行的路径**不经过**
  策略提议，故 `repeat_tool_limit` 的"同工具同参连续"计数**不覆盖**关卡路径（策略路径不变）；④ `pre_tool`
  checkpoint 语义不变（审批挂起仍落 durable）。实测总 turn 数**不增**（原本要 N 次 round-trip 才闭合的
  调用，现在一次回发前完成），成本只降不升。
- **代价 / 需持续守的约束**：关卡只保证"发出前成对"，**不消除**并行需求——完整并行 gate 仍归 P5；
  `retryable` 的**编排消费者（退避/fallback 链/凭据池）仍归 P10**（plan/01 §1.2 后置项），本轮刻意不自动重试，
  所以分类结果目前只对外经 `run_failed.error.retryable` 供客户端决策——它已有消费者，不是假扩展位。
  `ErrorEntry.resumable` 的填充随"失败后人工复活"机制落地，本轮保持 False 不谎报。
- **UNVERIFIED**：真机 key 下的 DeepSeek/OpenAI 具体异常类型与状态码载体（litellm 版本相关）未验证；
  分类器已按"显式 `status_code` → 消息里的 `Error code: NNN` → 有序模式表 → fail-closed UNKNOWN"
  三段兜底，但真实异常形状仍需在 P10 用真网关复验。

## 备选（被否）

1. **投影侧补占位 tool_result**（`providers/litellm_adapter.py::to_openai_messages` 造一条合成的 tool 消息）：
   本项目是事件溯源——历史由 `event_log` 重放/快照重建，而投影层凭空造出的结果**从不落 ledger**，等于把
   "context 有、账本无"的分叉**制度化**（正是缺陷 3 的形状），同时让实际发出的请求与 replay/resume 重建出的
   历史分叉。比这个 400 更贵的不变式破坏 → 否（连"临时止血"都不该放这里）。
2. **只改策略、让它一轮返回多个意图**：覆盖面不足——stop-gate 那条 `continue` 路径同样带悬空回发，且策略
   输出多个意图会把"配对"责任推给 L4，而配对是内核不变式（I1/C7）。关卡一处即同时收掉两条路径 → 否。
3. **先接退避重试再补关卡**：重试一条我们自己造出来的非法请求只会重复失败并烧预算 → 否（顺序必须是
   关卡/归一在前，重试编排在后）。
4. **把重复 `tool_use_id` 的拒收改成"reduce 内改写 id 继续"**：会静默改掉 provider 给的关联键，破坏
   UI/resume 依赖的 `tool_call_id` 契约（C18） → 否，改为 fail-closed 出声。
5. **只修 DoD 不补机械守卫**：未来第二个 provider 调用点（P5 MCP、P9 OpenAI 兼容 API 都可能是）会静默
   把这条不变式变成"看运气" → 否，落第 8 条源码级判红。

## peer-scan（AGENTS §4.5；逐仓实扒）

| 能力 | 扫描仓与证据 | 结论 |
|---|---|---|
| 「每次请求前校验配对」的**位置** | CowAgent `agent/protocol/agent_stream.py:1604-1608`（`_call_llm_stream` 前必调 `_validate_and_fix_messages`）、`:917-920`（trim 后再校验，防边界孤儿） | **采纳位置口径**：关卡长在 provider 边界，不靠上游自觉 |
| 孤儿配对的**修复手段** | CowAgent `agent/protocol/message_utils.py:21-120`（`_SYNTH_TOOL_ERR` 合成 tool_result 抹平）、GenericAgent `llmcore.py:751 _fix_messages` | **改造**：不用合成结果抹平（见被否 1），改为内核**真执行**未闭合调用；不可执行则 fail-closed |
| provider 异常 → `{layer, code, retryable}` | hermes `agent/error_surface.py:1-58,88-103,211-234`（advisory 描述符、"NEVER raises"、`format_error` 列入 `_NON_RETRYABLE_REASONS`）、`agent/error_classifier.py:34-56,286-288`（"deterministic rejections of the transcript → fail fast as format_error"） | **改造复用形状**（纯函数、状态码优先、模式兜底、绝不抛），表按本项目 ErrorKind 命名空间收窄；MIT © Nous Research，已就地注明 provenance，非照搬 |
| 崩溃域隔离的先例 | 本仓 P2 审计修复 #1/#7（工具 panic→`_execute_tool` 兜底）+ `test_p2_tool_fault_isolation.py` | **对称补齐 provider 侧**，沿用同一条 BaseException 纪律 |

## 关联

- 取代/延续：ADR-0021（派发函数改名 `_settle_open_calls`，行为不变）、ADR-0020（`closed_prefix` 用途仍为"识别在途集"）、ADR-0010（分类=纯函数进 contracts，本 ADR 是其首次真接线）、ADR-0016/0019（ToolCall 生命周期与载荷有界）。
- 红线：HARD-CONSTRAINTS **C19**（新增）、C7/I1（配对与取消回填）、C10（故障隔离）、C13（恰一终态）、C15（守卫可信）、C18。
- 设计回写：`../design/04-turn-loop.md` §5/§8、`../design/01-state-model.md` §5/§8。
- 计划偏差回填：`../plan/01-p1-minimal-loop.md` §11（T4 错误归一、DoD §5-2 第四条路径）；`../plan/03-p3-persistence-resume.md` T11 改名注记。
- 测试：`tests/integration/test_pairing_gate_and_provider_fault.py`（10 条：含机械守卫、“关卡真的发出并等待审批”、
  “非法参数也闭合”的判红样例）、`tests/unit/test_provider_error_classification.py`（8 条）。质量门：440 passed / 5 skipped（本分支基于 main）。
