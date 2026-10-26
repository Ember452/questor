"""`keymap.py`：声明了就必须有行为（同 ADR-0005 §4 判例）。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal import keymap


def test_build_returns_bindings_with_ctrl_c_and_ctrl_l() -> None:
    bindings = keymap.build()
    assert bindings is not None
    keys = {binding.keys for binding in bindings.bindings}
    assert ("c-c",) in keys
    assert ("c-l",) in keys


def test_build_registers_the_menu_keys_when_a_menu_is_given() -> None:
    """菜单键必须是真绑定（否则 ↑↓ 永远只动光标、菜单不会走）。"""

    from prompt_toolkit.keys import Keys

    class _Menu:
        active = False

    bindings = keymap.build(_Menu())
    assert bindings is not None
    keys = {binding.keys for binding in bindings.bindings}
    # prompt_toolkit 把 tab/enter 归一成 ControlI/ControlM；按枚举成员比对。
    for expected in (
        Keys.Up,
        Keys.Down,
        Keys.ControlP,
        Keys.ControlN,
        Keys.ControlI,
        Keys.ControlM,
        Keys.Escape,
    ):
        assert (expected,) in keys


def test_build_is_optional_dependency_safe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """没有 prompt_toolkit 时返回 None，让输入层回退裸 input。"""

    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("prompt_toolkit"):
            raise ImportError("absent")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert keymap.build() is None
