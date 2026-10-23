"""Cheap keyword/price matching that runs before any LLM call.

It is deliberately permissive: its job is to throw away the 95% of the feed that
obviously doesn't match anything, and leave the judgment calls to the LLM.
"""
from __future__ import annotations

import re

from .config import GiftProfile, WatchItem
from .models import Candidate, Deal

STOPWORDS = {
    "with", "from", "that", "this", "your", "they", "them", "their", "stuff",
    "things", "gear", "items", "kids", "for", "and", "the", "anything",
}


def _norm(text: str) -> str:
    return text.lower()


def _stem(word: str) -> str:
    word = word.lower()
    for suffix in ("ies", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def interest_terms(profile: GiftProfile) -> list[str]:
    terms: set[str] = set()
    for phrase in profile.interests + profile.keywords:
        for word in re.findall(r"[a-z0-9]+", phrase.lower()):
            if len(word) >= 4 and word not in STOPWORDS:
                terms.add(_stem(word))
    return sorted(terms)


def _has_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}", text) is not None


def is_excluded(deal: Deal, exclude: list[str]) -> bool:
    text = _norm(f"{deal.title} {deal.summary}")
    return any(k.lower() in text for k in exclude)


def match_watch(deal: Deal, item: WatchItem) -> bool:
    title = _norm(deal.title)
    if not all(tok.lower() in title for tok in item.match):
        return False
    if item.max_price is not None and deal.price is not None:
        # Allow 10% headroom; the LLM/price check decides whether it's good.
        return deal.price <= item.max_price * 1.1
    return True


def match_profile(deal: Deal, profile: GiftProfile) -> bool:
    text = _norm(f"{deal.title} {deal.summary}")
    if not any(_has_term(text, t) for t in interest_terms(profile)):
        return False
    if profile.budget and deal.price is not None:
        lo, hi = profile.budget
        return lo * 0.5 <= deal.price <= hi * 1.15
    return True


def find_candidates(
    deals: list[Deal], watchlist: list[WatchItem], profiles: list[GiftProfile]
) -> list[Candidate]:
    out = []
    for d in deals:
        c = Candidate(
            deal=d,
            watch_items=[w.item for w in watchlist if match_watch(d, w)],
            recipients=[p.name for p in profiles if match_profile(d, p)],
        )
        if c.watch_items or c.recipients:
            out.append(c)
    return out
