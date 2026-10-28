"""Fetchers: Hugging Face Daily Papers, the arXiv API, and RSS blogs."""
from __future__ import annotations

import calendar
import hashlib
import html
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote

import feedparser

from .models import Paper

log = logging.getLogger(__name__)
ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", text or ""))).strip()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def hf_daily(entry: dict[str, Any], get: Callable[[str], Any]) -> list[Paper]:
    data = get(f"https://huggingface.co/api/daily_papers?limit={int(entry.get('limit', 100))}").json()
    out = []
    for row in data if isinstance(data, list) else []:
        p = row.get("paper") or {}
        pid = p.get("id")
        if not pid or not p.get("title"):
            continue
        published = _parse_ts(p.get("publishedAt")) or _parse_ts(row.get("publishedAt"))
        org = (p.get("organization") or row.get("organization") or {}).get("fullname")
        out.append(Paper(
            id=f"arxiv:{pid}", title=_clean(p["title"]), abstract=_clean(p.get("summary")),
            url=f"https://arxiv.org/abs/{pid}", pdf=f"https://arxiv.org/pdf/{pid}",
            authors=[a.get("name", "") for a in p.get("authors") or [] if a.get("name")],
            org=org, published=_iso(published) if published else None, source="HF Daily Papers",
            upvotes=int(p.get("upvotes") or 0), hf_url=f"https://huggingface.co/papers/{pid}",
            code=p.get("githubRepo"), project=p.get("projectPage"),
            summary_hint=_clean(p.get("ai_summary")) or None, kind="paper",
        ))
    return out


def arxiv(entry: dict[str, Any], get: Callable[[str], Any], pause: float = 3.0) -> list[Paper]:
    out: list[Paper] = []
    n = int(entry.get("max_results", 200))
    for i, q in enumerate(entry.get("queries") or []):
        if i:
            time.sleep(pause)  # arXiv asks for ~3 seconds between API calls
        url = ("https://export.arxiv.org/api/query?search_query=" + quote(q, safe=":()\"")
               + f"&sortBy=submittedDate&sortOrder=descending&max_results={n}")
        try:
            feed = feedparser.parse(get(url).content)
        except Exception as exc:
            log.warning("arXiv query failed (%s): %s", q, exc)
            continue
        for e in feed.entries:
            m = ARXIV_ID.search(e.get("id", ""))
            if not m:
                continue
            pid = m.group(1)
            ts = e.get("published_parsed")
            out.append(Paper(
                id=f"arxiv:{pid}", title=_clean(e.get("title")), abstract=_clean(e.get("summary")),
                url=f"https://arxiv.org/abs/{pid}", pdf=f"https://arxiv.org/pdf/{pid}",
                authors=[a.get("name", "") for a in e.get("authors", []) if a.get("name")],
                published=_iso(datetime.fromtimestamp(calendar.timegm(ts), timezone.utc)) if ts else None,
                source="arXiv", category=(e.get("arxiv_primary_category") or {}).get("term"),
                kind="paper",
            ))
    return out


def rss(entry: dict[str, Any], get: Callable[[str], Any]) -> list[Paper]:
    out = []
    for name, url in (entry.get("feeds") or {}).items():
        try:
            feed = feedparser.parse(get(url).content)
        except Exception as exc:
            log.warning("Feed %s failed: %s", name, exc)
            continue
        for e in feed.entries:
            link = e.get("link")
            if not link or not e.get("title"):
                continue
            ts = e.get("published_parsed") or e.get("updated_parsed")
            m = ARXIV_ID.search(link) if "arxiv.org" in link else None
            out.append(Paper(
                id=f"arxiv:{m.group(1)}" if m else "post:" + hashlib.sha1(link.encode()).hexdigest()[:16],
                title=_clean(e.get("title")), abstract=_clean(e.get("summary"))[:1500], url=link,
                published=_iso(datetime.fromtimestamp(calendar.timegm(ts), timezone.utc)) if ts else None,
                source=name, org=name, kind="blog",
            ))
    return out


FETCHERS = {"hf_daily": hf_daily, "arxiv": arxiv, "rss": rss}


def fetch_all(sources: list[dict[str, Any]], get: Callable[[str], Any],
              lookback_days: int, now: datetime | None = None) -> tuple[list[Paper], dict[str, Any]]:
    """Fetch every source, drop old items, and merge duplicates (same arXiv id)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    merged: dict[str, Paper] = {}
    report: dict[str, Any] = {}
    for entry in sources:
        kind = entry.get("type")
        label = entry.get("name") or kind
        fn = FETCHERS.get(kind)
        if not fn:
            log.warning("Unknown paper source type %r", kind)
            continue
        try:
            items = fn(entry, get)
        except Exception as exc:
            log.warning("Source %s failed: %s", label, exc)
            report[label] = f"failed: {exc}"
            continue
        fresh = [p for p in items if not p.published or _parse_ts(p.published) >= cutoff]
        if kind == "rss":  # one line per feed, so a dead feed shows up as 0
            for name in entry.get("feeds") or {}:
                report[name] = sum(1 for p in fresh if p.source == name)
        else:
            report[label] = len(fresh)
        for p in fresh:
            merged[p.id] = merged[p.id].merge(p) if p.id in merged else p
    return list(merged.values()), report
