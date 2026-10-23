"""Subreddit feeds via Reddit's public RSS (no API key). Config:

  - type: reddit
    subreddits: [deals, buildapcsales]
    sort: new          # new | hot | top

All subreddits are fetched as ONE combined feed (r/a+b+c), because Reddit
rate-limits (HTTP 429) unauthenticated clients that make several requests in a
row. Deals link to the Reddit post, so you see the comments (often "expired" or
"better price at X") before clicking through.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import feedparser

from ..models import Deal
from .base import FetchContext, deal_from_entry

log = logging.getLogger(__name__)


def combined_url(subreddits: list[str], sort: str = "new", limit: int = 100) -> str:
    return f"https://www.reddit.com/r/{'+'.join(subreddits)}/{sort}/.rss?limit={limit}"


def _subreddit_of(entry: Any) -> str | None:
    for tag in entry.get("tags") or []:
        term = (tag.get("term") or "").strip()
        if term:
            return term
    return None


def fetch(entry: dict[str, Any], ctx: FetchContext) -> list[Deal]:
    subs = [s.strip().removeprefix("r/") for s in entry.get("subreddits", []) if s.strip()]
    if not subs:
        return []
    url = combined_url(subs, entry.get("sort", "new"), int(entry.get("limit", 100)))

    content = None
    for attempt in range(2):
        try:
            content = ctx.get(url).content
            break
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429 and attempt == 0:
                retry_after = exc.response.headers.get("Retry-After", "")  # type: ignore[union-attr]
                wait = min(int(retry_after) if retry_after.isdigit() else 10, 30)
                log.info("Reddit rate-limited; retrying in %ss", wait)
                time.sleep(wait)
                continue
            # Reddit sometimes refuses datacenter IPs (e.g. GitHub Actions).
            log.warning("Reddit feed failed: %s", exc)
            return []

    deals = []
    for e in feedparser.parse(content).entries:
        sub = _subreddit_of(e)  # label each deal r/deals, r/buildapcsales, ...
        d = deal_from_entry(e, f"r/{sub}" if sub else "reddit")
        if d:
            deals.append(d)
    return deals
