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
