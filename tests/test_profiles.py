from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml

from dealsgalore.config import GiftProfile, _parse_profiles
from dealsgalore.models import Deal
from dealsgalore.prefilter import match_profile

EXAMPLE = Path(__file__).parent.parent / "gifts.example.yaml"

COUPLE = GiftProfile(
    name="Brother & his wife",
    keywords=["le creuset", "dutch oven", "stand mixer"],
    interests=["cookware", "espresso"],
    budget=(100, 400),
)


def _d(title: str, price: float | None) -> Deal:
    return Deal("s", title, "u", price=price)


def test_keyword_phrases_match_whole_phrase():
    assert match_profile(_d("Le Creuset 5.5 qt Signature Dutch Oven $279", 279), COUPLE)
    assert match_profile(_d("Lodge Dutch-Ovens 2-pack $129", 129), COUPLE)
    assert match_profile(_d("KitchenAid Artisan Stand Mixer $299", 299), COUPLE)
    # "stand" alone must not match a standing desk, nor "oven" a toaster oven
    assert not match_profile(_d("Flexispot standing desk $199", 199), COUPLE)
    assert not match_profile(_d("Toaster oven $120", 120), COUPLE)


def test_budget_still_applies():
    assert not match_profile(_d("Le Creuset dutch oven $29 mini", 29), COUPLE)
    assert not match_profile(_d("All-Clad cookware 14pc $999", 999), COUPLE)


def test_expired_profiles_are_dropped():
    past = (date.today() - timedelta(days=1)).isoformat()
    future = (date.today() + timedelta(days=30)).isoformat()
    profiles = _parse_profiles({"gift_profiles": [
        {"name": "Old", "interests": ["lego"], "until": past},
        {"name": "Wedding", "interests": ["cookware"], "until": future, "occasion": "wedding"},
        {"name": "Always", "interests": ["coffee"]},
    ]})
    assert [p.name for p in profiles] == ["Wedding", "Always"]
    assert profiles[0].occasion == "wedding" and profiles[0].until is not None


def test_example_file_parses():
    data = yaml.safe_load(EXAMPLE.read_text())
    for p in data["gift_profiles"]:
        p.pop("until", None)  # keep this test independent of today's date
    profiles = _parse_profiles(data)
    assert profiles[0].name == "Brother & his wife"
    assert profiles[0].budget == (100.0, 400.0)


def test_watch_item_any_of_groups():
    from dealsgalore.config import WatchItem
    from dealsgalore.prefilter import match_watch

    w = WatchItem(item="Good watch", search=False,
                  any_of=[["seiko", "tag heuer"], ["watch", "chronograph"]])
    assert w.query is None and w.match == []
    assert match_watch(_d("Seiko Presage Automatic Watches $299", 299), w)
    assert match_watch(_d("TAG Heuer Formula 1 Chronograph $999", 999), w)
    assert not match_watch(_d("Seiko clock $40", 40), w)          # missing kind word
    assert not match_watch(_d("Apple Watch SE $199", 199), w)     # missing brand


def test_premium_brand_detection_and_boost(tmp_path):
    from dealsgalore.config import WatchItem
    from dealsgalore.scoring import premium_brand

    brands = ["omega", "tag heuer", "gucci", "saint laurent"]
    assert premium_brand("TAG Heuer Carrera Chronograph $2,400", brands) == "tag heuer"
    assert premium_brand("Saint Laurent Loulou bag $1,690", brands) == "saint laurent"
    assert premium_brand("Seiko 5 Sports $189", brands) is None


def test_watch_item_price_range():
    from dealsgalore.config import WatchItem
    from dealsgalore.prefilter import match_watch

    w = WatchItem(item="Watches", min_price=100, max_price=500, search=False,
                  any_of=[["seiko", "omega"], ["watch"]])
    assert match_watch(_d("Seiko Presage watch $349", 349), w)
    assert match_watch(_d("Seiko watch $500", 500), w)
    assert not match_watch(_d("Seiko 5 watch $89", 89), w)        # too cheap
    assert not match_watch(_d("Omega Seamaster watch $3,900", 3900), w)  # over budget
    assert not match_watch(_d("Seiko watch $520", 520), w)        # no headroom above max
    assert match_watch(_d("Omega watch sale this weekend", None), w)  # price unknown: scorer decides


def test_scored_price_outside_range_is_demoted(tmp_path):
    from dealsgalore.config import Config, Settings, WatchItem
    from dealsgalore.models import Candidate, Scored
    from dealsgalore.scoring import apply_price_history
    from dealsgalore.store import Store

    w = WatchItem(item="Watches", min_price=100, max_price=500, search=False, any_of=[["seiko"]])
    cfg = Config(Settings(), [], [w], [], [], {})
    s = Scored(Candidate(_d("Seiko watch", 1695), watch_items=["Watches"]), score=0.9, watch_item="Watches")
    apply_price_history(s, cfg, Store(tmp_path / "d.json"))
    assert s.score == 0.2 and "budget" in s.price_note


def test_price_from_summary_and_require_price():
    from dealsgalore.config import WatchItem
    from dealsgalore.models import Deal
    from dealsgalore.prefilter import match_watch

    d = Deal("r/Watchexchange", "[WTS] Rolex GMT Master II Batgirl 126710BLNR", "u",
             summary="Full set, 2023 card. Asking $14,250 shipped CONUS.")
    d.fill_prices()
    assert d.price == 14250.0
    w = WatchItem(item="Watches", min_price=100, max_price=500, require_price=True,
                  search=False, any_of=[["rolex", "seiko"]])
    assert not match_watch(d, w)  # over budget, now that the price is known
    assert not match_watch(Deal("news", "Seiko watch sale this weekend", "u"), w)  # no price
    ok = Deal("r/Watchexchange", "[WTS] Seiko SPB143", "u", summary="Price: $450")
    ok.fill_prices()
    assert match_watch(ok, w)


def test_implausibly_cheap_luxury_is_demoted(tmp_path):
    from dealsgalore.config import Config, Settings, WatchItem
    from dealsgalore.models import Candidate, Scored
    from dealsgalore.scoring import score_candidates
    from dealsgalore.store import Store

    class NoLLM:
        available = False
        calls = 0
        providers: list = []

    w = WatchItem(item="Watches", search=False, any_of=[["omega", "seiko"], ["watch", "wts"]])
    cfg = Config(Settings(), [], [w], [], [], {}, premium_brands=["omega"],
                 plausible_min={"omega": 900})
    cands = [
        Candidate(_d("[WTS] Omega Speedmaster Moonwatch $250", 250), watch_items=["Watches"]),
        Candidate(_d("[WTS] Omega x Swatch Mission to the Moon $260", 260), watch_items=["Watches"]),
        Candidate(_d("[WTS] Seiko Presage watch $250", 250), watch_items=["Watches"]),
    ]
    by_title = {s.deal.title: s for s in score_candidates(cands, cfg, NoLLM(), Store(tmp_path / "d.json"))}
    assert by_title["[WTS] Omega Speedmaster Moonwatch $250"].score == 0.1
    assert "implausibly low" in by_title["[WTS] Omega Speedmaster Moonwatch $250"].price_note
    assert by_title["[WTS] Omega x Swatch Mission to the Moon $260"].score > 0.3
    assert by_title["[WTS] Seiko Presage watch $250"].score > 0.3
