"""Turn prefiltered candidates into scored deals.

Candidates are sent to the LLM in batches (one request scores up to
`batch_size` deals) to stay well inside free-tier daily request limits.
Anything the LLM can't reach falls back to a transparent heuristic.
"""
from __future__ import annotations

import json
import logging
import re

from .config import Config, GiftProfile, WatchItem
from .llm import LLMClient, LLMUnavailable
from .models import Candidate, Scored
from .store import Store

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a sharp, skeptical holiday-deal analyst.
You get a shopper's watchlist (items with target prices), gift profiles for
family members (interests, budget, notes), and a numbered list of deal posts
from Reddit, Slickdeals and retailer feeds.

For EVERY deal, return how worth-alerting it is:
- score 0.0-1.0. 0.85+ = genuinely great: matches a watchlist item at/below its
  target, or an excellent, specific gift fit for someone at a real discount.
  0.5-0.8 = decent, worth a digest line. Below 0.4 = noise.
- Judge a WATCHLIST match purely on its own value: genuine product from that
  brand, a real discount or fair price, under max_price if one is set. Ignore
  gift profiles and their budgets/occasions for watchlist matches, and say
  nothing about gifts in their reason. Gift profiles apply only to gift matches.
- Respect a profile's occasion: a wedding gift for a couple should be something
  both share and that feels gift-worthy (quality home, kitchen, experiences),
  not a single-person or utilitarian item.
- Premium brands (listed in premium_brands) are the shopper's priority: a
  genuine discount on one deserves a higher score than a similar discount on
  an everyday brand.
- Penalize: vague listings, accessories posing as the main product, refurbished
  or used unless the item says so, likely-expired posts, inflated "list price"
  discounts, and gifts that only loosely fit an interest.
- price: the actual sale price in USD if you can tell, else null.
- recipient: exact profile name the gift suits best, or null.
- watch_item: exact watchlist item name it matches, or null.
- reason: one short sentence (max 20 words) on why. Do NOT include any
  person's name in the reason; say "them" instead.

Respond with JSON only:
{"results": [{"idx": 0, "score": 0.0, "price": null, "recipient": null,
  "watch_item": null, "reason": ""}]}"""


def _profiles_block(profiles: list[GiftProfile]) -> list[dict]:
    return [
        {
            "name": p.name,
            "interests": p.interests,
            "budget_usd": list(p.budget) if p.budget else None,
            "occasion": p.occasion or None,
            "buy_by": p.until.isoformat() if p.until else None,
            "notes": p.notes,
        }
        for p in profiles
    ]


def _watch_block(watchlist: list[WatchItem]) -> list[dict]:
    return [
        {"item": w.item, "max_price_usd": w.max_price,
         **({"must_include_one_of_each": w.any_of} if w.any_of else {})}
        for w in watchlist
    ]


def build_user_prompt(batch: list[Candidate], cfg: Config) -> str:
    deals = [
        {
            "idx": i,
            "source": c.deal.source,
            "title": c.deal.title,
            "summary": c.deal.summary[:300],
            "parsed_price": c.deal.price,
            "parsed_list_price": c.deal.list_price,
            "keyword_hints": {"watch": c.watch_items, "gift_for": c.recipients},
        }
        for i, c in enumerate(batch)
    ]
    return json.dumps(
        {
            "watchlist": _watch_block(cfg.watchlist),
            "premium_brands": cfg.premium_brands,
            "gift_profiles": _profiles_block(cfg.gift_profiles),
            "deals": deals,
        },
        indent=1,
    )


def heuristic_score(c: Candidate, cfg: Config) -> Scored:
    d = c.deal
    watch = next((w for w in cfg.watchlist if w.item in c.watch_items), None)
    if watch and d.price is None:
        return Scored(c, score=0.3, watch_item=watch.item,
                      reason="Watchlist keywords but no price; likely an article or not a deal")
    if watch:
        under = watch.max_price is not None and d.price is not None and d.price <= watch.max_price
        return Scored(
            c,
            score=0.85 if under else 0.55,
            watch_item=watch.item,
            reason="At or below your target price" if under else "Watchlist match; price unclear",
        )
    discount = (
        1 - d.price / d.list_price if d.price and d.list_price and d.list_price > d.price else 0
    )
    # Without an LLM, keyword gift matches land in the digest, not instant alerts.
    # A post with no price is usually a question or discussion, not a deal.
    if d.price is None:
        return Scored(c, score=0.3, recipient=c.recipients[0] if c.recipients else None,
                      reason="Keyword match but no price; likely not a deal")
    score = 0.5 + min(discount, 0.5) * 0.5
    return Scored(
        c,
        score=round(score, 2),
        recipient=c.recipients[0] if c.recipients else None,
        reason=f"Keyword gift match, {discount:.0%} off" if discount else "Keyword gift match",
    )


def _clamp(x: object) -> float:
    try:
        return max(0.0, min(1.0, float(x)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def llm_score(
    candidates: list[Candidate], cfg: Config, llm: LLMClient
) -> dict[int, Scored]:
    """Score as many candidates as the per-run batch budget allows."""
    out: dict[int, Scored] = {}
    size = max(1, cfg.settings.batch_size)
    for b, start in enumerate(range(0, len(candidates), size)):
        if b >= cfg.settings.max_llm_batches_per_run or not llm.available:
            break
        batch = candidates[start : start + size]
        try:
            data, provider = llm.complete_json(SYSTEM_PROMPT, build_user_prompt(batch, cfg))
        except LLMUnavailable as exc:
            log.warning("LLM unavailable, falling back to heuristics: %s", exc)
            break
        watch_names = {w.item for w in cfg.watchlist}
        profile_names = {p.name for p in cfg.gift_profiles}
        for r in data.get("results", []):
            try:
                idx = int(r.get("idx"))
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(batch):
                continue
            c = batch[idx]
            price = r.get("price")
            if isinstance(price, (int, float)) and price > 0:
                c.deal.price = float(price)
            out[start + idx] = Scored(
                c,
                score=_clamp(r.get("score")),
                reason=str(r.get("reason") or "")[:200],
                recipient=r.get("recipient") if r.get("recipient") in profile_names else None,
                watch_item=r.get("watch_item") if r.get("watch_item") in watch_names else None,
                scored_by=provider,
            )
    return out


def apply_price_history(s: Scored, cfg: Config, store: Store) -> None:
    """Down-rank 'deals' that aren't actually below recent prices."""
    if not s.watch_item or s.deal.price is None:
        return
    stats = store.price_stats(s.watch_item, cfg.settings.history_days)
    price = s.deal.price
    if stats and stats["count"] >= 3:
        if price > stats["median"]:
            s.score = max(0.0, s.score - 0.3)
            s.price_note = f"Above {cfg.settings.history_days}-day median ${stats['median']:.0f}"
        elif price <= stats["min"]:
            s.score = min(1.0, s.score + 0.1)
            s.price_note = f"Lowest price seen in {cfg.settings.history_days} days"
    watch = next((w for w in cfg.watchlist if w.item == s.watch_item), None)
    if watch and watch.max_price is not None and price > watch.max_price:
        s.score = min(s.score, 0.6)
        s.price_note = (s.price_note + "; " if s.price_note else "") + (
            f"above your ${watch.max_price:.0f} target"
        )


def scrub_names(text: str, profiles: list[GiftProfile]) -> str:
    for p in profiles:
        if p.name:
            text = re.sub(re.escape(p.name), "them", text, flags=re.IGNORECASE)
    return text


def premium_brand(title: str, brands: list[str]) -> str | None:
    """The premium brand named in a title, if any (longest name wins)."""
    from .prefilter import _has_phrase_prefix

    low = title.lower()
    for b in sorted(brands, key=len, reverse=True):
        if _has_phrase_prefix(low, b):
            return b
    return None


def score_candidates(
    candidates: list[Candidate], cfg: Config, llm: LLMClient, store: Store
) -> list[Scored]:
    # Watchlist hits first so they are never starved of the LLM budget.
    candidates = sorted(candidates, key=lambda c: (not c.watch_items, c.deal.title))
    by_llm = llm_score(candidates, cfg, llm) if llm.available else {}
    results = []
    for i, c in enumerate(candidates):
        s = by_llm.get(i) or heuristic_score(c, cfg)
        apply_price_history(s, cfg, store)
        s.premium = premium_brand(c.deal.title, cfg.premium_brands)
        if s.premium and s.score >= 0.4:  # boost real deals, not noise
            s.score = min(1.0, s.score + cfg.premium_boost)
        results.append(s)
    return results
