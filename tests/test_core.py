from __future__ import annotations

import json

from dealsgalore.config import GiftProfile, WatchItem
from dealsgalore.models import Candidate, Deal, Scored, parse_prices
from dealsgalore.notifiers import Notifier
from dealsgalore.pipeline import digest, scan
from dealsgalore.prefilter import find_candidates, interest_terms, match_watch
from dealsgalore.scoring import apply_price_history, llm_score, scrub_names
from dealsgalore.sources.base import parse_feed
from dealsgalore.store import Store


class Recorder(Notifier):
    name = "recorder"

    def __init__(self):
        self.alerts, self.digests = [], []

    def alert(self, a):
        self.alerts.append(a)

    def digest(self, alerts, subject):
        self.digests.append((subject, alerts))


def test_parse_prices():
    assert parse_prices("Dyson V15 $449.99 (Reg. $749.99)") == (449.99, 749.99)
    assert parse_prices("Was $1,299 now $999 at Best Buy") == (999.0, 1299.0)
    assert parse_prices("TV $1,099") == (1099.0, None)
    assert parse_prices("No price here") == (None, None)


def test_watch_match_respects_price():
    w = WatchItem(item="Dyson V15", match=["dyson", "v15"], max_price=500)
    assert match_watch(Deal("s", "Dyson V15 Detect $499", "u", price=499), w)
    assert not match_watch(Deal("s", "Dyson V15 Detect $799", "u", price=799), w)
    assert not match_watch(Deal("s", "Dyson V8 $199", "u", price=199), w)


def test_interest_terms_stem_and_filter():
    p = GiftProfile(name="Dad", interests=["history books", "coffee", "art"])
    assert interest_terms(p) == ["book", "coffee", "history"]


def test_parse_feed_and_candidates(feed_xml, cfg):
    deals = parse_feed(feed_xml, "slickdeals")
    assert len(deals) == 4
    for d in deals:
        d.fill_prices()
    cands = find_candidates(deals, cfg.watchlist, cfg.gift_profiles)
    titles = {c.deal.title.split(" ")[0]: c for c in cands}
    assert titles["Dyson"].watch_items == ["Dyson V15 Detect"]
    assert titles["LEGO"].recipients == ["Niece"]
    assert all("Paper" not in c.deal.title for c in cands)


def test_scan_heuristic_end_to_end(feed_xml, cfg, tmp_path):
    store = Store(tmp_path / "deals.json")
    rec = Recorder()
    deals = parse_feed(feed_xml, "slickdeals")
    scored = scan(cfg, store, [rec], deals=deals)

    # old post filtered by age; paper towels never become candidates
    assert len(scored) == 2
    assert len(rec.alerts) == 1 and rec.alerts[0].watch_item == "Dyson V15 Detect"

    saved = json.loads((tmp_path / "deals.json").read_text())
    assert len(saved["deals"]) == 3  # every fresh item is remembered as seen
    assert "Niece" not in json.dumps(saved)  # no private names in the public store
    assert (tmp_path / "docs" / "index.html").exists()

    # Second run: nothing is new, so no duplicate alerts.
    rec2 = Recorder()
    assert scan(cfg, Store(tmp_path / "deals.json"), [rec2], deals=parse_feed(feed_xml, "x")) == []
    assert rec2.alerts == []

    # Digest re-derives the recipient from private profiles and sends once.
    rec3 = Recorder()
    store3 = Store(tmp_path / "deals.json")
    assert digest(cfg, store3, [rec3]) == 2
    recipients = {a.recipient for a in rec3.digests[0][1]}
    assert "Niece" in recipients
    assert digest(cfg, Store(tmp_path / "deals.json"), [Recorder()]) == 0


class FakeLLM:
    available = True
    calls = 0

    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, system, user):
        self.calls += 1
        assert "Niece" in user  # profiles are sent to the model
        return self.payload, "fake"


def test_llm_score_validates_output(cfg):
    cands = [
        Candidate(Deal("s", "LEGO set $30", "u1", price=30), recipients=["Niece"]),
        Candidate(Deal("s", "Dyson V15 $480", "u2", price=480), watch_items=["Dyson V15 Detect"]),
    ]
    llm = FakeLLM({"results": [
        {"idx": 0, "score": 0.9, "recipient": "Niece", "reason": "Niece would love it"},
        {"idx": 1, "score": 7, "watch_item": "Not on list", "price": 470},
        {"idx": 9, "score": 1},
    ]})
    out = llm_score(cands, cfg, llm)
    assert out[0].recipient == "Niece" and out[0].score == 0.9
    assert out[1].score == 1.0 and out[1].watch_item is None
    assert cands[1].deal.price == 470
    assert scrub_names(out[0].reason, cfg.gift_profiles) == "them would love it"


def test_price_history_penalizes_fake_discount(cfg, tmp_path):
    store = Store(tmp_path / "d.json")
    for p in (430, 440, 450):
        store.record_price("Dyson V15 Detect", p, "x")
    c = Candidate(Deal("s", "Dyson V15 $480", "u", price=480), watch_items=["Dyson V15 Detect"])
    s = Scored(c, score=0.9, watch_item="Dyson V15 Detect")
    apply_price_history(s, cfg, store)
    assert s.score < 0.7 and "median" in s.price_note


def test_heuristic_demotes_priceless_posts(cfg):
    from dealsgalore.scoring import heuristic_score

    q = Candidate(Deal("r/BuyItForLife", "In search of durable luggage", "u"), recipients=["Niece"])
    assert heuristic_score(q, cfg).score < cfg.settings.digest_threshold
    d = Candidate(Deal("s", "LEGO set $39.99", "u2", price=39.99), recipients=["Niece"])
    assert heuristic_score(d, cfg).score >= cfg.settings.digest_threshold


def test_heuristic_demotes_priceless_watchlist_hits(cfg):
    from dealsgalore.scoring import heuristic_score

    news = Candidate(Deal("news", "Watch live: Hamilton debate tonight", "u"),
                     watch_items=["Dyson V15 Detect"])
    assert heuristic_score(news, cfg).score < cfg.settings.digest_threshold
