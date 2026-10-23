"""Slickdeals RSS. Config:

  - type: slickdeals
    feeds: [frontpage, popular]
    search_watchlist: true   # also run a Slickdeals search for every watchlist item
    searches: ["lego star wars"]  # extra free-text searches
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from ..models import Deal
from .base import FetchContext, fetch_feed

log = logging.getLogger(__name__)

BASE = "https://slickdeals.net/newsearch.php"
FEEDS = {
    "frontpage": f"{BASE}?mode=frontpage&searcharea=deals&searchin=first&rss=1",
    "popular": f"{BASE}?mode=popdeals&searcharea=deals&searchin=first&rss=1",
}


def search_url(query: str) -> str:
    return f"{BASE}?q={quote_plus(query)}&searcharea=deals&searchin=first&rss=1"


def fetch(entry: dict[str, Any], ctx: FetchContext) -> list[Deal]:
    urls: list[tuple[str, str]] = []
    for name in entry.get("feeds", ["frontpage"]):
        if name in FEEDS:
            urls.append((FEEDS[name], f"slickdeals:{name}"))
        else:
            log.warning("Unknown Slickdeals feed %r", name)
    queries = list(entry.get("searches", []))
    if entry.get("search_watchlist", True):
        queries += [w.query for w in ctx.watchlist if w.query]
    for q in queries:
        urls.append((search_url(q), "slickdeals:search"))

    deals: list[Deal] = []
    for url, source in urls:
        try:
            deals.extend(fetch_feed(url, source, ctx))
        except Exception as exc:
            log.warning("Slickdeals %s failed: %s", source, exc)
    return deals
