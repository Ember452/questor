# plugins — Agent Contract

职责：插件发现、清单解析与插件提供的工具 / 命令 / 技能装配。
不负责：技能加载与注册表在 `src/questorharness/capabilities/skills`，工具注册表在 `src/questorharness/capabilities/tools`。
公开入口：`__init__.py`。
拥有的数据：插件目录扫描结果与已解析的插件清单。
允许依赖：`capabilities` + `contracts` + `platform`；`plugins-stay-an-extension-layer` 禁止其 import 上层。
不变式：插件只作为扩展层被装配；`capabilities` 经 `PluginSource` 端口取插件，不 import 本包。
禁止：不要在插件层引入回合或权限逻辑；不要让 capabilities 反向 import 本包。
测试：`uv run pytest tests/unit/test_plugins -q`
关键文件：`__init__.py`、`loader.py`、`types.py`
