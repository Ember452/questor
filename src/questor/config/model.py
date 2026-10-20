"""L7 横切：组合根配置的 frozen 纯数据模型（OPT-3 c1）。

本层只做一件事：把散在 ``composition.*_from_env`` / ``surfaces._assembly.*_from_env`` /
``__main__`` 内联里的 env 读取**收口成一份可测的数据**。env 名、默认值、判定顺序逐字平移，
本刀不动"读什么"，也不动"怎么判"：

- 只 import stdlib（不引 pydantic；配置是横切薄层，不是第二个框架）；
- **不 import observability**（``config ⟂ observability`` independence 契约，见 .importlinter）：
  故只保存 ``QUESTOR_LOG_LEVEL`` 的**原始字符串**，``LogLevel`` 解析留在 ``surfaces._assembly``，
  ``configure_logging`` 保持 env-free；
- 不搬解析/校验：``QUESTOR_COMPACTION``/``QUESTOR_LOG_PAYLOAD`` 的合法性与 fail-closed 拒绝启动
  仍在 ``_assembly``（本模型只提供原样字符串）。"读"与"判"分开，行为才零漂移。

失败语义与历史一致：``QUESTOR_SIDECAR_GENERATION`` 坏值回落 1、``QUESTOR_LOG_KEEP_DAYS`` 坏值回落 14；
而 ``QUESTOR_DREAM_LOOKBACK`` 历史上是**使用点**才 ``int()``（坏值直接抛）、``QUESTOR_OPENAI_PORT``
是使用点才解析（坏值回落 8000）——故两者保留为惰性属性，避免把"只在某个子命令才响的错"
提前成"任何入口都响的错"。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def _cwd_path(*parts: str) -> str:
    """``<cwd>/parts...`` 的字符串形式（历史默认值的同一口径：调用时点解析 cwd）。"""
    return str(Path.cwd().joinpath(*parts))


def _int_or(raw: str, fallback: int) -> int:
    """``int(raw)``，坏值回落 ``fallback``（历史 ``except ValueError`` 口径）。"""
    try:
        return int(raw)
    except ValueError:
        return fallback


def _bool_or(raw: str, fallback: bool) -> bool:
    """``on/off`` 开关：off/0/false/no 为 False；坏值回落。"""
    value = (raw or "").strip().lower()
    if value in {"on", "1", "true", "yes"}:
        return True
    if value in {"off", "0", "false", "no"}:
        return False
    return fallback


@dataclass(frozen=True, slots=True)
class PathsConfig:
    """持久层与能力目录（组合根独占读取；内核 env-free）。"""

    store_path: str
    memory_db: str
    memory_root: str
    skills_dir: str
    mcp_json: str


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """模型路由：``model`` 保留**原样**（None = 未设），是否带密钥单独成字段。"""

    model: str | None
    has_litellm_key: bool

    @property
    def model_name(self) -> str:
        """组合根口径的模型名（未设 → 离线 "echo"）；surface 的 model 走这里，不再读 env。"""
        return self.model or "echo"


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """日志面的 env 原文（级别/载荷/压缩的**解析**留在 ``surfaces._assembly``）。"""

    console_level: str
    log_dir: str
    keep_days: int
    payload_preview: str
    compaction: str


@dataclass(frozen=True, slots=True)
class SidecarConfig:
    """sidecar 宿主：bootstrap 代数/路径 + 前端静态产物目录。"""

    generation: int
    bootstrap_path: str
    web_dist_raw: str | None

    @property
    def web_dist(self) -> Path | None:
        """静态产物**目录**；未设/不是目录 → None（历史：非目录视同未配置，不挂载）。"""
        if not self.web_dist_raw:
            return None
        path = Path(self.web_dist_raw)
        return path if path.is_dir() else None


@dataclass(frozen=True, slots=True)
class OpenAIConfig:
    """鉴权 OpenAI lane：key 列表 + 绑定地址（port 惰性解析）。"""

    api_keys: tuple[str, ...]
    host: str
    port_raw: str

    @property
    def port(self) -> int:
        """监听端口；坏值回落 8000（历史行为）。"""
        try:
            return int(self.port_raw)
        except ValueError:
            return 8000


@dataclass(frozen=True, slots=True)
class DeliveryConfig:
    """交付账本开关与上限（B11；账本失败绝不阻塞发送）。"""

    enabled: bool
    max_rows: int
    retry_base_seconds: float


@dataclass(frozen=True, slots=True)
class Config:
    """一次配置快照（frozen）：``load_config()`` 的返回，调用方按需取子块。"""

    paths: PathsConfig
    llm: LlmConfig
    logging: LoggingConfig
    sidecar: SidecarConfig
    openai: OpenAIConfig
    delivery: DeliveryConfig
    dream_lookback_raw: str

    @property
    def dream_lookback(self) -> int:
        """``--dream`` 的回看天数；坏值沿历史行为**抛 ValueError**（不是静默回落）。"""
        return int(self.dream_lookback_raw)


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """按给定 env（默认 ``os.environ``）读一份配置：纯读、无 IO、**无缓存**。

    无缓存是刻意的：读取时点 = 调用时点，测试的 monkeypatch 与宿主改 env 都会即时生效，
    与历史"每个 ``*_from_env`` 现读现用"逐字等价。``env`` 形参只为测试注入（生产不传）。
    """
    source: Mapping[str, str] = os.environ if env is None else env
    return Config(
        paths=PathsConfig(
            store_path=source.get("QUESTOR_STORE_PATH", _cwd_path(".questor", "state.db")),
            memory_db=source.get("QUESTOR_MEMORY_DB", _cwd_path(".questor", "memory.db")),
            memory_root=source.get("QUESTOR_MEMORY_ROOT", _cwd_path(".questor", "memory_store")),
            skills_dir=source.get("QUESTOR_SKILLS_DIR", _cwd_path(".questor", "skills")),
            mcp_json=source.get("QUESTOR_MCP_JSON", _cwd_path("mcp.json")),
        ),
        llm=LlmConfig(
            model=source.get("QUESTOR_MODEL"),
            has_litellm_key=bool(source.get("LITELLM_API_KEY")),
        ),
        logging=LoggingConfig(
            console_level=source.get("QUESTOR_LOG_LEVEL", "INFO"),
            log_dir=source.get("QUESTOR_LOG_DIR", _cwd_path(".questor", "logs")),
            keep_days=_int_or(source.get("QUESTOR_LOG_KEEP_DAYS", "14"), 14),
            payload_preview=source.get("QUESTOR_LOG_PAYLOAD", "off"),
            compaction=source.get("QUESTOR_COMPACTION", "off"),
        ),
        sidecar=SidecarConfig(
            generation=_int_or(source.get("QUESTOR_SIDECAR_GENERATION", "1"), 1),
            bootstrap_path=source.get("QUESTOR_SIDECAR_BOOTSTRAP", _cwd_path(".questor", "sidecar-bootstrap.json")),
            web_dist_raw=source.get("QUESTOR_WEB_DIST"),
        ),
        openai=OpenAIConfig(
            api_keys=tuple(key.strip() for key in source.get("QUESTOR_OPENAI_API_KEYS", "").split(",") if key.strip()),
            host=source.get("QUESTOR_OPENAI_HOST", "127.0.0.1"),
            port_raw=source.get("QUESTOR_OPENAI_PORT", "8000"),
        ),
        delivery=DeliveryConfig(
            enabled=_bool_or(source.get("QUESTOR_DELIVERY_LEDGER", "on"), True),
            max_rows=500,
            retry_base_seconds=5.0,
        ),
        dream_lookback_raw=source.get("QUESTOR_DREAM_LOOKBACK", "7"),
    )


def ledger_enabled(config: Config) -> bool:
    """交付账本开关（唯一读取点；失败/关闭不得阻塞发送）。"""
    return config.delivery.enabled


__all__ = [
    "Config",
    "DeliveryConfig",
    "LlmConfig",
    "LoggingConfig",
    "OpenAIConfig",
    "PathsConfig",
    "SidecarConfig",
    "ledger_enabled",
    "load_config",
]
