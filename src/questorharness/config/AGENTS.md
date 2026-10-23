# config — Agent Contract

职责：设置模型与加载/保存（环境变量 > 配置文件 > 默认值）。
公开入口：`config/__init__.py`（`Settings` / `ProviderProfile` / `load_settings` / `save_settings`）。
拥有的数据：`Settings` 全部嵌套模型、provider profile 默认值、凭据解析辅助函数。
允许依赖：`contracts` + 标准库；不得 import `runtime` / `capabilities` / `engine` / `ui` / `plugins` / `surfaces`。
不变式：import 本包不读环境、不写文件；只有 `load_settings` / `save_settings` 才触达 IO。
已知债：`Settings.resolve_auth()` 在函数内惰性 import `providers.auth.*`（凭据解析仍挂在模型上）；settings 有 103 处 import，是最大共享依赖。
禁止：不要把新增业务状态塞进 `Settings`；不要在模块顶层加载配置。
测试：`uv run pytest tests/unit/test_config -q`
关键文件：`settings.py`、`schema.py`、`__init__.py`
