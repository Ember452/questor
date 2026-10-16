# Questor 计划 2（P2）· 工具 + 权限 lite · 全面修订版开发计划

> 用途：P2 的开工基线与任务分解。  
> 修订依据：2026-10-15 对抗评审 + ADR-0013-0019。  
> 母文档：[`VISION.md`](../VISION.md)；阶段口径：[`ROADMAP.md`](../ROADMAP.md)；工程红线：[`HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md) C1-C18。  
> 契约：[`design/00`](../design/00-layering.md)-[`04`](../design/04-turn-loop.md)；决策：[`adr/0013`](../adr/0013-run-command-inbox.md)-[`0019`](../adr/0019-bounded-artifact-projection.md)。  
> 本文取代原 plan/02 中以下旧口径：POSIX bash 代表 Windows DoD、full_auto 可越过无写围栏、审批仅阻塞回调、工具直接 spawn、artifact 失败回原文、投影 identity、PermissionCtx 与引擎双配置。

---

## 0. 定位与不可突破原则

**一句话**：P2 不是“多写几个工具”，而是把真实写/exec 所依赖的承重接缝一次定成可长期扩展的闭环：**Command Inbox → PermissionCtx 纯求值 → Shell Analysis IR → OS capability floor → ApprovalRequest 生命周期 → Harness ProcessRunner → 有界 Artifact → 字段级投影 → 完整 checkpoint**。

固定四条轴：

1. **能力守界**：P2 仍只支持串行工具、单模型、本地 surfaces；不实现 MCP、并行 gate、子 agent、桌面 UI、Docker sandbox。
2. **架构优先**：安全/一致性接缝不因省事而留下第二真相；本计划不以“少写代码”为目标，而以“后续 P3/P5/P7/P9 不返工”为目标。
3. **fail-closed**：未知参数、未知命令、缺沙箱能力、审批歧义、投影超限、artifact IO 故障均不得升级成静默放行或上下文膨胀。
4. **证据优先**：每条 DoD 必须有可运行测试和真实平台复现；无法在当前机器复现的项目必须标 UNVERIFIED，不能拿 fake 冒充真机。

**开工前基线**：P0/P1 已实测 66 tests green、ruff/import-linter/protocol/AST/P0/thread guards green。该事实只证明 P1 可进入 P2，不证明旧 P2 计划可实施；本文件的 ADR 前置已完成。

---

## 1. 范围与文件结构

### 1.1 P2 必须完成

- L0：审批/工具生命周期/Shell IR/SandboxDescriptor/ProcessRunner/Artifact/Command Inbox contracts。
- L1：PermissionCtx、ApprovalRequest、ToolCall 全字段与完整 snapshot round-trip。
- L2：RunController、Command Inbox、五层校验、POSIX/PowerShell parser、capability floor、权限纯引擎、HITL、ProcessRunner orchestration、真投影。
- L3：ToolRegistry + read/write/edit/apply_patch/ls/glob/grep/bash/powershell。
- L5：Null/Job/Seatbelt/Bwrap descriptor 与 wrap；Windows Job Object 实机；ArtifactStore；Provider env registry。
- L6：CLI ApprovalAdapter、HTTP `/approve`、`/permissions`、SSE 新事件，只提交 Command。
- 横切：字段级 protocol schema、AST/import/protocol/secret/output guards、license ledger、真实平台 DoD。

### 1.2 明确不做

| 项 | 后置 |
|---|---|
| 并行 tool gate / reader-writer scheduling | P5 |
| MCP server 生命周期与进程隔离 | P5 |
| 子 agent/DAG | P8 |
| Tauri approval UI | P7 |
| Docker/容器 backend | 非 v1 |
| 完整 fallback/provider credential pool | P10 |
| 远程 Command Inbox/多机 lease | P9/P10 |
| 三层记忆、Deep Dream | P4 |

### 1.3 目标文件结构

```text
src/questor/
├─ contracts/
│  ├─ artifacts.py             ArtifactRef / output envelope（纯数据）
│  ├─ events.py                RequestApproval / ResolveApproval / ExpireApproval / MarkToolRunning / SetPermissionMode
│  ├─ inbox.py                 CommandInboxPort / InboxReceipt
│  ├─ process.py               ProcessRequest / ProcessResult / ProcessRunnerPort
│  ├─ sandbox.py               SandboxDescriptor / SandboxCapabilities
│  ├─ shell_analysis.py        ShellDialect / ShellSegment / ShellAnalysis
│  ├─ state_schema.py          ApprovalRequest / ApprovalStatus / ToolArgsStatus / ToolCallStatus / PermissionRule / Budget
│  └─ tool.py                  ToolSpec.timeout_s / ToolContext.run_process / put_artifact / declare_env_passthrough
├─ kernel/
│  ├─ run_control.py           RunController / InMemoryCommandInbox
│  ├─ shell_parse_posix.py     POSIX shell → ShellAnalysis IR
│  ├─ shell_parse_powershell.py PowerShell → ShellAnalysis IR
│  ├─ permission_policy.py     pure eight-step + capability floor
│  ├─ permissions.py           PermissionEngine facade（无自身 mode/rules）
│  ├─ events.py                per-type projection
│  └─ loop.py                  五层校验 + HITL + ProcessRunner settle
├─ state/
│  ├─ domain_state.py          PermissionCtx.approvals
│  ├─ reduce.py                tool lifecycle commands
│  └─ snapshot.py              versioned complete round-trip
├─ capabilities/tools/
│  ├─ registry.py / write.py / edit.py / apply_patch.py / ls.py / glob.py / grep.py / bash.py / powershell.py
├─ providers/
│  ├─ sandbox.py               backend detection + descriptors + wrap
│  ├─ _win_job.py              ctypes Job Object
│  ├─ process_runner.py        asyncio + kill-tree + env + timeout + output
│  ├─ artifact_store.py        content-addressed artifact
│  └─ env_safety.py            provider credential registry + scrub
├─ surfaces/
│  ├─ approval.py              CLI approval adapter（只提交 Command）
│  ├─ cli.py / http_sse.py     command inbox wiring + /approve + /permissions
└─ protocol/event.schema.json  per-type data schema

tests/unit/
├─ test_command_inbox.py / test_shell_parse_posix.py / test_shell_parse_powershell.py
├─ test_permission_policy.py / test_capability_floor.py / test_approval_state.py
├─ test_tool_lifecycle_reduce.py / test_snapshot_v2.py / test_projection.py
├─ test_output_budget.py / test_env_safety.py / test_registry.py
tests/integration/
├─ test_p2_hitl_inbox.py / test_p2_approval_cancel_race.py / test_p2_process_timeout_tree.py
├─ test_p2_write_sandbox_matrix.py / test_p2_powershell_dod.py / test_p2_bash_dod.py
└─ test_p2_dod.py
scripts/
├─ check_layering_ast.py / check_protocol_schema.py / check_output_budgets.py / check_secret_projection.py
```

---

## 2. 已定契约（实现者不得再自行发明第二套）

### 2.1 Command 与 ApprovalRequest

```python
@dataclass(frozen=True, slots=True)
class RequestApproval:
    run_id: str
    tool_call_id: str
    request_id: str
    args_summary: str
    risk: str
    reason: str
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class ResolveApproval:
    run_id: str
    request_id: str
    decision: str                 # allow | deny
    decided_by: str               # user | http_client | cli | system

@dataclass(frozen=True, slots=True)
class ExpireApproval:
    run_id: str
    request_id: str

@dataclass(frozen=True, slots=True)
class MarkToolValidated:
    run_id: str
    tool_call_id: str

@dataclass(frozen=True, slots=True)
class MarkToolRunning:
    run_id: str
    tool_call_id: str
    capability: str
    risk: str
    timeout_s: float

@dataclass(frozen=True, slots=True)
class SetPermissionMode:
    run_id: str
    mode: str
    changed_by: str

@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    request_id: str
    tool_call_id: str
    status: ApprovalStatus        # pending | approved | denied | expired | cancelled
    args_summary: str
    risk: str
    reason: str
    created_at: datetime
    expires_at: datetime
    decision: str | None = None
    decided_by: str | None = None
    resolved_at: datetime | None = None
```

### 2.2 Command Inbox

```python
@dataclass(frozen=True, slots=True)
class InboxReceipt:
    accepted: bool
    status: str   # accepted | duplicate | rejected_terminal | queue_full | unknown_run
    reason: str | None = None

@runtime_checkable
class CommandInboxPort(Protocol):
    async def submit(
        self,
        command: Command,
        *,
        source: str,
        idempotency_key: str,
    ) -> InboxReceipt: ...
```

- 每个 run queue 上限 1024；队满返回 `queue_full`，不得丢弃。
- 相同 idempotency key + same command digest → `duplicate`；相同 key + 不同 digest → `rejected_terminal`。
- terminal 后所有写 Command → `rejected_terminal`；只允许 replay/read。

### 2.3 PermissionCtx 纯求值输入

```python
@dataclass(frozen=True, slots=True)
class PermissionEvaluation:
    tool_name: str
    tool_spec: ToolSpec
    args_status: ToolArgsStatus
    arguments: JsonObject | None
    raw_args_summary: str | None
    shell_analysis: ShellAnalysis | None
    permission: PermissionCtx
    sandbox: SandboxDescriptor

@dataclass(frozen=True, slots=True)
class PermissionOutcome:
    decision: PermissionDecision
    reason: str
    request_id: str | None
    warnings: tuple[str, ...]
    args_summary: str
    floor_applied: str | None
```

`PermissionEngine.evaluate(evaluation)` 不接收也不保存 mode/rules。engine factory 只装配 helper；配置全部来自 evaluation.permission。

### 2.4 ToolCall 状态与非法参数

```python
class ToolArgsStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"

class ToolCallStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CRITICAL_ERROR = "critical_error"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    DENIED = "denied"
```

`ContentBlock` 增加：

```python
raw_input: str | None
args_status: ToolArgsStatus = ToolArgsStatus.MISSING
args_error: str | None = None
```

provider 的 tool args 分片先累积为 raw string。定稿 ContentBlock 时：
- JSON 有效：input frozen map + args_status valid；
- JSON 无效：input None、raw_input 有界摘要（最多 4096 chars）、args_status invalid；
- 永远不得把 invalid 变成 `{}` 继续校验。

### 2.5 ProcessRunner / SandboxDescriptor

```python
@dataclass(frozen=True, slots=True)
class ProcessRequest:
    capability: Capability
    argv: tuple[str, ...]
    cwd: Path
    timeout_s: float
    declared_env_names: tuple[str, ...]
    stdout_limit: int
    stderr_limit: int

@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int | None
    stdout_text: str
    stderr_text: str
    stdout_artifact: ArtifactRef | None
    stderr_artifact: ArtifactRef | None
    timed_out: bool
    process_tree_killed: bool
    sandbox_backend: str
    confinement: str
    warning: str | None
    env_scrubbed: tuple[str, ...]
```

`ToolContext.run_process` 返回上述结果；工具不能直接 import subprocess/asyncio process API。

---

## 3. 参考扫描与复用（AGENTS §4.5 硬门，已在评审中重验）

| 能力 | 证据 | 结论 | 本计划改造点 |
|---|---|---|---|
| permission/MCP approval | DeepCode `core/harness/permissions.py:264-309` | 可改造 | 抽成纯 policy，补 CapabilityFloor，不保留 engine mode |
| shell segment/substitution | CowAgent `agent/permission/policy.py:290-410,729-879` | 可改造 | 输出 IR，不只返回 bool；拆 POSIX/PowerShell |
| protected roots | CowAgent `policy.py:482-612` | 可改造 | realpath fail-closed + 受保护 config/mcp/env |
| sandbox separation | DeepCode `sandbox.py:291-431` | 可改造 | 保留 wrap separation，拒绝 passthrough；加 descriptor |
| no silent unconfined | wuu `internal/processsandbox/sandbox.go:37-105` | 强约束 | partial 不等于 allow；返回 warning/拒绝 |
| result envelope | wuu `result_budget.go:57-105` | 可改造 | 写失败不 fail-open 原文，改 bounded error |
| provider env credential | hermes `env_passthrough.py:46-92` | 取纪律 | Questor 自建 provider registry；blocklist 缺失 fail-closed |

**License**：DeepCode/CowAgent/wuu/hermes 抽样均为 MIT。每个移植文件首部必须写：
```python
# 改造自 <repo> <path>:<lines>，MIT License；未保留原符号名/内部依赖。
```
P2 收尾前生成 `docs/references/license-ledger-p2.md`，列 repo/path/our file/action/copyright；缺文件不算 DoD。

---

## 4. 任务分解（严格按依赖，不按标题数字执行）

> 每个 Task 均按：**写失败测试 → 跑红 → 最小实现 → 跑绿 → 全量相关测试 → 文档同 PR**。  
> 不得在未获得用户当轮许可时 commit/push。每个 Task 完成必须贴命令输出。

### T0：契约与 ADR 落地（前置，已完成于本修订）

**文件**：ADR-0013-0019、design/01-04、HARD-CONSTRAINTS。  
**验证**：ADR README 可达；文档中无旧“工具直接 spawn / full_auto 覆盖 / artifact fail-open / identity projection”冲突口径。

---

### T1：L0/状态基础契约（依赖 T0）

**文件**
- Modify：`contracts/state_schema.py`
- Modify：`contracts/events.py`
- Modify：`contracts/tool.py`
- Modify：`contracts/common.py`
- Create：`contracts/shell_analysis.py`、`contracts/sandbox.py`、`contracts/process.py`、`contracts/artifacts.py`、`contracts/inbox.py`

**接口**：§2 全类型。

- [ ] 写失败测试 `tests/unit/test_contracts.py::test_toolcall_lifecycle_fields_roundtrip`
```python
assert {status.value for status in ToolCallStatus} == {
    "pending",
    "validated",
    "awaiting_approval",
    "ready",
    "running",
    "success",
    "error",
    "critical_error",
    "timed_out",
    "cancelled",
    "denied",
}
```
断言新枚举、ApprovalRequest、SandboxDescriptor、InboxReceipt、ProcessRequest/Result 均可构造且 frozen。
- [ ] 跑 `uv run pytest tests/unit/test_contracts.py -q`，预期新增测试红。
- [ ] 实现 contracts；禁止 import state/kernel/providers/capabilities。
- [ ] 跑：
```text
uv run pytest tests/unit/test_contracts.py -q
uv run python -c "import questor.contracts.state_schema, questor.contracts.inbox, questor.contracts.process, questor.contracts.sandbox"
```
预期全绿；`lint-imports` 证明 L0 依赖方向不变。

---

### T2：完整 versioned snapshot（依赖 T1）

**文件**
- Modify：`contracts/state_schema.py`：Checkpoint 加 `contract_version`
- Modify：`state/domain_state.py`：PermissionCtx 加 approvals
- Modify：`state/snapshot.py`
- Create：`tests/unit/test_snapshot_v2.py`

**不变式**：snapshot v2 必含 task_tree、permission_ctx（rules/approvals/decisions）、tool_ledger 全字段、error_stack、budget 新字段；v1 仅允许有损迁移并明确记录，未知 v>current fail-closed。

- [ ] 写失败测试：mode、approval pending、permission reason、task_tree、error_stack 经 `to_snapshot/from_snapshot` 后逐项相等。
- [ ] 写失败测试：
```python
future_payload = {**to_snapshot(run), "contract_version": 999}
with pytest.raises(SnapshotVersionError):
    from_snapshot(future_payload)
```
- [ ] 实现序列化；禁止 `permission_ctx=PermissionCtx()` placeholder。
- [ ] 跑：
```text
uv run pytest tests/unit/test_snapshot_v2.py tests/unit/test_checkpoint.py -q
uv run python scripts/check_layering_ast.py --self-test
```

---

### T3：Command Inbox + RunController（依赖 T1/T2）

**文件**
- Create：`kernel/run_control.py`
- Modify：`kernel/loop.py`
- Modify：`surfaces/cli.py`
- Modify：`surfaces/http_sse.py`
- Create：`tests/unit/test_command_inbox.py`
- Create：`tests/integration/test_p2_hitl_inbox.py`

**接口**
```python
class RunController:
    def __init__(self, run: Run, *, limit: int = 1024) -> None
    async def submit(self, command: Command, *, source: str, idempotency_key: str) -> InboxReceipt
    async def next_batch(self) -> tuple[Command, ...]
    async def wait_for(self, predicate, timeout: float | None) -> Command | None
    def close(self) -> None
```

- [ ] 写红测：
  - same idempotency key/digest duplicate no event；
  - terminal submit rejected；
  - queue full receipt；
  - two concurrent HTTP approvals 串行且只有一个有效 transition。
- [ ] 实现 inbox；L6 不再直接调用 reduce。
- [ ] 跑 `uv run pytest tests/unit/test_command_inbox.py tests/integration/test_p2_hitl_inbox.py -q`。
- [ ] AST 新规则（可先 local 验证，T20 扩 CI）：surfaces 禁 import reduce/store implementation。

---

### T4：五层校验重排 + raw args（依赖 T1/T3）

**文件**
- Modify：`kernel/loop.py`
- Modify：`contracts/tool.py` / `state_schema.py`（T1 已定）
- Create：`tests/integration/test_validation_order.py`

**次序**
```text
unknown tool/static candidate
→ args_status
→ schema/coerce
→ arg-key + shell analysis
→ permission/floor
→ sandbox process
→ tool business validation
```

- [ ] 红测：非法 JSON 必须产生 `args_status=INVALID` error ToolResult，不进 permission/execute，且 `raw_args_summary` 与原始有界内容一致。
- [ ] 红测：schema invalid 不进 permission；permission deny 不进 execute；通过五层检查后必须产生 `MarkToolValidated`，ToolCall 进入 validated。
- [ ] 红测：provider stream 到达 tool_call 分片期间收到 Cancel，async iterator 被正确关闭、半 tool_use 不进入可执行状态、最终仍经 Cancel Command 闭合；绝不允许“已定稿 tool_use 但无 result”。
- [ ] 修改 `_stream_turn` 累积 raw，不先 `_parse_args` 成 `{}`；修改 `_handle_tool_call` 为 JSON→schema→shell analysis→MarkToolValidated→permission→floor→execute。
- [ ] 跑：
```text
uv run pytest tests/integration/test_validation_order.py tests/integration/test_loop.py -q
```
- [ ] 确认 Cancel/deny/illegal intent 既有三条异常路径仍绿。

---

### T5：L0 arg-key + ShellAnalysis IR（依赖 T1/T4）

**文件**
- Create：`contracts/tool_args.py`
- Modify：`contracts/shell_analysis.py`
- Create：`tests/unit/test_tool_args.py`

纯数据：
```python
PATH_ARG_KEYS = ...
SHELL_ARG_KEYS = ...
ACTION_ARG_KEYS = ...
PATCH_PATH_PREFIXES = ...
NULL_SINKS = ...
PROTECTED_IN_ROOTS = ("mcp.json", "config.json", ".env", ".env.*")
```
Shell IR：dialect/status/segments/dynamic/destructive/write_paths/read_only。

- [ ] 表驱动抽取 `read/write/edit/bash/powershell/apply_patch` 路径。
- [ ] 测试 `PROTECTED_IN_ROOTS` 不丢失 Windows 盘符和 UNC path。
- [ ] AST 验证 `contracts/tool_args.py` 无函数体/IO。

---

### T6：POSIX shell parser（依赖 T5）

**文件**
- Create：`kernel/shell_parse_posix.py`
- Create：`tests/unit/test_shell_parse_posix.py`

处理：`; && || | & ( ) { } newline`、quotes、backticks、`$(...)`、`<(...) process substitution`、`env/nohup/time/timeout/nice/xargs/setsid`、VAR=、fd dup、NULL sinks、flags、git subcommand。

- [ ] 红测 corpus 每条都断言具体 IR：
```text
rm -rf /；rm  -rf /；rm -r -f /；rm --recursive --force /
env FOO=1 nohup rm -rf /；find . -delete；sed -i ...；sort -o out
awk 'system("x")'；bash -c 'rm -rf /'；$(rm -rf /)；`rm -rf /`
git branch v1 vs git branch -l；git config user.name（无 --get=写）
grep "a|b" file（引号内不切段）
```
- [ ] unparsable/dynamic 必须 `read_only=False`、status 精确。
- [ ] parser 模块禁 IO/subprocess/async；`uv run pytest tests/unit/test_shell_parse_posix.py -q`。

---

### T7：PowerShell parser（依赖 T5）

**文件**
- Create：`kernel/shell_parse_powershell.py`
- Create：`tests/unit/test_shell_parse_powershell.py`

处理：`; | & command`、single/double quote、backtick escape、`>`/`>>`、`-File`、splatting、cmdlet/alias：
- destructive：`Remove-Item/rm/del/erase/rd/rmdir/ri`
- recursive/force：`-Recurse/-Force/-rf` 等价组合
- read-only：`Get-ChildItem/dir/ls/cat/gc/type` only with safe flags
- dynamic：`Invoke-Expression/iex/& $x`、scriptblock、external exe、EncodedCommand、`Start-Process`、`-Command` 递归。

- [ ] Windows corpus 至少测：
```text
Remove-Item -Recurse -Force C:\tmp
rm -Recurse -Force .\x
del /s /q C:\x
Get-ChildItem .
iex "Get-Process"
& { Remove-Item x }
Start-Process -FilePath cmd
powershell -EncodedCommand <base64>
```
- [ ] EncodedCommand 解码后递归分析；解码失败 dynamic ask。
- [ ] 未识别 cmdlet `read_only=False`；不能按名 substring allow。

---

### T8：PermissionCtx pure engine + eight-step policy（依赖 T1/T4-T7）

**文件**
- Rewrite：`kernel/permissions.py`
- Create：`kernel/permission_policy.py`
- Create：`tests/unit/test_permission_policy.py`

固定顺序：
```text
1 invalid args → deny
2 escalate: approval reply 不带 mode
3 sensitive/protected path → deny
4 capability floor
5 rules last-match-wins
6 mode default
7 approval_policy never → ask deny
8 approval_mode compose only tighten
```
所有路径以 `PermissionCtx` 为输入，engine 不持 mode/rules。

- [ ] 红测 `SetPermissionMode` 后 evaluate 使用新模式；mode 不回溯历史。
- [ ] 红测 `read_only=True` 只能来自 ToolSpec，不能从工具名猜。
- [ ] 红测 `PermissionRule` 统一字段；同一 argument 多条 rules last-match-wins。
- [ ] 红测 realpath OSError deny、expandvars、normcase、Windows drive/UNC、symlink/junction。
- [ ] 红测 `approval_mode=auto` 不能把 deny/ask 翻 allow；unknown deny。

---

### T9：SandboxDescriptor + capability floor（依赖 T8）

**文件**
- Rewrite：`contracts/sandbox.py`、`providers/sandbox.py`
- Create：`kernel/capability_floor.py`
- Create：`tests/unit/test_capability_floor.py`
- Create：`tests/integration/test_p2_write_sandbox_matrix.py`

矩阵严格按 design/03 §5：
- none：all exec deny；write ask floor。
- job：proven read-only exec allow；其他 exec/write ask floor。
- seatbelt/bwrap：full 才按普通 permission；缺项 ask/deny。
- full_auto 只能消解“无 floor 的 ask”，不能消解 capability floor。

- [ ] parametrize `(backend,fences,read_only,exec,write,mode) → decision`。
- [ ] 断言每个 non-full confinement outcome 至少一个 warning。
- [ ] 断言 `full_auto + none + write → ask`、`full_auto + job + unknown exec → ask`。
- [ ] 禁止 backend descriptor 为空/unknown 时执行。

---

### T10：ArtifactStore + output budget（依赖 T1/T4）

**文件**
- Create：`providers/artifact_store.py`
- Create：`capabilities/tools/_output.py`
- Create：`tests/unit/test_output_budget.py`
- Create：`scripts/check_output_budgets.py`

**数据目录**：`<store_root>/runs/<run_id>/artifacts/<sha256>.txt`，临时文件 fsync + atomic rename。  
**Envelope**：artifact_ref、sha256、bytes、preview、continuation。

- [ ] 红测 1 MiB stdout → event/context 只保存 preview，ref 可读取全文。
- [ ] 红测 artifact write failure → status error + bounded preview；断言结果长度 <= limit。
- [ ] 红测 path traversal/run id escape deny。
- [ ] 红测同内容去重、并发写同一 hash 原子、损坏文件不覆盖已有内容。
- [ ] guard self-test：空 fixture fail-on-empty、超限 payload 判红。

---

### T11：Provider env safety（依赖 T1/T9/T10）

**文件**
- Create：`providers/env_safety.py`
- Create：`tests/unit/test_env_safety.py`

规则：
1. scrub credential-shaped names；
2. Questor/LiteLLM/provider credential 永不透传；
3. `declare_env_passthrough` 只能增加非 provider allowlist；
4. blocklist load fail → deny passthrough；
5. Windows case-insensitive match；
6. `env_scrubbed` 仅保存 names，不保存 values。

- [ ] 红测 `LITELLM_API_KEY`、`OPENAI_API_KEY`、`QUESTOR_*_API_KEY` 即使 declare 仍拒绝。
- [ ] 红测 `TENOR_API_KEY` 显式 allow 可透传。
- [ ] 红测 PATH/HOME/locale/proxy 保留。

---

### T12：ProcessRunner adapter（依赖 T9/T10/T11）

**文件**
- Create：`providers/process_runner.py`、`providers/_win_job.py`
- Create：`tests/integration/test_p2_process_timeout_tree.py`
- Create：`tests/unit/test_process_runner.py`

职责：绝对 argv、sandbox wrap、cwd containment、env、stdout/stderr budget、timeout、tree kill、cancel poll、non-silent backend fail。

- [ ] fake runner 单测 argv/env/timeout/result。
- [ ] 真实 PowerShell 小脚本：parent 启动 child，timeout 后两者 PID 均不存在；测试结束无残留。
- [ ] 真实 POSIX（Linux CI/有 bash）跑 sleep + child 同测试；Windows 本机无 bash 时不得伪称该测试真跑。
- [ ] Job Object 任一 Win32 call failure → ProcessResult error，argv 不执行。
- [ ] 输出 > limit → artifact refs；stderr 独立计数。

---

### T13：HITL lifecycle + approval idempotency（依赖 T2-T9/T3/T4）

**文件**
- Modify：`state/reduce.py`、`kernel/loop.py`、`contracts/events.py`
- Create：`tests/unit/test_tool_lifecycle_reduce.py`
- Create：`tests/integration/test_p2_approval_cancel_race.py`
- Create：`tests/integration/test_p2_hitl_inbox.py`

- [ ] MarkToolValidated 只能 pending→validated；重复 validated 幂等无 event；非法状态 skip 并 warning。
- [ ] RequestApproval 将 validated tool 转 awaiting，发 approval_request；同 tool_call 已有 pending request 拒绝 duplicate。
- [ ] Resolve same request same decision → 无新 event；different decision → rejected event；expired → no flip。
- [ ] MarkToolRunning 是 tool_started 唯一来源。
- [ ] ExpireApproval timer 与 external Resolve 同时发生：Inbox FIFO 第一个 transition 胜，第二个 stale。
- [ ] Cancel while awaiting：approval cancelled、tool backfilled、恰一 terminal、seq unique。
- [ ] approval timeout default 300，None 取 300；过期不得让后续 resolve 复活。
- [ ] CLI/HTTP 两条路径最终都提交同一 Command。

---

### T14：ToolRegistry + run freeze（依赖 T1/T4）

**文件**
- Rewrite：`capabilities/tools/registry.py`
- Modify：`kernel/loop.py`、`surfaces/cli.py`、`surfaces/http_sse.py`
- Create：`tests/unit/test_registry.py`

接口：
```python
register/unregister/has/get/list_available/definitions/freeze_for_run(run_id)
```
描述 min20/max2000，sanitize；unknown candidate only hint。

- [ ] run 中 register/unregister 不影响 frozen snapshot。
- [ ] available false 不注册进 surface。
- [ ] 长/短/控制字符 description fallback。
- [ ] unknown tool returns candidate hint、不 execute、错误可回模型。

---

### T15：文件工具（依赖 T4/T5/T8/T9/T10/T14）

**文件**
- Modify：`capabilities/tools/read.py`
- Create：`write.py`、`edit.py`、`apply_patch.py`、`ls.py`、`glob.py`、`grep.py`
- Create：`tests/unit/test_file_tools.py`、`tests/integration/test_p2_file_tools.py`

共同：
- 只返回 ToolResult，不 reduce/state/command；
- workspace containment；
- 所有路径 realpath/expandvars/normcase；realpath OSError deny；
- result/display bounded；
- timeout_s 明确。

逐工具必测：
- read：offset/limit、行/字节双上限、目录 error、binary error。
- write：越界 deny、protected root deny、无 fence ask warning。
- edit：唯一锚点；多个 match 且 replace_all false → error；replace_all 回报 count。
- apply_patch：精确上下文 all-or-nothing；任一失败无半文件；路径逐条 denylist。
- ls/glob：entry/match caps、skip `.git/node_modules/__pycache__/.venv/dist/build`、symlink escape。
- grep：Python fallback 与 rg 同 envelope；regex invalid error；path caps。

---

### T16：`bash` + `powershell` tools（依赖 T4-T15）

**文件**
- Create：`capabilities/tools/bash.py`、`powershell.py`
- Create：`tests/integration/test_p2_bash_dod.py`、`test_p2_powershell_dod.py`

两个工具只解析 args → 构造 `ProcessRequest` → `ctx.run_process()` → envelope。  
不得 import subprocess/asyncio/sandbox concrete。

- [ ] bash：`rm -rf` ask；denylist outside root；timeout；process kill；env scrub。
- [ ] powershell Windows 真机：`Remove-Item -Recurse -Force <tmp path>` ask；答 n denied+run continues；答 y 仅 workspace 内执行。
- [ ] `full_auto` 对 unknown PowerShell 仍 ask。
- [ ] read-only `Get-ChildItem <workspace>` job allow。
- [ ] EncodedCommand/iex/& scriptblock ask。
- [ ] 缺 bash 的 Windows：bash `available=False`；powershell DoD 必须真跑，不以 fake 代替。

---

### T17：真投影 + 字段级 protocol（依赖 T1-T16）

**文件**
- Rewrite：`kernel/events.py`
- Rewrite：`protocol/event.schema.json`
- Modify：`contracts/events.py`
- Create：`scripts/check_output_budgets.py`、`tests/unit/test_projection.py`

- [ ] EventType 从 17 → 19：新增 `approval_resolved`、`permission_mode_changed`。
- [ ] schema `$defs` + `oneOf` per type，required fields、string maxLength、data `additionalProperties:false`。
- [ ] project 白名单：完整 args、abs path、env names?（names可，values禁）、provider state 默认不外发。
- [ ] approval_request 字段：request_id/tool_call_id/name/args_summary/risk/reason/expires_at。
- [ ] tool_started：tool_call_id/name/args_summary/capability/risk。
- [ ] hidden 不进入外部 Envelope。
- [ ] protocol `--self-test` 增加 per-field fixture；造多余字段/缺 required/超长都判红；fail-on-empty。

---

### T18：Surfaces 审批与权限端点（依赖 T3/T13/T17）

**文件**
- Modify：`surfaces/cli.py`
- Create：`surfaces/approval.py`
- Modify：`surfaces/http_sse.py`
- Create：`tests/integration/test_surfaces_approval.py`

CLI：
- 显示 request_id、args_summary、risk、reason、backend warning；
- y/n 转 ResolveApproval；
- noninteractive deny；
- input pump 必须有唯一 lifecycle，timeout/cancel 后线程退出，不留 reader。

HTTP：
```text
POST /runs/{run_id}/approvals/{request_id}/resolve
POST /runs/{run_id}/permissions
```
只构造 Command + submit inbox，不碰 reduce。返回 InboxReceipt 映射 HTTP status。

- [ ] duplicate request no-op；terminal late approve 409；unknown run 404；queue full 429。
- [ ] SSE client 能收到 approval request → resolve → approval resolved → tool started/completed。
- [ ] CLI 与 HTTP 并发审批同 request，只有一个 first transition。

---

### T19：完整 checkpoint/HITL resume（依赖 T13/T15/T16/T18）

**文件**
- Modify：`kernel/recovery.py`、`kernel/loop.py`、`tests/integration/test_checkpoint_and_resume.py`

- [ ] awaiting_approval snapshot 重启后仍是 awaiting，且 request id/expiry 不丢失。
- [ ] approved tool 重启不得自动执行需人审的操作；按当前 PermissionCtx/floor 重新判断是否仍需 pending request。
- [ ] timeout expiry 持久化；恢复不重复 request。
- [ ] permission mode 变更和 decisions round-trip。
- [ ] kill/restart 后 tool pairing、seq、terminal uniqueness 一致。

注意：P3 仍负责通用 durable resume/after_seq 加固；P2 必须至少证明 **权限/审批状态不会在 checkpoint 静默蒸发**，这是 ADR-0014/0016 的验收点。

---

### T20：守卫扩规则 + CI（依赖 T5/T10/T17/T18）

**文件**
- Modify：`scripts/check_layering_ast.py`
- Modify：`scripts/check_protocol_schema.py`
- Create：`scripts/check_output_budgets.py`、`scripts/check_secret_projection.py`
- Modify：`.github/workflows/ci-python.yml`
- Modify：`.importlinter`

新增机器规则：
1. contracts no implementation/IO；
2. reduce no in-place mutation；
3. surfaces no reduce/store import；
4. capabilities no subprocess/asyncio process/sandbox concrete import；
5. event data payload size static check；
6. protocol per-type fields；
7. provider credential env guard。

- [ ] 每条 `--self-test` 造坏样本必须红、真实码必须绿、空目录必须红。
- [ ] boundaries job 独立 blocking，不受 change classifier 门控。
- [ ] CI matrix 区分 Windows PowerShell 真机与 POSIX bash 真机；缺失平台显式 skip 报告，不能绿冒充覆盖。

---

### T21：端到端 DoD + 活文档（依赖全部）

**文件**
- Create：`tests/integration/test_p2_dod.py`
- Modify：CHANGELOG、ROADMAP link、plan deviations、license ledger、delivery report

逐条执行 §5 并记录命令输出。

---

## 5. 修订后的 DoD（全部可复现，平台分栏）

### 5.1 Windows 本机主验收

1. 注册 `powershell`；真实执行 `Remove-Item -Recurse -Force <workspace temp path>` 触发 ask；答 `n` 后 ToolCall denied、事件与 ledger 一致、run 续跑。
2. 同路径答 `y` 仅在 workspace root 内执行；root 外路径 deny；`~/.ssh`、`.env`、`*.pem`、`id_rsa` 在 full_auto 下仍 deny。
3. full_auto + job backend + unknown command → ask；证明 capability floor 不可被 mode 降 allow。
4. `SetPermissionMode` 经 HTTP inbox 提交，下一调用读取新模式，历史 decision 不变。
5. `POST approvals/resolve` 与 Cancel 并发：恰一有效 transition，无 duplicate terminal，无 seq collision。
6. approval timeout → request expired → tool denied；同 request 迟到 allow 被拒。
7. PowerShell timeout 杀 parent/child 全树；无残留 PID/线程；结果 `timed_out`。
8. 非法 JSON、schema required/type/additionalProperties/timeout 越界全部在 execute 前 error。
9. `apply_patch` 任一 hunk 失败则全文件无部分写入。
10. >1 MiB stdout 有 artifact ref；event table 和 checkpoint payload bounded；artifact write failure 返回 bounded error。
11. `bash` 在缺 bash 的 Windows 上 `available=False`，不得被 provider 看到或误执行。
12. 完整质量门：
```text
uv run pytest -q
uv run ruff check src scripts tests
uv run lint-imports
uv run python scripts/check_layering_ast.py --self-test
uv run python scripts/check_layering_ast.py
uv run python scripts/check_protocol_schema.py --check
uv run python scripts/check_protocol_schema.py --self-test
uv run python scripts/check_output_budgets.py --self-test
uv run python scripts/check_secret_projection.py --self-test
uv run python scripts/verify_p0.py
uv run python scripts/check_thread_leak.py --self-test
```
13. 不违 C1-C18；每移植文件有 provenance；license ledger 完整。

### 5.2 POSIX 主验收（Linux/macOS/CI）

1. 有真实 bash 时执行 `rm -rf` 危险语料，Windows 无 bash 不得用 fake 声称真跑。
2. bash 杀 parent/child process group。
3. seatbelt/bwrap 实机执行分别标 VERIFIED/UNVERIFIED；当前 Windows 只验 descriptor/argv 生成。

### 5.3 必须诚实标注 UNVERIFIED

- seatbelt/bwrap 在 Windows 的实机运行。
- 真实 LiteLLM 网络端到端（无 key）。
- 跨真实 socket 的 HTTP SSE 重连若 uvicorn/目标环境不可用；进程内 async transport 测试不能冒充网络真跑。
- 多 agent/远程 Command inbox（P8/P9 后置）。

---

## 6. 测试覆盖矩阵

| 层级 | 必测项 | 最小数量/策略 |
|---|---|---|
| Contracts | lifecycle、approval identity、frozen containers、receipt | 18 条，逐枚举/字段 |
| Reduce | pending→awaiting→running→result/deny/expire/cancel | 状态机 8×N，含 duplicate |
| Inbox | duplicate、terminal、queue full、concurrent race | 8 条 async |
| Validation | raw invalid、schema、order、unknown tool | 10 条 |
| POSIX parser | separators、quotes、substitution、wrappers、flags、redirect、git | 40 条语料 |
| PowerShell parser | aliases、dynamic、encoded、pipeline、paths | 30 条语料 |
| Permission | eight steps、mode not retroactive、rules、approval_mode | 25 条 |
| Sensitive | realpath fail、symlink/junction、UNC、drive、root protect | 15 条 |
| Floor | backend×capability×mode 全表 | 24 格 parametrize |
| HITL | request/resolve/expire/cancel/stale/race | 12 条 |
| Process | fake + PowerShell tree + timeout + env + limits | 10 条，真实子进程 |
| File tools | containment、atomic、offset、globs、grep fallback | 35 条 |
| Registry | freeze、description、unknown candidate | 10 条 |
| Artifact | bounds、dedup、write fail、path escape | 12 条 |
| Projection | per-type required/redaction/truncation | 19 types snapshot |
| Snapshot | v2 roundtrip、v1 migration、unknown version | 10 条 |
| Surfaces | CLI/HTTP same commands、receipt status | 12 条 |
| Guards | self-test bad/green/empty | 7 条 |

目标不是凑数字；任何上述分支缺失即 P2 incomplete。测试文件与实现目录一一对应，安全/持久化/并发必须有 integration test，不能只单测纯函数。

---

## 7. 红线对照（修订后）

| 红线 | P2 机械落点 |
|---|---|
| C1/C14 | ToolContext/Ports；capabilities import guard；surfaces inbox only |
| C2/C5 | Command → reduce；Inbox 单消费者；Event no feedback |
| C3 | per-call state 小对象，不每轮全量快照 |
| C4 | StorePort/ArtifactStorePort，工具不自拼路径 |
| C6 | 19 event types、per-type schema、additive |
| C7/C13 | lifecycle reduce、terminal uniqueness、seq unique |
| C8 | validation/permission/sandbox/process settle 全 Harness；业务校验工具内 |
| C9 | PermissionCtx + ApprovalRequest + SandboxDescriptor + floors |
| C10 | panic→error、settle shielded、no crash |
| C11 | additive fields；P5/P7/P8 只做 contract placeholders |
| C15 | schema/type/field triple lock + guard self-tests |
| C16 | CommandInboxPort + RunController + surfaces import rules |
| C17 | pure PermissionCtx policy + capability floor matrix tests |
| C18 | lifecycle command + bounded projection/artifact asserts |

---

## 8. 风险与缓解

- **R-A｜PowerShell parser 误判**：采用保守 allowlist；unknown/dynamic/encoded ask；parser bug 只能通过测试暴露，不能成为安全边界。
- **R-B｜asyncio 审批竞态**：所有 transition 由 inbox FIFO + reduce 单写；request id 幂等。
- **R-C｜进程清理失败**：backend wrapper 返回 `process_tree_killed`；任一步 error 记结构化 ProcessResult；真实测试查 PID。
- **R-D｜artifact 磁盘 IO**：atomic fsync + hash dedup；写失败有界；GC 归 P10。
- **R-E｜协议扩展破坏 P7**：先 schema/contract 后实现；per-type snapshot tests。
- **R-F｜平台假绿**：CI matrix 区分 PowerShell/bash；skip 状态可见；fake 不满足真实 DoD。
- **R-G｜full_auto 可用性争议**：明确 mode 是审批便利、不是隔离声明；只 capability floor ask 保留。
- **R-H｜参考实现许可**：MIT 但需保留声明；license ledger 与 provenance 是硬门。

---

## 9. 被否方案（相对旧 plan/02）

- **否：只实现 bash，Windows 以 fake 满足 DoD**：与 ADR-0017 冲突，真实用户不可用。
- **否：job backend allow 未知 exec**：无文件系统边界，是安全假象。
- **否：审批用 loop 内阻塞 callback**：不能持久化、超时、取消、重放。
- **否：surfaces 直接调 reduce**：破坏单写者。
- **否：工具自己 subprocess**：env/sandbox/timeout/artifact 无法统一。
- **否：artifact fail-open 原文**：IO 局部失败会撑爆 prompt/event/checkpoint。
- **否：投影 identity**：内部结构会被 P7/P9 依赖，后续只能破坏兼容。
- **否：PermissionEngine 自带 mode**：与 PermissionCtx 双真相。

---

## 10. 提交粒度（每次 commit/push 均需用户明确许可）

```text
docs(adr): add p2 architecture decisions
feat(contracts): add approval process sandbox artifact inbox types
feat(state): version and roundtrip full permission checkpoint
feat(kernel): add run command inbox controller
feat(kernel): validate raw tool args before permission
feat(contracts): add shell analysis argument dictionaries
feat(kernel): add posix shell parser
feat(kernel): add powershell shell parser
feat(kernel): evaluate permissions from permission context
feat(kernel): enforce sandbox capability floors
feat(providers): add artifact store output budgets
feat(providers): add provider credential env safety
feat(providers): add harness owned process runner
feat(kernel): implement hitl tool lifecycle reduce
feat(capabilities): implement tool registry and per-run freeze
feat(capabilities): implement file tools
feat(capabilities): implement bash and powershell tools
feat(kernel): project event payloads with field whitelist
feat(surfaces): submit approval commands through inbox
test(integration): cover p2 lifecycle and platform dod
ci(guards): enforce inbox permission projection output boundaries
docs: record p2 deviations and license ledger
```

---

## 11. 开工前硬门

- [ ] ADR-0013-0019 已存在且 README 链接。
- [ ] design/01-04、HARD-CONSTRAINTS 与 ADR 口径无冲突。
- [ ] 本文 T0-T21 无 `TBD/类似上文/加适当处理` 占位。
- [ ] 每 Task 都有红测、命令、接口和完成判据。
- [ ] Windows 本机 PowerShell DoD 与 POSIX bash DoD 分开。
- [ ] 所有 fake 测试不得替代真实 process tree/permission state/protocol snapshot 验收。
- [ ] peer-scan 和 license ledger 已按能力记录。
- [ ] 用户确认后才允许开始 T1。

---

## 12. 收尾与活文档清单

- 回填 §13 “实际 vs 计划偏差”。
- ADR 若实现中改变，先更新 ADR 再改代码。
- `protocol/event.schema.json`、EventType、投影、TS codegen placeholder 同 PR。
- CHANGELOG P2 条目。
- `docs/delivery/P1-completion-report.md` 的下一步链接指向修订版 plan/02。
- license ledger。
- 平台 UNVERIFIED 清单。
- DoD 命令输出原文。

---

## 13. 实现偏差回填

当前本文件是**修订基线，尚未实现**。T0-T21 执行后在此记录：
1. 实际文件结构与本文差异；
2. parser 语料发现的未覆盖语法；
3. Job Object/seatbelt/bwrap 真机状态；
4. artifact GC 与 P10 交接；
5. approval timeout 的真实调度实现；
6. PowerShell 5.1 vs pwsh 7 差异；
7. 任何被 ADR 否决后又被现实证明必须调整的决策（必须新增/修订 ADR）。

---

## 13.1 已实现批次（2026-10-15 → 2026-10-16；分支 `feat/p2-foundation-hitl`，覆盖 T1-T13）

本轮**只做到 T1-T13 基础架构与 HITL**，T14-T21 尚未开始。以下为实现对本文的偏差与实况：

- **实现范围**：覆盖率非阻断基线 + T1 契约 + T2 versioned snapshot + T3 RunController/Command Inbox + T4 五层校验/raw args + T5 arg-key+Shell IR + T6 POSIX parser + T7 PowerShell parser + T8 PermissionCtx 纯引擎 + T9 SandboxDescriptor/capability floor + T10 ArtifactStore/输出预算 + T11 env safety + T12 ProcessRunner + T13 HITL 生命周期与 surfaces 只提交 Command。全量 `pytest` 246 passed，coverage 86%（branch），六守卫全绿，protocol 19 types lockstep。
- **PermissionDecision/Outcome 下沉 L0**：本文把 outcome 记在 kernel；实现改为 `contracts/permission.py` 放 `PermissionDecision`/`PermissionOutcome` 纯数据，避免 `capability_floor` 与 `permission_policy` import 环。属 additive，不改 wire 契约。
- **Windows Job Object 落地口径**：`AssignProcessToJobObject` 在子进程已继承其它 job 时返回 error 5。实现按本文 T9/ADR-0015 的“给不了围栏绝不静默裸跑”原则，Job 分配失败时**不谎报 full**，仍维持 partial descriptor，并在超时时用 `taskkill /F /T` 兜底杀进程树；真实 Windows PowerShell 父子进程超时清理有 `test_p2_process_timeout_tree.py` 实机验证（非 fake）。
- **approval 事件订阅依赖 durable store**：`approval_request` 是 durable 事件。`store=None` 的进程内总线只 fan-out live 帧，晚挂的订阅者会漏；外部审批（SSE/HTTP/CLI `_approve`）必须依赖 store 重放。测试据此改用带 store 的总线，符合生产语义。
- **permission warnings 尚未落 ToolCall**：capability floor 的 warning 目前只进入权限返回值与日志，未写进 `ToolCall.permission_warnings`/投影。留待 T17 字段级投影统一处理（不阻塞 T13 DoD）。
- **未做（本批次当时后置，现已由 §13.2 完成）**：T14 ToolRegistry、T15 文件工具、T16 bash/powershell 工具实例、T17 per-type protocol schema/投影、T18 surfaces 产品化端点细化、T19 resume 完整化、T20 新守卫扩规则、T21 端到端 DoD。`security-ci + pip-audit` 仍依 STRUCTURE `[P#]` 纪律待有对外攻击面后铺。

---

## 13.2 T14–T21 完成批次（2026-10-16；同分支 `feat/p2-foundation-hitl`）

本批次把 P2 做到**完整**（T14–T21），并回填相对本文的偏差与实况：

- **实现范围**：T14 `ToolRegistry` + L0 `RunToolSurface`（run 内冻结快照、description sanitize/长度界、误名候选提示，loop/surfaces 全面接入）；T15 文件工具（共享 `_paths` containment + `read`/`write`/`edit`/`apply_patch`/`ls`/`glob`/`grep`）；T16 `bash`/`powershell` 只经 `ctx.run_process`，并把真实 `ProcessRunner`/`ArtifactStore` 接进 `ToolContext`；T17 字段级 protocol schema（per-type `$defs`+`if/then`）+ per-type 投影白名单 + 守卫扩 per-type 覆盖；T18 `surfaces/approval.py`（receipt→HTTP 映射 + 唯一生命周期 TTY pump）+ CLI/HTTP 收口；T19 `resume_run` 经 reduce 闭合过期审批；T20 三条新守卫 + CI 平台分相 job（原计 matrix，因 job 级 `if` 看不到 `matrix` 上下文而拆为两 job，见下）；T21 端到端 DoD。
- **`RunToolSurface` 下沉 L0**：`freeze_for_run` 的快照类型放 `contracts/tool.py` 而非 L3，避免 L2 kernel import L3 capabilities（否则违反分层）；`edit_distance` 纯函数放 `contracts/common.py`。属实现分层修正，不改 wire 契约。
- **投影即白名单净化**：`project()` 从“仅滤内部类型”升级为“按 `EXTERNAL_EVENT_FIELDS` 逐类型只保留白名单键”。因此本文 §13.1 遗留的“permission warnings 未落 ToolCall/投影”仍成立且**不影响安全**——warning 属内部观测，本就不在对外白名单；把它写进 `ToolCall.permission_warnings` 并作为可选 additive 字段外发，是 UX 增强，明确后置到 P3（需先扩 ADR/契约再实现，遵循“先改 ADR 再改码”）。`ToolCall.sandbox_backend/confinement` 同理未在 `MarkToolRunning` 处填充（结果映射回账本留 P3 与 durable resume 一并做）。
- **surfaces 去具体 store**：T20 的 AST forbidden 规则要求 surfaces 不 import `state.reduce` 与 store 具体实现；据此把 `cli.run_once` 改为不注入具体 store（单次进程内 run 用内存总线），并**在 start drive 前同步挂订阅队列**，消除 store=None 时“晚订阅漏早期事件”的竞态。`http_sse.EventServer` 的 store 参数改为 `StorePort` 抽象（具体 SQLiteStore 由调用方/后续 L7 shell 注入）。
- **surfaces-no-reduce 只做 AST、不做 import-linter**：import-linter `forbidden` 是**传递**的，会误报 `surfaces → kernel → reduce`（合法的装配路径）。故该约束由 `check_layering_ast.py` 以“直接 import”语义机械强制（非传递），`.importlinter` 内以注释显式说明，不新增会假红的契约。
- **`check_output_budgets.py` 语义**：本文原把它列为“静态 payload 尺寸检查”。实现取更**可证伪**的口径：对真实有界原语做不变式检查（budget 全正、`preview_bytes` 含多字节边界不超限、超限走 artifact 不落内联），并 `--self-test` 证明“原语若失效即判红”。静态尺寸扫描易给出假信心，故不采用。
- **T20 “CI 矩阵”→ 两条分相 job**（本文 §T20/§R-F 写的是 matrix）：初版确实写成 `strategy.matrix.os` + job 级 `if` 区分平台，但 **job 级 `if` 表达式里 `matrix` 上下文不可用**，GitHub 因此判定整个 workflow 文件非法、**一条 run 都不创建**（本地 PyYAML 解析通过，给不了任何信号——这正是“本地绿≠对”的又一例）。现改为并列 `tests-posix` / `tests-windows` 两个 job，门控条件只用 `github.*`；代价是 steps 有意重复、需同步维护，换来的是固定 check 名与可验证的语法。
- **CI 首跑（Linux runner）暴露的两件真事**（本地 Windows 全绿都没报出来）：
  1. **`surfaces/approval.py` 线程回调 bug**：worker 线程的 `loop.call_soon_threadsafe` 写在 `try` 外面，审批超时后循环已关 → 迟到的按键从 daemon 线程抛 `RuntimeError: Event loop is closed`（Linux 上表现为 `PytestUnhandledThreadExceptionWarning`）。已改为 `_safe_settle()` 吞掉“循环已关闭”（丢弃迟到决策正是“超时即 deny”的语义），并补两条可证伪测试：一条直接测 `_safe_settle`，一条用 `threading.excepthook` 端到端重现（修复前本地就能复现同样异常）。
  2. **§5.2 POSIX 真机验收未达成**（不是测试写错，是能力缺口的真实反映）：`providers/sandbox.py` 里只有 Windows Job 的 `wrap_argv` 有实现，seatbelt/bwrap 是 `_UnimplementedSandbox`（raise），NullSandbox 也 raise——即 **POSIX 今天根本不能受控跑子进程**（ADR-0015 已声明后置）。原测试只按 `shutil.which("powershell")` 判平台，而 **GitHub ubuntu runner 装了 `pwsh`**，于是该 skip 的没 skip，又拿 `NullSandbox` 当真跑后端 → 4 条红。现改为**探测真能力**（`detect_sandbox().wrap_argv` 能不能用）：不能就明确 skip 并报原因；同时新增一条**所有平台都跑**的断言：后端包不住时必须回结构化 error 且绝不落到执行（fail-closed 本身被测试锁定）。另加两条 POSIX 分相“防回归”断言：一旦将来 wrapping 实现，它们会红，提醒同步放开真机验收与 ADR-0015。
- **T21 DoD 覆盖口径**：`test_p2_dod.py` 跑“全接线” loop（真实引擎 + capability floor + registry + inbox）验证头部判据（写 ask→allow 执行 / 写 ask→deny run 续跑 / full_auto 不越 exec 下限 / 敏感路径 full_auto 仍 deny / 非法参数 execute 前拒 / Windows 真机 PowerShell 删除需审批并真删）。§5.1 其余条目（并发 resolve×cancel、approval timeout 迟到拒绝、>1MiB artifact、schema required/type 越界、apply_patch 原子）已由 T4/T10/T13/T15 各自 integration/unit 覆盖，DoD 不重复堆叠，避免脆弱重言。
- **质量门实况**：
  - Windows 本机：`pytest` 317 passed / 5 skipped；branch coverage 85%；`ruff` clean；`lint-imports` 4 kept；`check_layering_ast`（66 files, 0 violation）+ self-test PASS；`check_protocol_schema` 19 types lockstep + self-test PASS；`check_output_budgets` self-test PASS；`check_secret_projection` self-test PASS；`verify_p0` ALL PASS；`check_thread_leak` self-test PASS。
  - GitHub CI（ubuntu-24.04，commit `0e63d66`）：首跑 **6 failed / 308 passed / 2 skipped**，即上述两件真事；修复后待重新验证。注意本地全绿挡不住这两个问题，**不要把“本地绿”当验收结论**。
- **仍标 UNVERIFIED（诚实，非缺陷）**：seatbelt/bwrap 在 Windows 的实机运行；**POSIX 受控子进程执行整体未实现**（§5.2 的 bash 真机验收因此只到“描述符/拒绝路径”层面，`rm -rf` 真实语料需在 Linux CI 跑通的项延到 wrapping 落地后）；真实 LiteLLM 网络端到端（无 key）；跨真实 socket 的 HTTP SSE 重连（此处为进程内 async transport，不冒充网络真跑）；多 agent/远程 Command inbox（P8/P9）；`security-ci + pip-audit` lane 待有对外攻击面时铺。
- **P2 达成判定**：§5.1 **Windows 主验收**的三条判据（危险操作触发 `ask`；`deny`/敏感路径不可越；非法参数被拒）已由**真实 shell/文件工具 + 真实审批闭环 + 端到端 DoD** 证明，不再只是 fake/内部测试层面。**§5.2 POSIX 真机运行未达成**（受控子进程的 POSIX wrapping 本身未实现，属 ADR-0015 已声明的后置项，不是漏测）。因此 P2 结论按平台分栏：**Windows = 达成，POSIX = 描述符/拒绝路径达成、真机执行待后续**。
- **TDD 流程偏差**：T1/T2 部分契约测试与实现同批提交，未逐个先跑红；从 T3 起严格 RED→GREEN，并为 T1/T2 补了可证伪的生命周期/snapshot/审批/幂等回归用例。
- **交付方式**：远端 main 已启用 “must be made through a pull request”；本批次全程走 `feat/p2-foundation-hitl` 分支逐任务 commit/push，未直推 main。

---

## 13.3 P2 审计闭环（2026-10-16；回应 `docs/audit/P2-review-2026-10-15.md`）

该审计给出 **NO-GO（有条件）**，列出 4 条阻断项。**我逐条亲手复现，4 条全部属实，无异议**；本轮已全部修复：

| 审计项 | 复现证据 | 修法 | 锁住它的测试 |
|---|---|---|---|
| #1 工具 panic 不兜底（C10/design/03 §8） | `loop.py` 仅策略处有 `except Exception`；`tool.execute` 裸奔 | `asyncio.wait_for` + `except Exception` → `ToolResult(status="error")`；BaseException（取消/中断）仍向上抛 | `test_p2_tool_fault_isolation.py::test_tool_panic_becomes_error_result_and_run_survives` |
| #2 `FinalizeRun` 不回填 open tool_use（C7/I1） | 实跑：终态后 `status=pending`、无 `tool_result` | failed/completed 均先 `_backfill_open_calls(note=…)` 并连续取号 | `test_reduce_finalize_pairing.py`（3 条，含 seq 唯一与“无 open 调用时不多产事件”） |
| #3 flag 簇不展开 → `sed -ni` 误判只读 | 实跑：`all_read_only=True, write=()`；写 `-n -i` 却正确 | `_flag_forms()` 把 `-ni`/`-i.bak`/`--in-place=x` 展开后比对写形式集合 | `test_bundled_short_flags_are_expanded` + `test_same_semantics_regardless_of_flag_spacing` |
| #4 `PermissionCtx.denylist` 假控制面（ADR-0014） | 实跑：denylist 含该路径时 `full_auto` 仍 `ALLOW` | 新增第 4 步 `_denylisted()`（`configured-denylist`），与内置默认取并集、不可取消默认 | `test_configured_denylist_denies_even_under_full_auto` 等 4 条 |

另主动修了审计列为“应修/建议”、但我认为不该拖到 P3 的项：

- **#7 deadline 武装**：文件工具不过 ProcessRunner，`spec.timeout_s` 以前只是记录——实测一个 `sleep(30)` 的只读工具跑满 30s 还报 success，即 §5-6 描述的“挂死工具卡住单写者循环”。现在 Harness 对**每个**工具武装 deadline。
- **`TIMED_OUT` 状态以前从不产生**（审计未点名）：`process_to_tool_result` 把超时压成 `"error"`，账本无法区分“被杀”与“业务失败”。现超时统一产 `status="timed_out"`；不新增第 20 个事件类型，投影为 `tool_completed{status:"timed_out"}`。
- **#5 三条未验分支**：`enforce_read_only`、`protected-root` 各有正反用例；**Windows 链跳由 UNVERIFIED 变实测**——用 `mklink /J` 真建 junction（只接受目录目标），containment 正确拒绝（注：`Path.resolve()` 在 Windows 确实跟随 junction，这是实测得到而非推定）。
- **#6 / E1**：`check_output_budgets --self-test` 以前只能自证绿；现注入“全文直通”的失效原语并断言必须报 problem（C15 的“守卫能判红”）。同时修了它自身 `_preview_bounds` 不接收注入参数的结构问题。
- **E2**：AST 守卫对 `from questor import surfaces` 这种包级导入漏判（module 只到 `questor` → layer None）；现已把导入名补成完整模块路径参与判定，self-test 加了对应红样本。
- **#5-5 `wrap_shell` 缺失**：design/03 §4 承诺的接缝现在存在于 `SandboxPort`，并在**所有**后端抛 NotImplemented；`test_sandbox_backends.py` 钉住“任何后端不得把 shell 串原样返回”。这不是空有签名：它把 ADR-0017 “不得把命令串拼回 shell 伪装成 argv” 变成可测的。
- **#5-3 / 死字段**：`parallel_safe`/`orchestrator`/`barrier` 逐项标 `NOT enforced until P5/P8`，`available` 字段明写“动态可用性唯一真源是 `Tool.available()`”；`envelope_for_text` 保留（guard 在用），但进程侧 preview 改用合法 UTF-8 前缀切法，不再在多字节字符中间开刀。
- **文档反向漂移**：把八步求值次序正式写进 `design/03` **§3.1**（带 `floor_applied` 对应表），修正四处引用不存在的 `§11 八步` 的 docstring，并在 **ADR-0014 追加“实现回填”**说明 denylist 曾经的假控制面与现在的确切语义（不回改原始决策）。

**复验结果（2026-10-16 Windows 本机）**：`pytest` **345 passed / 5 skipped**（新增 18 条测试）、branch coverage **87%**；`ruff` clean；`lint-imports` 4 kept；AST 66 files 0 violation 且 self-test 新增 package-import 项 PASS；`check_output_budgets` self-test 现在 `broken-primitive-caught=True`；其余守卫全绿。仍 UNVERIFIED：seatbelt/bwrap 实机、POSIX 受控子进程执行、真网络 LLM/ SSE、多 agent inbox、`security-ci + pip-audit`。

**落地**：上述修复连同全部 P2 工作（含 CI 触发器收窄 `ec0123f`）经 **PR #19 合入 main**（merge commit `1f5c171`，2026-10-16）。上文复验基线（345 passed / 87%）即合入时点的最终实测；后续演进自 P3 另起计划。
