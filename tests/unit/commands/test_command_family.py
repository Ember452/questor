"""命令族打标（plan03 T18）：`register_builtin_commands` 逐族写入 family。"""

from __future__ import annotations

from questorharness.commands.registry import create_default_command_registry

EXPECTED_FAMILIES = {
    "session",
    "memory",
    "workspace",
    "account",
    "skill",
    "config",
    "plugin-management",
    "policy",
    "model",
    "appearance",
    "diagnostics",
    "git",
    "project",
    "settings",
    "agents",
}


def test_every_builtin_command_carries_a_family() -> None:
    registry = create_default_command_registry()
    commands = registry.list_commands()
    assert commands, "注册表不该为空"
    missing = [command.name for command in commands if not command.family]
    assert missing == [], f"没有族名的命令：{missing}"


def test_known_families_are_present() -> None:
    registry = create_default_command_registry()
    families = {command.family for command in registry.list_commands()}
    assert EXPECTED_FAMILIES <= families


def test_family_survives_aliases() -> None:
    """别名与原命令是同一实例，族名不会因为别名而丢。"""

    registry = create_default_command_registry()
    alias_command = registry.lookup("/quit")
    assert alias_command is not None
    command, _args = alias_command
    assert command.family == "session"


def test_set_family_stamps_unknown_commands() -> None:
    from questorharness.commands.models import CommandRegistry, SlashCommand

    async def handler(_args: str, _context: object) -> object:  # pragma: no cover - 不入执行路径
        raise AssertionError("not used")

    registry = CommandRegistry()
    registry.set_family("custom")
    command = SlashCommand(name="demo", description="d", handler=handler)  # type: ignore[arg-type]
    registry.register(command)
    assert command.family == "custom"
    # 已显式声明族名的命令不被覆盖
    explicit = SlashCommand(name="demo2", description="d", handler=handler, family="own")  # type: ignore[arg-type]
    registry.register(explicit)
    assert explicit.family == "own"
