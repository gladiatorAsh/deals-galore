"""Subreddit feeds via Reddit's public RSS (no API key). Config:

  - type: reddit
    subreddits: [deals, buildapcsales]
    sort: new          # new | hot | top

Deals link to the Reddit post, so you see the comments (often "expired" or
"better price at X") before clicking through.
"""
from __future__ import annotations

import logging
from typing import Any

from ..models import Deal
from .base import FetchContext, fetch_feed

log = logging.getLogger(__name__)


def fetch(entry: dict[str, Any], ctx: FetchContext) -> list[Deal]:
    sort = entry.get("sort", "new")
    deals: list[Deal] = []
    for sub in entry.get("subreddits", []):
        url = f"https://www.reddit.com/r/{sub}/{sort}/.rss"
        try:
            deals.extend(fetch_feed(url, f"r/{sub}", ctx))
        except Exception as exc:
            # Reddit sometimes refuses datacenter IPs (e.g. GitHub Actions).
            log.warning("r/%s failed: %s", sub, exc)
    return deals
