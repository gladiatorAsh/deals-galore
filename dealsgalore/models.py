from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

_PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
_LIST_PRICE_RE = re.compile(
    r"(?:reg\.?|regular|was|list|msrp|orig\.?|retail)\s*:?\s*\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_prices(text: str) -> tuple[float | None, float | None]:
    """Best-effort (price, list_price) from a deal title.

    Deal titles usually lead with the sale price ("Dyson V15 $499 (reg. $749)"),
    so the first dollar amount that isn't tagged as a regular/list price wins.
    """
    if not text:
        return None, None
    list_match = _LIST_PRICE_RE.search(text)
    list_price = _to_float(list_match.group(1)) if list_match else None
    list_span = list_match.span() if list_match else None
    for m in _PRICE_RE.finditer(text):
        if list_span and list_span[0] <= m.start() < list_span[1]:
            continue
        return _to_float(m.group(1)), list_price
    return None, list_price


@dataclass
class Deal:
    source: str
    title: str
    url: str
    published: datetime | None = None
    summary: str = ""
    price: float | None = None
    list_price: float | None = None
    id_salt: str = ""  # e.g. current price, for sources whose URL never changes

    @property
    def id(self) -> str:
        key = f"{self.url.strip().lower()}|{self.id_salt}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    def fill_prices(self) -> None:
        if self.price is None:
            price, list_price = parse_prices(self.title)
            self.price = price
            if self.list_price is None:
                self.list_price = list_price


@dataclass
class Candidate:
    deal: Deal
    watch_items: list[str] = field(default_factory=list)  # watchlist item names
    recipients: list[str] = field(default_factory=list)  # gift profile names


@dataclass
class Scored:
    candidate: Candidate
    score: float
    reason: str = ""
    recipient: str | None = None
    watch_item: str | None = None
    price_note: str = ""
    scored_by: str = "heuristic"

    @property
    def deal(self) -> Deal:
        return self.candidate.deal
