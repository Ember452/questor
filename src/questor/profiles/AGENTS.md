# profiles（产品侧）— Agent Contract

职责：**形态数据**。每个 `*.yaml` 描述一种产品形态（人设/模型/技能目录/工具面/界面能力位）；当前是 `coding`（默认）与 `personal`（首批 declared）。
不负责：解析与校验（在 `questorharness.profiles`）、形态切换（宿主/CLI）、界面实现。
公开入口：无 Python 符号（数据包，`__all__` 为空是刻意的）；消费方式是 `load_profile(Path(__file__).parent, profile_id)`。
拥有的数据：`coding.yaml` / `personal.yaml`——这是形态的唯一真源，改它等于改产品行为。
允许依赖：不 import 任何东西（纯数据）。
不变式：`page id` 一旦进入 git 只增不改名、不删除（下线用 `absent`）；`ui.capabilities` 只能是 `ready|declared|absent`；工具面差异用 `denied_tools` 表达，`allowed_tools` 只用于无副作用的显式放行；工具名必须取自 `create_default_tool_registry()` 的 39 个真实名字。
禁止：不要在这里写代码分支或导入引擎；不要把 `personal` 的工具面改成编码面。
测试：`uv run pytest tests/unit/profiles tests/unit/test_permissions/test_profile_tool_surface.py -q`。
关键文件：`coding.yaml`、`personal.yaml`
