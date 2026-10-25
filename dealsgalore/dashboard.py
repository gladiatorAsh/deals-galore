"""Static dashboard written to docs/index.html and served by GitHub Pages.

The page is public, so it shows deals and watchlist matches only, never gift
recipient names (those exist only in the GIFT_PROFILES secret).
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from .store import Store
from .watchlist import new_issue_url

STAR = ('<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M12 3.5l2.6 5.3 5.9.9-4.3 '
        '4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>')

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deals Galore</title>
<style>
:root{{--bg:#faf8f5;--card:#fff;--ink:#1d1b18;--muted:#6f6a63;--line:#e8e3dc;--accent:#b4441c;--good:#2f7d4a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151412;--card:#1e1c1a;--ink:#ece8e2;--muted:#a19a90;--line:#2f2c28;--accent:#f0875c;--good:#6fc28d}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:860px;margin:0 auto;padding:28px 16px 60px}}
h1{{font-size:28px;margin:0 0 4px;letter-spacing:-.02em}}.sub{{color:var(--muted);margin:0 0 20px}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px}}
.chip{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit;font-size:13px}}
.chip.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.toggle{{margin-left:auto;display:inline-flex;gap:6px;align-items:center;font-size:13px;color:var(--muted);cursor:pointer;user-select:none}}
.toggle input{{accent-color:var(--accent);width:16px;height:16px}}
.deal{{display:grid;grid-template-columns:72px 1fr;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:10px}}
.deal.top{{border-color:var(--good)}}
.price{{font-weight:700;font-size:17px;font-variant-numeric:tabular-nums}}.score{{font-size:12px;color:var(--good)}}
.deal a.t{{color:var(--ink);text-decoration:none;font-weight:600}}.deal a.t:hover{{color:var(--accent)}}
.meta{{color:var(--muted);font-size:13px;margin-top:4px}}
.tag{{display:inline-block;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);margin-bottom:2px}}
.tag.top::before{{content:"\2605 Top pick · ";color:var(--good)}}
.empty{{color:var(--muted);padding:40px 0;text-align:center}}
.prem{{background:#8a6d1f;color:#fff;border-radius:4px;padding:1px 6px;margin-right:6px;letter-spacing:.04em}}
.row{{display:flex;gap:10px;align-items:flex-start;justify-content:space-between}}
.watch{{flex:none;display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:999px;padding:4px 10px;font-size:12px;font-weight:600;color:var(--muted);text-decoration:none;white-space:nowrap}}
.watch:hover{{color:var(--accent);border-color:var(--accent)}}
.hint{{color:var(--muted);font-size:13px;margin:24px 0 0}}
.gift{{background:var(--card);border:1px solid var(--accent);border-radius:10px;padding:10px 14px;margin:-8px 0 18px;font-weight:600}}
</style></head><body><main>
<h1>Deals Galore</h1>
<p class="sub">{total} deals · {top} top picks · updated {updated}</p>{banner}
<div class="bar">{chips}<label class="toggle"><input type="checkbox" id="toponly">Top picks only</label></div>
<p class="empty" id="none" hidden>Nothing here right now. New matches appear as deals are posted.</p>
<div id="list">{items}</div>
<p class="hint">Tap <b>Watch</b> on a deal to track that exact item at a target price (opens a pre-filled GitHub issue; submit it and the next scan starts watching).</p>
</main><script>
let cat='all';const top=document.getElementById('toponly');
function render(){{let n=0;
document.querySelectorAll('.chip').forEach(c=>c.classList.toggle('on',c.dataset.c===cat));
document.querySelectorAll('.deal').forEach(d=>{{const v=(cat==='all'||d.dataset.c===cat||(cat==='premium'&&d.dataset.p==='1'))&&(!top.checked||d.dataset.top==='1');
d.hidden=!v;n+=v;}});document.getElementById('none').hidden=n>0;}}
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{{cat=c.dataset.c;render();}});
top.onchange=render;render();
</script></body></html>
"""

DEFAULT_TZ = "America/Los_Angeles"


def _tz(name: str | None):
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return timezone.utc


def _local(ts: str, tz) -> str:
    try:
        dt = datetime.fromisoformat(ts).astimezone(tz)
    except ValueError:
        return ts[:16]
    return dt.strftime("%b %-d, %-I:%M %p")


def _category(rec: dict[str, Any]) -> str:
    if rec.get("candidate") or rec.get("score"):
        if rec.get("watch_item"):
            return rec["watch_item"]
        hint = rec.get("match_hint")
        if hint and hint != "Gift idea":
            return hint
        if rec.get("gift_match") or hint == "Gift idea":
            return "Gift ideas"
    return "Other deals"


def _item(rec: dict[str, Any], cat: str, is_top: bool, repo: str | None, tz) -> str:
    price = f"${rec['price']:,.0f}" if rec.get("price") is not None else "—"
    meta = " · ".join(x for x in (
        f"at {rec['store']}" if rec.get("store") else None,
        rec.get("source"), rec.get("reason"), rec.get("price_note"), rec.get("note"),
        _local(rec["first_seen"], tz),
    ) if x)
    scored = rec.get("candidate") or rec.get("score")
    score = f'<div class="score">score {rec.get("score", 0):.2f}</div>' if scored else ""
    prem = (f'<span class="prem">{html.escape(rec["premium"].title())}</span>'
            if rec.get("premium") else "")
    watch = ""
    if repo:
        url = new_issue_url(repo, rec["title"], rec.get("price"))
        watch = (f'<a class="watch" href="{html.escape(url)}" target="_blank" rel="noopener" '
                 f'title="Track this exact item at a target price">{STAR}Watch</a>')
    return (
        f'<div class="deal{" top" if is_top else ""}" data-c="{html.escape(cat)}" '
        f'data-p="{int(bool(rec.get("premium")))}" data-top="{int(is_top)}"><div><div class="price">{html.escape(price)}</div>{score}</div><div>'
        f'<div class="row"><div class="tag{" top" if is_top else ""}">{prem}{html.escape(cat)}</div>{watch}</div>'
        f'<a class="t" href="{html.escape(rec["url"])}" target="_blank" rel="noopener">'
        f'{html.escape(rec["title"])}</a><div class="meta">{html.escape(meta)}</div></div></div>'
    )


def render(store: Store, output: str | Path, min_score: float, max_items: int,
           fp: str | None = None, browse_sources: list[str] | None = None,
           browse_hours: float = 48, browse_items: int = 80, repo: str | None = None,
           browse_only_matches: bool = False, timezone_name: str | None = None,
           stale_hours: float = 12, hide_below: float = 0.3, banner: str | None = None,
           max_per_store: int = 0) -> Path:
    """One list, best first, with a filter chip per category actually present.

    Included: deals scored at/above min_score under the current config (fp), plus
    recent keyword matches of any score, plus (unless browse_only_matches) recent
    priced deals from browse_sources. Top picks are those at/above min_score.
    """
    tz = _tz(timezone_name)
    fresh_cut = (datetime.now(timezone.utc) - timedelta(hours=stale_hours)).isoformat()
    # Only deals scored under the current config and still listed by a source
    # recently (drops expired posts and sold/removed items).
    fresh = lambda v: v.get("last_seen", "") >= fresh_cut  # noqa: E731  (no stamp = legacy, stale)
    current = lambda v: (fp is None or v.get("fp") == fp) and fresh(v)  # noqa: E731
    rows: dict[str, dict[str, Any]] = {}
    for k, v in store.recent(min_score):
        if current(v):
            rows[k] = v
    for k, v in store.recent(0.0, browse_hours):
        if k in rows:
            continue
        if v.get("candidate"):
            # skip stale scores and matches the scorer rejected (suspicious prices etc.)
            if current(v) and (v.get("score") or 0) >= hide_below:
                rows[k] = v
        elif not browse_only_matches and browse_sources and v.get("source") in browse_sources \
                and v.get("price") is not None and fresh(v):
            rows[k] = v
    # Best score first (premium brands already carry a score boost), then newest.
    ordered = sorted(rows.values(), key=lambda v: (v.get("score") or 0, v["first_seen"]), reverse=True)
    ordered = ordered[: max_items + browse_items]

    cards, counts, per_store = [], {}, {}
    n_top = n_premium = 0
    for rec in ordered:
        shop = rec.get("store") or rec.get("source") or "?"
        per_store[shop] = per_store.get(shop, 0) + 1
        if max_per_store and per_store[shop] > max_per_store and rec.get("source") != "tracked":
            continue  # one big sale shouldn't push every other store off the page
        cat = _category(rec)
        is_top = (rec.get("score") or 0) >= min_score
        n_top += is_top
        counts[cat] = counts.get(cat, 0) + 1
        n_premium += bool(rec.get("premium"))
        cards.append(_item(rec, cat, is_top, repo, tz))

    # "All" plus one chip per category present (largest first); a lone category
    # needs no chip of its own.
    chips = [f'<button class="chip" data-c="all">All ({len(cards)})</button>']
    if n_premium:
        chips.append(f'<button class="chip" data-c="premium">★ Premium ({n_premium})</button>')
    if len(counts) > 1:
        for cat, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            chips.append(f'<button class="chip" data-c="{html.escape(cat)}">{html.escape(cat)} ({n})</button>')

    now = datetime.now(timezone.utc).astimezone(tz)
    page = PAGE.format(
        total=len(cards),
        top=n_top,
        banner=f'<p class="gift">{html.escape(banner)}</p>' if banner else "",
        updated=now.strftime("%b %-d, %-I:%M %p %Z"),
        chips="".join(chips),
        items="".join(cards),
    )
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out
