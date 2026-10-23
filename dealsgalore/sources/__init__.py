"""Source adapters. Each adapter turns one config entry into a list of Deals.

To add a new kind of source, write a function `fetch(entry, ctx) -> list[Deal]`
and register it in ADAPTERS below.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from ..models import Deal
from . import bestbuy, reddit, rss, shopify, slickdeals
from .base import FetchContext

log = logging.getLogger(__name__)

ADAPTERS: dict[str, Callable[[dict[str, Any], FetchContext], list[Deal]]] = {
    "rss": rss.fetch,
    "reddit": reddit.fetch,
    "slickdeals": slickdeals.fetch,
    "bestbuy": bestbuy.fetch,
    "shopify": shopify.fetch,
}


def fetch_all(entries: list[dict[str, Any]], ctx: FetchContext) -> list[Deal]:
    deals: list[Deal] = []
    for entry in entries:
        if entry.get("enabled", True) is False:
            continue
        kind = entry.get("type")
        adapter = ADAPTERS.get(kind)
        if not adapter:
            log.warning("Unknown source type %r, skipping", kind)
            continue
        try:
            found = adapter(entry, ctx)
            log.info("%s: %d items", entry.get("name") or kind, len(found))
            deals.extend(found)
        except Exception as exc:  # one bad source must not sink the run
            log.warning("Source %s failed: %s", entry.get("name") or kind, exc)
    return deals


__all__ = ["ADAPTERS", "FetchContext", "fetch_all"]
