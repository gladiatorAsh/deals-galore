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


def test_describe_token_problem():
    from dealsgalore.notifiers import describe_token_problem

    good = "123456789:" + "A" * 35
    assert describe_token_problem(good) is None
    assert describe_token_problem(f"bot{good}\n") is None
    assert "no ':'" in describe_token_problem("123456789")  # chat id pasted
    assert "unexpected characters" in describe_token_problem("<123456789:" + "A" * 35 + ">")
    assert "is 5 characters" in describe_token_problem("123456789:AAAAA")
    assert good not in (describe_token_problem("x" + good) or "")


def test_config_change_rechecks_recent_deals_without_duplicate_alerts(feed_xml, cfg, tmp_path):
    from dealsgalore.config import GiftProfile
    from dealsgalore.pipeline import scan
    from dealsgalore.sources.base import parse_feed
    from dealsgalore.store import Store
    from test_core import Recorder

    path = tmp_path / "deals.json"
    cfg.gift_profiles = []  # first run: no profiles yet
    rec = Recorder()
    stats: dict = {}
    scan(cfg, Store(path), [rec], deals=parse_feed(feed_xml, "s"), stats=stats)
    assert stats["new"] == 3 and stats["rechecked"] == 0 and len(rec.alerts) == 1  # Dyson

    # Same config: nothing to do.
    stats = {}
    scan(cfg, Store(path), [Recorder()], deals=parse_feed(feed_xml, "s"), stats=stats)
    assert stats["new"] == 0 and stats["rechecked"] == 0

    # Add a profile: recent posts are re-checked, LEGO now matches, Dyson not re-alerted.
    cfg.gift_profiles = [GiftProfile(name="Niece", interests=["lego"], budget=(25, 60))]
    rec3, stats = Recorder(), {}
    scored = scan(cfg, Store(path), [rec3], deals=parse_feed(feed_xml, "s"), stats=stats)
    assert stats["new"] == 0 and stats["rechecked"] == 3 and stats["profiles"] == 1
    assert any(s.recipient == "Niece" or "Niece" in s.candidate.recipients for s in scored)
    assert rec3.alerts == []
    store = Store(path)
    assert len(store.prices["Dyson V15 Detect"]) == 1  # price not double-counted


def test_detect_store():
    from dealsgalore.models import detect_store

    stores = ["Costco", "Nordstrom", "Nordstrom Rack", "Macy's", "Coach Outlet", "Target"]
    assert detect_store("Seiko 5 Automatic $189 at Nordstrom Rack", stores) == "Nordstrom Rack"
    assert detect_store("Citizen Eco-Drive $99 @ Costco (in-warehouse)", stores) == "Costco"
    assert detect_store("Coach tote $150 at Macy’s", stores) == "Macy's"
    assert detect_store("Coach Outlet: Willow tote $129", stores) == "Coach Outlet"
    assert detect_store("Fossil watch $59", stores) is None
    # "at X" beats an earlier incidental mention
    assert detect_store("Target-free shipping... Kate Spade bag $99 at Costco", stores) == "Costco"
