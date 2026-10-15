# Questor 工具接口（L3 Capabilities + L0 Contracts）

> 承接分层(00)、状态(01)、事件(02)、红线 HARD-CONSTRAINTS C1/C4/C8/C9/C16-C18。
> 一句话：**工具是 Harness 暴露给策略的能力**；策略只能"提议调用工具 X + 参数"，**校验/权限/沙箱/进程执行/超时/记账全在 Harness**。
> P2 关键决策由 ADR-0013-0019 固定；本节是实现契约，不再保留互相矛盾的“工具可自己 spawn / fail-open 原文”旧口径。

---

## 0. 边界（不可破）
- 策略层 **只提交 `ProposeAction(tool, args)`**，看不到也管不着沙箱、审批 future、Store、UI。
- 工具 **不得** import provider/store/sandbox/UI（C1）；不得调用 `subprocess`、`asyncio.create_subprocess_*` 或具体 Job/seatbelt adapter（ADR-0018）。
- 工具只返回有界 `ToolResult`；状态写入、事件、审批、artifact 落盘均经 Harness。
- L6 surfaces 只向 RunCommand Inbox 提交 Command，不能直接 reduce（ADR-0013/C16）。

## 1. ToolSpec（L0 契约）
```python
ToolSpec(
    name, description,
    params: JsonObject,                  # JSON Schema；Harness 第一层校验
    capability: readonly|write|exec|network|memory,
    risk: low|medium|high,
    read_only: bool,                     # 唯一权威；未知一律 fail-closed
    timeout_s: float | None,             # None → Budget 默认；<=0 注册期拒绝
    available: bool,
    parallel_safe=False,                 # P2 仍不开放并行
    approval_mode: str | None,           # MCP 只收紧、unknown→deny
    orchestrator=False, barrier=False,
    description_max_chars=2000,
)
```
- description 少于 20 字或超上限、控制字符/不可见注入，注册前 sanitize；退化到工具名。
- 改既有工具语义必须走 design/ADR 评审；新增工具只是 registry 数据。

## 2. Tool、ToolContext 与 ProcessRunner
```python
Tool.execute(args: JsonObject, ctx: ToolContext) -> ToolResult
```
`ToolResult` 保持 `status/result/display/files/artifact/error`。新增字段只可 additive。

`ToolContext` 至少提供：
```python
tool_call_id: str
workspace_root: Path
cwd: Path
is_cancelled() -> bool
report_progress(message) -> None
emit_progress(payload) -> None
declare_env_passthrough(name) -> None
async run_process(ProcessRequest) -> ProcessResult
async put_artifact(bytes, kind, media_type) -> ArtifactRef
```
- `run_process` 是 shell/外部程序唯一出口；由 L2 构造、L5 adapter 实现。
- `put_artifact` 只接收受控 kind/bytes，工具不能拼任意路径。
- Provider/LiteLLM/Questor 管理凭据永不默认继承；声明透传也要再过滤（ADR-0018）。

## 3. Harness 五层校验（严格次序）
1. **args 可解析性**：provider 工具参数必须保留 bounded `raw_input`；不可解析直接 `args_status=invalid`、有界摘要/错误，绝不伪装成 `{}`。
2. **JSON-Schema**：required/type/additionalProperties/数值范围；保守 coerce 只在无歧义时。
3. **arg-key 词典**：path/command/action/patch prefix/redirect/pipeline 抽成结构化事实；词典数据在 L0。
4. **PermissionCtx + capability floor**：敏感路径与 OS 能力先于 mode。
5. **业务校验**：工具 execute 内完成，不下沉沙箱。

## 4. SandboxDescriptor 与 ProcessRequest
`SandboxPort` 不再只返回三个裸布尔：
```python
SandboxDescriptor(
    backend: seatbelt|bwrap|job|none,
    confinement: full|partial|none,
    fences_writes: bool,
    fences_network: bool,
    isolates_process_tree: bool,
    workspace_profile: JsonObject,
    executable_path: str | None,
    limitation: str,
)
wrap_argv(...) / wrap_shell(...) / describe()
```
`wrap_shell` 与 `wrap_argv` 仍严格分离；argv 数组不得拼回一个 shell string 执行。

`ProcessRequest(argv, cwd, capability, timeout_s, declared_env, output_limit)` 只允许绝对程序路径；Job Object、seatbelt、bwrap 包装失败即结构化 error，绝不 passthrough。

## 5. Capability floor（高于 mode，ADR-0015）
| backend/confinement | read-only exec | 其他 exec | write | network |
|---|---|---|---|---|
| seatbelt/bwrap **full** | 可 allow（仍过 rules/risk） | 正常 ask/deny | workspace 内可 allow/ask | ask/deny |
| Windows **job/partial** | 只有 parser 证明无写/无重定向/无动态才可 allow | **至少 ask**；full_auto 不可降 | **至少 ask + containment + warning** | deny |
| **none** | deny | deny | **ask + containment + warning**，full_auto 不可降 | deny |

- 敏感路径和 protected roots 在 floor 前 deny，任何 mode/rule 不可覆盖。
- `approval_policy=never` 与非交互 stdin 只把 ask 降 deny，不能把 deny 升 ask。
- unknown/unparsable/dynamic command 永远不得归类 read-only。

## 6. 平台 Shell 与注册表（ADR-0017）
- P2 一等内置：`read/write/edit/apply_patch/ls/glob/grep/bash/powershell`。
- `bash` 仅当真实 POSIX shell 存在时可用；Windows 无 bash 时**不冒充执行 PowerShell/cmd/WSL**。
- `powershell` 在 Windows 上探测 PowerShell 5.1；存在 pwsh 时优先 pwsh，但 tool name 保持 `powershell`。
- 两工具共享 dialect-tagged `ShellAnalysis` IR，解析器各自维护；program、args、redirects、pipeline、write paths、dynamic flags 必须结构化。
- Registry 实现 `register/unregister/has/get/list_available/definitions/freeze_for_run`；run 起点冻结 surface，热更只影响下一 run。

## 7. ToolCall 生命周期（ADR-0016）
```text
pending
  → args/schema invalid: error（不 execute）
  → MarkToolValidated: validated
  → permission deny: denied
  → permission ask: awaiting_approval
       ├ request_id allow → ready → MarkToolRunning → running
       ├ request_id deny/expired/cancelled → denied/cancelled
       └ 重复同 decision no-op；异 decision rejected
  → permission allow: ready → MarkToolRunning → running
running
  → success/error/critical_error/timed_out/cancelled
```
`tool_started` 只能在 pending/ready→running 的 reduce 中产生；不得裸发事件。

## 8. 取消、超时与 settle
- 有效 timeout：`ToolSpec.timeout_s ?? Budget.tool_default_timeout_seconds ?? 300`；0/负值注册期拒绝。
- 每个工具由 ProcessRunner 武装 deadline；超时产 `TOOL_TIMEOUT` 结构化 ToolResult，并杀进程树。
- approval timeout 默认 300s，None 仍取安全默认；到期只能过期同 request_id 的 pending request。
- settle 必须使用脱离取消链的执行上下文：外层 Cancel 后仍能把最终/取消结果经 Command 落账。
- KeyboardInterrupt/SystemExit 透传；普通工具 panic 转 error，不崩 run。

## 9. 输出预算与 artifact（ADR-0019）
- 默认：model result 16 KiB、human display 64 KiB、stdout/stderr 各 1 MiB；配置只可更严或 additive 调整。
- 超预算由 ArtifactStorePort 内容寻址保存；模型侧返回 `{kind,artifact_ref,content_sha256,total_bytes,preview,continuation}`。
- artifact 写失败：返回 error + 已捕获有界 preview；禁止原文 fail-open 进状态/事件/prompt。
- 事件 payload 与 checkpoint 只保存有界摘要/ref；全文不进 `event_log`。

## 10. 投影（ADR-0019）
- `project()` 从 identity 升为 per-type field whitelist；所有 external data 有长度与类型约束。
- 默认不外发：完整 args、secret/env scrub 明细、artifact 绝对路径、内部 reason、provider 专有 state。
- `hidden` 只控制 Kernel 内部订阅者可见性，不是 wire Envelope 字段。
- 外部 schema 单真源；CI 校验 type 集合 + 每 type required fields。

## 11. 被否与反例
- 否：工具直接 spawn，以便“少一层 Port”。会让 env/sandbox/timeout/artifact 散落且无法测。
- 否：backend 缺失时 passthrough。缺能力只能 deny/ask floor。
- 否：POSIX parser 处理 PowerShell。语法和 alias 不同，必然产生错误 allow。
- 否：full_auto 覆盖 write capability floor。审批模式不能伪造 OS 围栏。
- 否：artifact 写失败回退全文。局部 IO 故障不应升级为上下文/内存故障。
