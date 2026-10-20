"""L5 embedding 选择（B8 收口修正）：**向量通道的能力声明必须与实现同源**。

为什么单独一个文件（与 `provider_factory` / `model_windows` 同族）：

- 组合根守卫禁止业务分支，所以"要不要有向量能力"的判据必须住在 providers 层；
- 本仓**目前没有**任何真实 embedding 适配器（`litellm_adapter` 无 embed 路径、config 无 embedding
  项）。因此生产的正确答案是 `None` = 向量通道关闭，keyword + structured 照旧默认开；
- **绝不拿确定性 fake 顶位**：fake 向量与真向量来自不同空间，一旦 store 侧存了真 embedding 而
  query 侧用 sha256（或反之），融合排序就会按噪声决定注入哪几条——比"没有向量通道"更糟，
  而且没有一条测试会红。fake 的正当位置是测试与离线演示，由调用方**显式**注入。

env：``QUESTOR_EMBED_MODEL``（配 ``LITELLM_API_KEY`` 之类凭据由实现自己要求）。设了模型名但
**没有注册对应 builder** 时不猜、不降级成 fake：发一条 warning 后返回 ``None``（静默关闭才是
这里最坏的失败模式）。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from questor.contracts.memory import EmbeddingPort

_LOG = logging.getLogger("questor.embedders")

#: 家族名/模型名 → 构造器。**当前为空**：仓内没有真 embedding 实现。接入真 provider 时在此登记，
#: 组合根与调用方代码一行不改（与 `WINDOW_TABLE`/`PROFILES` 同一"数据表优先"口径）。
EMBEDDER_BUILDERS: dict[str, Callable[[str], EmbeddingPort]] = {}


def embedder_from_env() -> EmbeddingPort | None:
    """按 env 决定向量能力；未配置或配置了但没有实现 → ``None``（向量通道关闭）。"""
    model = os.environ.get("QUESTOR_EMBED_MODEL", "").strip()
    if not model:
        return None
    builder = EMBEDDER_BUILDERS.get(model) or next(
        (factory for name, factory in EMBEDDER_BUILDERS.items() if model.startswith(name)), None
    )
    if builder is None:
        # 不静默：用户明确要了向量能力，而这里给不出实现——必须出声，否则"以为在跑向量检索"。
        _LOG.warning(
            "QUESTOR_EMBED_MODEL=%r has no registered embedding builder; vector channel stays off (keyword+structured remain enabled)",
            model,
        )
        return None
    return builder(model)


def shared_embedder(store: object, embedder: EmbeddingPort | None) -> EmbeddingPort | None:
    """只有 store 侧用的确实是同一个实例时，才让 query 侧也用它（否则关向量通道）。

    为什么需要这一道：`spec.memory` 可以带自己的 embedder 进来，而 query 向量与 stored 向量必须
    同一空间才能比。两边不同实例（或一边有一边无）时，“开着向量通道”比“关掉”更危险：余弦值
    是不同空间之间的噪声，却直接决定三通道融合后注入哪 5 条，而且没有一条测试会红。

    本判据住在 providers 层而不是组合根：组合根守卫（`check_extension_points` D）禁止业务分支，
    而“能不能用向量”正是能力判据，不是装配收窄。
    """
    if embedder is None:
        return None
    store_embedder = getattr(store, "embedder", None)
    if store_embedder is embedder:
        return embedder
    _LOG.warning(
        "vector channel stays off: memory store uses a different embedder (%r) than the resolved one (%r)",
        type(store_embedder).__name__,
        type(embedder).__name__,
    )
    return None


__all__ = ["EMBEDDER_BUILDERS", "embedder_from_env", "shared_embedder"]
