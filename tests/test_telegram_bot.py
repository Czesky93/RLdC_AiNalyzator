import asyncio
from types import SimpleNamespace

import requests

from telegram_bot import bot as tg_bot


class _FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.replies = []

    async def reply_text(self, text: str):
        self.replies.append(text)


class _FakeUpdate:
    def __init__(self, text: str, chat_id: int = 123):
        self.message = _FakeMessage(text)
        self.effective_chat = SimpleNamespace(id=chat_id)


def _run(coro):
    return asyncio.run(coro)


def test_message_router_uses_lightweight_status(monkeypatch):
    update = _FakeUpdate("status")
    context = SimpleNamespace(args=[])

    called = {"status": False, "post": False}

    async def _ok_auth(_update):
        return True

    async def _fake_status(_update, _context):
        called["status"] = True

    def _boom_post(*args, **kwargs):
        called["post"] = True
        raise AssertionError("requests.post should not be called for lightweight status")

    monkeypatch.setattr(tg_bot, "_check_auth", _ok_auth)
    monkeypatch.setattr(tg_bot, "status_command", _fake_status)
    monkeypatch.setattr(tg_bot.requests, "post", _boom_post)

    _run(tg_bot.message_command_router(update, context))

    assert called["status"] is True
    assert called["post"] is False


def test_message_router_timeout_has_controlled_message(monkeypatch):
    update = _FakeUpdate("kup btc teraz")
    context = SimpleNamespace(args=[])
    captured = {"text": None}

    async def _ok_auth(_update):
        return True

    async def _fake_send_reply(_update, text: str, command=None):
        captured["text"] = text

    async def _timeout_thread(*args, **kwargs):
        raise requests.Timeout("simulated timeout")

    monkeypatch.setattr(tg_bot, "_check_auth", _ok_auth)
    monkeypatch.setattr(tg_bot, "_send_reply", _fake_send_reply)
    monkeypatch.setattr(tg_bot.asyncio, "to_thread", _timeout_thread)

    _run(tg_bot.message_command_router(update, context))

    assert isinstance(captured["text"], str)
    assert "Backend odpowiada zbyt wolno" in captured["text"]
    assert "Traceback" not in captured["text"]


def test_http_get_json_timeout_returns_controlled_error(monkeypatch):
    def _timeout(*args, **kwargs):
        raise requests.Timeout("boom")

    monkeypatch.setattr(tg_bot.requests, "get", _timeout)
    payload, err = tg_bot._http_get_json("http://localhost/fake")

    assert payload == {}
    assert err == "timeout"
