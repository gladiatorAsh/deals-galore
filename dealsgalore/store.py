"""JSON-file store for seen deals and price history.

The file is committed back to the repo by the workflow, which makes it free,
durable, and diff-able. Because the repo is public, nothing personal is stored
here: no gift recipient names, and LLM reasons are scrubbed of profile names.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class Store:
    def __init__(self, path: str | Path = "data/deals.json"):
        self.path = Path(path)
        if self.path.exists():
            data = json.loads(self.path.read_text() or "{}")
        else:
            data = {}
        self.deals: dict[str, dict[str, Any]] = data.get("deals", {})
        # watch item name -> list of {"price", "at", "deal"}
        self.prices: dict[str, list[dict[str, Any]]] = data.get("prices", {})
        self.meta: dict[str, Any] = data.get("meta", {})

    # ---- deals -------------------------------------------------------
    def seen(self, deal_id: str) -> bool:
        return deal_id in self.deals

    def add_deal(self, deal_id: str, record: dict[str, Any]) -> None:
        record.setdefault("first_seen", _iso(_now()))
        record.setdefault("notified", False)
        record.setdefault("digested", False)
        self.deals[deal_id] = record

    def mark(self, deal_id: str, **fields: Any) -> None:
        if deal_id in self.deals:
            self.deals[deal_id].update(fields)

    def recent(self, min_score: float, hours: float | None = None) -> list[tuple[str, dict[str, Any]]]:
        cutoff = _now() - timedelta(hours=hours) if hours else None
        rows = [
            (k, v)
            for k, v in self.deals.items()
            if (v.get("score") or 0) >= min_score
            and (cutoff is None or _parse(v["first_seen"]) >= cutoff)
        ]
        rows.sort(key=lambda kv: kv[1]["first_seen"], reverse=True)
        return rows

    # ---- price history -----------------------------------------------
    def record_price(self, watch_item: str, price: float, deal_id: str) -> None:
        self.prices.setdefault(watch_item, []).append(
            {"price": price, "at": _iso(_now()), "deal": deal_id}
        )

    def price_stats(self, watch_item: str, days: int) -> dict[str, float] | None:
        cutoff = _now() - timedelta(days=days)
        values = [
            p["price"] for p in self.prices.get(watch_item, []) if _parse(p["at"]) >= cutoff
        ]
        if not values:
            return None
        return {"median": statistics.median(values), "min": min(values), "count": len(values)}

    # ---- housekeeping ------------------------------------------------
    def prune(self, retention_days: int, history_days: int) -> None:
        deal_cutoff = _now() - timedelta(days=retention_days)
        self.deals = {
            k: v for k, v in self.deals.items() if _parse(v["first_seen"]) >= deal_cutoff
        }
        price_cutoff = _now() - timedelta(days=max(history_days, retention_days))
        for item, rows in list(self.prices.items()):
            kept = [r for r in rows if _parse(r["at"]) >= price_cutoff]
            if kept:
                self.prices[item] = kept
            else:
                del self.prices[item]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.meta["updated"] = _iso(_now())
        payload = {"meta": self.meta, "deals": self.deals, "prices": self.prices}
        self.path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
