# ADR-0018: 子进程执行由 Harness 的 ProcessRunnerPort 拥有，工具不得直接 spawn

- 状态：✅（2026-10-15）
- 背景：若 `bash`/`powershell` 工具直接调用 `asyncio.create_subprocess_exec`，则 SandboxPort 包装、env scrub、per-tool deadline、进程树清理、输出预算与取消只能散落在各 capability 实现中；测试也会误把 fake subprocess 当成 Harness 已覆盖。
- 决策：
  - 新增 `ProcessRunnerPort`（L0 契约，L5/L2 实现）：工具只提交结构化 `ProcessRequest`，由 Harness 统一执行。
  - `ToolContext.run_process(request)` 是 shell/外部程序唯一出口；工具不得 import subprocess、asyncio process API 或具体 Sandbox adapter。
  - ProcessRunner 固定负责：解析 sandbox argv、credential env scrub、显式 env passthrough、cwd 校验、timeout、Job Object/killpg 进程树清理、stdout/stderr 捕获、artifact 落盘、取消轮询和结构化结果。
  - provider credential 与非 Provider 但 credential-shaped 环境变量默认全部擦除；`declare_env_passthrough` 只能转发经 settings 显式允许且非 Questor/LiteLLM 管理凭据的变量。
  - 沙箱 launcher 失败、包装失败或无法提供请求的 confinement 必须返回明确失败；绝不回退为未包装执行。
- 后果：shell、MCP 进程、未来子 agent 和测试 fake 共用一个执行边界；代价是多一层 Port，但这是防止安全机制漂移的必要结构。
- 备选（被否）：
  1. 工具直接 spawn、loop 只 timeout：权限/沙箱/审计无法保证全覆盖 → 否。
  2. 把 SandboxPort 塞进 ToolContext：L3 可间接依赖具体 backend，且 env/timeout/artifact 仍散落 → 否。
  3. 只测试 fake subprocess、不测真实进程树：无法兑现 Windows `powershell` DoD → 否。
- 关联：ADR-0015、ADR-0017、ADR-0019；HARD-CONSTRAINTS C1/C4/C8/C10；[`../design/03-tool-interface.md`](../design/03-tool-interface.md) §2/§8/§11。
