"""L5 模型窗口表（B10/§7.1；ADR-0057）。

压缩改成**绝对阈值**后，内核必须知道两件事：模型能吃多少（`context_window`）、一次最多吐多少
（`max_output`）。这两个数**不属于内核**（内核 env-free、也不认模型名），所以住在 providers：
由组合根读 env / 查表，算好后作为 `CompactionConfig` 的字段注入。

诚实边界：
- 表值来自各家公开目录的常见档位，**未逐一以官方文档校准**（标 UNVERIFIED）；命中不到家族时
  返回 :data:`UNKNOWN_WINDOW`（``context_window=None``）= **不知道窗口**，压缩逐字退回旧的
  `max_items`/`trigger_tokens` 信号，绝不拿猜来的窗口去算绝对阈值（宁可不压，也不误截）。
- ``QUESTOR_CONTEXT_WINDOW`` / ``QUESTOR_MAX_OUTPUT`` 显式覆盖优先于查表：用户知道自己模型时
  应当直接给数，而不是指望这张表。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelWindow:
    """一个模型的窗口尺寸（token）。任一字段为 ``None`` 即"不知道"，绝对阈值不启用。"""

    context_window: int | None = None
    max_output: int | None = None

    def known(self) -> bool:
        return self.context_window is not None


#: 家族前缀 → (context_window, max_output)。**顺序即优先级**：先匹配到的家族生效。
#: 值取公开目录常见档位（UNVERIFIED：未逐个回官方页校准）。
WINDOW_TABLE: tuple[tuple[str, tuple[int, int]], ...] = (
    ("claude-", (200_000, 8_192)),
    ("anthropic/", (200_000, 8_192)),
    ("gpt-4.1", (128_000, 16_384)),
    ("gpt-4o", (128_000, 16_384)),
    ("o3", (200_000, 100_000)),
    ("o4-mini", (200_000, 100_000)),
    ("deepseek-", (128_000, 8_192)),
    ("qwen-", (128_000, 8_192)),
    ("gemini-", (1_000_000, 8_192)),
    ("llama-", (128_000, 4_096)),
)

#: 不知道窗口的返回值（不是"猜一个默认窗口"——那会让绝对阈值按假数截断）。
UNKNOWN_WINDOW = ModelWindow()


def windows_for_model(model: str | None) -> ModelWindow:
    """按模型名查窗口；未命中家族返回 :data:`UNKNOWN_WINDOW`（不猜）。"""
    name = (model or "").strip().lower()
    if not name:
        return UNKNOWN_WINDOW
    bare = name.split("/")[-1]  # 去掉 provider 前缀（``openai/gpt-4o`` → ``gpt-4o``）
    for prefix, sizes in WINDOW_TABLE:
        if bare.startswith(prefix):
            return ModelWindow(context_window=sizes[0], max_output=sizes[1])
    return UNKNOWN_WINDOW


def _positive_int(raw: str) -> int | None:
    """env 值解析：非正整数一律不当真（返回 None = 不提供该维度）。"""
    digits = raw.strip()
    if digits.isdigit() and int(digits) > 0:
        return int(digits)
    return None


def window_from_env(model: str | None) -> ModelWindow:
    """``QUESTOR_CONTEXT_WINDOW`` / ``QUESTOR_MAX_OUTPUT`` 覆盖 → 再查表。

    读取属**组合根/providers** 职责（与 `compaction_from_env` 同族，内核 env-free）。
    两个 env 各自独立：只给 context_window 也能用绝对阈值（`max_output` 未知时按摘要预留扣满）。
    """
    context = _positive_int(os.environ.get("QUESTOR_CONTEXT_WINDOW", ""))
    max_output = _positive_int(os.environ.get("QUESTOR_MAX_OUTPUT", ""))
    if context is not None:
        return ModelWindow(context_window=context, max_output=max_output)
    table = windows_for_model(model)
    if max_output is not None:
        return ModelWindow(context_window=table.context_window, max_output=max_output)
    return table


__all__ = ["ModelWindow", "UNKNOWN_WINDOW", "WINDOW_TABLE", "window_from_env", "windows_for_model"]
