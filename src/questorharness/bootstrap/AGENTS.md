# bootstrap — Agent Contract

职责：进程装配。`runtime.py` 是组合根（读配置、建引擎、装工具、连 provider），`hosts/` 是进程宿主（stdio REPL、React backend、前端启动器）。
公开入口：`build_runtime` / `start_runtime` / `close_runtime` / `handle_line` / `RuntimeBundle`；宿主侧 `hosts/__init__.py` 导出 run_repl / run_print_mode，`hosts/backend_host.py` 导出 run_backend_host。
拥有的数据：`RuntimeBundle`（引擎 + 设置 + app state + 命令表 + 会话后端）、宿主进程的输入输出循环。
允许依赖：本层是依赖秩最高的一层，可以 import 任何下层；反向不允许——`surfaces-are-thin` 契约禁止 `surfaces` import 本包。
不变式：宿主不直接构造引擎，只调 `build_runtime`；autopilot 需要跑一轮对话时由本包注入 runner（`configure_runtime_runner`），未注入时 fail-closed 抛错。
禁止：不要把业务策略写进 `runtime.py`（它只做装配）；不要在 `hosts/` 里 import 其他层的**私有**名字（`_foo`）——需要时先把函数下沉到 `runtime/` 或 `contracts/`。
测试：`uv run pytest tests/unit/test_ui tests/unit/test_runtime -q`
关键文件：`runtime.py`（组合根）、`hosts/app.py`（模式分派）、`hosts/backend_host.py`（React stdio 协议）、`hosts/coordinator_drain.py`（协调者收尾）
