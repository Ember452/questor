"""#188：回放缺 ts 的旧/异构行时，兜底时间必须 tz-aware（守"永不 naive"）。"""

from __future__ import annotations

from questor.contracts.events import Envelope, EventType
from questor.kernel.events import _row_to_envelope


def test_row_to_envelope_fallback_ts_is_timezone_aware() -> None:
    env = _row_to_envelope("run_x", {"seq": 1, "type": EventType.RUN_STARTED, "turn": 0, "data": {}})
    assert isinstance(env, Envelope)
    assert env.ts.tzinfo is not None and env.ts.utcoffset() is not None, "naive 兜底时间戳违反'永不 naive'"
