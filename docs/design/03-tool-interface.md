# Questor 工具接口（L3 Capabilities + L0 Contracts）

> 承接分层(00)、状态(01)、事件(02)、红线 HARD-CONSTRAINTS C1/C4/C8/C9。设计文档，非实现。
> 一句话：**工具是 Harness 暴露给策略的能力**；策略只能"提议调用工具 X + 参数"，**校验/权限/沙箱/超时/记账全在 Harness**。

---

## 0. 边界（不可破）
- 策略层 **只发 `ProposeAction(tool, args)` 决策事件**，看不到也管不着沙箱、权限、执行细节（只知工具名 + 入参）。
- 工具 **不得** import provider/store/sandbox/UI（C1）；需读数据走 StorePort 接口，需写状态**只能返回结果由 Harness 记账**，绝不自建持久化旁路。
- 一切执行都在 Harness 工具路由里包一层：**校验 → 权限 → 沙箱 → 超时 → 账本**。

## 1. ToolSpec（L0 契约，注册进 L3）
```
ToolSpec {
  name, description,
  params: JSON-Schema,            # 参数结构，Harness 据此做①校验
  capability: readonly|write|exec|network|memory,  # 决定默认风险/沙箱档
  risk: low|medium|high,
  parallel_safe: bool = false,    # 默认可否并行
  available(): bool,              # 动态可用性（开关/凭据缺失时隐藏）
}
```
- **只增不改**：新增工具=加注册；改既有工具语义=契约变更（走评审）。

## 2. 工具实现接口（进程内）
```
Tool.execute(args, ctx) -> ToolResult
ToolResult { status: success|error|critical_error, result, display?, files?, artifact? }
```
- `ctx` 只给受控能力：workspace 根、`is_cancelled()`、`report_progress()`、`emit_event()`、StorePort 读接口——**不给裸向量库/文件系统越权句柄**。
- `result`=给模型；`display`=给人（卡片）。长任务须轮询 `is_cancelled()` 早退。

## 3. Harness 侧的两层校验（C8，别混）
1. **schema 校验**：按 `params` JSON-Schema 校参数形状/类型（非法→直接拒绝 Command）。
2. **权限判定**：capability+risk → 三态 `allow/ask/deny`（denylist 敏感路径不可覆盖）。
> 业务语义校验放**工具自身 execute 里**（纯函数），**不下沉沙箱**；沙箱只管"执行隔离"。

## 4. 沙箱适配（可插拔，对齐 C9/ADR-0006）
```
SandboxPort.wrap/exec(capability, cmd|fs|net) -> 受限执行
后端: macOS seatbelt / Linux bubblewrap / Windows 受限 / 兜底"受限执行+审计"
降级: 无后端时不崩，走最严默认 + 记 warning
```
`exec`/`network`/`write` 类工具必须过 SandboxPort；`readonly` 可直连但受 workspace 边界约束。

## 5. 工具账本（写回状态，见 01 §4）
每次调用由 Harness 生成/回填 `ToolCall{tool_call_id,status,result,display,permission_decision,elapsed,seq_*}`；取消/超时也要回填 error 记录保配对不变式。

## 6. 注册表与来源
- **内置工具**：进程内注册（P2 起步：`read/write/edit/ls/grep/glob/bash/apply_patch`）。
- **MCP 工具**（P5）：DeepCode 式"工具=独立 server 进程"，经适配器映射成同一 `ToolSpec`，走**同一套权限/沙箱门**。
- **热更**：工具集变更发 `tools_changed` 事件；一个 run 内**工具面冻结**（防模型看到中途变化的工具集，wuu 经验）。
- **按需注入**：工具多时用检索选 top-k 注入（可选，MCP 场景）。

## 7. 能力分类与默认策略（v1 建议）
| capability | 默认风险 | 默认决策 | 需沙箱 |
|---|---|---|---|
| readonly | low | allow（workspace 内） | 否 |
| write | medium | ask（首触/denylist 外） | 是(写边界) |
| exec | high | ask | 是 |
| network | medium | ask | 是 |
| memory | low | allow，**写经 Command→StorePort**（C4） | 否 |

## 8. 取消/超时
每个工具执行带 deadline；超时=一条 error `ToolResult`；取消经 `Cancel` Command（C7），Harness 回填未完成调用、不硬杀线程。

## 9. 待定（v0 后锁）
- 工具总数与 v1 白名单（对齐 ROADMAP P2）；`memory` 工具与 StorePort 的具体只读接口签名。
- MCP 适配放 P5，先留 `ToolSpec` 形状兼容，不提前实现进程隔离。

## 10. 落地补充（评审采纳）
- **T1 ctx.emit_event 只能发瞬态观测事件**（如 `tool_progress`）；**严禁工具内提交 Command / 改 Domain_State**。工具只能返回 `ToolResult`，状态写入由 Harness reduce 完成——否则绕开单写者。（写进 §2 ctx 注释）
- **T3 memory 写只发 `WriteMemory` 意图 Command**，经 reduce→StorePort；工具绝不直连向量库（C4）。
- **T4 沙箱降级 = 更安全不是更松**：无可用后端时，`exec`/high 风险工具**直接 deny**（绝不裸执行）；readonly/write 走最严边界 + warning。
- **T2 并行时序**：并行返回事件乱序属正常，客户端靠 tool_call_id 归组（见 02 §9）。

## 11. 评审增补（R04；均为落地细节，不动"策略只提议、校验/权限/沙箱/记账在 Harness"主轴）
- ToolSpec 补 `read_only`（权威布尔、缺 metadata=fail-closed）· `orchestrator`（嵌套/子代理、不参 gate）· `barrier`（同批独占、可占位）· `approval_mode`（MCP **只收紧不放宽**、unknown→deny）· `description max_chars` + untrusted sanitize。
- **§3 五层校验**：JSON 合法→schema→**arg-key 词典抽路径/命令/动作**（path/shell/action keys + apply_patch 结构化前缀，属 L0）→权限→业务（工具内、不下沉沙箱）。
- **§4 权限求值 8 步次序**：提权拦截（审批回复不带 mode 提权）→sensitive-path denylist（**realpath+expanduser+evalsymlink**、不可被 rules/mode 覆盖）→roots 内二次保护（mcp.json/config.json/.env）→read-only 上限→rules last-match-wins（二维通配）→mode 默认→`approval_policy=never` 时 ask 降 deny→MCP approval_mode 组合。`reason` 面向模型可读、给合法替代、不重试同 call。
- **shell 命令解析（阻断级）**：先按分隔符切段再 shlex；unwrap env/nohup/time 等 wrapper + 前置 VAR=；flag 簇展开(-rf/-r -f/--recursive)；redirect 目标单抽（NULL sink 除外）；只读命令的"写形态"flag 精确列；git 子命令白名单+写flag黑名单；**unparsable 在 read-only 判定=fail-closed deny、在 destructive screen=交沙箱**（沙箱才是边界）。
- **§4 沙箱**：`SandboxPort` 能力探针 `fences_writes/fences_network/isolates_process_tree`；后端**绝对路径/verified lookup** 防 PATH 注入；策略 **deny-default + 显式 regrant**；降级矩阵：`none`→exec/high **deny**、Windows job（无 write-fence）→write 加严走 ask；**wrap_shell/wrap_argv 分离**（禁 shell 串伪装 argv）。
- **新 §11 子进程 env**：exec/write 默认 scrub credential-shaped env（留 PATH/HOME/proxy）、`ctx.declare_env_passthrough` 显式转发（记 `ToolCall.env_scrubbed` 审计）、provider 凭据永不默认继承；MCP env 是白名单装配（另一方向）。
- **§6 MCP 进程模型 7 条**（一 server 一 task 拥 transport / child-task 独立 timeout / transport 三绑 / env 白名单 / 占位符 / plugin containment / stderr 落盘 / 上限256）+ 映射同一 ToolSpec + 命名 `mcp_<server>_<tool>` rules 按 **suffix** + **账本同源**（走同一路由写 ToolLedger，observability 补充非替代）。
- **§8 并行 gate + 取消四源**：reader 共享/writer 独占+饥饿保护/orchestrator 绕 gate；**返回顺序=模型请求顺序**（保配对）；**账本 settle 用脱离取消链的 ctx**；取消源 owner/invocation/user/observation-detach（断连后台续跑）；工具异常/panic 转 error ToolResult，KeyboardInterrupt/SystemExit 例外透传。
