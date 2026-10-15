# P1 交付报告 · 最小可跑循环

> 目的：让你读完后能讲清"P1 到底跑通了什么、真实架构长什么样、审计暴露了什么、修成了什么样、还剩哪些坑"。
> 口径：以**仓库当下代码 + 实测命令输出**为准。判据来自 [`docs/plan/01-p1-minimal-loop.md`](../plan/01-p1-minimal-loop.md)、[`docs/ROADMAP.md`](../ROADMAP.md) §2.5、[`docs/audit/P0-P1-review-2026-10-15.md`](../audit/P0-P1-review-2026-10-15.md)。

---

## 1. 一句话概括

P1 用**最窄的能力面**（单模型 + 一个 `read` 工具 + 流式 + 可取消）把**返工代价最高的承重接缝一次砌到位**：唯一写者 `reduce`、事件溯源存储、内外事件投影、三态权限引擎、turn 循环、断点恢复、fail-closed 沙箱闸——现在能在终端"问一句→流式答一句"，中途可取消且状态/事件一致。

**能力面刻意守界**：无并行 / 无 MCP / 无子 agent（ROADMAP §2.5）。P1 的唯一目的 = **证明整套设计自洽、无逻辑漏洞**，不是把功能做全。

---

## 2. 交付物清单（按层）

| 层 | 交付 | 关键文件 |
|---|---|---|
| L1 状态 | `reduce` = **Domain_State 唯一写者**：配对不变式、终态唯一(first-writer-wins)、Cancel 回填未闭合工具、COW 产新态 | `state/reduce.py` `state/domain_state.py` |
| L1 真不可变 | 深冻结 JSON 叶（`immutables.Map`）：`ToolCall.args`/`ContentBlock.input/payload`/`Envelope.data` 不再能被原地篡改 | `contracts/common.py` `freeze/thaw` |
| L1 快照/恢复 | turn 边界落 checkpoint（写门 `closed_prefix`）+ `resume_run` 从最近快照重建 | `state/snapshot.py` `state/checkpoint.py` `kernel/recovery.py` |
| L2 内核循环 | phase pipeline：提交→流式→定稿→问策略→路由；护栏 + 取消探针 + 策略故障隔离回滚 | `kernel/loop.py` |
| L2 事件总线 | 内部→对外投影、live-only delta 不落库、终态唯一、版本闸门、`after_seq` 重放不丢不重 | `kernel/events.py` |
| L2 权限引擎 | 三态/三 mode、不可覆盖 realpath denylist、五层求值次序、`never→deny` | `kernel/permissions.py` |
| L3 工具 | `read`（workspace 内读文件）+ 工具路由（schema 校验/权限/记账/无沙箱 fail-closed） | `capabilities/tools/read.py` `registry.py` |
| L5 Provider | LiteLLM 流式适配（tool-args 跨块累积、usage 末块）+ fake/scripted provider | `providers/litellm_adapter.py` `fake.py` |
| L5 Store | SQLite 事件溯源：per-run seq + `UNIQUE(run_id,seq)` + `replay(after_seq)` + checkpoint 存取 | `providers/store_sqlite.py` |
| L4 策略 | 进程内硬编码单 ReAct（实现 PolicyPort），非法工具名不崩、回填 context 下轮自纠 | `policy/react_policy.py` |
| L6 传输面 | CLI 终端（DoD 主面）+ 本地 HTTP+SSE（`id:<seq>` + `Last-Event-ID` 续传） | `surfaces/cli.py` `http_sse.py` |
| 横向 | 结构化日志 + ErrorEntry 错误栈（只依赖 contracts、只读） | `observability/logging.py` |

**实测复核（报告撰写时亲自跑）**：`pytest` **66 passed**、`ruff` 全绿、`lint-imports` **4 契约 KEPT / 0 broken**、`git log` 87 commits。三条异常路径（取消 / deny / 非法意图）在真实代码路径上以 fake provider 跑通。

---

## 3. 架构全景（一次 run 的真实数据流）

```
用户消息
  │  SubmitMessage(Command)
  ▼
[loop.drive] ──reduce──▶ 新 Run + 事件          ← 唯一写者，绝不原地改
  │
  ├─▶ [provider.stream]  逐块 text_delta/reasoning_delta  ──▶ bus（live-only，不落库）
  │        └─ 累积 tool_call 分片 → 定稿一条 assistant 消息
  ├─▶ [policy.propose_action]  读 PolicyView(只读投影) → 返回意图（调工具 / Finish）
  │        └─ 策略抛错 → 捕获 + 回滚到 turn 起点 + 发 warning（连续3次优雅 failed）
  ├─▶ 若是 ProposeToolCall：工具路由
  │        permission.evaluate → deny/ask/approve
  │        schema 校验 → 非法即 error 回填
  │        _sandbox_denial → 需沙箱能力但无后端 → DENY（fail-closed）
  │        tool.execute → RecordToolResult → reduce → tool_completed
  ├─▶ 每个 turn 边界：save_checkpoint（供 kill-重启续跑）
  └─▶ 护栏探针（每 turn 顶）：cancel / deadline / max_turns / max_tokens / 重复工具 / 空答
         ▼
      FinalizeRun / Cancel → 唯一终态事件 → bus（first-writer-wins）→ CLI 打印 / SSE 推流
```

三条铁律在代码里可指认：
- **单写者**（C2/C5）：所有状态变更都经过 `reduce`，loop 从不直接 `run.xxx = ...`。
- **Command 改状态 / Event 只广播**（C5）：delta 走 `_live()` 直发总线、`LIVE_ONLY` 集不入库。
- **瘦 surface**（S6）：CLI/SSE 只造 Command + 投事件，无一行业务逻辑。

---

## 4. 关键决策与取舍

| 决策 | 选择 | 放弃了什么 / 为什么 |
|---|---|---|
| **能力面 vs 工程面** | 能力守界（单模型/串行/一个工具），但**接缝砌实**（事件溯源/不可变/权限/投影/恢复） | 放弃"纯薄桩过 P1"——那只够点亮 DoD、接缝留白，P3/P5/P9 回头大改已锁接缝，返工最痛。判据线 = "necessary vs gratuitous"：砌的是接缝形状与不变式，不是提前实现未来能力。 |
| **是否 fork DeepCode 内核** | 否，只**改造复用其已验证片段**并守分层 | DeepCode 是单投影（无内外两层）、浅不可变、`normpath` 非 `realpath`、无 PolicyPort 分层——与我们契约不同构，且违"从零自研"。 |
| **复用来源**（逐条 peer-scan） | 流式装配←crewAI；取消不变式←CowAgent；权限引擎←DeepCode（**补 realpath 缺口**）；事件溯源+`after_seq`←DeepCode（**自写 id:seq 续传**，两家都缺）；`closed_prefix` 写门←CowAgent | 12 仓全扫、逐条记 `file:line`、真移植处标 provenance。 |
| **seq 分配** | 一次 reduce 产出的事件按 `run.seq+1..+n` 连续取号，`Run.seq` 推进到最大事件号 | 见 §5——旧写法在 Cancel 时会撞 seq、打断落库。 |
| **无沙箱时降级** | **deny**（fail-closed），不是 ask、更不是裸执行 | "降级只会更安全、不会更松"。P1 只有 read（readonly）不暴露此路径，但机制已接。 |

---

## 5. 一条重要时间线：审计 → 全量修复

P1 不是"一次写完就对"。过程是**先交付 → 对抗式审计揪出 Blocker → 逐条修复并补证伪测试**。这段正是最有价值的部分：

**审计（`docs/audit/P0-P1-review-2026-10-15.md`）判 P1 = NO-GO**，当场复现出两个致命缺陷 + 若干阻断项。随后全部修复（当前代码即为修复后状态）：

| # | 审计发现的缺陷 | 修复（代码指认处） | 证伪测试 |
|---|---|---|---|
| 1 | **C2 假不可变**：frozen dataclass 的叶 `dict` 可变，经 COW 在新旧态间共享 → 一处改动污染"不可变"历史（已复现泄漏） | `common.py` `freeze/thaw` 用 `immutables.Map` 递归深冻结 | `test_leaf_dict_is_immutable`、`test_cow_states_do_not_share_mutable_leaf` |
| 2 | **Cancel seq 碰撞**：回填事件与终态事件同 seq → 落库 `IntegrityError`（已复现崩溃） | `reduce.py` Cancel 分支连续取号、`Run.seq` 推进到最大 | `test_cancel_persist.py`（带 store 跑取消） |
| 3 | **断点恢复根本没接线**：checkpoint 只被单测调用，loop 从不写/读 | loop turn 边界 `save_checkpoint` + `recovery.py: resume_run` | `test_checkpoint_and_resume_roundtrip`（关库重开模拟新进程） |
| 4 | **沙箱/capability fail-closed 未接**：`NullSandbox` 无消费者 | `loop._sandbox_denial`：exec/write/network/high 无后端 → deny | `test_sandbox_gate.py` |
| 5 | **护栏全是死字段**：`Budget` 四阈值定义了但 loop 只读 `max_turns` | loop 接入 `deadline_seconds/max_tokens/repeat_tool_limit/max_consecutive_continuations` + 拒绝过早 Finish | `test_loop_hardening.py` |
| 6 | **策略 panic 被静默吞**（违 C10）：不发事件、不回滚 | 捕获 → 回滚 `Domain_State` 到 turn 起点 → 发 warning → 连续3次优雅 failed | `test_run_survives_panicking_policy_and_fails_gracefully` |
| 7 | 入口陈旧 + 活文档腐化：`python -m questor` 仍打印 P0 banner、CHANGELOG 无 P0/P1 | 接 CLI；CHANGELOG 补 Added/Fixed；协议守卫加 fail-on-empty | — |

> **为什么值得写进报告**：这份审计 + 修复本身就证明了工程纪律——不是"AI 写完就宣称完成"，而是"用能证伪的测试逼出真状态"。审计里"糊弄测试"的盲点（取消测试用 `store=None` 绕开碰撞路径）也被修好了。

---

## 6. 诚实边界（P1 有意后置 / 未验证的）

**降级为 draft（非"已完成"）**：
- 梯度终止的"软预警 / wall-clock wrap-up 提示 / 一次无工具 grace call / 耗尽强制总结"需额外 provider 往返，属 `[加固]` 项，**P1 未实现**（当前：预算/截止/重复到点直接 `run_failed`）。字段与接缝已就位，P10 补全。
- 流式看门狗双超时、idle-progress 看门狗、shell 命令解析 fail-closed：后置 P2/P10。

**UNVERIFIED（环境限制，非代码缺陷）**：
- **真实 LiteLLM 端到端**：无 API key，只验了 fake/scripted provider 与代码静态。默认可跑面走 `EchoProvider`（假流式），**对外不得称"跑通了真模型"**。
- **跨真实 HTTP 的 SSE 续传**：环境无 `uvicorn`，`after_seq` 续传经 async 生成器/`store.replay` 级验证，未做 curl/浏览器级断连重连。
- **完整 HITL 审批往返**：P1 唯一工具 `read` 是 readonly→allow，`ask→批准通过` 的真实端到端未触发。

**能力面未越界（审计 scope-drift 核验确认）**：无并行 / MCP / 子 agent——`parallel_safe`、`kind=subagent`、多模态事件 `type` 均只是**契约占位**，符合 §2.5。

---

## 7. 它带来了什么 / 下一步

**价值**：P1 证明了"从分层契约 → 单写者状态 → 事件溯源 → 权限三态 → 可取消循环"这一整套设计**没有逻辑漏洞、能真跑**。承重墙已砌到位，后续加功能主要是"挂新件、不动内核"。触发**发布里程碑节点 B**：可开源"最小可运行原型（终端 Demo）"，拿第一批真实反馈。

**下一步 = P2**（工具 + 权限 lite）：引入文件/shell 核心工具集、把三态权限在真写/exec 上验透、受限沙箱。2026-10-15 对抗审计后的开工 Blocker 已由 ADR-0013-0019 关闭：P2 以 Command Inbox、PermissionCtx 单一真源、capability floor、ApprovalRequest 生命周期、Shell IR、Harness ProcessRunner、有界 Artifact 和字段级投影为硬契约。详规与 T0-T21 任务分解见修订版 [`plan/02`](../plan/02-p2-tools-permission.md)。
