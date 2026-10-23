"""Generic RSS/Atom feed. Config:

  - type: rss
    name: my-feed
    url: https://example.com/deals.rss
"""
from __future__ import annotations

from typing import Any

from ..models import Deal
from .base import FetchContext, fetch_feed


def fetch(entry: dict[str, Any], ctx: FetchContext) -> list[Deal]:
    urls = entry.get("urls") or [entry["url"]]
    name = entry.get("name", "rss")
    deals: list[Deal] = []
    for url in urls:
        deals.extend(fetch_feed(url, name, ctx))
    return deals
