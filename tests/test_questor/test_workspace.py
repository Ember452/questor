from pathlib import Path

from questor.workspace import (
    get_bootstrap_path,
    get_gateway_config_path,
    get_identity_path,
    get_memory_index_path,
    get_soul_path,
    get_user_path,
    get_workspace_root,
    initialize_workspace,
    workspace_health,
)


def test_default_workspace_is_isolated_from_legacy_questor_data(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("QUESTOR_WORKSPACE", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    assert get_workspace_root() == (tmp_path / ".questor" / "agent").resolve()


def test_explicit_workspace_is_used_as_is(tmp_path: Path):
    target = tmp_path / "custom-workspace"

    assert get_workspace_root(target) == target.resolve()


def test_initialize_workspace_creates_expected_files(tmp_path: Path):
    workspace = tmp_path / ".questor-home"
    root = initialize_workspace(workspace)
    assert root == workspace
    assert get_soul_path(workspace).exists()
    assert get_user_path(workspace).exists()
    assert get_identity_path(workspace).exists()
    assert get_bootstrap_path(workspace).exists()
    assert get_memory_index_path(workspace).exists()
    assert get_gateway_config_path(workspace).exists()

    health = workspace_health(workspace)
    assert all(health.values())

    soul_text = get_soul_path(workspace).read_text(encoding="utf-8")
    user_text = get_user_path(workspace).read_text(encoding="utf-8")
    identity_text = get_identity_path(workspace).read_text(encoding="utf-8")
    bootstrap_text = get_bootstrap_path(workspace).read_text(encoding="utf-8")
    assert "Be genuinely helpful, not performatively helpful." in soul_text
    assert "Remember that access is intimacy." in soul_text
    assert "Relationship notes" in user_text
    assert "learn enough to help well, not to build a dossier" in user_text
    assert "Name: questor" in identity_text
    assert "first conversation" in bootstrap_text
