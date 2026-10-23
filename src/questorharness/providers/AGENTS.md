# providers — Agent Contract

职责：引擎适配器（LLM 客户端、认证、沙箱、MCP transport）。
公开入口：各子包门面 `llm/__init__.py`、`auth/__init__.py`、`sandbox/__init__.py`、`mcp/__init__.py`。
拥有的数据：供应商凭据句柄、sandbox 会话、MCP 连接与配置。
允许依赖：`contracts` + `platform`（最底层，允许）；当前仍有 `config` 存量依赖，后续波次收敛。
不变式：不 import `capabilities` / `runtime` / `surfaces` / `engine`；不在适配器里写产品策略。
禁止：不要把 MCP transport 塞回 `capabilities/tools`；不要让装配层之外的模块持有本包单例。
测试：`uv run pytest tests/unit/test_api tests/unit/test_auth tests/integration/test_sandbox tests/integration/test_mcp -q`
关键文件：`llm/__init__.py`、`auth/__init__.py`、`sandbox/__init__.py`、`mcp/__init__.py`
