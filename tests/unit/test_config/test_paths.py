"""Tests for questorharness.platform.paths."""

from __future__ import annotations

from pathlib import Path

from questorharness.platform.paths import (
    get_config_dir,
    get_config_file_path,
    get_data_dir,
    get_logs_dir,
    get_project_autopilot_dir,
    get_project_config_dir,
)


def test_get_config_dir_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("QUESTORHARNESS_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    config_dir = get_config_dir()
    assert config_dir == tmp_path / ".questorharness"
    assert config_dir.is_dir()


def test_project_config_dir_does_not_create_directories(tmp_path: Path) -> None:
    """项目配置目录只算路径：它在构建 system prompt 时就会被调用。

    实跑现场：从 `C:\\Windows\\System32` 启动 → WinError 5 → 整个 CLI 带一屏
    traceback 挂掉。调用方只能用 `.exists()` 判断，不能靠副作用建目录。
    """

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert get_project_config_dir(workspace) == workspace / ".questorharness"
    assert not (workspace / ".questorharness").exists()


def test_project_autopilot_dir_survives_an_unwritable_parent(
    tmp_path: Path, monkeypatch
) -> None:
    """建不出来不得抛：受保护目录下启动只降级为“没有 autopilot 状态”。"""

    import questorharness.platform.paths as paths_module

    def _deny(self: Path, *_args: object, **_kwargs: object) -> None:
        raise PermissionError(5, "Access is denied")

    # 让 mkdir 失败（而不是替换 _ensure_dir）：测的正是“失败被吞掉”这件事。
    assert paths_module._ensure_dir is not None
    monkeypatch.setattr(Path, "mkdir", _deny)
    resolved = get_project_autopilot_dir(tmp_path)
    assert resolved == tmp_path / ".questorharness" / "autopilot"


def test_get_config_dir_env_override(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom_config"
    monkeypatch.setenv("QUESTORHARNESS_CONFIG_DIR", str(custom))
    config_dir = get_config_dir()
    assert config_dir == custom
    assert config_dir.is_dir()


def test_get_config_file_path(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("QUESTORHARNESS_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = get_config_file_path()
    assert path == tmp_path / ".questorharness" / "settings.json"


def test_get_data_dir_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("QUESTORHARNESS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("QUESTORHARNESS_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    data_dir = get_data_dir()
    assert data_dir == tmp_path / ".questorharness" / "data"
    assert data_dir.is_dir()


def test_get_data_dir_env_override(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom_data"
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(custom))
    data_dir = get_data_dir()
    assert data_dir == custom
    assert data_dir.is_dir()


def test_get_logs_dir_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("QUESTORHARNESS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("QUESTORHARNESS_LOGS_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    logs_dir = get_logs_dir()
    assert logs_dir == tmp_path / ".questorharness" / "logs"
    assert logs_dir.is_dir()


def test_get_logs_dir_env_override(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom_logs"
    monkeypatch.setenv("QUESTORHARNESS_LOGS_DIR", str(custom))
    logs_dir = get_logs_dir()
    assert logs_dir == custom
    assert logs_dir.is_dir()
