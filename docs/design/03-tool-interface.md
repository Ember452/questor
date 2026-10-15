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
