# P2 交付报告 · 工具 + 权限

> 目的：读完后能讲清"P2 到底交付了什么能力、权限/审批/沙箱/进程/投影的真实接缝长什么样、和 plan/02 有哪些偏差、还剩哪些诚实边界"。
> 口径：以**仓库当下代码 + 实测命令输出**为准。判据来自 [`docs/plan/02-p2-tools-permission.md`](../plan/02-p2-tools-permission.md) §5 DoD、[`docs/ROADMAP.md`](../ROADMAP.md)、ADR-0013…0019。

---

## 1. 一句话概括

P2 把"只会读一个文件的最小循环"升级成**能对危险操作做正确的事**：注册即用的一组文件/shell 工具，全部经唯一写者 Command Inbox 驱动，由**权威 PermissionCtx 纯引擎 + 不可被 mode 覆盖的 capability floor** 决定 allow/ask/deny，`ask` 走**可持久、幂等、可超时/取消**的审批生命周期，shell 命令在真沙箱后端（Windows Job Object + `taskkill` 进程树清理）里由 **Harness-owned ProcessRunner** 执行，超大输出只以**有界 preview + 内容寻址 artifact** 回模型，对外事件按**字段级白名单投影**。

P2 的 ROADMAP 判据——"危险操作触发 `ask`；`deny`/敏感路径不可越；非法参数被拒"——现在由**真实工具 + 真实审批闭环 + 端到端 DoD** 证明，不再停在 fake/内部单测层面。

---

## 2. 交付物清单（按任务 · 按层）

| 任务 | 层 | 交付 | 关键文件 |
|---|---|---|---|
| T1 契约 | L0 | 工具生命周期枚举、`ApprovalRequest`/状态、raw-args 状态、`SandboxDescriptor`、`ProcessRequest/Result`、`ArtifactRef`/`OutputBudget`/`ArtifactEnvelope`、`ShellAnalysis` IR、`CommandInboxPort`/`InboxReceipt`、`PermissionDecision/Outcome`；EventType 17→19 | `contracts/*.py` |
| T2 快照 | L1 | v2 全权威 round-trip（permission/approvals/rules/task_tree/error_stack/ToolCall 扩展字段），未知版本 fail-closed + v1 有损迁移 | `state/snapshot.py` |
| T3 Inbox | L2 | `RunController` 串行 Command Inbox（FIFO/幂等/背压/终态拒绝）+ loop 安全点消费 | `kernel/run_control.py` `kernel/loop.py` |
| T4 五层校验 | L2 | args→schema→shell-analysis→validated→permission→floor 重排；raw args 有界保留 | `kernel/loop.py` |
| T5 arg-key/IR | L0 | `PATH/SHELL/ACTION_ARG_KEYS`、`PROTECTED_IN_ROOTS`、`NULL_SINKS`、patch 前缀（纯数据） | `contracts/tool_args.py` |
| T6 POSIX parser | L2 | 分隔符/引号/命令替换/包装器/重定向/git 子命令，fail-closed 分类 | `kernel/shell_parse_posix.py` |
| T7 PowerShell parser | L2 | cmdlet/别名/递归 force/splatting/EncodedCommand 解码递归/scriptblock dynamic | `kernel/shell_parse_powershell.py` |
| T8 权限引擎 | L2 | 八步纯求值，引擎不持 mode/rules（全读 PermissionCtx） | `kernel/permission_policy.py` |
| T9 能力下限 | L2 | `apply_capability_floor`（none exec deny / job 非只读 exec ask / write 无围栏 ask，mode 不放宽） | `kernel/capability_floor.py` |
| T10 Artifact | L3/L5 | 内容寻址 `FileSystemArtifactStore`（atomic fsync + dedup）+ 有界 preview/envelope，写失败不回落原文 | `providers/artifact_store.py` `capabilities/tools/_output.py` |
| T11 env 安全 | L5 | credential 形状名 scrub、provider 凭据永不透传、declare 只能加非 provider allowlist、只存 names 不存 values | `providers/env_safety.py` |
| T12 ProcessRunner | L5 | 绝对 argv、sandbox wrap、env、timeout、Job Object（best-effort）+ `taskkill /F /T` 兜底杀树、输出限额→artifact | `providers/process_runner.py` `providers/_win_job.py` |
| T13 HITL | L1/L2/L6 | 完整审批生命周期（request/resolve/expire/cancel 幂等、超时、stale 拒绝）；CLI/HTTP 只提交 Command | `state/reduce.py` `kernel/loop.py` `surfaces/*` |
| T14 注册表 | L0/L3/L6 | `ToolRegistry` + L0 `RunToolSurface`（run 内冻结、description sanitize、误名候选）；loop/surfaces 接入 | `capabilities/tools/registry.py` `contracts/tool.py` |
| T15 文件工具 | L3 | 共享 containment `_paths` + `read`/`write`/`edit`/`apply_patch`/`ls`/`glob`/`grep` | `capabilities/tools/*.py` |
| T16 shell 工具 | L3/L2 | `bash`/`powershell` 只经 `ctx.run_process`；loop 把真实 runner/store 接进 ToolContext | `capabilities/tools/bash.py` `powershell.py` `kernel/loop.py` |
| T17 投影 | L2/protocol | per-type `$defs`+`if/then` schema + `EXTERNAL_EVENT_FIELDS` 白名单净化投影 + 守卫扩 per-type 覆盖 | `kernel/events.py` `protocol/event.schema.json` |
| T18 surfaces | L6 | `surfaces/approval.py`（receipt→HTTP + 唯一生命周期 TTY pump）；HTTP 端点映射 404/409/429/200/202 | `surfaces/approval.py` `http_sse.py` `cli.py` |
| T19 resume | L2 | `resume_run` 恢复 awaiting 状态并经 reduce 闭合过期审批（权限/审批不蒸发） | `kernel/recovery.py` |
| T20 守卫+CI | scripts/CI | AST forbidden-import + output-budget + secret-projection 三守卫（各带 --self-test 可判红）；CI 拆为 `tests-posix` / `tests-windows` 两条平台分相 job（原计 matrix，因 job 级 `if` 看不到 `matrix` 上下文会整文件非法而拆） | `scripts/check_*.py` `.github/workflows/ci-python.yml` |
| T21 DoD | tests | 端到端"全接线" loop DoD（写 ask→执行/拒绝、floor、敏感 deny、非法参数、真机 PowerShell 删除） | `tests/integration/test_p2_dod.py` |

**实测复核（报告撰写时于 Windows 本机亲自跑）**：`pytest` **316 passed**、branch coverage **86%**、`ruff` 全绿、`lint-imports` **4 kept / 0 broken**、`check_layering_ast`（66 files, 0 violation）+ `check_protocol_schema`（19 types lockstep）+ `check_output_budgets` + `check_secret_projection` + `check_thread_leak` 全部 `--self-test` PASS、`verify_p0` ALL PASS。分支相对 main **70 commits**、测试文件 **49** 个。

---

## 3. 危险操作的真实判定路径（可指认）

```
模型提议 write "out.txt"（default mode, NullSandbox）
  → args 有界解析 → schema 校验 → MarkToolValidated
  → PermissionCtx 八步：invalid? no → sensitive? no → floor：write 无写围栏 → ASK
  → RequestApproval(durable, request_id, expires_at) → 发 approval_request
       ├─ 外部 resolve allow → MarkToolRunning → tool.execute → out.txt 落盘 → tool_completed
       ├─ 外部 resolve deny   → MarkToolDenied → run 续跑到 completed（拒绝不崩）
       ├─ 超时 ExpireApproval → denied + tool_result（不复活）
       └─ Cancel              → 审批 CANCELLED、未闭合工具回填 CANCELLED、恰一终态
```

- `full_auto` 面对 exec（无沙箱后端）→ capability floor **直接 deny**，mode 不放宽。
- `full_auto` 面对 workspace 内 `.env`/`~/.ssh`/`*.pem` → sensitive-path 步 **先于 floor/mode deny**，且不产生审批请求（不可越）。
- 非法 JSON / schema required/type/additionalProperties/timeout 越界 → 在 execute **之前** error，不进权限、不进执行。

---

## 4. 关键决策与取舍（对齐 ADR）

| 决策 | 选择 | 放弃了什么 / 为什么 |
|---|---|---|
| 权限真相归属 | 权威在 **PermissionCtx**（Domain_State），引擎无配置 | 放弃"引擎自带 mode"（双真相）。见 ADR-0014。`SetPermissionMode` 下一调用即见新模式、历史 decision 不回溯。 |
| 外部写入口 | 一切经 **Command Inbox**（RunController），surfaces 绝不碰 reduce | 放弃"loop 内阻塞回调审批"（不可持久/超时/取消/重放）。见 ADR-0013/0016。 |
| 能力下限 vs mode | floor 高于 mode，`full_auto` 只消解"无 floor 的 ask" | 放弃"job backend allow 未知 exec"（无写围栏=安全假象）。见 ADR-0015/0017。 |
| 进程与隔离 | **Harness-owned ProcessRunner**，工具不 spawn；Job 失败不谎报 full、超时 `taskkill` 兜底 | 放弃"工具自 subprocess"（env/timeout/artifact 无法统一）。见 ADR-0018。 |
| 超大输出 | 有界 preview + 内容寻址 artifact，写失败不回落原文 | 放弃"fail-open 塞原文"（撑爆 prompt/event/checkpoint）。见 ADR-0019。 |
| 平台 shell | Windows 真 PowerShell 为主验收、POSIX bash 分栏；缺平台 skip 不 fake | 放弃"只 bash + Windows 用 fake 凑绿"（真实用户不可用）。见 ADR-0017。 |
| 投影 | 字段级 per-type 白名单（非 identity 透传） | 放弃"内部结构直发"（会被 P7/P9 依赖、后续只能破坏兼容）。 |

---

## 5. 实现偏差（详见 plan/02 §13.1 / §13.2）

- **`RunToolSurface`/`PermissionDecision`/`edit_distance` 下沉 L0**：避免 L2 kernel import L3、以及 `capability_floor↔permission_policy` import 环。属分层修正，additive，不改 wire 契约。
- **surfaces 去具体 store + 同步挂订阅队列**：T20 forbidden 规则要求 surfaces 不 import store 具体实现；据此 `cli.run_once` 用内存总线，并在 start drive 前预挂订阅队列，消除 store=None 的"晚订阅漏事件"竞态；`EventServer.store` 改 `StorePort` 抽象。
- **surfaces-no-reduce 只做 AST（非传递），不做 import-linter**：import-linter `forbidden` 传递会误报合法的 `surfaces→kernel→reduce`，故该约束由 AST 守卫按"直接 import"强制，`.importlinter` 注释说明。
- **`check_output_budgets.py` 取"对真实有界原语做不变式 + 可判红 self-test"**，而非静态 payload 尺寸扫描（后者易假信心）。
- **permission warnings / `ToolCall.sandbox_backend·confinement` 未落投影与账本**：warning 属内部观测、不在对外白名单，安全无碍；写成 additive 字段外发是 UX 增强，**先改 ADR/契约再做**，明确后置 P3。

---

## 6. 诚实边界（UNVERIFIED，环境限制非代码缺陷）

- **seatbelt/bwrap 实机**：Windows 只验 descriptor/argv 生成；macOS/Linux 的 seatbelt/bwrap profile 真执行未做。
- **真实 LiteLLM 网络端到端**：无 key，走 fake/scripted provider；对外不称"跑通真模型"。
- **跨真实 socket 的 SSE 重连**：进程内 async transport 验证，未做 uvicorn/浏览器级断连重连。
- **多 agent / 远程 Command inbox**：P8/P9。
- **`security-ci + pip-audit` lane**：依 STRUCTURE `[P#]` 纪律，待有对外攻击面时再铺。
- **coverage 仍非阻断**：86% branch 为观测基线，未设 `--cov-fail-under` 门槛（基线阶段不造虚假闸）。

---

## 7. 它带来了什么 / 下一步

**价值**：P2 证明了"注册即用的一组真工具 + 单一权威权限模型 + 不可越的能力下限 + 可持久可取消的审批 + 受管进程/沙箱 + 有界投影"这套设计**能真跑且判定正确**，且新增能力主要是"挂新工具、不动内核"。危险操作从"提议"到"执行/拒绝/超时/取消"的每一条路径都有 integration/DoD 级证据，Windows 真机 PowerShell 进程树清理与审批后删除被实机验证。

**下一步 = P3**：durable resume / `after_seq` 加固、permission warnings 与 `ToolCall.sandbox_backend/confinement` 的契约化外发（先扩 ADR）、把 concrete store/ProcessRunner 的组装上移到 L7 shell 组合根、以及更多工具与 UX 打磨。触发**发布里程碑**可讨论项：P2 已具备"可给真实用户试用带审批的文件/命令 Agent"的能力面。
