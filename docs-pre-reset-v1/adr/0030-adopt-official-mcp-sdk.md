# ADR-0030: MCP 客户端采用官方 `mcp` Python SDK（stdio transport）

- 状态：✅（2026-10-17）
- 背景：P5 要接入 MCP（挂一个 server 列出并调用其工具，`docs/plan/05-p5-skills-mcp.md` DoD②）。
  MCP 是 JSON-RPC 2.0 over stdio/SSE 的协议：握手（`initialize`/`initialized`）、`tools/list`、
  `tools/call`、会话与取消语义都有规范要求。参考集里 hermes / DeepCode / OpenManus / CowAgent /
  autogen / crewAI **全部使用官方 `mcp` Python SDK**（`from mcp import ClientSession, StdioServerParameters`、
  `mcp.client.stdio.stdio_client`），没有一家用手写 JSON-RPC 扛生产。
- 决策：**在 `capabilities/mcp` 引入并使用官方 `mcp` SDK 作为 MCP 客户端**（stdio transport），
  而非手写 JSON-RPC 协议层。依赖只在 `capabilities/mcp/`（L3）内 import；`pyproject.toml` 增加
  `mcp` 依赖 + `uv.lock` 锁定，**与首个真连接提交（C12 transport 生命周期）同条落地**（不预先塞未用依赖）。
- 后果：
  - 正面：协议正确性（握手/取消/error 形状）由 SDK 承担，代码量小、与生态一致、可复用 reference 的改造经验。
  - 需持续守：
    1. **凭据/env**：`mcp.json` 里 server 的 env 值属机密；启动子进程一律经 `providers/env_safety.py`
       （`scrub_environment`/`build_child_env`），provider 凭据即使被 declare 也抛错（C17）；env 值不入事件/日志（C20）。
    2. **子进程句柄/线程**：SDK 的 stdio_client 起真子进程 + reader 任务——测试必须在结束时
       **await/取消 reader、退出 AsyncExitStack、关 transport**，否则本仓 autouse 的**非守护线程泄漏守卫**
       （`tests/conftest.py`）会判红；这也是 DoD② 真 stdio roundtrip 的硬约束。
    3. **不污染 observability**：MCP 工具描述/结果只走账本→投影白名单；SDK 若自带 logging/emit，
       其记录按 C20「非 `questor.*` 来源门」处理，第三方 sink 由引入它的适配器侧治理（仿 litellm handler 摘除先例）。
    4. **传输边界**：SDK 只管 transport/protocol；权限/沙箱/账本/配对关卡仍在 Harness（C4/C8/C19），
       MCP 工具必须经 `ToolRegistry`→`_handle_tool_call`→`_execute_tool` 派发，**不得在 kernel 直接持有 SDK 句柄**。
- 备选（被否）：
  1. **手写 stdio JSON-RPC**：否——协议细节（初始化握手/进度令牌/取消/error 映射）自己扛，漂移与兼容风险高、
     代码量大，且与全部参考实现背道而驰；违背"复用已验证实现"（AGENTS §4.5）。
  2. **P5 先不做真连接、只留 stub**：否——DoD② 要求真列出并调用远程工具，且 MCP 是"第一个从进程外引入错误源"
     的 Phase（ADR-0027），必须真跑才能验 C19/C20 守卫；stub 会把核心风险推到未验证态。
- 关联：`docs/plan/05-p5-skills-mcp.md` §2（T1–T7/T14/T15）、DoD②/③/⑤；HARD-CONSTRAINTS C17/C18/C19/C20、
  C4/C8/C13；ADR-0018（Harness-owned process runner）、ADR-0028（配对关卡）；AGENTS §4.5/§5.6（复用+许可）。
  许可：`mcp` SDK 为 MIT。改造处文件内标 provenance、CHANGELOG 注明。
