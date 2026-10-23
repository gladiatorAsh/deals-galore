"""Brand stores built on Shopify: read their public sale collection. Config:

  - type: shopify
    name: brand-sales
    stores:
      - url: https://www.mzwallace.com
        collection: sale            # optional; default "sale"
      - https://www.dagnedover.com  # shorthand

Only discounted products (compare_at_price above price) become deals, with the
real sale and original prices. Titles are prefixed with the brand (Shopify's
"vendor") and the product type, so watchlist rules like "a Coach ... bag" work
even when the product name is just "Landon Carryall". A deal's id includes its
price, so you're alerted again only when the price changes.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from ..models import Deal
from .base import FetchContext, strip_html

log = logging.getLogger(__name__)


def _money(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _store_name(base: str) -> str:
    host = urlparse(base).netloc.lower().removeprefix("www.").removeprefix("us.").removeprefix("shop.")
    return host.split(".")[0]


def products_to_deals(products: list[dict[str, Any]], base: str, source: str,
                      store_label: str | None = None) -> list[Deal]:
    now = datetime.now(timezone.utc)
    deals = []
    for p in products:
        best: tuple[float, float] | None = None
        for v in p.get("variants") or []:
            if v.get("available") is False:
                continue
            price, was = _money(v.get("price")), _money(v.get("compare_at_price"))
            if price and was and was > price and (best is None or price < best[0]):
                best = (price, was)
        if not best or not p.get("handle"):
            continue
        price, was = best
        vendor = html.unescape(p.get("vendor") or "").strip()
        name = html.unescape(p.get("title") or "").strip()
        ptype = html.unescape(p.get("product_type") or "").strip()
        label = name if vendor and vendor.lower() in name.lower() else f"{vendor} {name}".strip()
        if ptype and ptype.lower() not in label.lower():
            label = f"{label} – {ptype}"
        deals.append(Deal(
            source=source,
            title=f"{label} ${price:,.2f} (was ${was:,.2f})",
            url=f"{base}/products/{p['handle']}",
            published=now,
            summary=strip_html(p.get("body_html") or "", 300),
            price=price,
            list_price=was,
            id_salt=f"{price:.2f}",
            store=store_label or vendor or None,
        ))
    return deals


def fetch(entry: dict[str, Any], ctx: FetchContext) -> list[Deal]:
    source = entry.get("name", "shopify")
    deals: list[Deal] = []
    for raw in entry.get("stores", []):
        spec = {"url": raw} if isinstance(raw, str) else dict(raw)
        base = spec["url"].rstrip("/")
        collection = spec.get("collection", "sale")
        label = spec.get("label")
        paths = [f"{base}/collections/{collection}/products.json", f"{base}/products.json"]
        for path in paths:
            try:
                data = ctx.get(path, params={"limit": 250}).json()
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 404 and path != paths[-1]:
                    continue  # no such collection: fall back to all products
                log.warning("Shopify store %s failed: %s", _store_name(base), exc)
                break
            found = products_to_deals(data.get("products") or [], base,
                                      f"{source}:{_store_name(base)}", label)
            deals.extend(found)
            break
    return deals
