from __future__ import annotations

import calendar
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import feedparser
import requests

from ..config import WatchItem
from ..models import Deal

log = logging.getLogger(__name__)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class FetchContext:
    user_agent: str = "deals-galore/0.1"
    timeout: float = 20
    watchlist: list[WatchItem] = field(default_factory=list)
    session: requests.Session | None = None

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        sess = self.session or requests
        resp = sess.get(
            url,
            headers={"User-Agent": self.user_agent, **kwargs.pop("headers", {})},
            timeout=self.timeout,
            **kwargs,
        )
        resp.raise_for_status()
        return resp


def strip_html(text: str, limit: int = 500) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def entry_time(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    return None


def deal_from_entry(e: Any, source: str) -> Deal | None:
    link = e.get("link")
    title = strip_html(e.get("title", ""), 300)
    if not link or not title:
        return None
    summary = e.get("summary", "")
    if not summary and e.get("content"):
        summary = e["content"][0].get("value", "")
    return Deal(
        source=source,
        title=title,
        url=link,
        published=entry_time(e),
        summary=strip_html(summary),
    )


def parse_feed(content: bytes | str, source: str) -> list[Deal]:
    feed = feedparser.parse(content)
    return [d for e in feed.entries if (d := deal_from_entry(e, source))]


def fetch_feed(url: str, source: str, ctx: FetchContext) -> list[Deal]:
    resp = ctx.get(url)
    return parse_feed(resp.content, source)
