from __future__ import annotations

from dealsgalore import notifiers
from dealsgalore.notifiers import Alert, NtfyNotifier, configured_notifiers


class _Resp:
    def raise_for_status(self):
        return None


def _capture(monkeypatch):
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append({"url": url, "data": data, "headers": headers})
        return _Resp()

    monkeypatch.setattr(notifiers.requests, "post", fake_post)
    return calls


def _alert(score=0.95, **kw):
    return Alert(title="Dyson V15 Detect $449", url="https://example.com/d", price=449.0,
                 score=score, source="slickdeals", reason="Below target", **kw)


def test_ntfy_alert_headers(monkeypatch):
    calls = _capture(monkeypatch)
    NtfyNotifier("my-topic").alert(_alert(watch_item="Dyson V15 Detect"))
    (c,) = calls
    assert c["url"] == "https://ntfy.sh/my-topic"
    assert c["headers"]["Click"] == "https://example.com/d"
    assert c["headers"]["Priority"] == "high"
    assert c["headers"]["Tags"] == "eyes"
    assert "Authorization" not in c["headers"]

    NtfyNotifier("t").alert(_alert(score=0.82))
    assert calls[-1]["headers"]["Priority"] == "default"


def test_ntfy_digest_splits_under_limit(monkeypatch):
    calls = _capture(monkeypatch)
    alerts = [_alert(score=0.6) for _ in range(60)]
    NtfyNotifier("t", token="tk").digest(alerts, "Deals digest")
    assert len(calls) > 1
    assert all(len(c["data"]) <= NtfyNotifier.MAX_BYTES for c in calls)
    assert calls[0]["headers"]["Title"].decode().endswith(f"(1/{len(calls)})")
    assert calls[0]["headers"]["Authorization"] == "Bearer tk"
    assert sum(c["data"].decode().count("https://example.com/d") for c in calls) == 60


def test_ntfy_enabled_from_env(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "SMTP_USER", "NTFY_SERVER", "NTFY_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NTFY_TOPIC", "abc")
    monkeypatch.setenv("NTFY_SERVER", "")  # unset GitHub secrets arrive as ""
    (n,) = configured_notifiers()
    assert isinstance(n, NtfyNotifier) and n.endpoint == "https://ntfy.sh/abc" and n.token is None
