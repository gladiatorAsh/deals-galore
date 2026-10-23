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
    """Loose, stemmed single words from `interests` (keywords match as phrases)."""
    terms: set[str] = set()
    for phrase in profile.interests:
        for word in re.findall(r"[a-z0-9]+", phrase.lower()):
            if len(word) >= 4 and word not in STOPWORDS:
                terms.add(_stem(word))
    return sorted(terms)


def _has_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}", text) is not None


def is_excluded(deal: Deal, exclude: list[str]) -> bool:
    # Titles only: a real bag's description may well mention "shoulder strap".
    text = _norm(deal.title)
    return any(k.lower() in text for k in exclude)


def match_watch(deal: Deal, item: WatchItem) -> bool:
    title = _norm(deal.title)
    if not all(tok.lower() in title for tok in item.match):
        return False
    for group in item.any_of:
        if not any(_has_phrase_prefix(title, term) for term in group):
            return False
    if deal.price is None and item.require_price:
        return False
    if deal.price is not None:
        if item.max_price is not None and deal.price > item.max_price:
            return False
        if item.min_price is not None and deal.price < item.min_price:
            return False
    return True


def _has_phrase_prefix(text: str, phrase: str) -> bool:
    """Phrase at a word start; the last word may continue ("watch" -> "watches")."""
    words = [re.escape(w) for w in re.findall(r"[a-z0-9'&]+", phrase.lower())]
    return bool(words) and re.search(r"\b" + r"[\s\-]+".join(words), text) is not None


def _has_phrase(text: str, phrase: str) -> bool:
    words = [re.escape(w) for w in re.findall(r"[a-z0-9']+", phrase.lower())]
    if not words:
        return False
    # "dutch oven" also matches "Dutch-Oven" / "dutch  ovens"
    return re.search(r"\b" + r"[\s\-]+".join(words) + r"(?:e?s)?\b", text) is not None


def match_profile(deal: Deal, profile: GiftProfile) -> bool:
    text = _norm(f"{deal.title} {deal.summary}")
    hit = any(_has_phrase(text, k) for k in profile.keywords) or any(
        _has_term(text, t) for t in interest_terms(profile)
    )
    if not hit:
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
