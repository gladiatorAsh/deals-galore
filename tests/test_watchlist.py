from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from dealsgalore.config import load_config
from dealsgalore.watchlist import (
    add_to_config, clean_title, issue_body, new_issue_url, parse_issue_body, suggest_match,
)

ROOT = Path(__file__).parent.parent
TITLE = "KitchenAid Deluxe 4.5 Quart Tilt-Head Stand Mixer (Contour Silver) $299.99 + Free Shipping"


def test_clean_title_and_match():
    assert clean_title(TITLE) == "KitchenAid Deluxe 4.5 Quart Tilt-Head Stand Mixer"
    assert suggest_match(TITLE) == ["kitchenaid", "deluxe", "quart"]
    assert suggest_match("[Refurbished] Intel ARC A750 8GB $159") == ["intel", "arc", "a750"]


def test_issue_url_roundtrip():
    url = new_issue_url("me/repo", TITLE, 299.99)
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://github.com/me/repo/issues/new?")
    assert q["title"][0].startswith("Watch: KitchenAid")
    entry = parse_issue_body(q["body"][0])
    assert entry == {"item": "KitchenAid Deluxe 4.5 Quart Tilt-Head Stand Mixer",
                     "max_price": 299.99, "match": ["kitchenaid", "deluxe", "quart"]}


def test_parse_rejects_garbage():
    for bad in ("", "hello", "```yaml\nitem: ''\n```", "```yaml\nitem: x\nmax_price: -5\n```"):
        with pytest.raises(ValueError):
            parse_issue_body(bad)


def test_add_to_config_preserves_comments_and_dedupes(tmp_path):
    cfg = tmp_path / "config.yaml"
    shutil.copy(ROOT / "config.yaml", cfg)
    before = cfg.read_text()
    entry = parse_issue_body(issue_body(TITLE, 279.0))
    assert "Added" in add_to_config(cfg, entry)
    after = cfg.read_text()
    # every original line kept (comments included), and still loads
    assert all(line in after.splitlines() for line in before.splitlines())
    items = [w.item for w in load_config(cfg).watchlist]
    assert items[-1] == "KitchenAid Deluxe 4.5 Quart Tilt-Head Stand Mixer"
    assert load_config(cfg).watchlist[-1].max_price == 279
    assert "dashboard" in yaml.safe_load(after)  # following section intact
    assert "already" in add_to_config(cfg, entry)
    assert cfg.read_text() == after


def test_add_to_empty_watchlist(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("settings: {}\nwatchlist: []\n\ndashboard:\n  enabled: true\n")
    add_to_config(cfg, {"item": "Thing: with colon", "max_price": None, "match": ["thing"]})
    data = yaml.safe_load(cfg.read_text())
    assert data["watchlist"] == [{"item": "Thing: with colon", "match": ["thing"]}]
    assert data["dashboard"] == {"enabled": True}


def test_dashboard_has_watch_buttons(tmp_path):
    from dealsgalore import dashboard
    from dealsgalore.store import Store

    st = Store(tmp_path / "d.json")
    st.add_deal("a", {"title": TITLE, "url": "https://x", "source": "slickdeals:frontpage",
                      "price": 299.99, "score": 0.0})
    st.add_deal("b", {"title": "Dyson V15 $449", "url": "https://y", "source": "s", "price": 449.0,
                      "score": 0.9, "watch_item": "Dyson V15 Detect", "fp": "f"})
    out = dashboard.render(st, tmp_path / "i.html", 0.5, 10, fp="f",
                           browse_sources=["slickdeals:frontpage"], repo="me/repo").read_text()
    assert out.count('class="watch"') == 2
    assert "https://github.com/me/repo/issues/new?title=Watch%3A%20KitchenAid" in out
    # one list: top pick first, then other deals; chips only for categories present
    assert out.index("Dyson V15 $449") < out.index("KitchenAid")
    assert 'data-c="Dyson V15 Detect"' in out and 'data-c="Other deals"' in out
    assert "Gift ideas" not in out
    assert "PDT" in out or "PST" in out


def test_dashboard_hides_items_no_longer_listed(tmp_path):
    from datetime import datetime, timedelta, timezone

    from dealsgalore import dashboard
    from dealsgalore.store import Store

    st = Store(tmp_path / "d.json")
    old = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat(timespec="seconds")
    st.add_deal("gone", {"title": "Gone tote $150", "url": "https://g", "source": "s", "price": 150.0,
                         "score": 0.9, "fp": "f", "watch_item": "Bags", "last_seen": old})
    st.add_deal("live", {"title": "Live tote $150", "url": "https://l", "source": "s", "price": 150.0,
                         "score": 0.9, "fp": "f", "watch_item": "Bags"})
    out = dashboard.render(st, tmp_path / "i.html", 0.5, 10, fp="f").read_text()
    assert "Live tote" in out and "Gone tote" not in out


def test_dashboard_hides_rejected_matches(tmp_path):
    from dealsgalore import dashboard
    from dealsgalore.store import Store

    st = Store(tmp_path / "d.json")
    st.add_deal("scam", {"title": "Omega Speedmaster $250", "url": "https://s", "source": "r", "price": 250.0,
                         "score": 0.1, "fp": "f", "candidate": True, "match_hint": "Watches"})
    st.add_deal("ok", {"title": "Seiko Presage $350", "url": "https://o", "source": "r", "price": 350.0,
                       "score": 0.45, "fp": "f", "candidate": True, "match_hint": "Watches"})
    out = dashboard.render(st, tmp_path / "i.html", 0.5, 10, fp="f", browse_only_matches=True).read_text()
    assert "Seiko Presage" in out and "Speedmaster" not in out


def test_exclusions_check_titles_only():
    from dealsgalore.models import Deal
    from dealsgalore.prefilter import is_excluded

    ex = ["bag strap", "– accessory"]
    assert is_excluded(Deal("s", "Celine Logo Bag Strap – Accessory $446", "u"), ex)
    assert not is_excluded(Deal("s", "Coach Tabby 26 $295", "u", summary="Detachable bag strap"), ex)


def test_dashboard_caps_cards_per_store_except_tracked(tmp_path):
    from dealsgalore import dashboard
    from dealsgalore.store import Store

    st = Store(tmp_path / "d.json")
    for i in range(12):
        st.add_deal(f"d{i}", {"title": f"Dooney bag {i} $109", "url": f"https://d/{i}", "source": "brand:dooney",
                              "store": "Dooney & Bourke", "price": 109.0, "score": 0.8, "fp": "f",
                              "watch_item": "Women's bag"})
    for i in range(10):
        st.add_deal(f"t{i}", {"title": f"Rack pick {i} $120", "url": f"https://r/{i}", "source": "tracked",
                              "store": "Nordstrom Rack", "price": 120.0, "score": 0.7, "fp": "f",
                              "watch_item": "Women's bag"})
    out = dashboard.render(st, tmp_path / "i.html", 0.5, 50, fp="f", max_per_store=8).read_text()
    assert out.count("Dooney bag") == 8 and out.count("Rack pick") == 10
    assert "18 deals" in out
