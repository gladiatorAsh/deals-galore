"""Best Buy Products API (free key from developer.bestbuy.com). Config:

  - type: bestbuy
    skus: [6505727, 6522371]

Requires the BESTBUY_API_KEY environment variable; skipped silently without it.
Each SKU becomes a deal whose id changes whenever the price changes, so you are
only alerted on new prices.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from ..models import Deal
from .base import FetchContext

log = logging.getLogger(__name__)
API = "https://api.bestbuy.com/v1/products(sku in({skus}))"


def fetch(entry: dict[str, Any], ctx: FetchContext) -> list[Deal]:
    key = os.environ.get("BESTBUY_API_KEY")
    skus = [str(s) for s in entry.get("skus", [])]
    if not key or not skus:
        if skus:
            log.info("BESTBUY_API_KEY not set; skipping Best Buy")
        return []
    resp = ctx.get(
        API.format(skus=",".join(skus)),
        params={
            "apiKey": key,
            "format": "json",
            "show": "sku,name,salePrice,regularPrice,url,onSale",
            "pageSize": 100,
        },
    )
    now = datetime.now(timezone.utc)
    deals = []
    for p in resp.json().get("products", []):
        price = p.get("salePrice")
        deals.append(
            Deal(
                source="bestbuy",
                title=f"{p.get('name')} ${price}",
                url=p.get("url") or f"https://www.bestbuy.com/site/{p.get('sku')}.p",
                published=now,
                summary="On sale" if p.get("onSale") else "",
                price=float(price) if price is not None else None,
                list_price=float(p["regularPrice"]) if p.get("regularPrice") else None,
                id_salt=str(price),
            )
        )
    return deals
