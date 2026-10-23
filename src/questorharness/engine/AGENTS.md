# engine — Agent Contract

职责：编排层：把会话历史、工具注册表、权限、上下文压缩与模型调用串成一轮循环。
不负责：工具能力本体在 `src/questorharness/capabilities/tools`，宿主装配在 `src/questorharness/bootstrap`。
公开入口：`__init__.py`（`QueryEngine`）；`query.py`（`run_query`）；产品只通过 `questorharness.api` 使用。
拥有的数据：单轮运行上下文（`QueryContext`）、工具调用中间态、成本累计；不持久化。
允许依赖：`contracts` / `capabilities` / `providers` / `runtime` / `config`；这是唯一允许同时组合这四层的包。
不变式：永不 import 产品包；工具执行必须经 `capabilities/tools/base.py::ToolExecutionContext`，端口在这里注入。
已知债：`query_engine.py` 直接 import `providers.llm`；`tool_execution.py` 在模块级实例化 `runtime.services`；`query.py` 仍同时承担压缩触发与流事件编排。
禁止：不要在此写产品策略（群规则、通知）；不要新增对 `ui` 的依赖。
测试：`uv run pytest tests/unit/test_engine tests/unit/test_commands -q`
关键文件：`query.py`、`tool_execution.py`、`tool_metadata.py`、`vision.py`、`context.py`
