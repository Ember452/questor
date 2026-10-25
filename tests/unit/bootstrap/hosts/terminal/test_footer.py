"""`footer.py` 的契约：可选字段缺失渲染 `—`，状态栏把 status_bar 接活。"""

from __future__ import annotations

from rich.console import Console

from questorharness.bootstrap.hosts.terminal import footer, strings


def _plain(renderable: object) -> str:
    console = Console(
        width=120,
        color_system=None,
        legacy_windows=False,
        safe_box=True,
        emoji=False,
        record=True,
        file=None,
    )
    console.print(renderable)
    return console.export_text()


def test_missing_optional_fields_render_a_visible_placeholder() -> None:
    """空白等于静默：缺数据时必须看得见 `—`。"""
    text = _plain(footer.render(footer.FooterVM(profile="coding")))
    assert "coding" in text
    assert text.count(strings.PLACEHOLDER) >= 3  # ctx / 费用 / 权限模式 / 分支


def test_context_shows_ratio_and_share_when_the_window_is_known() -> None:
    text = _plain(
        footer.render(
            footer.FooterVM(profile="coding", context_used=12000, context_window=200000)
        )
    )
    assert "12000/200000 (6%)" in text


def test_context_without_window_still_shows_the_count() -> None:
    text = _plain(footer.render(footer.FooterVM(profile="coding", context_used=999)))
    assert "999" in text


def test_busy_state_and_queue_are_visible() -> None:
    text = _plain(
        footer.render(footer.FooterVM(profile="coding", busy=True, queue_depth=1))
    )
    assert "回合进行中" in text
    assert "队列 1" in text


def test_idle_state_is_explicit() -> None:
    assert "空闲" in _plain(footer.render(footer.FooterVM(profile="coding")))


def test_cost_uses_four_decimals() -> None:
    text = _plain(footer.render(footer.FooterVM(profile="coding", cost_usd=0.01234)))
    assert "0.0123" in text


def test_model_and_permission_mode_join_the_line() -> None:
    text = _plain(
        footer.render(
            footer.FooterVM(
                profile="coding",
                model="deepseek-v4",
                permission_mode="plan",
                branch="main",
            )
        )
    )
    assert "deepseek-v4" in text
    assert "plan" in text
    assert "main" in text


def test_status_bar_is_no_longer_dead_code() -> None:
    """F1 回归守卫：terminal_theme.status_bar 必须真的被调到。"""
    from questorharness.bootstrap.hosts.serve import terminal_theme as theme

    original = theme.status_bar
    calls: list[tuple[str, str | None, bool]] = []

    def spy(profile: str, model: str | None = None, busy: bool = False):
        calls.append((profile, model, busy))
        return original(profile, model, busy)

    theme.status_bar = spy  # type: ignore[assignment] # 运行期探针，立即还原
    try:
        footer.render(footer.FooterVM(profile="coding", model="m", busy=True))
    finally:
        theme.status_bar = original
    assert calls == [("coding", "m", True)]
