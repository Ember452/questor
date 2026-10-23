# runtime — Agent Contract

职责：有状态运行时服务（session / services / tasks / hooks / autopilot / coordinator / swarm / bridge）。
不负责：工具实现与能力策略在 `src/questorharness/capabilities`，协议词表在 `src/questorharness/contracts`。
公开入口：各子包 `__init__.py`；`services/__init__.py` 提供 `default_task_runtime` / `default_subagent_runtime`。
拥有的数据：后台任务与输出文件、hook 注册与执行、团队与 agent 生命周期、worktree、bridge 会话。
允许依赖：目标只有 `contracts` 与同层 runtime；当前仍存在少量惰性边，见“已知债”。
不变式：capabilities 只通过 `capabilities/ports.py` 反向拿服务；runtime 不持有产品策略。
已知债（逐条销账）：`hooks/executor.py` → `providers.llm`/`providers.sandbox`（顶层）；`swarm/in_process.py` → `engine.query`（函数内，环）；`swarm/permission_sync.py` → `capabilities.policy`（函数内）；`autopilot/service.py` → `capabilities.schedule`（函数内；agent 执行走 bootstrap 注入的 runner，已无 ui 依赖）；`coordinator/agent_definitions.py` → `plugins.loader`（函数内）。
禁止：不要把 `engine/` 或 `commands/` 搬进来——循环是编排层，命令分派是应用层（见 STRUCTURE.md §8）。
测试：`uv run pytest tests/unit/test_services tests/unit/test_hooks tests/integration/test_swarm -q`
关键文件：`tasks/task_manager.py`、`hooks/executor.py`、`services/task_runtime.py`、`services/subagent_runtime.py`、`output.py`（引擎消息 → 终端摘要，宿主共用）
