# questor — Agent Contract

职责：产品组合根：网关、群策略、产品提示词与个人记忆应用。
不负责：引擎内核与能力域在 `src/questorharness`；本产品只装配，不实现回合循环。
公开入口：`__init__.py`。
拥有的数据：工作区、群注册表与产品会话存储布局。
允许依赖：只允许 `questorharness.api` 公开面（`product-uses-public-face` 契约）。
不变式：产品策略不下沉进 harness；harness 也永不 import 本产品。
禁止：不要 import `src/questorharness/engine` 内部模块或 `contracts`，只走 api 门面。
测试：`uv run pytest tests/integration/test_questor -q`
关键文件：`__init__.py`、`cli.py`、`workspace.py`
