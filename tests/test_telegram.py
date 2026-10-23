from __future__ import annotations

from dealsgalore import notifiers
from dealsgalore.notifiers import Alert, TelegramNotifier, configured_notifiers


class _Resp:
    def raise_for_status(self):
        return None


def _capture(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None, **kw):
        calls.append({"url": url, "json": json})
        return _Resp()

    monkeypatch.setattr(notifiers.requests, "post", fake_post)
    return calls


def _alert(**kw):
    return Alert(title="LEGO <Botanical> Bonsai & more $39.99", url="https://example.com/x?a=1&b=2",
                 price=39.99, score=0.86, source="slickdeals", reason="Great fit for them", **kw)


def test_telegram_alert_is_escaped_html(monkeypatch):
    calls = _capture(monkeypatch)
    TelegramNotifier("TOKEN", "42").alert(_alert(recipient="Niece"))
    (c,) = calls
    assert c["url"] == "https://api.telegram.org/botTOKEN/sendMessage"
    body = c["json"]
    assert body["chat_id"] == "42" and body["parse_mode"] == "HTML"
    assert "&lt;Botanical&gt;" in body["text"] and "Gift for Niece" in body["text"]
    assert 'href="https://example.com/x?a=1&amp;b=2"' in body["text"]


def test_telegram_digest_splits_long_messages(monkeypatch):
    calls = _capture(monkeypatch)
    TelegramNotifier("T", "1").digest([_alert() for _ in range(60)], "Deals digest")
    assert len(calls) > 1
    assert all(len(c["json"]["text"]) <= 4000 for c in calls)
    assert sum(c["json"]["text"].count("example.com") for c in calls) == 60


def test_telegram_enabled_from_env(monkeypatch):
    for k in ("NTFY_TOPIC", "SMTP_USER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123")
    (n,) = configured_notifiers()
    assert isinstance(n, TelegramNotifier) and n.chat_id == "-100123"
