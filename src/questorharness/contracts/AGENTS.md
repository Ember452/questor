# contracts — Agent Contract

职责：全仓共享词表与 Port；不承载业务实现。
公开入口：按模块导入（`contracts.task` / `contracts.subagent` / `contracts.hooks` / `contracts.domain.*`），包级 `__init__.py` 只做标记。
拥有的数据：消息与事件模型、任务/子代理/hook 词表、usage、工具输出阈值。
允许依赖：标准库与 pydantic；不得 import `capabilities` / `runtime` / `engine` / `surfaces` / `ui`。
不变式：跨层类型只允许有一个定义处；新增词表优先放这里，而不是由消费方定义。
已知债：`io` / `locking` / `network` / `tokens` / `tool_outputs` 仍是共享实现；`shell.py` 依赖 `providers.sandbox`、`session_storage.py` 依赖 `config`，这两条边必须在分层守卫开启前销账。
禁止：不要把实现、配置解析或产品策略搬进 contracts；不要在这里起进程或读环境。
测试：`uv run lint-imports` + `uv run pytest tests/unit/test_tools tests/unit/test_engine -q`
关键文件：`task.py`、`subagent.py`、`hooks.py`、`domain/message.py`
