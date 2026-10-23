# capabilities — Agent Contract

职责：模型可见的能力域（context / memory / policy / tools / skills），每个子域一个叶子。
公开入口：`__init__.py` 只做包标记；公开面在子域门面（`memory/__init__.py`、`policy/__init__.py`、`tools/__init__.py`）。
拥有的数据：记忆文件与索引、权限模式、工具 schema 与注册表、技能定义与 bundled 内容。
允许依赖：`contracts` + `platform`（最底层，允许）；当前仍有 `config` 存量依赖，后续波次收敛。
不变式：不 import `runtime` / `providers` / `surfaces`；任务、子代理、hook 只通过 `ports.py` 注入；工具注册表只有一处。
禁止：不要跨子域 import 内部模块（只走子域门面）；不要再开新的平级类型桶。
测试：`uv run pytest tests/unit/test_tools tests/unit/test_memory tests/unit/test_permissions -q`
关键文件：`ports.py`、`context/prompts/context.py`、`memory/__init__.py`、`policy/__init__.py`、`tools/__init__.py`、`skills/__init__.py`
