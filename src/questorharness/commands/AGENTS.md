# commands — Agent Contract

职责：slash 命令注册与应用层分派。
不负责：能力实现与状态变更在 `src/questorharness/capabilities`，CLI 参数解析在 `src/questorharness/cli.py`。
公开入口：`create_default_command_registry()`、`CommandRegistry`、`CommandContext`、`CommandResult`、`lookup_skill_slash_command()`。
拥有的数据：命令名、别名、描述、handler 及其注册顺序。
允许依赖：`contracts` / `capabilities` / `providers` / `runtime` / `engine`；这是应用层，允许组合。
不变式：注册顺序是唯一真相——`registry.py` 的 `register_builtin_commands()` 逐行列出族的调用顺序；`help_text()` 按名字排序，`list_commands()` 保留注册顺序；别名与主命令共享同一个 `SlashCommand` 实例。
禁止：不要调整族与族之间的相对顺序；不要在族模块里 import `commands.registry`（`command-families-are-leaf` 契约会红）；不要把 handler 塞回 `registry.py`（`check_layout.py` 限它 250 行）；不要绕过 `CommandResult` 返回裸字符串。
测试：`uv run pytest tests/unit/test_commands -q`（含 `test_registry_snapshot.py` 的 help/order/alias 三条快照）
关键文件：`registry.py`（107 行，只管顺序）、`types.py`（含 `CommandRegistry`）、`families/`（一族一文件，≤600 行）、`helpers.py`、`memory_commands.py`
