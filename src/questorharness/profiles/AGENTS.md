# profiles — Agent Contract

职责：从磁盘读取 profile bundle（`profile.yaml`）并做 fail-closed 校验。`model.py` 定义只读数据形状，`loader.py` 负责解析、三态能力位校验与未知键拒绝。
不负责：形态的**选择**（由宿主/CLI 传入 `profile_id`）、界面渲染、工具执行；bundle 的**内容**属于产品侧（`src/questor/profiles/`）。
公开入口：`ProfileInfo` / `ProfileError` / `list_profiles` / `load_profile` / `boundary_map`（见 `__init__.py`，并经 `questorharness.api` 再导出）。
拥有的数据：无持久状态；每次调用都从磁盘重读，避免进程内缓存掩盖编辑。
允许依赖：只依赖标准库与 `yaml`；不 import 其它引擎层（本包是叶子）。
不变式：未知顶层键、非法 `ui.capabilities` 取值、缺失 `name` 一律抛 `ProfileError`；`load_profile` **不回退**到默认形态；`allowed_tools` 是显式放行、`denied_tools` 是硬拒（两者不得交集）。
禁止：不要在此包内做形态分支判断；不要把产品语义（page id、工具名单）写进 loader。
测试：`uv run pytest tests/unit/profiles -q`；消费端见 `tests/unit/test_permissions/test_profile_tool_surface.py`。
关键文件：`model.py`（数据形状）、`loader.py`（解析与校验）
