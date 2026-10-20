"""config 模型：默认值表 / 覆盖优先级 / 坏值回落 / 惰性语义（OPT-3 c5）。

这些断言是"env 读取平移"的可验证契约：默认值逐条对表、覆盖只可能来自 env、坏值处置与历史
逐字一致（generation/keep_days/port 回落、lookback 在使用点抛）。任何一条变了就说明
``questor.config.model`` 不再是历史读取口径的等价物。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.config.model import load_config
from questor.observability.entry import LogLevel
from questor.surfaces._assembly import console_level_from_env

#: 组合根读的全部 env（缺一个就说明口径没收干净；新增 env 必须同步这里）。
_ENV_KEYS = (
    "QUESTOR_STORE_PATH",
    "QUESTOR_MEMORY_DB",
    "QUESTOR_MEMORY_ROOT",
    "QUESTOR_SKILLS_DIR",
    "QUESTOR_MCP_JSON",
    "QUESTOR_MODEL",
    "LITELLM_API_KEY",
    "QUESTOR_LOG_LEVEL",
    "QUESTOR_LOG_DIR",
    "QUESTOR_LOG_KEEP_DAYS",
    "QUESTOR_LOG_PAYLOAD",
    "QUESTOR_COMPACTION",
    "QUESTOR_SIDECAR_GENERATION",
    "QUESTOR_SIDECAR_BOOTSTRAP",
    "QUESTOR_WEB_DIST",
    "QUESTOR_DREAM_LOOKBACK",
    "QUESTOR_OPENAI_API_KEYS",
    "QUESTOR_OPENAI_HOST",
    "QUESTOR_OPENAI_PORT",
)


def _clear_env(monkeypatch) -> None:  # noqa: ANN001
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_table(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """全缺省：默认值逐条对表（含 ``<cwd>`` 解析发生在调用时点）。"""
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    q = tmp_path / ".questor"
    assert cfg.paths.store_path == str(q / "state.db")
    assert cfg.paths.memory_db == str(q / "memory.db")
    assert cfg.paths.memory_root == str(q / "memory_store")
    assert cfg.paths.skills_dir == str(q / "skills")
    assert cfg.paths.mcp_json == str(tmp_path / "mcp.json")
    assert (cfg.llm.model, cfg.llm.has_litellm_key, cfg.llm.model_name) == (None, False, "echo")
    assert (cfg.logging.console_level, cfg.logging.log_dir, cfg.logging.keep_days) == ("INFO", str(q / "logs"), 14)
    assert (cfg.logging.payload_preview, cfg.logging.compaction) == ("off", "off")
    assert (cfg.sidecar.generation, cfg.sidecar.bootstrap_path, cfg.sidecar.web_dist) == (
        1,
        str(q / "sidecar-bootstrap.json"),
        None,
    )
    assert (cfg.openai.api_keys, cfg.openai.host, cfg.openai.port) == ((), "127.0.0.1", 8000)
    assert cfg.dream_lookback == 7


def test_env_overrides_every_default(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """给了 env 就全用 env（覆盖优先级：env > 默认值；映射注入与 os.environ 同一条路径）。"""
    _clear_env(monkeypatch)
    env = {
        "QUESTOR_STORE_PATH": str(tmp_path / "s.db"),
        "QUESTOR_MEMORY_DB": str(tmp_path / "m.db"),
        "QUESTOR_MEMORY_ROOT": str(tmp_path / "mroot"),
        "QUESTOR_SKILLS_DIR": str(tmp_path / "skills"),
        "QUESTOR_MCP_JSON": str(tmp_path / "mcp.json"),
        "QUESTOR_MODEL": "vendor/model-x",
        "LITELLM_API_KEY": "sk-test",
        "QUESTOR_LOG_LEVEL": "debug",
        "QUESTOR_LOG_DIR": str(tmp_path / "logs"),
        "QUESTOR_LOG_KEEP_DAYS": "3",
        "QUESTOR_LOG_PAYLOAD": "truncate:128",
        "QUESTOR_COMPACTION": "on",
        "QUESTOR_SIDECAR_GENERATION": "7",
        "QUESTOR_SIDECAR_BOOTSTRAP": str(tmp_path / "boot.json"),
        "QUESTOR_WEB_DIST": str(tmp_path),
        "QUESTOR_DREAM_LOOKBACK": "30",
        "QUESTOR_OPENAI_API_KEYS": " a , ,b ",
        "QUESTOR_OPENAI_HOST": "0.0.0.0",
        "QUESTOR_OPENAI_PORT": "9001",
    }
    cfg = load_config(env)
    assert cfg.paths.store_path == str(tmp_path / "s.db")
    assert cfg.paths.memory_db == str(tmp_path / "m.db")
    assert cfg.paths.memory_root == str(tmp_path / "mroot")
    assert cfg.paths.skills_dir == str(tmp_path / "skills")
    assert cfg.paths.mcp_json == str(tmp_path / "mcp.json")
    assert (cfg.llm.model, cfg.llm.has_litellm_key, cfg.llm.model_name) == ("vendor/model-x", True, "vendor/model-x")
    assert (cfg.logging.console_level, cfg.logging.keep_days) == ("debug", 3)
    assert (cfg.logging.payload_preview, cfg.logging.compaction) == ("truncate:128", "on")
    assert (cfg.sidecar.generation, cfg.sidecar.bootstrap_path, cfg.sidecar.web_dist) == (7, str(tmp_path / "boot.json"), tmp_path)
    assert cfg.openai.api_keys == ("a", "b"), "key 列表要逐项 strip 并丢掉空项（历史口径）"
    assert (cfg.openai.host, cfg.openai.port) == ("0.0.0.0", 9001)
    assert cfg.dream_lookback == 30


def test_bad_numeric_values_follow_historical_fallbacks() -> None:
    """坏值处置逐字一致：keep_days/generation/port 回落；lookback **在使用点**才抛。"""
    cfg = load_config(
        {
            "QUESTOR_LOG_KEEP_DAYS": "abc",
            "QUESTOR_SIDECAR_GENERATION": "x",
            "QUESTOR_OPENAI_PORT": "x",
            "QUESTOR_DREAM_LOOKBACK": "x",
        }
    )
    assert cfg.logging.keep_days == 14
    assert cfg.sidecar.generation == 1
    assert cfg.openai.port == 8000
    # 惰性：load_config 本身不抛，只有真正取 lookback 时才 ValueError（历史行为）。
    with pytest.raises(ValueError):
        _ = cfg.dream_lookback


def test_web_dist_only_resolves_to_an_existing_directory(tmp_path: Path) -> None:
    """``QUESTOR_WEB_DIST`` 非目录 = 未配置（历史：``path.is_dir()`` 才挂载静态面）。"""
    assert load_config({"QUESTOR_WEB_DIST": ""}).sidecar.web_dist is None
    a_file = tmp_path / "dist.txt"
    a_file.write_text("x", encoding="utf-8")
    assert load_config({"QUESTOR_WEB_DIST": str(a_file)}).sidecar.web_dist is None
    assert load_config({"QUESTOR_WEB_DIST": str(tmp_path)}).sidecar.web_dist == tmp_path


def test_missing_keys_are_not_invented() -> None:
    """空 env：不凭空造 model/key/静态目录（None/False/() 才是"未设"）。"""
    cfg = load_config({})
    assert cfg.llm.model is None
    assert cfg.llm.has_litellm_key is False
    assert cfg.openai.api_keys == ()
    assert cfg.sidecar.web_dist_raw is None


def test_console_level_is_parsed_in_assembly_not_config(monkeypatch) -> None:  # noqa: ANN001
    """级别字符串→``LogLevel`` 的解析留在 observability 侧（config 不得 import observability）。"""
    monkeypatch.setenv("QUESTOR_LOG_LEVEL", "debug")
    assert console_level_from_env() is LogLevel.DEBUG  # 历史 .upper() 口径
    monkeypatch.setenv("QUESTOR_LOG_LEVEL", "no-such-level")
    assert console_level_from_env() is LogLevel.INFO
