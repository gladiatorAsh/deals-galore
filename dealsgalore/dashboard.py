"""Static dashboard written to docs/index.html and served by GitHub Pages.

The page is public, so it shows deals and watchlist matches only, never gift
recipient names (those exist only in the GIFT_PROFILES secret).
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
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
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}}
.filters button{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit;font-size:13px}}
.filters button.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.deal{{display:grid;grid-template-columns:72px 1fr;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:10px}}
.price{{font-weight:700;font-size:17px;font-variant-numeric:tabular-nums}}.score{{font-size:12px;color:var(--good)}}
.deal a{{color:var(--ink);text-decoration:none;font-weight:600}}.deal a:hover{{color:var(--accent)}}
.meta{{color:var(--muted);font-size:13px;margin-top:4px}}.tag{{display:inline-block;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);margin-bottom:2px}}
.empty{{color:var(--muted);padding:40px 0;text-align:center}}
.row{{display:flex;gap:10px;align-items:flex-start;justify-content:space-between}}
.watch{{flex:none;display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:999px;padding:4px 10px;font-size:12px;font-weight:600;color:var(--muted)!important;text-decoration:none;white-space:nowrap}}
.watch:hover{{color:var(--accent)!important;border-color:var(--accent)}}
.hint{{color:var(--muted);font-size:13px;margin:-8px 0 16px}}
</style></head><body><main>
<h1>Deals Galore</h1>
<p class="sub">{count} picks for you · {browse_count} recent deals to browse · updated {updated} UTC</p>
<div class="filters">
<button data-f="mine">For you ({count})</button><button data-f="watch">Watchlist</button>
<button data-f="gift">Gift ideas</button><button data-f="browse">Browse all ({browse_count})</button></div>
<p class="hint">Tap <b>Watch</b> on any deal to add it to your watchlist (opens a pre-filled GitHub issue; submit it and the next scan starts watching).</p>
<p class="empty" id="none" hidden>Nothing here yet. Matches appear as new deals are posted.</p>
<div id="list">{items}</div>
</main><script>
function show(f){{
document.querySelectorAll('.filters button').forEach(x=>x.classList.toggle('on',x.dataset.f===f));
let n=0;document.querySelectorAll('.deal').forEach(d=>{{const k=d.dataset.kind;
const v=f==='mine'?k!=='browse':k===f;d.hidden=!v;n+=v;}});
document.getElementById('none').hidden=n>0;}}
document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>show(b.dataset.f));
show({default_tab});
</script></body></html>
"""


def _item(rec: dict[str, Any], browse: bool = False, repo: str | None = None) -> str:
    price = f"${rec['price']:,.0f}" if rec.get("price") is not None else "—"
    if browse:
        kind, tag = "browse", rec.get("match_hint") or "Deal"
    elif rec.get("watch_item"):
        kind, tag = "watch", f"Watchlist · {rec['watch_item']}"
    else:
        kind, tag = "gift", "Gift idea"
    meta = " · ".join(
        x for x in (rec.get("source"), rec.get("reason"), rec.get("price_note"), rec["first_seen"][:16].replace("T", " ")) if x
    )
    score = "" if browse else f'<div class="score">score {rec.get("score", 0):.2f}</div>'
    watch = ""
    if repo and kind != "watch":
        url = new_issue_url(repo, rec["title"], rec.get("price"))
        watch = (f'<a class="watch" href="{html.escape(url)}" target="_blank" rel="noopener" '
                 f'title="Add to watchlist">{STAR}Watch</a>')
    return (
        f'<div class="deal" data-kind="{kind}"><div><div class="price">{html.escape(price)}</div>'
        f'{score}</div><div>'
        f'<div class="row"><div class="tag">{html.escape(tag)}</div>{watch}</div>'
        f'<a href="{html.escape(rec["url"])}" target="_blank" rel="noopener">{html.escape(rec["title"])}</a>'
        f'<div class="meta">{html.escape(meta)}</div></div></div>'
    )


def render(store: Store, output: str | Path, min_score: float, max_items: int,
           fp: str | None = None, browse_sources: list[str] | None = None,
           browse_hours: float = 48, browse_items: int = 80, repo: str | None = None,
           browse_only_matches: bool = False) -> Path:
    """Picks = deals scored under the current config (fp); Browse = latest posts
    from curated feeds such as the Slickdeals front page, newest first."""
    picks = [(k, v) for k, v in store.recent(min_score) if fp is None or v.get("fp") == fp][:max_items]
    picked = {k for k, _ in picks}
    browse = []
    if browse_only_matches:
        # Every recent post that matched your watchlist/gift keywords, any score.
        browse = [
            (k, v) for k, v in store.recent(0.0, browse_hours)
            if v.get("candidate") and v.get("fp") == fp and k not in picked
        ][:browse_items]
    elif browse_sources:
        browse = [
            (k, v) for k, v in store.recent(0.0, browse_hours)
            if v.get("source") in browse_sources and k not in picked and v.get("price") is not None
        ][:browse_items]
    items = "".join(_item(rec, repo=repo) for _, rec in picks) + "".join(
        _item(rec, True, repo) for _, rec in browse)
    page = PAGE.format(
        count=len(picks),
        browse_count=len(browse),
        default_tab="'mine'" if picks or not browse else "'browse'",
        updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        items=items,
    )
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out
