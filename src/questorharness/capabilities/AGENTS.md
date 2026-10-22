# capabilities — Agent Contract

职责：模型可见的能力域（memory / policy / tools），每个子域一个叶子。
公开入口：`__init__.py` 只做包标记；公开面在子域门面（`memory/__init__.py`、`policy/__init__.py`、`tools/__init__.py`）。
拥有的数据：记忆文件与索引、权限模式、工具 schema 与注册表。
允许依赖：目标只有 `contracts`；当前仍有 `config` / `utils` / `engine` 存量依赖，Phase 2 收敛。
不变式：不 import `surfaces`；新代码不依赖 `ui` / `utils` / `services`；工具注册表只有一处。
禁止：不要跨子域 import 内部模块（只走子域门面）；不要再开新的平级类型桶。
测试：`uv run pytest tests/unit/test_tools tests/unit/test_memory tests/unit/test_permissions -q`
关键文件：`memory/__init__.py`、`policy/__init__.py`、`tools/__init__.py`
