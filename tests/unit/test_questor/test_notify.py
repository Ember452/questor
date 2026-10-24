"""Mirror test for ``gateway/notify.py`` (plan 01, R7).

Scope note: ``QuestorNotificationError``/``_chunk_text``/``_send_feishu_text_sync``/
``send_feishu_dm``/``register_handlers`` were named by no test before this file. Two
decisions live here and are easy to break silently: how a long message is cut into
provider-sized chunks (a bad cut loses text or sends nothing), and which notify target
wins when a cron job carries several id fields (the wrong winner DMs the wrong person).
The Feishu SDK is replaced by a stub module -- no socket, no credentials.
"""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

from questor.gateway import notify
from questor.gateway.notify import (
    QuestorNotificationError,
    _chunk_text,
    register_handlers,
    send_feishu_dm,
)


class _Response:
    """Stand-in for a lark API response."""

    def __init__(self, *, ok: bool = True, code: int = 0, msg: str = "ok", log_id: str = "cli_log_1") -> None:
        self.ok = ok
        self.code = code
        self.msg = msg
        self._log_id = log_id

    def success(self) -> bool:
        return self.ok

    def get_log_id(self) -> str:
        return self._log_id


class _BodyBuilder:
    def __init__(self) -> None:
        self.fields: dict[str, object] = {}

    def receive_id(self, value):
        self.fields["receive_id"] = value
        return self

    def msg_type(self, value):
        self.fields["msg_type"] = value
        return self

    def content(self, value):
        self.fields["content"] = value
        return self

    def build(self):
        return self


class _RequestBuilder:
    def __init__(self) -> None:
        self.fields: dict[str, object] = {}

    def receive_id_type(self, value):
        self.fields["receive_id_type"] = value
        return self

    def request_body(self, value):
        self.fields["request_body"] = value
        return self

    def build(self):
        return self


@pytest.fixture()
def lark(monkeypatch):
    """Install a stub ``lark_oapi`` that records what would have been sent."""
    sent: list[_RequestBuilder] = []
    responses: list[_Response] = [_Response()]
    built: dict[str, object] = {}

    class _Message:
        def create(self, request):
            sent.append(request)
            if len(sent) > len(responses):
                responses.append(_Response())
            return responses[len(sent) - 1]

    class _Client:
        @staticmethod
        def builder():
            class _Step:
                def app_id(self, value):
                    built["app_id"] = value
                    return self

                def app_secret(self, value):
                    built["app_secret"] = value
                    return self

                def log_level(self, value):
                    built["log_level"] = value
                    return self

                def build(self):
                    return SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(message=_Message())))

            return _Step()

    module = types.ModuleType("lark_oapi")
    module.Client = _Client  # type: ignore[attr-defined]
    module.LogLevel = SimpleNamespace(INFO=1)  # type: ignore[attr-defined]
    im_v1 = types.ModuleType("lark_oapi.api.im.v1")
    im_v1.CreateMessageRequest = type("CreateMessageRequest", (), {"builder": staticmethod(_RequestBuilder)})  # type: ignore[attr-defined]
    im_v1.CreateMessageRequestBody = type("CreateMessageRequestBody", (), {"builder": staticmethod(_BodyBuilder)})  # type: ignore[attr-defined]

    for name, value in (
        ("lark_oapi", module),
        ("lark_oapi.api", types.ModuleType("lark_oapi.api")),
        ("lark_oapi.api.im", types.ModuleType("lark_oapi.api.im")),
        ("lark_oapi.api.im.v1", im_v1),
    ):
        monkeypatch.setitem(sys.modules, name, value)

    return SimpleNamespace(sent=sent, responses=responses, built=built)


@pytest.fixture()
def gateway_config(monkeypatch):
    """Feed the gateway config from memory and remember which workspace was asked for."""
    seen: list[object] = []
    config = SimpleNamespace(channel_configs={"feishu": {"app_id": "cli_a", "app_secret": "sec_b"}})

    def _load(workspace=None):
        seen.append(workspace)
        return config

    monkeypatch.setattr(notify, "load_gateway_config", _load)
    return SimpleNamespace(seen=seen, config=config)


# --- chunking -------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_blank_text_produces_no_chunks(text: str) -> None:
    assert _chunk_text(text) == []


def test_short_text_is_one_stripped_chunk() -> None:
    assert _chunk_text("  hello\n ") == ["hello"]


def test_a_late_newline_is_the_split_point() -> None:
    """A newline past the halfway mark of the window is preferred over a hard cut."""
    assert _chunk_text("012345678\nxx yy", max_chars=10) == ["012345678", "xx yy"]


def test_an_early_newline_is_ignored_and_the_text_is_cut_at_the_limit() -> None:
    """Pinned: the newline at index 4 is too close to the front to be a split point.

    Splitting there would waste 6/10 of the window, so the code cuts at ``max_chars``
    and the newline stays inside the first chunk.
    """
    assert _chunk_text("aaaa\nbbbbbbcc", max_chars=10) == ["aaaa\nbbbbb", "bcc"]


def test_text_without_any_newline_is_cut_into_limit_sized_pieces() -> None:
    chunks = _chunk_text("a" * 25, max_chars=10)

    assert [len(chunk) for chunk in chunks] == [10, 10, 5]


def test_the_default_window_is_1800_characters() -> None:
    chunks = _chunk_text("b" * 2000)

    assert [len(chunk) for chunk in chunks] == [1800, 200]


def test_chunking_never_loses_a_non_whitespace_character() -> None:
    text = "alpha\n" + "x" * 37 + "\nbeta 伽马 " + "y" * 61
    chunks = _chunk_text(text, max_chars=23)

    assert "".join("".join(chunk.split()) for chunk in chunks) == "".join(text.split())
    assert all(len(chunk) <= 23 for chunk in chunks)


# --- sending --------------------------------------------------------------


def test_a_missing_app_id_is_reported_before_any_client_is_built(monkeypatch) -> None:
    monkeypatch.setattr(
        notify,
        "load_gateway_config",
        lambda workspace: SimpleNamespace(channel_configs={"feishu": {"app_id": "  ", "app_secret": "s"}}),
    )

    with pytest.raises(QuestorNotificationError, match="app_id/app_secret are not configured"):
        notify._send_feishu_text_sync(user_open_id="ou_1", content="hi")


def test_blank_content_does_not_open_a_request(lark, gateway_config) -> None:
    notify._send_feishu_text_sync(user_open_id="ou_1", content="   \n ")

    assert lark.sent == []
    assert gateway_config.seen == [None]


def test_credentials_and_workspace_reach_the_client(lark, gateway_config) -> None:
    notify._send_feishu_text_sync(user_open_id="ou_1", content="hi", workspace=r"D:\work")

    assert lark.built["app_id"] == "cli_a"
    assert lark.built["app_secret"] == "sec_b"
    assert gateway_config.seen == [r"D:\work"]


def test_each_chunk_becomes_a_separate_text_message_with_json_content(lark, gateway_config) -> None:
    # 4 + 2000 characters, so the default 1800 window cuts it in two
    content = "第一行\n" + "z" * 2000

    notify._send_feishu_text_sync(user_open_id="ou_1", content=content, workspace=None)

    assert len(lark.sent) == 2
    first = lark.sent[0]
    assert first.fields["receive_id_type"] == "open_id"
    body = first.fields["request_body"]
    assert body.fields["receive_id"] == "ou_1"
    assert body.fields["msg_type"] == "text"
    # ensure_ascii=False: the payload keeps readable text instead of \uXXXX escapes
    assert json.loads(body.fields["content"]) == {"text": "第一行\n" + "z" * 1796}
    assert json.loads(lark.sent[1].fields["request_body"].fields["content"]) == {"text": "z" * 204}


def test_a_rejected_response_names_the_code_message_and_the_log_id(lark, gateway_config) -> None:
    lark.responses[0] = _Response(ok=False, code=99991400, msg="frequency limit", log_id="log_42")

    with pytest.raises(QuestorNotificationError) as raised:
        notify._send_feishu_text_sync(user_open_id="ou_1", content="hi")

    assert "code=99991400" in str(raised.value)
    assert "msg=frequency limit" in str(raised.value)
    assert "log_id=log_42" in str(raised.value)


async def test_the_async_wrapper_hands_the_blocking_call_to_a_thread(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_sync(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(notify, "_send_feishu_text_sync", fake_sync)

    await send_feishu_dm(user_open_id="ou_2", content="body", workspace="/tmp/w")

    assert seen == {"user_open_id": "ou_2", "content": "body", "workspace": "/tmp/w"}


# --- handler registration -------------------------------------------------


@pytest.fixture()
def handlers(monkeypatch):
    """Capture what the cron scheduler is told to call for each notify type."""
    registered: dict[str, object] = {}

    import questorharness.api as api

    monkeypatch.setattr(api, "register_notification_handler", lambda name, handler: registered.__setitem__(name, handler))
    calls: list[dict[str, object]] = []

    async def fake_send(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(notify, "send_feishu_dm", fake_send)
    register_handlers()
    return SimpleNamespace(registered=registered, calls=calls)


def test_both_spelling_of_the_feishu_notify_type_are_registered(handlers) -> None:
    assert set(handlers.registered) == {"feishu_dm", "feishu"}
    assert handlers.registered["feishu_dm"] is handlers.registered["feishu"]


@pytest.mark.parametrize(
    "notify_config",
    [
        {"user_open_id": " ou_owner "},
        {"open_id": "ou_second"},
        {"to": "ou_third"},
    ],
)
async def test_the_target_is_taken_from_the_first_field_that_carries_one(handlers, notify_config) -> None:
    await handlers.registered["feishu_dm"]({}, {}, notify_config, "text")  # type: ignore[index]

    assert handlers.calls == [{"user_open_id": notify_config[next(iter(notify_config))].strip(), "content": "text", "workspace": None}]


async def test_user_open_id_wins_over_the_other_target_fields(handlers) -> None:
    """The order is a contract: the three fields are not interchangeable.

    ``to`` is where a group chat id lands, so taking it first would DM the wrong
    subject -- or a chat id that is not a user at all.
    """
    await handlers.registered["feishu"](  # type: ignore[index]
        {}, {}, {"user_open_id": "ou_owner", "open_id": "ou_second", "to": "oc_group"}, "text"
    )

    assert handlers.calls[0]["user_open_id"] == "ou_owner"


async def test_a_notify_block_without_any_target_refuses_to_guess(handlers) -> None:
    with pytest.raises(ValueError, match="missing notify.user_open_id"):
        await handlers.registered["feishu"]({}, {}, {"to": "   "}, "text")  # type: ignore[index]

    assert handlers.calls == []


async def test_an_empty_workspace_string_is_not_sent_as_a_path(handlers) -> None:
    await handlers.registered["feishu"]({}, {}, {"user_open_id": "ou_1", "workspace": ""}, "text")  # type: ignore[index]

    assert handlers.calls == [{"user_open_id": "ou_1", "content": "text", "workspace": None}]


async def test_a_workspace_object_is_forwarded_as_its_string(handlers) -> None:
    await handlers.registered["feishu"]({}, {}, {"user_open_id": "ou_1", "workspace": r"D:\proj"}, "text")  # type: ignore[index]

    assert handlers.calls[0]["workspace"] == r"D:\proj"
