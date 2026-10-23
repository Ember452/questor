# commands — Agent Contract

职责：slash 命令注册与应用层分派。
公开入口：`create_default_command_registry()`、`CommandRegistry`、`CommandContext`、`CommandResult`、`lookup_skill_slash_command()`。
拥有的数据：命令名、别名、描述、handler 及其注册顺序。
允许依赖：`contracts` / `capabilities` / `providers` / `runtime` / `engine` / `bootstrap`；这是应用层，允许组合。
不变式：注册顺序是唯一真相；`help_text()` 按名字排序，`list_commands()` 保留注册顺序；别名与主命令共享同一个 `SlashCommand` 实例。
禁止：不要调整族与族之间的相对顺序；不要在 handler 里直接 import `bootstrap` 之外的新层；不要绕过 `CommandResult` 返回裸字符串。
测试：`uv run pytest tests/unit/test_commands -q`（含 `test_registry_snapshot.py` 的 help/order/alias 三条快照）
关键文件：`registry.py`、`types.py`、`helpers.py`、`memory_commands.py`
