"""Specific product pages you want tracked (e.g. a sale found by hand). Config:

  - type: pages
    name: tracked
    items:
      - url: https://www.macys.com/shop/product/...
        title: Fossil Men's Grant Chronograph Stainless Steel Watch 44mm
        store: Macy's
        price: 97.50          # last confirmed price (fallback)
        was: 195.00           # regular price, for the discount
        checked: 2026-10-23   # when that price was confirmed

Each scan fetches the page and reads its schema.org Product data (the
structured data stores publish for search engines) to refresh the price and
stock status. If the store blocks the request, the last confirmed price is
shown with its date, so the item never silently disappears.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterator

from ..models import Deal
from .base import FetchContext

log = logging.getLogger(__name__)
MAX_FALLBACK_DAYS = 7
_LD_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _is_product(node: dict) -> bool:
    t = node.get("@type")
    return t == "Product" or (isinstance(t, list) and "Product" in t)


def read_offer(html_text: str) -> tuple[float | None, bool | None]:
    """(lowest offered price, in_stock) from a page's schema.org Product data.

    Only a page describing exactly ONE product counts; a listing page with many
    products returns (None, None) so the confirmed price is kept instead.
    """
    prices: list[float] = []
    stock: list[bool] = []
    products = 0
    for block in _LD_RE.findall(html_text or ""):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for node in _walk(data):
            if not _is_product(node):
                continue
            products += 1
            for offer in _walk(node.get("offers") or []):
                for key in ("price", "lowPrice"):
                    try:
                        value = float(str(offer.get(key, "")).replace(",", "").replace("$", ""))
                    except ValueError:
                        continue
                    if value > 0:
                        prices.append(value)
                avail = str(offer.get("availability", ""))
                if avail:
                    stock.append("InStock" in avail or "LimitedAvailability" in avail)
    if products != 1:
        return None, None
    return (min(prices) if prices else None), (any(stock) if stock else None)


def fetch(entry: dict[str, Any], ctx: FetchContext) -> list[Deal]:
    source = entry.get("name", "tracked")
    now = datetime.now(timezone.utc)
    deals = []
    for item in entry.get("items", []):
        url, title = item["url"], item["title"]
        price = float(item["price"]) if item.get("price") is not None else None
        was = float(item["was"]) if item.get("was") is not None else None
        checked = str(item.get("checked", ""))
        note = f"price confirmed {checked or 'earlier'}; couldn't re-check this scan"
        try:
            live, in_stock = read_offer(ctx.get(url).text)
            if in_stock is False:
                log.info("Tracked page out of stock: %s", title)
                continue
            if live:
                price, note = live, "price checked on the store page this scan"
        except Exception as exc:
            log.info("Tracked page not re-checked (%s): %s", title, exc)
        if note.startswith("price confirmed") and checked:
            # Don't show a hand-confirmed price forever.
            try:
                age = (now.date() - datetime.fromisoformat(checked).date()).days
            except ValueError:
                age = 0
            if age > MAX_FALLBACK_DAYS:
                log.warning("Tracked item %r: price not confirmed for %d days; hidden", title, age)
                continue
        if price is None:
            continue
        label = f"{title} ${price:,.2f}" + (f" (was ${was:,.2f})" if was and was > price else "")
        deals.append(Deal(
            source=source, title=label, url=url, published=now, summary=note, note=note,
            price=price, list_price=was, id_salt=f"{price:.2f}", store=item.get("store"),
        ))
    return deals
