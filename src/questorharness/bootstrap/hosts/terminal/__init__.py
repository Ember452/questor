"""终端瘦客户端的呈现层：帧 → 视图模型、图元、输入与覆盖层。

只消费 serve 契约（wire 帧 + `/history`），不持有会话事实，不 import 引擎；
`prompt_toolkit` 仅在输入层按需导入，包根必须能在无它时冷导入。
"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal.unsupported import (
    UNSUPPORTED,
    badge_reason,
    badge_text,
)

__all__ = ["UNSUPPORTED", "badge_reason", "badge_text"]
