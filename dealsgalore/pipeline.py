from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

from . import dashboard
from .config import Config
from .llm import LLMClient
from .models import Deal, Scored, detect_store
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
        store=d.store, premium=s.premium,
    )


def gift_countdown(cfg: Config, today: date | None = None) -> str | None:
    """'13 days to Nov 5 · order by Oct 31' while gift mode is on."""
    if not cfg.gift_deadline:
        return None
    today = today or date.today()
    days = (cfg.gift_deadline - today).days
    if days < 0:
        return None
    order_by = cfg.order_by()
    tail = (f" · order by {order_by:%b} {order_by.day} for standard shipping" if order_by >= today
            else " · past standard-shipping cutoff: pick fast shipping or in-store pickup")
    return f"🎁 {days} day{'s' if days != 1 else ''} to {cfg.gift_deadline:%b} {cfg.gift_deadline.day}{tail}"


# Bump when scoring logic changes in a way that should re-check recent posts.
SCORING_VERSION = 17


def config_fingerprint(cfg: Config) -> str:
    """Short hash of what decides a match. Only a hash is stored (public repo)."""
    payload = {
        "scoring": SCORING_VERSION,
        "watch": [(w.item, w.max_price, w.min_price, w.require_price, w.match, w.any_of,
                   w.exclude, w.notes, w.active()) for w in cfg.watchlist],
        "gift_deadline": cfg.gift_deadline,
        "gifts": [(p.name, p.interests, p.keywords, p.budget, p.occasion) for p in cfg.gift_profiles],
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:10]


def scan(cfg: Config, store: Store, notifiers: list[Notifier], llm: LLMClient | None = None,
         deals: list[Deal] | None = None, stats: dict | None = None) -> list[Scored]:
    st = cfg.settings
    stats = stats if stats is not None else {}
    stats.update(profiles=len(cfg.gift_profiles), watchlist=len(cfg.watchlist))
    if deals is None:
        ctx = FetchContext(user_agent=st.user_agent, timeout=st.request_timeout, watchlist=cfg.watchlist)
        deals = fetch_all(cfg.sources, ctx)

    # A deal is skipped only if it was already evaluated against the CURRENT
    # watchlist and gift profiles. Editing either re-checks recent posts.
    fp = config_fingerprint(cfg)
    unique: dict[str, Deal] = {}
    rechecked = 0
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for d in deals:
        if d.id in unique:
            continue
        rec = store.deals.get(d.id)
        if rec:
            rec["last_seen"] = now_iso  # still listed by its source
            rec["title"] = d.title  # sources may improve titles over time
        if rec and rec.get("fp") == fp and not rec.get("pending"):
            continue
        if not _fresh(d, st.max_age_hours) or is_excluded(d, st.exclude_keywords):
            continue
        d.fill_prices()
        d.store = d.store or detect_store(f"{d.title} {d.summary}", cfg.stores)
        if cfg.only_stores and d.store not in cfg.only_stores:
            continue
        unique[d.id] = d
        rechecked += bool(rec)
    stats.update(fetched=len(deals), new=len(unique) - rechecked, rechecked=rechecked)
    log.info("Fetched %d items, %d new, %d re-checked after config change",
             len(deals), len(unique) - rechecked, rechecked)

    candidates = find_candidates(list(unique.values()), cfg.watchlist, cfg.gift_profiles)
    log.info("%d candidates after keyword prefilter", len(candidates))

    llm = llm or LLMClient(cfg.llm_providers)
    scored = score_candidates(candidates, cfg, llm, store)
    log.info("Scored %d candidates (%d LLM calls)", len(scored), llm.calls)
    stats.update(candidates=len(candidates), llm_calls=llm.calls, alerts=0)

    # Record every evaluated item so it isn't re-processed until config changes.
    for d in unique.values():
        if store.seen(d.id):
            store.mark(d.id, fp=fp, store=d.store, title=d.title, url=d.url, price=d.price, score=0.0, watch_item=None, gift_match=False,
                       reason="", price_note="", candidate=False)
        else:
            store.add_deal(d.id, {"title": d.title, "url": d.url, "source": d.source,
                                  "price": d.price, "score": 0.0, "fp": fp, "store": d.store})

    for s in sorted(scored, key=lambda x: x.score, reverse=True):  # premium boost already applied
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
            candidate=True,  # matched your watchlist/gift keywords (shown in Browse)
            # Rule-scored because the AI budget ran out: AI-score it next scan.
            pending=bool(s.scored_by == "heuristic" and llm.providers),
            match_hint=(s.candidate.watch_items or ["Gift idea"])[0],
            premium=s.premium,
        )
        already_logged = any(p["deal"] == d.id for p in store.prices.get(s.watch_item or "", []))
        if s.watch_item and d.price is not None and not already_logged:
            store.record_price(s.watch_item, d.price, d.id)
        if (s.score >= st.instant_threshold and not store.deals[d.id].get("notified")
                and stats["alerts"] < st.max_alerts_per_run):
            if send_all(notifiers, "alert", _alert_from_scored(s)):
                store.mark(d.id, notified=True)
                stats["alerts"] += 1

    store.prune(st.retention_days, st.history_days)
    if cfg.dashboard.get("enabled", True):
        dashboard.render(
            store, cfg.dashboard["output"], cfg.dashboard["min_score"], cfg.dashboard["max_items"],
            fp=fp, browse_sources=cfg.dashboard.get("browse_sources"),
            browse_hours=cfg.dashboard.get("browse_hours", 48),
            browse_items=cfg.dashboard.get("browse_items", 80),
            browse_only_matches=cfg.dashboard.get("browse_only_matches", False),
            timezone_name=cfg.dashboard.get("timezone"),
            stale_hours=cfg.dashboard.get("stale_hours", 12),
            hide_below=cfg.dashboard.get("hide_below", 0.3),
            banner=gift_countdown(cfg),
            repo=cfg.dashboard.get("repo") or os.environ.get("GITHUB_REPOSITORY"),
        )
    store.save()
    return scored


def digest(cfg: Config, store: Store, notifiers: list[Notifier], hours: float = 36) -> int:
    """Send everything above the digest threshold that hasn't been digested yet."""
    from .prefilter import match_profile

    # Only deals scored under the current watchlist/profiles (stale scores are skipped).
    fp = config_fingerprint(cfg)
    rows = [
        (k, v) for k, v in store.recent(cfg.settings.digest_threshold, hours)
        if not v.get("digested") and v.get("fp") == fp
    ]
    if not rows:
        log.info("Nothing new for the digest")
        return 0
    alerts = []
    for _, rec in sorted(rows, key=lambda kv: (bool(kv[1].get("premium")), kv[1].get("score", 0)),
                         reverse=True):
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
            store=rec.get("store"), premium=rec.get("premium"),
        ))
    subject = f"Deals digest — {len(alerts)} picks ({datetime.now(timezone.utc):%b %d})"
    countdown = gift_countdown(cfg)
    if countdown:
        subject += f" · {countdown}"
    if send_all(notifiers, "digest", alerts, subject):
        for k, _ in rows:
            store.mark(k, digested=True)
        store.save()
    return len(alerts)
