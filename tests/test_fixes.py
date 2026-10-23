from __future__ import annotations

import requests

from dealsgalore.notifiers import TelegramNotifier
from dealsgalore.sources import reddit
from dealsgalore.sources.base import FetchContext

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><category term="deals" label="r/deals"/><title>Le Creuset Dutch Oven $199</title>
<link href="https://www.reddit.com/r/deals/comments/a1/x/"/><updated>2026-10-22T10:00:00+00:00</updated>
<content type="html">deal</content></entry>
<entry><category term="buildapcsales" label="r/buildapcsales"/><title>[GPU] Something $299</title>
<link href="https://www.reddit.com/r/buildapcsales/comments/b2/y/"/><updated>2026-10-22T10:00:00+00:00</updated>
<content type="html">gpu</content></entry>
<entry><title>no link entry</title></entry>
</feed>"""


def test_clean_token_forgives_paste_mistakes():
    good = "123456789:AAHfx9kQ2-example"
    for raw in (good, f" {good}\n", f'"{good}"', f"bot{good}",
                f"https://api.telegram.org/bot{good}/getUpdates"):
        assert TelegramNotifier.clean_token(raw) == good
    n = TelegramNotifier(f"bot{good}\n", " 42\n")
    assert n.url == f"https://api.telegram.org/bot{good}/sendMessage" and n.chat_id == "42"


class _Resp:
    def __init__(self, status, content=b"", headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class _Session:
    def __init__(self, responses):
        self.responses, self.urls = list(responses), []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.responses.pop(0)


def test_reddit_single_combined_request_labels_subreddits(monkeypatch):
    sess = _Session([_Resp(200, ATOM.encode())])
    ctx = FetchContext(session=sess)
    deals = reddit.fetch({"subreddits": ["deals", "r/buildapcsales"]}, ctx)
    assert sess.urls == ["https://www.reddit.com/r/deals+buildapcsales/new/.rss?limit=100"]
    assert [d.source for d in deals] == ["r/deals", "r/buildapcsales"]


def test_reddit_retries_once_on_429(monkeypatch):
    monkeypatch.setattr(reddit.time, "sleep", lambda s: None)
    sess = _Session([_Resp(429, headers={"Retry-After": "3"}), _Resp(200, ATOM.encode())])
    deals = reddit.fetch({"subreddits": ["deals"]}, FetchContext(session=sess))
    assert len(sess.urls) == 2 and len(deals) == 2

    sess = _Session([_Resp(429), _Resp(429)])
    assert reddit.fetch({"subreddits": ["deals"]}, FetchContext(session=sess)) == []
