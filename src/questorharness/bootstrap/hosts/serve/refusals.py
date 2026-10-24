"""线协议的拒绝码白名单。

客户端按码分支，不解析自由文本；新增码只能追加，不得改名。
"""

from __future__ import annotations

from typing import Final

TURN_BUSY: Final[str] = "turn.busy"
TURN_NOT_OWNER: Final[str] = "turn.not_owner"
APPROVAL_NOT_OWNER: Final[str] = "approval.not_owner"
APPROVAL_ALREADY_SETTLED: Final[str] = "approval.already_settled"
ASK_NOT_OWNER: Final[str] = "ask.not_owner"
ASK_ALREADY_SETTLED: Final[str] = "ask.already_settled"
SUBMIT_INVALID: Final[str] = "submit.invalid"
PROFILE_UNKNOWN: Final[str] = "profile.unknown"
AUTH_REQUIRED: Final[str] = "auth.required"
AUTH_ORIGIN: Final[str] = "auth.origin"
AUTH_HOST: Final[str] = "auth.host"
REPLAY_GAP: Final[str] = "replay.gap"
NOT_FOUND: Final[str] = "route.not_found"

ALL: Final[frozenset[str]] = frozenset(
    {
        TURN_BUSY,
        TURN_NOT_OWNER,
        APPROVAL_NOT_OWNER,
        APPROVAL_ALREADY_SETTLED,
        ASK_NOT_OWNER,
        ASK_ALREADY_SETTLED,
        SUBMIT_INVALID,
        PROFILE_UNKNOWN,
        AUTH_REQUIRED,
        AUTH_ORIGIN,
        AUTH_HOST,
        REPLAY_GAP,
        NOT_FOUND,
    }
)


class Refusal(Exception):
    """携带白名单拒绝码的异常；路由层把它翻译成 409/400 响应。"""

    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        if code not in ALL:
            raise ValueError(f"refusal code not whitelisted: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
