from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import dashboard
from .config import Config
from .llm import LLMClient
from .models import Deal, Scored
from .notifiers import Alert, Notifier, send_all
from .prefilter import find_candidates, is_excluded
from .scoring import score_candidates, scrub_names
from .sources import FetchContext, fetch_all
from .store import Store

log = logging.getLogger(__name__)


def _fresh(deal: Deal, max_age_hours: float) -> bool:
    if deal.published is None:
        return True
    return deal.published >= datetime.now(timezone.utc) - timedelta(hours=max_age_hours)


def _alert_from_scored(s: Scored) -> Alert:
    d = s.deal
    return Alert(
        title=d.title, url=d.url, price=d.price, score=s.score, source=d.source,
        reason=s.reason, recipient=s.recipient, watch_item=s.watch_item, price_note=s.price_note,
    )


def scan(cfg: Config, store: Store, notifiers: list[Notifier], llm: LLMClient | None = None,
         deals: list[Deal] | None = None) -> list[Scored]:
    st = cfg.settings
    if deals is None:
        ctx = FetchContext(user_agent=st.user_agent, timeout=st.request_timeout, watchlist=cfg.watchlist)
        deals = fetch_all(cfg.sources, ctx)

    unique: dict[str, Deal] = {}
    for d in deals:
        if d.id in unique or store.seen(d.id):
            continue
        if not _fresh(d, st.max_age_hours) or is_excluded(d, st.exclude_keywords):
            continue
        d.fill_prices()
        unique[d.id] = d
    log.info("Fetched %d items, %d new", len(deals), len(unique))

    candidates = find_candidates(list(unique.values()), cfg.watchlist, cfg.gift_profiles)
    log.info("%d candidates after keyword prefilter", len(candidates))

    llm = llm or LLMClient(cfg.llm_providers)
    scored = score_candidates(candidates, cfg, llm, store)
    log.info("Scored %d candidates (%d LLM calls)", len(scored), llm.calls)

    # Record every new item as seen so it's never re-processed, even non-matches.
    for d in unique.values():
        store.add_deal(d.id, {"title": d.title, "url": d.url, "source": d.source,
                              "price": d.price, "score": 0.0})

    for s in sorted(scored, key=lambda x: x.score, reverse=True):
        d = s.deal
        store.mark(
            d.id,
            price=d.price,
            score=round(s.score, 3),
            watch_item=s.watch_item,
            gift_match=bool(s.recipient or s.candidate.recipients),
            reason=scrub_names(s.reason, cfg.gift_profiles),
            price_note=s.price_note,
            scored_by=s.scored_by,
        )
        if s.watch_item and d.price is not None:
            store.record_price(s.watch_item, d.price, d.id)
        if s.score >= st.instant_threshold:
            if send_all(notifiers, "alert", _alert_from_scored(s)):
                store.mark(d.id, notified=True)

    store.prune(st.retention_days, st.history_days)
    if cfg.dashboard.get("enabled", True):
        dashboard.render(store, cfg.dashboard["output"], cfg.dashboard["min_score"], cfg.dashboard["max_items"])
    store.save()
    return scored


def digest(cfg: Config, store: Store, notifiers: list[Notifier], hours: float = 36) -> int:
    """Send everything above the digest threshold that hasn't been digested yet."""
    from .prefilter import match_profile

    rows = [(k, v) for k, v in store.recent(cfg.settings.digest_threshold, hours) if not v.get("digested")]
    if not rows:
        log.info("Nothing new for the digest")
        return 0
    alerts = []
    for _, rec in sorted(rows, key=lambda kv: kv[1].get("score", 0), reverse=True):
        # Recipient names aren't stored (public repo); re-derive them from the
        # private profiles at send time.
        recipient = None
        if not rec.get("watch_item") and rec.get("gift_match"):
            probe = Deal(source=rec["source"], title=rec["title"], url=rec["url"], price=rec.get("price"))
            recipient = next(
                (p.name for p in cfg.gift_profiles if p.active() and match_profile(probe, p)), None
            )
        alerts.append(Alert(
            title=rec["title"], url=rec["url"], price=rec.get("price"), score=rec.get("score", 0),
            source=rec["source"], reason=rec.get("reason", ""), recipient=recipient,
            watch_item=rec.get("watch_item"), price_note=rec.get("price_note", ""),
        ))
    subject = f"Deals digest — {len(alerts)} picks ({datetime.now(timezone.utc):%b %d})"
    if send_all(notifiers, "digest", alerts, subject):
        for k, _ in rows:
            store.mark(k, digested=True)
        store.save()
    return len(alerts)
